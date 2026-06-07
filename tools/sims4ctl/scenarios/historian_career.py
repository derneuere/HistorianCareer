#!/usr/bin/env python3
"""historian_career.py -- end-to-end in-game verification of the ten-rank
Historian career, driven from outside the game through the sims4ctl bridge.

This is the worked example `_BUILD_SPEC.md` promises, and the scripted answer to
issue #32 ("verify remaining 10-rank Historian features in-game"). It exercises,
against a RUNNING Sims 4 with a loaded save:

  * career add at L1 + the exact §/h pay schedule L1..L10,
  * the Discover-University fast-track (degree trait -> start at L5),
  * ALL FIVE skill-gated promotions (L1->L2, L6->L7, L7->L8, L8->L9, L9->L10) --
    both that they BLOCK below the threshold and OPEN at it,
  * the 15 affordance/overlay level bands installed by level_gate.py,
  * the "Historian's Calling" aspiration track granting the Habilitation Renown
    reward trait,
  * Work-From-Home + the daily-task rotation stash,
  * and that the whole run produced no new UI exceptions.

WHY THE PYTHON API, NOT CHEATS (issue #30)
------------------------------------------
EA cheat commands run through the bridge `cmd` verb silently no-op for our custom
career -- `careers.add_career career_Adult_Historian` resolves nothing, so the old
cheat-driven scenario failed at the very first step. The reliable channel is the
game's own Python API, reached through the bridge `eval`/`exec` verb (proven
in-game in #30). Every mutation below therefore runs as a small Python snippet
ON THE MAIN THREAD via the bridge, using `hc.active_sim_info()` and the live
`services` managers -- never a cheat string. Each snippet then RE-READS live
state and the step asserts on what it observed, so a wrong assumption fails
loudly instead of passing silently.

PREREQUISITES (this script CANNOT create them -- there is no headless mode):
  1. The Sims 4 is RUNNING with the sims4ctl bridge installed (`sims4ctl install`,
     script mods enabled, game restarted) and a save LOADED with an active adult
     Sim in a loaded zone (not CAS/Build, not paused on a modal).
  2. The HistorianCareer mod (.package + .ts4script) is installed and loaded.

Run it:
    sims4ctl run-scenario historian_career --auto      # bootstraps load
    python scenarios/historian_career.py               # against an already-loaded save
    python scenarios/historian_career.py --no-offline  # skip the authoring preflight

Exit code is 0 only when EVERY check passes; non-zero otherwise, so CI/an agent
can gate on it. The authoring half (no game needed) is also runnable on its own:
    python scenarios/historian_offline_check.py

Talks ONLY through the documented host client (client.Client + crashwatch +
gamepaths) and the shared spec / offline checker. Stdlib + the host package only.
"""

import argparse
import json
import os
import sys
import time

