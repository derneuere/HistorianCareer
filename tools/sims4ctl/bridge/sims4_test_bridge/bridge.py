# bridge.py - the heart of the in-game bridge.
#
# install() wires TWO drain sources, both firing drain() ON THE MAIN THREAD:
#   (1) MAIN MENU (pre-zone): we wrap `areaserver.c_api_server_tick`, a
#       module-level per-frame main-thread tick the game fires even at the menu,
#       so commands are serviced BEFORE a save is loaded.
#   (2) IN-ZONE: we hook `zone.Zone.do_zone_spin_up`; once a zone has spun up,
#       _on_zone_loaded() starts a repeating REAL-TIME alarm whose callback runs
#       drain().
# drain() refreshes heartbeat.json, reads request.json, and when
# request.seq > last_handled_seq executes the verb ON THE MAIN THREAD and writes
# response.json with the same seq. It is wall-clock throttled so the same body is
# safe to call from BOTH the paced alarm and the high-frequency frame tick. (We
# do NOT use core_services.on_tick: `core_services` is not an importable module
# in TS4 1.124.55 -- see the note by the imports below.)
#
# THE ONE HARD RULE (see _BUILD_SPEC.md): drain() runs from the alarm callback,
# which fires on the main simulation thread -- that is precisely why we can touch
# services / sim objects here. We NEVER spawn a background thread; we NEVER touch
# services off-thread. Everything is wrapped in try/except so a bad request can
# only ever produce an ok=false response, never a crash.
#
# CPython 3.7-safe, stdlib only (json, traceback, functools, io, time).

import functools
import io
import sys
import time
import traceback

from . import protocol
from . import state

# Game modules: import lazily/defensively so this module imports cleanly even
# outside the game (host-side syntax checks, tests).
# NOTE: `core_services` is NOT an importable top-level module in TS4 1.124.55
# (verified against the game's own scripts). The per-frame `on_tick` lives on
# service CLASSES (game_services etc.), not a global module, and nothing is
# importable that early anyway. So IN A LOADED ZONE we drive the drain from a
# repeating REAL-TIME ALARM started at zone-spin-up (both
# `zone.Zone.do_zone_spin_up` and `alarms.add_alarm_real_time` are confirmed
# present). At the MAIN MENU there is no zone and the alarm timeline is torn
# down, so we ALSO wrap `areaserver.c_api_server_tick` -- a module-level,
# main-thread, per-frame tick that fires pre-zone. See install() below.

try:
    import services
except Exception:
    services = None

try:
    import sims4
except Exception:
    sims4 = None

try:
    import sims4.commands
except Exception:
    pass


# ---------------------------------------------------------------------------
# module-level state. last_handled_seq is recovered from response.json on first
# drain so a mid-session reload doesn't re-execute the last request.
# ---------------------------------------------------------------------------

_zone_hook_installed = False
_menu_hook_installed = False
_drain_loop_started = False
# The repeating alarm registers its AlarmHandle in a WEAK-ref table: if we drop
# the handle it is garbage-collected and the alarm is hard-stopped (verified in
# the game's alarms.py). So we MUST keep the handle alive at module scope.
_alarm_handle = None
_tick_count = 0
_last_handled_seq = None  # None until recovered/initialized
_seq_recovered = False

# The drain runs from a repeating real-time alarm (see _start_drain_loop); this
# interval sets the bridge's command latency and heartbeat cadence. It ALSO
# doubles as the wall-clock throttle for drain() itself (see _last_drain_ts):
# drain() is now called from TWO sources -- the 0.5s alarm (in a loaded zone)
# AND the high-frequency main-menu frame tick (areaserver.c_api_server_tick,
# ~30-60 Hz, pre-zone). The throttle makes drain() safe to call from both.
DRAIN_INTERVAL_REAL_SECONDS = 0.5

# Wall-clock timestamp of the last drain that did real work (heartbeat + request
# read). Used to throttle drain() to at most once per DRAIN_INTERVAL_REAL_SECONDS
# regardless of how fast the caller fires. 0.0 == "never drained yet".
_last_drain_ts = 0.0


