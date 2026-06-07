"""cli.py — the ``sims4ctl`` command-line entry point.

Subcommands (see _BUILD_SPEC.md "Host CLI commands"):

  ping                         round-trip the bridge; print pong + zone state
  cmd "<cheat>"                run a cheat via the bridge
  eval "<code>" [--exec]       eval (default) or exec arbitrary Python in-game
  state [topic] [--career N]   structured live state (career/skills/.../all)
  advance <4h|30m|2h30m>       fast-forward game time
  crashes [--mark|--since-mark]  bridge-free crash-log diff
  install                      build the bridge .ts4script and copy to <MODS>
  launch                       start TS4_x64.exe
  doctor                       print resolved paths + heartbeat freshness

Recipe B autonomous-loop commands (see docs/RECIPE_B.md). These drive the
menu->loaded-save gap that has NO in-game Python API by launching the game and
synthesizing mouse clicks against CONFIGURABLE targets:

  start                        launch TS4 and wait for the main MENU
  stop [--save]                save (best-effort) then terminate TS4_x64.exe
  load-save [--continue|--slot N]  focus window, dismiss MODS dialog, click
                               Continue/Load, wait for ZONE_LOADED
  new-game                     click 'Neues Spiel' (optional/stub)
  run-scenario <name> [--auto] run scenarios/<name>.py (with --auto: ensure a
                               zone is loaded first)
  wait-for <state> [--timeout] block until DOWN/MENU/LOADING/ZONE_LOADED
  state [--menu-aware]         (extended) report the gamestate, not just in-zone
  calibrate                    capture the window + print rect/size for deriving
                               click coordinates (NO clicking)

Global ``--json`` prints the raw JSON result of a command instead of the
human-readable rendering. Global ``--userdata PATH`` overrides the Sims 4
user-data folder (also honoured via the SIMS4CTL_USERDATA env var) so the CLI
runs in tests/CI with no game installed.

Exit codes: 0 success; non-zero on any assertion-style failure (timeout,
``ok=false``, unresolved paths, build/launch failure) so scripts and CI can
gate on ``sims4ctl <cmd>``.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import gamepaths
from .client import BridgeError, BridgeTimeout, Client
from .crashwatch import CrashWatch

# Path to the bridge build script (Slice "build/"). Resolved relative to this
# file: host/sims4ctl/cli.py -> ../../build/build.py
_BUILD_SCRIPT = Path(__file__).resolve().parents[2] / "build" / "build.py"

# How stale a heartbeat can be before doctor flags it (seconds). The bridge
# refreshes ~2x/sec, so anything older than a few seconds means it isn't ticking.
HEARTBEAT_FRESH_S = 5.0


class CliError(Exception):
    """A user-facing failure that maps to a non-zero exit code."""


# ---------------------------------------------------------------------------
# duration parsing for `advance`
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*$", re.IGNORECASE)


def parse_duration(text):
    """Parse ``4h`` / ``30m`` / ``2h30m`` -> ``(hours, minutes)`` ints.

    At least one of hours/minutes must be present and the total must be > 0.
    Raises :class:`CliError` on anything unparseable so the CLI exits non-zero
    with a clear message rather than silently advancing zero time.
    """
    if text is None:
        raise CliError("advance requires a duration like 4h, 30m, or 2h30m")
    m = _DURATION_RE.match(text)
    if not m or (m.group(1) is None and m.group(2) is None):
        raise CliError(
            "bad duration {0!r}; expected forms like 4h, 30m, 2h30m".format(text)
        )
    hours = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2)) if m.group(2) else 0
    if hours == 0 and minutes == 0:
        raise CliError("duration {0!r} is zero; nothing to advance".format(text))
    return hours, minutes


# ---------------------------------------------------------------------------
# output helpers
# ---------------------------------------------------------------------------

def _emit(args, payload, human):
    """Print ``payload`` as JSON when ``--json``, else the ``human`` string."""
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(human)


def _make_client(args):
    """Build a :class:`Client` from the resolved bridge dir, or raise CliError."""
    bridge_dir = gamepaths.find_bridge_dir(args.userdata)
    if bridge_dir is None:
        raise CliError(
            "could not resolve <USERDATA>/sims4ctl/. Pass --userdata or set "
            "SIMS4CTL_USERDATA (and make sure the game has run at least once)."
        )
    return Client(bridge_dir, poll_interval=args.poll_interval)


# ---------------------------------------------------------------------------
# subcommand handlers (each returns an int exit code)
# ---------------------------------------------------------------------------

def cmd_ping(args):
    client = _make_client(args)
    result = client.send("ping", {}, timeout=args.timeout)
    human = "pong  zone_loaded={0} active_sim={1} bridge_version={2}".format(
        result.get("zone_loaded") if isinstance(result, dict) else None,
        result.get("active_sim") if isinstance(result, dict) else None,
        result.get("bridge_version") if isinstance(result, dict) else None,
    )
    _emit(args, result, human)
    return 0


def cmd_cmd(args):
    client = _make_client(args)
    result = client.send("cmd", {"command": args.command}, timeout=args.timeout)
    output = result.get("output") if isinstance(result, dict) else None
    human = "executed: {0}".format(args.command)
    if output:
        human += "\n{0}".format(output)
    _emit(args, result, human)
    return 0


def cmd_eval(args):
    client = _make_client(args)
    mode = "exec" if args.exec_mode else "eval"
    result = client.send(
        "eval", {"code": args.code, "mode": mode}, timeout=args.timeout
    )
    if mode == "exec":
        human = result.get("stdout", "") if isinstance(result, dict) else str(result)
    else:
        human = result.get("repr", "") if isinstance(result, dict) else str(result)
    _emit(args, result, human)
    return 0


def cmd_state(args):
    # Menu-aware mode: report the file+process+window state machine (DOWN/MENU/
    # LOADING/ZONE_LOADED) instead of asking the bridge for in-zone state. This
    # works with NO bridge response (the game may be at the menu) and never
    # blocks on a bridge timeout.
    if getattr(args, "menu_aware", False):
        from .gamestate import GameState

        gs = GameState(userdata=args.userdata)
        snap = gs.snapshot()
        human = "state={0}  process_running={1} zone_loaded={2} " \
                "heartbeat_fresh={3} active_sim={4}".format(
                    snap["state"], snap["process_running"], snap["zone_loaded"],
                    snap["heartbeat_fresh"], snap["active_sim"],
                )
        _emit(args, snap, human)
        return 0

    client = _make_client(args)
    send_args = {"topic": args.topic}
    if args.career:
        send_args["career"] = args.career
    result = client.send("state", send_args, timeout=args.timeout)
    _emit(args, result, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_advance(args):
    hours, minutes = parse_duration(args.duration)
    client = _make_client(args)
    send_args = {}
    if hours:
        send_args["hours"] = hours
    if minutes:
        send_args["minutes"] = minutes
    result = client.send("advance", send_args, timeout=args.timeout)
    human = "advanced +{0}h{1}m -> clock {2}".format(
        hours,
        minutes,
        result.get("now") if isinstance(result, dict) else result,
    )
    _emit(args, result, human)
    return 0


def cmd_crashes(args):
    """Bridge-free crash-log diff. ``--mark`` sets a baseline; ``--since-mark``
    (the default) reports logs new/changed since it. Exits non-zero when new
    crashes are found so CI can gate on a clean run."""
    userdata = gamepaths.find_userdata(args.userdata)
    if userdata is None:
        raise CliError(
            "could not resolve the Sims 4 user folder. Pass --userdata or set "
            "SIMS4CTL_USERDATA."
        )
    watch = CrashWatch(userdata)
    if args.mark:
        snap = watch.mark()
        _emit(
            args,
            {"marked": sorted(snap.keys())},
            "marked baseline: {0} crash log(s)".format(len(snap)),
        )
        return 0
    # default + explicit --since-mark: report the diff
    new = watch.since_mark()
    _emit(
        args,
        {"new_or_changed": new, "count": len(new)},
        "no new crash logs since mark"
        if not new
        else "NEW/CHANGED crash logs ({0}): {1}".format(len(new), ", ".join(new)),
    )
    # Non-zero when crashes were found so a test script fails loudly.
    return 1 if new else 0


def cmd_install(args):
    """Build the bridge .ts4script (delegates to build/build.py) and copy it to
    ``<MODS>/sims4ctl/``."""
    if not _BUILD_SCRIPT.is_file():
        raise CliError("build script not found at {0}".format(_BUILD_SCRIPT))
    mods = gamepaths.find_mods(args.userdata)
    if mods is None:
        raise CliError(
            "could not resolve the Mods folder. Pass --userdata or set "
            "SIMS4CTL_USERDATA."
        )

    # 1. Build.
    proc = subprocess.run(
        [sys.executable, str(_BUILD_SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    if proc.stdout:
        sys.stderr.write(proc.stdout)
    if proc.returncode != 0:
        raise CliError("bridge build failed (exit {0})".format(proc.returncode))

    # 2. Locate the produced artifact and copy it to <MODS>/sims4ctl/.
    out_dir = _BUILD_SCRIPT.parent / "out"
    artifacts = sorted(out_dir.glob("*.ts4script")) if out_dir.is_dir() else []
    if not artifacts:
        raise CliError(
            "build produced no .ts4script in {0}".format(out_dir)
        )
    dest_dir = mods / "sims4ctl"
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for art in artifacts:
        dest = dest_dir / art.name
        shutil.copy2(str(art), str(dest))
        copied.append(str(dest))
    _emit(
        args,
        {"installed": copied},
        "installed bridge:\n  " + "\n  ".join(copied),
    )
    return 0


def cmd_launch(args):
    """Start ``TS4_x64.exe`` (default Steam Bin path). Does not wait for the
    game; returns once the process is spawned."""
    exe = gamepaths.find_ts4_exe()
    if exe is None:
        raise CliError(
            "TS4_x64.exe not found at the default Steam path ({0}). The game "
            "may be installed elsewhere; launch it manually.".format(
                gamepaths.DEFAULT_TS4_EXE
            )
        )
    # Detached: we don't want to block the CLI on the game's lifetime.
    subprocess.Popen([str(exe)], cwd=str(exe.parent))
    _emit(args, {"launched": str(exe)}, "launched {0}".format(exe))
    return 0


def cmd_doctor(args):
    """Print resolved USERDATA/Mods/bridge paths and heartbeat freshness."""
    info = gamepaths.resolve_all(args.userdata)
    ud = info["userdata"]

    hb = None
    hb_age = None
    bridge_dir = info["bridge_dir"]
    if bridge_dir is not None:
        client = Client(bridge_dir, poll_interval=args.poll_interval)
        hb = client.read_heartbeat()
        hb_age = client.heartbeat_age()

    fresh = hb_age is not None and 0 <= hb_age <= HEARTBEAT_FRESH_S

    payload = {
        "userdata": str(ud) if ud else None,
        "userdata_source": info["userdata_source"],
        "userdata_exists": bool(ud and Path(ud).is_dir()),
        "mods": str(info["mods"]) if info["mods"] else None,
        "bridge_dir": str(bridge_dir) if bridge_dir else None,
        "bridge_dir_exists": bool(bridge_dir and Path(bridge_dir).is_dir()),
        "ts4_exe": str(info["ts4_exe"]) if info["ts4_exe"] else None,
        "heartbeat": hb,
        "heartbeat_age_s": round(hb_age, 2) if hb_age is not None else None,
        "heartbeat_fresh": fresh,
    }

    lines = [
        "USERDATA    : {0}  ({1}{2})".format(
            payload["userdata"],
            payload["userdata_source"],
            "" if payload["userdata_exists"] else ", MISSING",
        ),
        "MODS        : {0}".format(payload["mods"]),
        "BRIDGE DIR  : {0}{1}".format(
            payload["bridge_dir"],
            "" if payload["bridge_dir_exists"] else "  (not created yet)",
        ),
        "TS4 EXE     : {0}".format(payload["ts4_exe"] or "not found at Steam path"),
    ]
    if hb is None:
        lines.append("HEARTBEAT   : none (bridge not running / game closed)")
    else:
        lines.append(
            "HEARTBEAT   : age={0}s fresh={1} tick={2} zone_loaded={3} "
            "active_sim={4} version={5}".format(
                payload["heartbeat_age_s"],
                fresh,
                hb.get("tick"),
                hb.get("zone_loaded"),
                hb.get("active_sim"),
                hb.get("bridge_version"),
            )
        )
    _emit(args, payload, "\n".join(lines))
    # doctor is informational; it succeeds even when the game is closed so it
    # can be run as a setup check. Only a wholly unresolved USERDATA is fatal.
    return 0 if ud is not None else 1


# ---------------------------------------------------------------------------
# Recipe B: autonomous-loop commands (launch -> dismiss dialog -> click ->
# wait -> run -> quit). See docs/RECIPE_B.md. The MECHANISM lives in
# winauto/gamestate/saves/automation_config; these handlers wire it into the CLI.
# ---------------------------------------------------------------------------

def _game_state(args):
    """Construct a GameState from the CLI args (shared by start/stop/wait-for)."""
    from .gamestate import GameState

    return GameState(userdata=args.userdata)


def cmd_start(args):
    """Launch TS4 (steam://rungameid/<appid> preferred, raw exe fallback) then
    block until the main MENU is reachable.

    Reads the appid from the game's ``steam_appid.txt`` (falling back to the
    known default) so the Steam/EA entitlement bridge negotiates correctly. The
    raw-exe path only works when EA Desktop is already up; the steam URL lets
    Steam start the whole stack. ``--exe`` forces the raw path.
    """
    from .gamestate import MENU, StateTimeout

    exe = gamepaths.find_ts4_exe()  # raw-exe fallback / --exe target
    launched = None

    if not args.exe:
        appid = gamepaths.find_steam_appid()
        url = "steam://rungameid/{0}".format(appid)
        try:
            # os.startfile is the reliable Windows way to hand a URL to Steam.
            if hasattr(os, "startfile"):
                os.startfile(url)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["cmd", "/c", "start", "", url])
            launched = url
        except OSError as e:
            # Fall back to the raw exe if the steam handler isn't available.
            if exe is None:
                raise CliError(
                    "could not launch via {0} ({1}) and TS4_x64.exe was not found "
                    "at {2}".format(url, e, gamepaths.DEFAULT_TS4_EXE)
                )
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
            launched = str(exe)
    else:
        if exe is None:
            raise CliError(
                "TS4_x64.exe not found at {0}; cannot honour --exe".format(
                    gamepaths.DEFAULT_TS4_EXE
                )
            )
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
        launched = str(exe)

    gs = _game_state(args)
    try:
        snap = gs.wait_for(MENU, timeout=args.timeout, poll=args.poll)
    except StateTimeout as e:
        raise CliError(
            "launched {0} but the main menu never came up: {1}".format(launched, e)
        )
    _emit(
        args,
        {"launched": launched, "state": snap["state"], "snapshot": snap},
        "launched {0}; reached state {1}".format(launched, snap["state"]),
    )
    return 0


def cmd_stop(args):
    """Best-effort save (with --save) then terminate TS4_x64.exe.

    With ``--save`` and a loaded zone, ask the bridge to save via the ``cmd``
    verb (``save`` console command) before killing -- TS4 does NOT autosave on
    exit, and killing mid-save corrupts the active slot, so we save first and
    only then taskkill. The kill tries a graceful ``taskkill /IM`` and escalates
    to ``/F`` if the process is still up.
    """
    from .gamestate import ZONE_LOADED, is_process_running

    saved = False
    if args.save:
        gs = _game_state(args)
        if gs.current_state() == ZONE_LOADED:
            try:
                client = _make_client(args)
                # The bridge `cmd` verb runs a cheat/console command on the main
                # thread; `save` triggers persistence.save_game for the active
                # slot. Best-effort: a failure here must not block the kill.
                client.send("cmd", {"command": "save"}, timeout=args.timeout)
                saved = True
            except (BridgeError, BridgeTimeout, CliError) as e:
                sys.stderr.write("warning: in-game save failed: {0}\n".format(e))
        else:
            sys.stderr.write(
                "warning: --save requested but no zone is loaded; skipping save\n"
            )

    killed = _terminate_ts4()
    payload = {"saved": saved, "killed": killed,
               "still_running": is_process_running()}
    human = "{0}terminated TS4_x64.exe (killed={1})".format(
        "saved + " if saved else "", killed
    )
    _emit(args, payload, human)
    # Non-zero if the process somehow survived both kill attempts.
    return 0 if not payload["still_running"] else 1


def _terminate_ts4():
    """taskkill TS4_x64.exe, escalating to /F. Returns True if a kill ran.

    On non-Windows (no taskkill) this is a no-op returning False.
    """
    if os.name != "nt":
        return False
    image = "TS4_x64.exe"
    # Graceful first.
    subprocess.run(["taskkill", "/IM", image],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Force if still present.
    from .gamestate import is_process_running

    if is_process_running(image):
        subprocess.run(["taskkill", "/F", "/IM", image],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _find_window_or_raise(config):
    """Find the game window using the config's title substring, or CliError."""
    from . import winauto

    title = config.get("window_title_substr", "Sims")
    try:
        window = winauto.find_game_window(title)
    except winauto.AutomationDepsMissing as e:
        raise CliError(str(e))
    if window is None:
        raise CliError(
            "no game window matching {0!r} found; is the game at the main menu "
            "and is its window visible?".format(title)
        )
    return window