# --- make the host package + sibling scenario modules importable ------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_HOST_DIR = os.path.join(os.path.dirname(_HERE), "host")
for _p in (_HERE, _HOST_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from sims4ctl import gamepaths
    from sims4ctl.client import BridgeError, BridgeTimeout, Client
    from sims4ctl.crashwatch import CrashWatch
except ImportError as exc:  # pragma: no cover - surfaced as a clear failure
    sys.stderr.write(
        "FATAL: could not import the sims4ctl host package from {0}\n"
        "       ({1})\n".format(_HOST_DIR, exc)
    )
    sys.exit(2)

import historian_spec as spec  # noqa: E402
from historian_offline_check import Harness, run_offline_checks  # noqa: E402


# ---------------------------------------------------------------------------
# In-game preamble: resolver helpers re-defined on EVERY exec call (the bridge
# builds a fresh eval namespace per request, so nothing persists between calls).
# Exposed namespace already has `services`, `sims4`, `hc`. We add `Types`,
# the resolver helpers, and `SI` (the active sim_info).
# ---------------------------------------------------------------------------

_RESULT_MARKER = "<<S4CTL_RESULT>>"

_IN_GAME_PREAMBLE = '''
import json
from sims4.resources import Types
_S = "%s"

def _mgr(t):
    return services.get_instance_manager(t)

def _by_name(mgr, name):
    if mgr is None:
        return None
    try:
        c = mgr.get(name)
        if c is not None:
            return c
    except Exception:
        pass
    try:
        for c in mgr.types.values():
            if getattr(c, "__name__", "") == name:
                return c
    except Exception:
        pass
    return None

def _career_cls():
    return _by_name(_mgr(Types.CAREER), "career_Adult_Historian")

def _hist_career(si):
    cls = _career_cls()
    if cls is None or si is None:
        return None
    try:
        return si.career_tracker.get_career_by_uid(cls.guid64)
    except Exception:
        return None

def _stat_cls(guid):
    try:
        return _mgr(Types.STATISTIC).get(guid)
    except Exception:
        return None

def _trait_cls(key):
    mgr = _mgr(Types.TRAIT)
    if mgr is None:
        return None
    if isinstance(key, int):
        try:
            c = mgr.get(key)
            if c is not None:
                return c
        except Exception:
            pass
        return None
    return _by_name(mgr, key)

def _track_cls(name):
    return _by_name(_mgr(Types.ASPIRATION_TRACK), name)

def _user_level(si):
    c = _hist_career(si)
    if c is None:
        return None
    try:
        return int(c.user_level)
    except Exception:
        return None

def _has_trait(si, key):
    cls = _trait_cls(key)
    if cls is None or si is None:
        return False
    try:
        return bool(si.has_trait(cls))
    except Exception:
        pass
    try:
        return bool(si.trait_tracker.has_trait(cls))
    except Exception:
        return False

SI = hc.active_sim_info()
''' % _RESULT_MARKER


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Driver: a thin convenience layer over client.Client. Mutations + special
# reads go through the bridge `eval`/`exec` verb (Python API); the plain career
# topic read uses the proven `state` verb.
# ---------------------------------------------------------------------------

class Driver(object):
    def __init__(self, client, timeout):
        self.client = client
        self.timeout = timeout

    # -- in-game exec primitive ---------------------------------------------

    @staticmethod
    def build_code(body, params=None):
        """Assemble the full in-game snippet: preamble + literal params + body +
        the RESULT print. Kept separate from _run so the snippet can be
        syntax-checked offline (the live game is the only place name resolution
        can be checked). `params` is a dict of {NAME: literal} injected as
        assignments so we never string-format Python into the body."""
        pre = ""
        if params:
            for k, v in params.items():
                pre += "{0} = {1}\n".format(k, repr(v))
        return (
            _IN_GAME_PREAMBLE + "\n" + pre + body + "\n"
            + "print(_S + json.dumps(RESULT, default=str))"
        )

    def _run(self, body, params=None):
        """Exec a Python `body` in-game (preamble prepended). `body` must set a
        variable `RESULT` to a JSON-able value, which is returned here."""
        code = self.build_code(body, params)
        out = self.client.send(
            "eval", {"code": code, "mode": "exec"}, timeout=self.timeout)
        stdout = out.get("stdout", "") if isinstance(out, dict) else ""
        for line in (stdout or "").splitlines():
            if line.startswith(_RESULT_MARKER):
                return json.loads(line[len(_RESULT_MARKER):])
        raise BridgeError(
            "in-game exec returned no RESULT (stdout={0!r})".format(stdout))

    # -- reads ---------------------------------------------------------------

    def career_state(self):
        result = self.client.send(
            "state", {"topic": "career"}, timeout=self.timeout)
        if isinstance(result, dict) and "career" in result:
            result = result["career"]
        return result if isinstance(result, list) else []

    def historian_entry(self):
        for c in self.career_state():
            if isinstance(c, dict) and c.get("name") == spec.CAREER_NAME:
                return c
        for c in self.career_state():
            if isinstance(c, dict) and "historian" in str(c.get("name", "")).lower():
                return c
        return None

    def historian_level_pay(self):
        entry = self.historian_entry()
        if entry is None:
            return None, None
        return _as_int(entry.get("user_level")), _as_int(entry.get("simoleons_per_hour"))

    def has_trait(self, key):
        return bool(self._run('RESULT = {"has": _has_trait(SI, KEY)}',
                              {"KEY": key}).get("has"))

    # -- mutations (Python API, never cheats) -------------------------------

    def add_career(self):
        body = '''
cls = _career_cls()
if cls is not None and SI is not None and _hist_career(SI) is None:
    try:
        SI.career_tracker.add_career(cls(SI))
    except Exception:
        pass
RESULT = {"level": _user_level(SI), "present": _hist_career(SI) is not None}
'''
        return self._run(body)

    def remove_career(self):
        body = '''
cls = _career_cls()
if cls is not None and SI is not None and _hist_career(SI) is not None:
    try:
        SI.career_tracker.remove_career(cls.guid64)
    except Exception:
        pass
RESULT = {"present": _hist_career(SI) is not None}
'''
        return self._run(body)

    def promote_once(self):
        """Natural, gate-respecting promote via the Python API. Returns
        {before, after, error}. Does NOT use the force-cheat, so a real gate can
        actually stop it (that's the point of the gate test)."""
        body = '''
c = _hist_career(SI)
before = _user_level(SI)
err = None
if c is not None:
    try:
        c.promote_career()
    except Exception as e:
        err = repr(e)
RESULT = {"before": before, "after": _user_level(SI), "error": err}
'''
        return self._run(body)

    def set_skill(self, guid, level):
        body = '''
cls = _stat_cls(GUID)
applied = None
if cls is not None and SI is not None:
    try:
        st = SI.get_statistic(cls, add=True)
        try:
            st.set_user_value(LEVEL)
        except Exception:
            try:
                st.set_value(LEVEL)
            except Exception:
                pass
        try:
            applied = int(st.get_user_value())
        except Exception:
            applied = None
    except Exception:
        pass
RESULT = {"guid": GUID, "want": LEVEL, "applied": applied}
'''
        return self._run(body, {"GUID": guid, "LEVEL": level})

    def set_skills(self, mapping):
        """Set several skills {guid: level}; returns {guid: applied}."""
        out = {}
        for guid, level in mapping.items():
            out[guid] = self.set_skill(guid, level).get("applied")
        return out

    def set_trait(self, key, present):
        body = '''
cls = _trait_cls(KEY)
if cls is not None and SI is not None:
    try:
        if PRESENT:
            SI.add_trait(cls)
        else:
            SI.remove_trait(cls)
    except Exception:
        pass
RESULT = {"has": _has_trait(SI, KEY)}
'''
        return self._run(body, {"KEY": key, "PRESENT": bool(present)})

    def set_aspiration_track(self, name):
        body = '''
cls = _track_cls(NAME)
err = None
applied = False
if cls is not None and SI is not None:
    tr = getattr(SI, "aspiration_tracker", None)
    if tr is not None:
        for meth in ("set_aspiration_track", "set_aspiration"):
            fn = getattr(tr, meth, None)
            if callable(fn):
                try:
                    fn(cls)
                    applied = True
                    break
                except Exception as e:
                    err = repr(e)
RESULT = {"applied": applied, "has_reward_trait": _has_trait(SI, REWARD), "error": err}
'''
        return self._run(body, {"NAME": name, "REWARD": spec.REWARD_TRAIT_NAME})

    # -- gate / affordance probes -------------------------------------------

    def promotion_blocked(self):
        """Evaluate the career's `block_promotion_tests` against the live Sim at
        its current level. Returns {blocked, note, level}. `blocked` is True when
        a gate group passes (EA: any group passing -> promotion blocked). This is
        the AUTHORITATIVE gate signal -- independent of whether promote_career()
        happens to honour the gate."""
        body = '''
cls = _career_cls()
blocked = None
note = None
if cls is not None and SI is not None:
    tests = getattr(cls, "block_promotion_tests", None)
    if tests is None:
        note = "no block_promotion_tests on career tuning"
    else:
        resolver = None
        try:
            from event_testing.resolver import SingleSimResolver
            resolver = SingleSimResolver(SI)
        except Exception as e:
            note = "resolver import failed: " + repr(e)
        if resolver is not None:
            res = None
            for meth in ("run_tests", "__call__"):
                fn = getattr(tests, meth, None)
                if callable(fn):
                    try:
                        res = fn(resolver)
                        break
                    except Exception as e:
                        note = meth + " failed: " + repr(e)
            if res is not None:
                blocked = bool(res)
RESULT = {"blocked": blocked, "note": note, "level": _user_level(SI)}
'''
        return self._run(body)

    def affordance_gate_state(self):
        """Read the per-class level band installed by level_gate.py on each
        HC_Interaction_* tuning. Returns {name: {min,max,installed} | None}."""
        body = '''
mgr = _mgr(Types.INTERACTION)
out = {}
by_name = {}
if mgr is not None:
    try:
        for c in mgr.types.values():
            nm = getattr(c, "__name__", "")
            if isinstance(nm, str) and nm.startswith("HC_Interaction_"):
                by_name[nm] = c
    except Exception:
        pass
for nm in NAMES:
    c = by_name.get(nm)
    if c is None:
        out[nm] = None
    else:
        out[nm] = {
            "min": getattr(c, "_hc_min_user_level", None),
            "max": getattr(c, "_hc_max_user_level", None),
            "installed": bool(getattr(c, "_hc_gate_installed", False)),
        }
RESULT = out
'''
        return self._run(body, {"NAMES": list(spec.AFFORDANCE_BANDS)})

    def daily_task_stash(self):
        body = '''
c = _hist_career(SI)
RESULT = {
    "name": getattr(c, "_hc_daily_task_name", None) if c is not None else None,
    "day": getattr(c, "_hc_daily_task_day", None) if c is not None else None,
}
'''
        return self._run(body)

    def wfh_enabled(self):
        """Best-effort runtime check that the career tuning exposes the enabled
        early-warning alarm carrying a work-from-home option. WFH authoring is
        also asserted offline; this confirms it survived into the live tuning."""
        body = '''
cls = _career_cls()
ewa = None
wfh = None
if cls is not None:
    msgs = getattr(cls, "career_messages", None)
    for src in (msgs, cls):
        if src is None:
            continue
        cand = getattr(src, "career_early_warning_alarm", None)
        if cand is not None:
            ewa = cand
            break
    if ewa is not None:
        wfh = getattr(ewa, "work_from_home_text", None)
RESULT = {"early_warning_alarm": ewa is not None, "has_wfh_text": wfh is not None}
'''
        return self._run(body)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

ALL_GATE_SKILL_IDS = tuple(sorted(spec.SKILL_IDS.values()))


def _max_all_gate_skills(drv):
    """Set every skill the gates ever look at to 10 so promotions are un-gated
    while we climb to a setup level."""
    drv.set_skills({g: 10 for g in ALL_GATE_SKILL_IDS})


def _fresh_career_at_l1(drv):
    """Remove the career + degree trait, then re-add so we start clean at L1."""
    drv.set_trait(spec.FAST_TRACK_TRAIT_ID, present=False)
    drv.remove_career()
    time.sleep(0.2)
    drv.add_career()
    time.sleep(0.3)


def _climb_to(drv, target, max_steps=12):
    """Promote (gate-respecting) until the Sim reaches `target` level. Skills
    must already be high enough that no gate fires. Returns the level reached."""
    last = drv.historian_level_pay()[0]
    for _ in range(max_steps):
        if last is not None and last >= target:
            break
        r = drv.promote_once()
        time.sleep(0.3)
        last = r.get("after")
        if r.get("error"):
            break
    return last


# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------

def step_offline_preflight(h, repo_root):
    """Run the static authoring checks too, so a live run also proves the tuning
    encodes the spec (and the live assertions below are checking the right LAW)."""
    print("\n== Offline authoring preflight (no game needed) ==")
    run_offline_checks(h, repo_root=repo_root)


def step_preflight(h, drv):
    print("\n== Live preflight: bridge reachable + zone loaded ==")
    try:
        pong = drv.client.send("ping", {}, timeout=drv.timeout)
    except (BridgeTimeout, BridgeError) as e:
        h.check(False, "ping the bridge", str(e))
        return False
    h.check(isinstance(pong, dict) and pong.get("pong") is True,
            "ping the bridge", "result={0!r}".format(pong))
    zone = pong.get("zone_loaded") if isinstance(pong, dict) else None
    h.check(bool(zone), "a zone is loaded",
            "zone_loaded={0} active_sim={1}".format(
                zone, pong.get("active_sim") if isinstance(pong, dict) else None))
    return bool(zone)


def step_add_and_pay(h, drv):
    print("\n== Add career via API: L1, then climb to L10 (pay schedule) ==")
    _fresh_career_at_l1(drv)
    level, pay = drv.historian_level_pay()
    h.eq(level, 1, "career added at L1 (Python API, not cheat)")
    h.eq(pay, spec.PAY[1], "L1 pay == {0}".format(spec.PAY[1]))

    # Un-gate, then promote to the top asserting the exact pay at each rank.
    _max_all_gate_skills(drv)
    for target in range(2, spec.MAX_LEVEL + 1):
        r = drv.promote_once()
        time.sleep(0.3)
        level = r.get("after")
        ok = h.eq(_as_int(level), target, "promoted to L{0}".format(target))
        _l, pay = drv.historian_level_pay()
        h.eq(pay, spec.PAY[target], "L{0} pay == {1}".format(target, spec.PAY[target]))
        if not ok:
            h.check(False, "promotion chain stalled at L{0}".format(target),
                    "stuck at {0!r} (err={1})".format(level, r.get("error")))
            return False
    return True


def step_fast_track(h, drv):
    print("\n== DU fast-track: History-degree trait -> join at L5 ==")
    drv.remove_career()
    time.sleep(0.2)
    h.check(drv.historian_entry() is None, "career removed before fast-track test")

    got = drv.set_trait(spec.FAST_TRACK_TRAIT_ID, present=True)
    h.check(got.get("has") is True,
            "History-degree trait {0} equipped".format(spec.FAST_TRACK_TRAIT_ID),
            "has={0}".format(got.get("has")))
    drv.add_career()
    time.sleep(0.3)
    level, _pay = drv.historian_level_pay()
    h.eq(level, spec.FAST_TRACK_START_LEVEL,
         "degree holder fast-tracks to L{0}".format(spec.FAST_TRACK_START_LEVEL))
    # Clean up so later steps start from a known place.
    drv.set_trait(spec.FAST_TRACK_TRAIT_ID, present=False)


def step_skill_gates(h, drv):
    print("\n== Skill gates: each transition BLOCKS below threshold, OPENS at it ==")
    guid = spec.SKILL_IDS
    for from_level in spec.gated_from_levels():
        reqs = spec.SKILL_GATES[from_level]  # {skill_key: min_required}
        to_level = from_level + 1
        label = "L{0}->L{1} {2}".format(from_level, to_level, reqs)
        print("\n  -- gate {0} --".format(label))

        # Arrive at the FROM level with all gate skills maxed (gates open).
        _fresh_career_at_l1(drv)
        _max_all_gate_skills(drv)
        reached = _climb_to(drv, from_level)
        if not h.eq(_as_int(reached), from_level,
                    "reached L{0} for gate test".format(from_level)):
            continue

        # 1) Knock the gated skills BELOW their minimum -> gate must BLOCK.
        below = {guid[k]: spec.skill_max_value_for_block(v) for k, v in reqs.items()}
        drv.set_skills(below)
        time.sleep(0.2)
        blk = drv.promotion_blocked()
        if blk.get("blocked") is None:
            h.check(False, "{0}: gate evaluable below threshold".format(label),
                    "could not evaluate: {0}".format(blk.get("note")))
        else:
            h.check(blk.get("blocked") is True,
                    "{0}: BLOCKED while skills below threshold".format(label),
                    "blocked={0} note={1}".format(blk.get("blocked"), blk.get("note")))
        # Secondary signal: a natural promote should NOT advance the level.
        r = drv.promote_once()
        time.sleep(0.3)
        h.eq(_as_int(r.get("after")), from_level,
             "{0}: promote_career() does not advance while blocked".format(label))

        # 2) Raise the gated skills TO their minimum -> gate must OPEN.
        at = {guid[k]: v for k, v in reqs.items()}
        drv.set_skills(at)
        time.sleep(0.2)
        blk2 = drv.promotion_blocked()
        if blk2.get("blocked") is None:
            h.check(False, "{0}: gate evaluable at threshold".format(label),
                    "could not evaluate: {0}".format(blk2.get("note")))
        else:
            h.check(blk2.get("blocked") is False,
                    "{0}: OPEN once skills reach threshold".format(label),
                    "blocked={0}".format(blk2.get("blocked")))
        # And a natural promote should now land the next level.
        r2 = drv.promote_once()
        time.sleep(0.3)
        h.eq(_as_int(r2.get("after")), to_level,
             "{0}: promote_career() advances once gate opens".format(label))


def step_affordance_bands(h, drv):
    print("\n== Affordance/overlay level bands installed by level_gate.py ==")
    state = drv.affordance_gate_state()
    if not isinstance(state, dict):
        h.check(False, "read affordance gate state", "got {0!r}".format(state))
        return
    installed = 0
    for name, (lo, hi) in spec.AFFORDANCE_BANDS.items():
        got = state.get(name)
        if not isinstance(got, dict):
            h.check(False, "{0}: gate present".format(name),
                    "not registered/gated: {0!r}".format(got))
            continue
        band_ok = (_as_int(got.get("min")) == lo and _as_int(got.get("max")) == hi)
        h.check(band_ok and got.get("installed"),
                "{0}: band [{1},{2}] installed".format(name, lo, hi),
                "got min={0} max={1} installed={2}".format(
                    got.get("min"), got.get("max"), got.get("installed")))
        if band_ok and got.get("installed"):
            installed += 1
    h.eq(installed, len(spec.AFFORDANCE_BANDS),
         "all {0} affordance/overlay gates installed".format(len(spec.AFFORDANCE_BANDS)))

    # Spot-check the derived "offered at level N" set against the spec at a few
    # ranks, using the live bands we just read (gate logic = min<=level<=max).
    def offered_from_live(level):
        out = set()
        for name, got in state.items():
            if isinstance(got, dict):
                lo, hi = _as_int(got.get("min")), _as_int(got.get("max"))
                if lo is not None and hi is not None and lo <= level <= hi:
                    out.add(name)
        return out
    for level in (1, 4, 8, 10):
        h.eq(offered_from_live(level), set(spec.affordances_offered_at(level)),
             "affordances offered at L{0} match spec".format(level))


def step_aspiration(h, drv):
    print("\n== Aspiration track grants the Habilitation Renown reward trait ==")
    # Make sure the trait isn't already on the Sim from a prior run.
    drv.set_trait(spec.REWARD_TRAIT_NAME, present=False)
    time.sleep(0.2)
    res = drv.set_aspiration_track(spec.ASPIRATION_TRACK_NAME)
    h.check(res.get("applied") is True,
            "set aspiration track {0}".format(spec.ASPIRATION_TRACK_NAME),
            "applied={0} error={1}".format(res.get("applied"), res.get("error")))
    # The provided trait should be granted while the track is the primary asp.
    has = res.get("has_reward_trait")
    if has is None:
        has = drv.has_trait(spec.REWARD_TRAIT_NAME)
    h.check(bool(has),
            "track grants reward trait {0}".format(spec.REWARD_TRAIT_NAME),
            "has_reward_trait={0}".format(has))


def step_wfh_and_rotation(h, drv):
    print("\n== Work-From-Home enabled + daily-task rotation ran ==")
    wfh = drv.wfh_enabled()
    # Best-effort: the alarm object should exist; WFH text presence is the
    # canonical "WFH offered" signal (also asserted offline).
    h.check(wfh.get("early_warning_alarm") is True,
            "career exposes early-warning alarm at runtime",
            "early_warning_alarm={0}".format(wfh.get("early_warning_alarm")))
    h.check(wfh.get("has_wfh_text") is True,
            "Work-From-Home option present at runtime",
            "has_wfh_text={0} (also verified offline)".format(wfh.get("has_wfh_text")))

    stash = drv.daily_task_stash()
    h.check(stash.get("name") is not None,
            "daily-task rotation chose a task for the Historian Sim",
            "stash={0}".format(stash))


def step_no_new_crashes(h, userdata):
    print("\n== Crash check: 0 new UI exceptions since mark ==")
    try:
        watch = CrashWatch(userdata)
    except ValueError as e:
        h.check(False, "crash watch available", str(e))
        return
    new = watch.since_mark()
    h.check(len(new) == 0, "no new/changed crash logs since mark",
            "new={0}".format(new) if new else "clean")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def run(userdata=None, timeout=20.0, poll_interval=0.1, do_offline=True):
    bridge_dir = gamepaths.find_bridge_dir(userdata)
    resolved_userdata = gamepaths.find_userdata(userdata)
    if bridge_dir is None or resolved_userdata is None:
        sys.stderr.write(
            "FATAL: could not resolve <USERDATA>/sims4ctl/. Pass --userdata or "
            "set SIMS4CTL_USERDATA, and make sure the game has run once.\n"
        )
        return 2

    print("sims4ctl scenario: HistorianCareer ten-rank in-game verification")
    print("  userdata   : {0}".format(resolved_userdata))
    print("  bridge dir : {0}".format(bridge_dir))

    client = Client(bridge_dir, poll_interval=poll_interval)
    drv = Driver(client, timeout)
    h = Harness()

    # Authoring preflight (no game needed). Repo root is three up from here.
    repo_root = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
    if do_offline:
        step_offline_preflight(h, repo_root)

    # Mark the crash baseline before touching the game.
    try:
        baseline = CrashWatch(resolved_userdata).mark()
        print("\n  crash mark : {0} existing log(s) baselined".format(len(baseline)))
    except ValueError as e:
        sys.stderr.write("FATAL: could not set crash mark: {0}\n".format(e))
        return 2

    try:
        if not step_preflight(h, drv):
            print("\n(No zone / bridge -- live checks skipped; "
                  "offline authoring results above still stand.)")
            ok = h.summary()
            return 0 if ok else 1
        step_add_and_pay(h, drv)
        step_fast_track(h, drv)
        step_skill_gates(h, drv)
        step_affordance_bands(h, drv)
        step_aspiration(h, drv)
        step_wfh_and_rotation(h, drv)
    except BridgeTimeout as e:
        h.check(False, "bridge stayed responsive", "timeout: {0}".format(e))
    except BridgeError as e:
        h.check(False, "bridge command succeeded", "bridge error: {0}".format(e))

    step_no_new_crashes(h, resolved_userdata)
    ok = h.summary()
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="historian_career.py",
        description="sims4ctl scenario: verify the ten-rank HistorianCareer mod "
        "end-to-end against a running Sims 4 (Python API, not cheats).",
    )
    parser.add_argument("--userdata", default=None,
                        help="override the Sims 4 user-data folder.")
    parser.add_argument("--timeout", type=float, default=20.0,
                        help="bridge response timeout in seconds (default 20).")
    parser.add_argument("--poll-interval", type=float, default=0.1,
                        help="how often to poll response.json (default 0.1s).")
    parser.add_argument("--no-offline", action="store_true",
                        help="skip the static authoring preflight.")
    args = parser.parse_args(argv)
    return run(
        userdata=args.userdata,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        do_offline=not args.no_offline,
    )


if __name__ == "__main__":
    sys.exit(main())