def _recover_last_seq():
    """On the first drain, seed _last_handled_seq from any existing
    response.json so we don't replay the last-handled request after a reload."""
    global _last_handled_seq, _seq_recovered
    if _seq_recovered:
        return
    _seq_recovered = True
    try:
        resp = protocol.read_response()
        if resp is not None:
            s = resp.get("seq")
            if isinstance(s, int):
                _last_handled_seq = s
    except Exception:
        pass


# ---------------------------------------------------------------------------
# verb helpers / eval namespace
# ---------------------------------------------------------------------------

class _HCHelpers(object):
    """A tiny helpers module exposed as `hc` inside eval/exec, so probes can
    reach the bridge's own serializers without re-deriving them."""
    get_state = staticmethod(state.get_state)
    active_sim_info = staticmethod(state.get_active_sim_info)
    active_sim_name = staticmethod(state.active_sim_name)
    serialize_sim = staticmethod(state.serialize_sim)
    serialize_career = staticmethod(state.serialize_career)
    serialize_skills = staticmethod(state.serialize_skills)
    serialize_traits = staticmethod(state.serialize_traits)
    serialize_clock = staticmethod(state.serialize_clock)


def _eval_namespace():
    """Build the namespace exposed to eval/exec: services, sims4, hc."""
    return {
        "services": services,
        "sims4": sims4,
        "hc": _HCHelpers,
    }


def _json_safe(value):
    """Return `value` if it is JSON-serializable, else None. Used by eval to
    populate the optional 'json' field without throwing."""
    try:
        import json
        json.dumps(value)
        return value
    except Exception:
        return None


# ---------------------------------------------------------------------------
# verb implementations. Each returns a JSON-able result or raises (the dispatch
# wrapper converts a raise into ok=false + traceback).
# ---------------------------------------------------------------------------

def _verb_ping(args):
    return {
        "pong": True,
        "zone_loaded": state.zone_is_loaded(),
        "active_sim": state.active_sim_name(),
        "bridge_version": protocol.BRIDGE_VERSION,
    }


def _verb_cmd(args):
    command = (args or {}).get("command")
    if not command or not isinstance(command, str):
        raise ValueError("cmd requires args.command (str)")
    if sims4 is None:
        raise RuntimeError("sims4 module unavailable (no zone / not in game)")
    output = None
    # Best-effort cheat-output capture via a CheatOutput-like callable. The
    # execute() signature is execute(command, client_or_output). Passing None
    # is the documented MVP path; capturing output is not guaranteed.
    captured = []

    class _Capture(object):
        def __call__(self, s, *a, **k):
            try:
                captured.append(str(s))
            except Exception:
                pass

    try:
        # Some builds accept a callable output; if not, fall back to None.
        sims4.commands.execute(command, _Capture())
    except Exception:
        # Retry with None per the spec's documented path.
        sims4.commands.execute(command, None)
    if captured:
        output = "\n".join(captured)
    return {"executed": True, "output": output}


def _verb_eval(args):
    args = args or {}
    code = args.get("code")
    mode = args.get("mode", "eval")
    if not code or not isinstance(code, str):
        raise ValueError("eval requires args.code (str)")
    ns = _eval_namespace()
    if mode == "exec":
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            exec(compile(code, "<s4ctl-exec>", "exec"), ns, ns)
        finally:
            sys.stdout = old
        return {"stdout": buf.getvalue()}
    elif mode == "eval":
        value = eval(compile(code, "<s4ctl-eval>", "eval"), ns, ns)
        return {"repr": repr(value), "json": _json_safe(value)}
    else:
        raise ValueError(
            "eval mode must be 'eval' or 'exec', got {0!r}".format(mode))


def _verb_state(args):
    args = args or {}
    topic = args.get("topic", "all")
    career = args.get("career")
    return state.get_state(topic, career)