def _focus_and_click_target(config, window, target, label, settle):
    """Focus the window, resolve a target to (x,y), and click it.

    Returns the clicked (x, y), or raises CliError if the target can't be
    resolved (no template match and no normalized fallback).
    """
    import time as _time

    from . import automation_config as acfg
    from . import winauto

    # Re-assert foreground right before the click (focus can be stolen between
    # steps); retry per the configured count.
    for _ in range(max(1, int(config.get("focus_retries", 3)))):
        if winauto.focus_window(window["hwnd"]):
            break
        _time.sleep(0.2)

    xy = acfg.resolve_target_xy(config, target, window, winauto)
    if xy is None:
        raise CliError(
            "could not resolve click target {0!r}: no template match and no "
            "normalized fallback. Calibrate it (sims4ctl calibrate) and update "
            "the automation config.".format(label)
        )
    winauto.click(xy[0], xy[1])
    _time.sleep(settle)
    return xy


def cmd_load_save(args):
    """Recipe B: focus the window, optionally dismiss the MODS dialog, click
    Continue (or Load->slot->confirm), then wait for ZONE_LOADED.

    Default is ``--continue`` (single click of 'Spiel fortsetzen', the most-
    recent save). ``--slot N`` instead clicks 'Spiel laden', the slot's
    thumbnail, then the confirm button. All click targets come from
    automation_config.json and are CONFIGURABLE / calibratable.
    """
    from . import automation_config as acfg
    from .gamestate import ZONE_LOADED, StateTimeout

    try:
        config = acfg.load_config(args.config)
    except acfg.ConfigError as e:
        raise CliError(str(e))

    window = _find_window_or_raise(config)
    settle = float(config.get("click_settle_seconds", 0.4))
    actions = []

    # 1. Dismiss the startup MODS dialog if configured + enabled. Best-effort:
    #    if it isn't on screen the template misses and (for a template-only
    #    target) we skip; a normalized-only dismiss always clicks, which is
    #    harmless on the menu.
    if not args.no_dismiss:
        try:
            dismiss = acfg.get_target(config, "mods_dialog_dismiss")
        except acfg.ConfigError:
            dismiss = None
        if dismiss and dismiss.get("enabled", True):
            try:
                xy = _focus_and_click_target(
                    config, window, dismiss, "mods_dialog_dismiss", settle
                )
                actions.append({"dismiss_mods_dialog": list(xy)})
            except CliError as e:
                # A missing dialog must not fail the load; just note it.
                sys.stderr.write("note: MODS-dialog dismiss skipped: {0}\n".format(e))

    # 2. Click Continue, or walk the Load-Game picker for an explicit slot.
    if args.slot is None:
        cont = acfg.get_target(config, "continue")
        xy = _focus_and_click_target(config, window, cont, "continue", settle)
        actions.append({"continue": list(xy)})
    else:
        load = acfg.get_target(config, "load_game")
        xy = _focus_and_click_target(config, window, load, "load_game", settle)
        actions.append({"load_game": list(xy)})
        slot_t = acfg.get_slot_target(config, args.slot)
        xy = _focus_and_click_target(
            config, window, slot_t, "save_slots[{0}]".format(args.slot), settle
        )
        actions.append({"slot_{0}".format(args.slot): list(xy)})
        confirm = acfg.get_target(config, "load_confirm")
        xy = _focus_and_click_target(config, window, confirm, "load_confirm", settle)
        actions.append({"load_confirm": list(xy)})

    # 3. Wait for the bridge to report a fresh loaded zone.
    gs = _game_state(args)
    try:
        snap = gs.wait_for(ZONE_LOADED, timeout=args.timeout, poll=args.poll)
    except StateTimeout as e:
        raise CliError(
            "clicked to load but ZONE_LOADED never arrived: {0}. The click "
            "targets may need calibration (sims4ctl calibrate).".format(e)
        )
    _emit(
        args,
        {"actions": actions, "state": snap["state"], "snapshot": snap},
        "loaded save; state {0} active_sim={1}".format(
            snap["state"], snap.get("active_sim")
        ),
    )
    return 0