def _verb_advance(args):
    args = args or {}
    hours = args.get("hours", 0) or 0
    minutes = args.get("minutes", 0) or 0
    try:
        hours = int(hours)
        minutes = int(minutes)
    except Exception:
        raise ValueError("advance hours/minutes must be ints")
    if services is None:
        raise RuntimeError("services unavailable (no zone / not in game)")
    gcs_accessor = getattr(services, "game_clock_service", None)
    if gcs_accessor is None:
        raise RuntimeError("game_clock_service unavailable")
    gcs = gcs_accessor()
    if gcs is None:
        raise RuntimeError("game clock not running")
    # Crank to SUPER_SPEED3 so the advance actually elapses. NOTE (spec): time
    # will not advance while paused / in a modal / in CAS or Build, and blocking
    # interactions force normal speed -- documented constraint, not a bug here.
    try:
        from clock import ClockSpeedMode
        setspeed = getattr(gcs, "set_clock_speed", None)
        if callable(setspeed):
            setspeed(ClockSpeedMode.SUPER_SPEED3)
    except Exception:
        # Non-fatal: advance_game_time below still moves the clock.
        pass
    # Advance the clock. The documented helper is advance_game_time; try its
    # keyword form first, then a positional fallback.
    advanced = False
    advance_fn = getattr(gcs, "advance_game_time", None)
    if callable(advance_fn):
        try:
            advance_fn(hours=hours, minutes=minutes)
            advanced = True
        except TypeError:
            try:
                advance_fn(hours, minutes, 0)
                advanced = True
            except Exception:
                advanced = False
    if not advanced:
        raise RuntimeError(
            "advance_game_time unavailable or rejected args "
            "(hours={0}, minutes={1})".format(hours, minutes))
    return state.serialize_clock()


def _verb_load_save(args):
    """STUB: load a save slot. There is no Python-callable save-load API in TS4
    1.124.55 -- loading a save is driven from the OUTSIDE by input automation
    (Recipe B), not from inside the bridge. We answer honestly (ok=true with a
    'not supported here' result, NOT an error) so the host CLI's future
    `load-save` command has a verb to call and gets a clear, parseable reason."""
    args = args or {}
    slot = args.get("slot")  # int|str|None -- accepted but not actionable here
    return {
        "loaded": False,
        "slot": slot,
        "reason": "no Python load API in 1.124.55; load is driven by input "
                  "automation (Recipe B)",
    }


# Dispatch table: verb name -> handler(args) -> JSON-able result.
_DISPATCH = {
    "ping": _verb_ping,
    "cmd": _verb_cmd,
    "eval": _verb_eval,
    "state": _verb_state,
    "advance": _verb_advance,
    "load_save": _verb_load_save,
}


def _handle_request(req):
    """Execute one request dict and write the response. Always writes a
    response with the request's seq; converts any failure into ok=false."""
    global _last_handled_seq
    seq = None
    try:
        seq = req.get("seq")
        verb = req.get("verb")
        args = req.get("args") or {}
        if not isinstance(seq, int):
            # Can't correlate without an int seq; log and bail (don't bump).
            protocol.log("request missing int seq; ignoring: {0!r}".format(req))
            return
        handler = _DISPATCH.get(verb)
        if handler is None:
            protocol.write_response(
                seq, False, None, "unknown verb: {0!r}".format(verb))
            _last_handled_seq = seq
            return
        try:
            result = handler(args)
            protocol.write_response(seq, True, result, None)
        except Exception as e:
            tb = traceback.format_exc()
            protocol.write_response(
                seq, False, None,
                "{0}: {1}\n{2}".format(type(e).__name__, e, tb))
        _last_handled_seq = seq
    except Exception as e:
        # Last-ditch: even response-writing failed/raised. Record what we can.
        protocol.log("FATAL in _handle_request (seq={0}): {1}\n{2}".format(
            seq, e, traceback.format_exc()))
        if isinstance(seq, int):
            _last_handled_seq = seq


# ---------------------------------------------------------------------------
# the drain: called from our on_tick wrapper. Throttled. Main-thread only.
# ---------------------------------------------------------------------------

def drain():
    """Throttled poll: refresh heartbeat, read request, handle if new. Runs on
    the MAIN THREAD -- from the in-zone real-time alarm (every 0.5s) AND/OR the
    main-menu frame tick (areaserver.c_api_server_tick, ~30-60 Hz). Never raises.

    Throttled by wall-clock to at most once per DRAIN_INTERVAL_REAL_SECONDS, so
    it is safe to call from BOTH the (already-paced) alarm and the high-frequency
    frame tick without doing 30-60x the real IO. _tick_count only advances on a
    drain that actually does work, keeping the heartbeat tick meaningful."""
    global _tick_count, _last_drain_ts
    try:
        # Wall-clock throttle. Calls arriving inside the interval are dropped
        # cheaply (no FS touch) -- this is what makes the high-frequency menu
        # tick affordable. time.time() can step backwards on a clock change, so
        # treat a negative delta as "due" rather than waiting it out.
        now = time.time()
        delta = now - _last_drain_ts
        if 0.0 <= delta < DRAIN_INTERVAL_REAL_SECONDS:
            return
        _last_drain_ts = now
        _tick_count += 1
        _recover_last_seq()
        # Heartbeat (every drain; cadence set by the alarm interval).
        try:
            protocol.write_heartbeat(
                _tick_count,
                state.zone_is_loaded(),
                state.active_sim_name())
        except Exception:
            pass
        # Request.
        req = protocol.read_request()
        if not req:
            return
        seq = req.get("seq")
        if not isinstance(seq, int):
            return
        if _last_handled_seq is not None and seq <= _last_handled_seq:
            return  # already handled (or stale)
        _handle_request(req)
    except Exception as e:
        # drain must never propagate into the game loop.
        try:
            protocol.log("drain error: {0}\n{1}".format(
                e, traceback.format_exc()))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Installation. At .ts4script load time `services`/`alarms`/`clock` are not yet
# usable, so we hook `zone.Zone.do_zone_spin_up` (the one entry point reliably
# patchable at import, proven by HistorianCareer's affordance_injector) and,
# once a zone has spun up on the MAIN THREAD, start a repeating real-time alarm
# that runs drain(). Everything is idempotent and defensive.
# ---------------------------------------------------------------------------

class _AlarmOwner(object):
    """A stable, long-lived owner object for the repeating drain alarm (alarms
    key their handles by owner; a module-level singleton keeps it alive)."""
    pass


_ALARM_OWNER = _AlarmOwner()


def _alarm_cb(handle=None):
    """Alarm callback (called with the AlarmHandle, or none on some builds)."""
    drain()


def _start_drain_loop(owner):
    """Start the repeating drain. Prefer a real-time alarm (wall-clock timeline,
    fires regardless of sim pause/speed); fall back to a sim-time alarm. Keeps
    the returned AlarmHandle alive (weak-ref'd by the game) so it isn't GC'd.
    Idempotent."""
    global _drain_loop_started, _alarm_handle
    if _drain_loop_started:
        return
    try:
        import alarms
        import clock
        ts = clock.interval_in_real_seconds(DRAIN_INTERVAL_REAL_SECONDS)
        # add_alarm_real_time(owner, time_span, callback, repeating,
        # use_sleep_time, cross_zone) -- NO repeating_time_span (verified against
        # the game's alarms bytecode); repeats every `time_span` when repeating.
        # MUST retain the returned handle (see _alarm_handle note above).
        _alarm_handle = alarms.add_alarm_real_time(
            owner, ts, _alarm_cb, repeating=True)
        _drain_loop_started = True
        protocol.log(
            "drain loop installed: add_alarm_real_time @ {0}s (handle held).".format(
                DRAIN_INTERVAL_REAL_SECONDS))
        return
    except Exception as e:
        protocol.log("real-time alarm failed ({0}); trying sim alarm.\n{1}".format(
            e, traceback.format_exc()))
    try:
        import alarms
        import clock
        ts = clock.interval_in_sim_minutes(1)
        _alarm_handle = alarms.add_alarm(
            owner, ts, _alarm_cb, repeating=True, repeating_time_span=ts)
        _drain_loop_started = True
        protocol.log("drain loop installed: add_alarm (sim-minutes, handle held).")
    except Exception as e:
        protocol.log("sim alarm ALSO failed; drain loop NOT started.\n{0}\n{1}".format(
            e, traceback.format_exc()))


def _on_zone_loaded(zone_obj):
    """Runs on the MAIN THREAD right after a zone spins up. Writes an immediate
    heartbeat, starts the repeating drain, and drains once so the first request
    after load is handled promptly. Never raises."""
    try:
        protocol.write_heartbeat(
            0, state.zone_is_loaded(), state.active_sim_name())
    except Exception:
        pass
    _start_drain_loop(_ALARM_OWNER)
    try:
        drain()
    except Exception:
        pass