def cmd_new_game(args):
    """Optional: click 'Neues Spiel' (New Game) on the main menu.

    Stub-ish: clicks the configured New-Game target and returns. It does NOT
    drive CAS to a loaded zone (that path is multi-screen and out of scope for
    the scaffold); a follow-up would wait for ZONE_LOADED after finishing CAS.
    """
    from . import automation_config as acfg

    try:
        config = acfg.load_config(args.config)
    except acfg.ConfigError as e:
        raise CliError(str(e))
    window = _find_window_or_raise(config)
    settle = float(config.get("click_settle_seconds", 0.4))
    target = acfg.get_target(config, "new_game")
    xy = _focus_and_click_target(config, window, target, "new_game", settle)
    _emit(
        args,
        {"clicked": {"new_game": list(xy)}},
        "clicked New Game at {0} (CAS is not automated by this scaffold)".format(xy),
    )
    return 0


def cmd_run_scenario(args):
    """Run ``scenarios/<name>.py`` against the running game.

    With ``--auto`` the loop is self-bootstrapping: if no zone is loaded it runs
    ``start`` then ``load-save --continue`` first, so the scenario always finds a
    loaded zone. Without ``--auto`` it just runs the scenario and lets it report
    its own preflight failure if no zone is loaded. Exit code is the scenario's.
    """
    from .gamestate import DOWN, MENU, ZONE_LOADED

    scenario_path = _SCENARIOS_DIR / "{0}.py".format(args.name)
    if not scenario_path.is_file():
        raise CliError(
            "scenario {0!r} not found at {1}".format(args.name, scenario_path)
        )

    if args.auto:
        gs = _game_state(args)
        state = gs.current_state()
        if state == DOWN:
            rc = cmd_start(args)
            if rc != 0:
                return rc
            state = MENU
        if state != ZONE_LOADED:
            # Reuse the load-save handler with continue semantics.
            args.slot = getattr(args, "slot", None)
            args.no_dismiss = getattr(args, "no_dismiss", False)
            args.config = getattr(args, "config", None)
            rc = cmd_load_save(args)
            if rc != 0:
                return rc

    # Run the scenario as a child process so its argparse/exit code are honoured
    # and a scenario crash can't take down the CLI.
    cmd = [sys.executable, str(scenario_path)]
    if args.userdata:
        cmd += ["--userdata", args.userdata]
    proc = subprocess.run(cmd)
    _emit(
        args,
        {"scenario": args.name, "exit_code": proc.returncode},
        "scenario {0} exited {1}".format(args.name, proc.returncode),
    )
    return proc.returncode