def _install_menu_hook():
    """Add a SECOND drain source that services commands at the MAIN MENU, before
    any save is loaded.

    The in-zone drain (zone spin-up hook + real-time alarm, see install() below)
    only runs once a zone exists. To answer commands pre-zone we wrap
    `areaserver.c_api_server_tick(absolute_ticks)` -- a module-level, per-frame,
    MAIN-THREAD tick that the game fires even at the menu (verified from the
    game's areaserver bytecode: a top-level function, single positional arg).
    Unlike `core_services` (not importable) and alarms (timeline torn down at the
    menu), this tick is live pre-zone. The wrapper calls drain() (wall-clock
    throttled, so the ~30-60 Hz frame rate costs ~2 real drains/sec) then defers
    to the original.

    `areaserver` may or may not be importable this early (core_services wasn't),
    so we just attempt + log honestly; we never crash. Idempotent via a marker
    attr on the wrapper and the module-level _menu_hook_installed flag.

    The two log lines below are read VERBATIM by the live experiment -- keep them
    stable.
    """
    global _menu_hook_installed
    if _menu_hook_installed:
        return
    try:
        import areaserver
    except Exception as e:
        protocol.log(
            "areaserver unavailable at import; menu hook NOT installed: "
            "{0}".format(e))
        return
    try:
        original = getattr(areaserver, "c_api_server_tick", None)
        if original is None:
            protocol.log(
                "areaserver has no c_api_server_tick; menu hook NOT installed.")
            return
        if getattr(original, "_s4ctl_menu_patched", False):
            _menu_hook_installed = True
            return  # already wrapped (module re-imported)

        @functools.wraps(original)
        def patched(*args, **kwargs):
            # drain() is wall-clock throttled and never raises, but guard anyway
            # so a bug here can never disturb the game's per-frame server tick.
            try:
                drain()
            except Exception:
                pass
            return original(*args, **kwargs)

        patched._s4ctl_menu_patched = True
        patched._s4ctl_original = original
        areaserver.c_api_server_tick = patched
        _menu_hook_installed = True
        protocol.log("menu drain hook installed: areaserver.c_api_server_tick")
    except Exception as e:
        protocol.log(
            "areaserver unavailable at import; menu hook NOT installed: "
            "{0}\n{1}".format(e, traceback.format_exc()))


def install():
    """Install BOTH drain sources, idempotently, never raising:

      1. the MAIN-MENU hook (areaserver.c_api_server_tick) so commands are
         serviced pre-zone (see _install_menu_hook), and
      2. the IN-ZONE hook (zone.Zone.do_zone_spin_up) that starts the repeating
         real-time alarm once a zone has spun up.

    Both are attempted on every call; one failing never blocks the other."""
    global _zone_hook_installed
    # (1) Menu drain source first -- it's the only thing that works pre-zone, and
    # attempting it must not depend on the zone hook below succeeding.
    _install_menu_hook()
    if _zone_hook_installed:
        return
    try:
        import zone
    except Exception as e:
        protocol.log("zone module unavailable; bridge NOT installed: {0}".format(e))
        return
    try:
        original = zone.Zone.do_zone_spin_up
        if getattr(original, "_s4ctl_patched", False):
            _zone_hook_installed = True
            return  # already wrapped (module re-imported)

        @functools.wraps(original)
        def patched(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            try:
                _on_zone_loaded(self)
            except Exception:
                try:
                    protocol.log("_on_zone_loaded error:\n{0}".format(
                        traceback.format_exc()))
                except Exception:
                    pass
            return result

        patched._s4ctl_patched = True
        patched._s4ctl_original = original
        zone.Zone.do_zone_spin_up = patched
        _zone_hook_installed = True
        protocol.log("zone spin-up hook installed (bridge v{0}).".format(
            protocol.BRIDGE_VERSION))
    except Exception as e:
        protocol.log("failed to install zone hook: {0}\n{1}".format(
            e, traceback.format_exc()))