def cmd_wait_for(args):
    """Block until the game reaches ``state`` (DOWN/MENU/LOADING/ZONE_LOADED)."""
    from .gamestate import ALL_STATES, StateTimeout

    want = args.state.upper()
    if want not in ALL_STATES:
        raise CliError(
            "unknown state {0!r}; expected one of {1}".format(
                args.state, ", ".join(ALL_STATES)
            )
        )
    gs = _game_state(args)
    try:
        snap = gs.wait_for(want, timeout=args.timeout, poll=args.poll)
    except StateTimeout as e:
        raise CliError(str(e))
    _emit(args, snap, "reached state {0}".format(snap["state"]))
    return 0


def cmd_calibrate(args):
    """Orchestrator helper: capture the game window + print its geometry.

    Prints the window title, the client rect (screen coords), width/height, and a
    DPI/coordinate-space diagnostic so the orchestrator can confirm that capture
    size == client size == physical pixels (they all agree once the process is
    per-monitor DPI aware -- e.g. ~1920x1080, NOT a scaled 1348x758). Optionally
    writes a full-window PNG (``--out``). With ``--crop label left top right
    bottom`` (image-local pixels, repeatable) it also saves button-template crops
    into the config's templates dir. NO clicking ever happens here.
    """
    from . import automation_config as acfg
    from . import winauto

    # DPI awareness must already be set (cli.main + winauto import both do it);
    # re-assert defensively and record the resolved mode for the diagnostic.
    dpi_result = winauto.ensure_dpi_aware()

    try:
        config = acfg.load_config(args.config)
    except acfg.ConfigError as e:
        raise CliError(str(e))

    window = _find_window_or_raise(config)
    vmetrics = winauto.virtual_screen_metrics()
    dpi_scale = winauto.window_dpi_scale(window["hwnd"])
    payload = {
        "title": window["title"],
        "hwnd": window["hwnd"],
        "client_rect": list(window["client_rect"]),
        "width": window["width"],
        "height": window["height"],
        "deps": winauto.deps_status(),
        "dpi": {
            "awareness": dpi_result,
            "virtual_screen": list(vmetrics) if vmetrics else None,
            "window_scale": dpi_scale,
        },
        "capture_size": None,
        "captured_png": None,
        "templates": [],
    }

    # Always capture the client area (cheap) so the diagnostic can report the
    # captured image size for the space-agreement check; keep the PNG only if
    # asked. Crops also need the image.
    image = None
    try:
        image = winauto.capture(window["client_rect"])
    except winauto.AutomationDepsMissing as e:
        # No mss/numpy: can't capture, but still print the geometry + DPI report.
        if args.out or args.crop:
            raise CliError(str(e))
    if image is not None:
        h, w = image.shape[:2]
        payload["capture_size"] = [int(w), int(h)]
        if args.out:
            winauto.save_png(image, args.out)
            payload["captured_png"] = str(args.out)

    # Optional template crops: each --crop is LABEL L T R B in client-local px.
    if args.crop:
        tdir = acfg.templates_dir(config)
        tdir.mkdir(parents=True, exist_ok=True)
        for spec in args.crop:
            if len(spec) != 5:
                raise CliError(
                    "--crop expects LABEL LEFT TOP RIGHT BOTTOM; got {0}".format(spec)
                )
            label = spec[0]
            try:
                box = tuple(int(v) for v in spec[1:])
            except ValueError:
                raise CliError("--crop coords must be integers: {0}".format(spec))
            crop_img = winauto.crop(image, box)
            out_path = tdir / "{0}.png".format(label)
            winauto.save_png(crop_img, str(out_path))
            payload["templates"].append(str(out_path))

    # Space-agreement verdict: capture size SHOULD equal the client size now that
    # everything is physical pixels. A mismatch means the process is still
    # DPI-scaled somewhere (capture would be ~1.5x the logical client rect).
    vm = payload["dpi"]["virtual_screen"]
    cap = payload["capture_size"]
    scale = payload["dpi"]["window_scale"]
    if cap is None:
        agree = "n/a (no mss/numpy; install sims4ctl[automation] to verify)"
    elif cap == [payload["width"], payload["height"]]:
        agree = "OK  capture {0}x{1} == client {2}x{3} (same physical space)".format(
            cap[0], cap[1], payload["width"], payload["height"]
        )
    else:
        agree = (
            "MISMATCH  capture {0}x{1} != client {2}x{3} -- coordinate spaces "
            "disagree (still DPI-scaled?)".format(
                cap[0], cap[1], payload["width"], payload["height"]
            )
        )

    human = (
        "window  : {0!r} (hwnd={1})\n"
        "client  : rect={2} size={3}x{4}\n"
        "dpi     : awareness={5}\n"
        "          virtual_screen={6}  window_scale={7}\n"
        "capture : size={8}\n"
        "spaces  : {9}\n"
        "deps    : {10}".format(
            payload["title"], payload["hwnd"], payload["client_rect"],
            payload["width"], payload["height"],
            payload["dpi"]["awareness"],
            vm, ("{0:.2f}x".format(scale) if scale else "unknown"),
            cap, agree,
            payload["deps"],
        )
    )
    if payload["captured_png"]:
        human += "\npng     : {0}".format(payload["captured_png"])
    if payload["templates"]:
        human += "\ntemplates:\n  " + "\n  ".join(payload["templates"])
    _emit(args, payload, human)
    return 0


# ---------------------------------------------------------------------------
# argument parser
# ---------------------------------------------------------------------------

# scenarios/ lives at the repo root: host/sims4ctl/cli.py -> ../../scenarios
_SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"


def build_parser():
    p = argparse.ArgumentParser(
        prog="sims4ctl",
        description="Drive & inspect a running The Sims 4 from outside.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="print the raw JSON result instead of human-readable text",
    )
    p.add_argument(
        "--userdata",
        default=None,
        help="override the Sims 4 user-data folder (else $SIMS4CTL_USERDATA "
        "or auto-detect)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="bridge response timeout in seconds (default 15)",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=0.1,
        help="how often to poll response.json, in seconds (default 0.1)",
    )
    p.add_argument(
        "--poll",
        type=float,
        default=1.0,
        help="how often to re-check the game STATE machine, in seconds "
        "(default 1.0; used by start/stop/load-save/wait-for)",
    )

    sub = p.add_subparsers(dest="cmd")
    sub.required = True  # py3.8: set after creation for a clear error

    sub.add_parser("ping", help="round-trip the bridge").set_defaults(func=cmd_ping)

    sp = sub.add_parser("cmd", help="run a cheat command in-game")
    sp.add_argument("command", help="the cheat string, e.g. 'stats.fill_commodities'")
    sp.set_defaults(func=cmd_cmd)

    sp = sub.add_parser("eval", help="eval/exec Python in-game (dev only)")
    sp.add_argument("code", help="Python source to evaluate")
    sp.add_argument(
        "--exec",
        dest="exec_mode",
        action="store_true",
        help="exec (statements) instead of eval (expression)",
    )
    sp.set_defaults(func=cmd_eval)

    sp = sub.add_parser("state", help="dump structured live game state")
    sp.add_argument(
        "topic",
        nargs="?",
        default="all",
        choices=["career", "skills", "traits", "sim", "clock", "all"],
        help="which slice of state (default: all)",
    )
    sp.add_argument("--career", default=None, help="restrict career state to NAME")
    sp.add_argument(
        "--menu-aware",
        dest="menu_aware",
        action="store_true",
        help="report the gamestate (DOWN/MENU/LOADING/ZONE_LOADED) instead of "
        "in-zone state; works with no bridge and never blocks on a timeout",
    )
    sp.set_defaults(func=cmd_state)

    sp = sub.add_parser("advance", help="fast-forward game time")
    sp.add_argument("duration", help="duration like 4h, 30m, or 2h30m")
    sp.set_defaults(func=cmd_advance)

    sp = sub.add_parser("crashes", help="diff crash logs (no bridge needed)")
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument(
        "--mark", action="store_true", help="record the current logs as baseline"
    )
    grp.add_argument(
        "--since-mark",
        action="store_true",
        help="report logs new/changed since the mark (default)",
    )
    sp.set_defaults(func=cmd_crashes)

    sub.add_parser(
        "install", help="build the bridge and copy it to <MODS>/sims4ctl/"
    ).set_defaults(func=cmd_install)

    sub.add_parser("launch", help="start TS4_x64.exe").set_defaults(func=cmd_launch)

    sub.add_parser(
        "doctor", help="print resolved paths + heartbeat freshness"
    ).set_defaults(func=cmd_doctor)

    # -- Recipe B autonomous-loop commands ----------------------------------

    sp = sub.add_parser("start", help="launch TS4 and wait for the main MENU")
    sp.add_argument(
        "--exe",
        action="store_true",
        help="force launching the raw TS4_x64.exe instead of steam://rungameid "
        "(only works if EA Desktop is already running)",
    )
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("stop", help="terminate TS4_x64.exe (optionally save first)")
    sp.add_argument(
        "--save",
        action="store_true",
        help="best-effort in-game save via the bridge before killing (a zone "
        "must be loaded; TS4 does not autosave on exit)",
    )
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser(
        "load-save",
        help="click out of the menu into a loaded save, then wait for ZONE_LOADED",
    )
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument(
        "--continue",
        dest="continue_",
        action="store_true",
        help="click 'Spiel fortsetzen' = load the most-recent save (default)",
    )
    grp.add_argument(
        "--slot",
        type=int,
        default=None,
        help="instead open 'Spiel laden' and load this slot id (decimal)",
    )
    sp.add_argument(
        "--no-dismiss",
        action="store_true",
        help="do NOT attempt to dismiss the startup MODS dialog first",
    )
    sp.add_argument(
        "--config",
        default=None,
        help="path to an automation config JSON (else $SIMS4CTL_AUTOMATION_CONFIG "
        "or the shipped default)",
    )
    sp.set_defaults(func=cmd_load_save)

    sp = sub.add_parser("new-game", help="click 'Neues Spiel' (optional/stub)")
    sp.add_argument("--config", default=None, help="path to an automation config JSON")
    sp.set_defaults(func=cmd_new_game)

    sp = sub.add_parser("run-scenario", help="run scenarios/<name>.py")
    sp.add_argument("name", help="scenario module name (without .py)")
    sp.add_argument(
        "--auto",
        action="store_true",
        help="ensure ZONE_LOADED first (start + load-save --continue as needed)",
    )
    sp.add_argument(
        "--config", default=None, help="path to an automation config JSON (for --auto)"
    )
    sp.set_defaults(func=cmd_run_scenario, slot=None, no_dismiss=False)

    sp = sub.add_parser("wait-for", help="block until a gamestate is reached")
    sp.add_argument(
        "state",
        help="target state: DOWN, MENU, LOADING, or ZONE_LOADED (case-insensitive)",
    )
    sp.set_defaults(func=cmd_wait_for)

    sp = sub.add_parser(
        "calibrate",
        help="capture the window + print rect/size (no clicking); --out PNG, "
        "--crop LABEL L T R B to save template crops",
    )
    sp.add_argument(
        "--out", default=None, help="write the captured client area to this PNG"
    )
    sp.add_argument(
        "--crop",
        nargs=5,
        action="append",
        metavar=("LABEL", "L", "T", "R", "B"),
        help="save a template crop: LABEL LEFT TOP RIGHT BOTTOM (client-local "
        "pixels); repeatable",
    )
    sp.add_argument("--config", default=None, help="path to an automation config JSON")
    sp.set_defaults(func=cmd_calibrate)

    return p


def main(argv=None):
    """Entry point. Returns/sets an int exit code; never lets an expected
    failure escape as a traceback."""
    # Establish per-monitor DPI awareness as the very first thing, before any
    # window/coords/capture call, so all coordinate spaces (mss capture,
    # GetClientRect, the SendInput virtual-screen mapping, template matches) live
    # in the same PHYSICAL-pixel space. Never raises; idempotent with winauto's
    # own import-time call.
    try:
        from . import winauto

        winauto.ensure_dpi_aware()
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as e:
        sys.stderr.write("error: {0}\n".format(e))
        return 2
    except BridgeTimeout as e:
        sys.stderr.write("timeout: {0}\n".format(e))
        return 3
    except BridgeError as e:
        sys.stderr.write("bridge error: {0}\n".format(e))
        return 4


if __name__ == "__main__":
    sys.exit(main())
