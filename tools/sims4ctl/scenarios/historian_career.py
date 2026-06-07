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

# Resolve the target Sim. Prefer a stable sim_id (sim_info_manager.get) which is
# immune to the active selection flicking to None while a notification/modal is
# up; fall back to the active Sim. SIM_ID is injected as a param when known.
SIM_ID = None

def _resolve_si():
    try:
        if SIM_ID is not None:
            s = services.sim_info_manager().get(SIM_ID)
            if s is not None:
                return s
    except Exception:
        pass
    return hc.active_sim_info()
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
        self.sim_id = None  # set by capture_sim_id(); pins snippets to one Sim

    # -- in-game exec primitive ---------------------------------------------

    @staticmethod
    def build_code(body, params=None):
        """Assemble the full in-game snippet: preamble + literal params + the SI
        resolution + body + the RESULT print. Kept separate from _run so the
        snippet can be syntax-checked offline (the live game is the only place
        name resolution can be checked). `params` is a dict of {NAME: literal}
        injected as assignments (so we never string-format Python into the body);
        SI is resolved AFTER params so an injected SIM_ID takes effect."""
        pre = ""
        if params:
            for k, v in params.items():
                pre += "{0} = {1}\n".format(k, repr(v))
        return (
            _IN_GAME_PREAMBLE + "\n" + pre + "SI = _resolve_si()\n" + body + "\n"
            + "print(_S + json.dumps(RESULT, default=str))"
        )

    def _run(self, body, params=None):
        """Exec a Python `body` in-game (preamble prepended). `body` must set a
        variable `RESULT` to a JSON-able value, which is returned here. The
        captured sim_id is injected as SIM_ID so every snippet targets the same
        Sim regardless of transient active-selection changes."""
        p = dict(params or {})
        if self.sim_id is not None and "SIM_ID" not in p:
            p["SIM_ID"] = self.sim_id
        code = self.build_code(body, p)
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

    def trait_exists(self, key):
        """True iff the trait tuning resolves at all (a missing EP means the
        University degree trait simply isn't loaded -> fast-track untestable)."""
        return bool(self._run(
            'RESULT = {"exists": _trait_cls(KEY) is not None}',
            {"KEY": key}).get("exists"))

    def skill_exists(self, guid):
        """True iff the skill statistic resolves. Research & Debate (221014) is a
        Discover University skill -> absent on a base-game install, which makes
        the R&D-only L6->L7 gate untestable there (the gate tuning is still
        verified offline)."""
        return bool(self._run(
            'RESULT = {"exists": _stat_cls(GUID) is not None}',
            {"GUID": guid}).get("exists"))

    def capture_sim_id(self):
        """Resolve and remember the active Sim's id so every later snippet pins
        to it via sim_info_manager (robust against active-selection flicker)."""
        body = '''
si = hc.active_sim_info()
sid = (getattr(si, "sim_id", None) or getattr(si, "id", None)) if si is not None else None
RESULT = {"sim_id": int(sid) if sid is not None else None}
'''
        self.sim_id = self._run(body).get("sim_id")
        return self.sim_id

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

    def add_hiwi_career(self):
        """Force-join the degree-gated HiWi fast-track career (separate entry).
        Returns its starting user_level so callers can assert the +4 (-> L5).
        Bypasses availability tests like add_career, so callers should equip the
        degree trait first to avoid the periodic availability check evicting the
        Sim."""
        body = '''
cls = _by_name(_mgr(Types.CAREER), "career_Adult_Historian_HiWi")
level = None
present = False
if cls is not None and SI is not None:
    try:
        if SI.career_tracker.get_career_by_uid(cls.guid64) is None:
            SI.career_tracker.add_career(cls(SI))
        c = SI.career_tracker.get_career_by_uid(cls.guid64)
        present = c is not None
        if c is not None:
            level = int(c.user_level)
    except Exception:
        pass
RESULT = {"level": level, "present": present}
'''
        return self._run(body)

    def remove_hiwi_career(self):
        body = '''
cls = _by_name(_mgr(Types.CAREER), "career_Adult_Historian_HiWi")
present = False
if cls is not None and SI is not None:
    try:
        if SI.career_tracker.get_career_by_uid(cls.guid64) is not None:
            SI.career_tracker.remove_career(cls.guid64)
        present = SI.career_tracker.get_career_by_uid(cls.guid64) is not None
    except Exception:
        pass
RESULT = {"present": present}
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
        """Promote one level via the Python API (EA's Career.promote()). Returns
        {before, after, error}. Used to climb to a setup level; the authoritative
        gate signal is is_promotion_blocked() (see promotion_blocked)."""
        body = '''
c = _hist_career(SI)
before = _user_level(SI)
err = None
if c is not None:
    try:
        c.promote()
    except Exception as e:
        err = repr(e)
RESULT = {"before": before, "after": _user_level(SI), "error": err}
'''
        return self._run(body)

    def demote_once(self):
        """Demote one level via EA's Career.demote() (no gate applies to a
        demotion). Used to drive the Sim DOWN to a target level -- the career
        remembers its level across remove/add (levels_lost_on_leave=0), so a
        remove/re-add does NOT reset to L1."""
        body = '''
c = _hist_career(SI)
before = _user_level(SI)
err = None
if c is not None:
    fn = getattr(c, "demote", None)
    if callable(fn):
        try:
            fn()
        except Exception as e:
            err = repr(e)
    else:
        err = "no demote()"
RESULT = {"before": before, "after": _user_level(SI), "error": err}
'''
        return self._run(body)

    def set_skill(self, guid, level):
        """Set a skill to an absolute level. EA's set_user_value reliably RAISES
        a skill but does not always LOWER one, so when the target is below the
        current level we first reset the statistic (remove / set_value(0)) and
        then raise to the target. Returns {guid, want, applied}."""
        body = '''
cls = _stat_cls(GUID)
applied = None
if cls is not None and SI is not None:
    try:
        st = SI.get_statistic(cls, add=True)
        cur = None
        try:
            cur = int(st.get_user_value())
        except Exception:
            cur = None
        if cur is not None and LEVEL < cur:
            # Reset first so we can land BELOW the current level.
            fn = getattr(SI, "remove_statistic", None)
            if callable(fn):
                try:
                    fn(cls)
                except Exception:
                    pass
            st = SI.get_statistic(cls, add=True)
            try:
                st.set_value(0)
            except Exception:
                pass
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
        """Make `name` the Sim's primary aspiration track. EA grants the track's
        `provided_traits` once it is the active track. The working path (verified
        live) is `sim_info.primary_aspiration = track` then
        `aspiration_tracker.reset_data()` to re-initialise; we then read whether
        the reward trait was granted."""
        body = '''
cls = _track_cls(NAME)
err = None
applied = False
active = None
if cls is not None and SI is not None:
    try:
        SI.primary_aspiration = cls
        applied = True
    except Exception as e:
        err = repr(e)
    tr = getattr(SI, "aspiration_tracker", None)
    if tr is not None:
        fn = getattr(tr, "reset_data", None)
        if callable(fn):
            try:
                fn()
            except Exception as e:
                err = (err or "") + " reset_data:" + repr(e)
        at = getattr(tr, "active_track", None)
        active = getattr(at, "__name__", None) if at is not None else None
RESULT = {"applied": applied, "active_track": active,
          "has_reward_trait": _has_trait(SI, REWARD), "error": err}
'''
        return self._run(body, {"NAME": name, "REWARD": spec.REWARD_TRAIT_NAME})

    def run_daily_rotation(self):
        """Invoke the mod's daily-task rotation directly (it normally fires at
        zone spin-up / midnight; the Sim joined the career after load, so we
        trigger it once) and read back the stash it writes on the career."""
        body = '''
err = None
try:
    import historian_career.daily_task_rotation as _dtr
    _dtr.rotate_daily_tasks()
except Exception as e:
    err = repr(e)
c = _hist_career(SI)
RESULT = {
    "name": getattr(c, "_hc_daily_task_name", None) if c is not None else None,
    "day": getattr(c, "_hc_daily_task_day", None) if c is not None else None,
    "error": err,
}
'''
        return self._run(body)

    # -- gate / affordance probes -------------------------------------------

    def promotion_blocked(self):
        """Ask EA's own `Career.is_promotion_blocked` whether the next promotion
        is gated for the Sim at its CURRENT level. Returns {blocked, note,
        level}. This runs the career's `block_promotion_tests` through the game's
        own code path -- the authoritative gate signal. (If the skill tests are
        malformed it raises inside here, which we surface as `note` rather than a
        crash -- that is exactly how the pre-fix `<V t="skill">` bug presented.)"""
        body = '''
c = _hist_career(SI)
blocked = None
note = None
if c is not None:
    v = getattr(c, "is_promotion_blocked", None)
    try:
        blocked = bool(v() if callable(v) else v)
    except Exception as e:
        note = "is_promotion_blocked raised: " + repr(e)
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
    while we navigate to a setup level."""
    drv.set_skills({g: 10 for g in ALL_GATE_SKILL_IDS})


def _ensure_career(drv):
    """Make sure the Sim is in the Historian career (add via API if not)."""
    if drv.historian_entry() is None:
        drv.add_career()
        time.sleep(0.3)


def _goto_level(drv, target, max_steps=24):
    """Drive the Sim to exactly `target` user_level. Maxes the gate skills first
    so promotions are never gated, then promotes UP or demotes DOWN as needed
    (the career remembers its level across remove/add, so demotion is the only
    way back down). Returns the level reached."""
    _ensure_career(drv)
    _max_all_gate_skills(drv)
    for _ in range(max_steps):
        lvl = _as_int(drv.historian_level_pay()[0])
        if lvl is None:
            _ensure_career(drv)
            continue
        if lvl == target:
            return lvl
        r = drv.promote_once() if lvl < target else drv.demote_once()
        time.sleep(0.3)
        if r.get("error") and _as_int(r.get("after")) == lvl:
            break  # stuck (can't move) -- bail with current level
    return _as_int(drv.historian_level_pay()[0])


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
    if not zone:
        return False
    # Pin every later snippet to this Sim so a transient active-selection change
    # (e.g. a notification popping) can't make hc.active_sim_info() return None.
    sid = drv.capture_sim_id()
    h.check(sid is not None, "captured active Sim id for stable targeting",
            "sim_id={0}".format(sid))
    return True


def step_add_and_pay(h, drv):
    print("\n== Add career via API: L1, then climb to L10 (pay schedule) ==")
    # Add via the Python API (the #30 fix: EA cheats no-op for a custom career).
    drv.remove_career()
    time.sleep(0.2)
    added = drv.add_career()
    h.check(added.get("present") is True,
            "career added via Python API (careers.add_career cheat no-ops, #30)",
            "present={0}".format(added.get("present")))
    # Force a clean L1 start (the career remembers its level across remove/add).
    _goto_level(drv, 1)
    level, pay = drv.historian_level_pay()
    h.eq(level, 1, "career at L1")
    h.eq(pay, spec.PAY[1], "L1 pay == {0}".format(spec.PAY[1]))

    # Skills already maxed by _goto_level, so promote to the top asserting pay.
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
    print("\n== DU fast-track: degree -> separate HiWi entry starts at L5 ==")
    # The fast-track is now a SEPARATE degree-gated career entry
    # (career_Adult_Historian_HiWi) rather than an in-place +4 on the regular
    # career. It keys off the hidden Discover University degree trait (230331);
    # if the DU pack isn't installed that trait never loads, so the entry is
    # hidden and there is nothing to verify in-game -- report it as a skip (the
    # HiWi career's unconditional +4 is verified offline).
    if not drv.trait_exists(spec.FAST_TRACK_TRAIT_ID):
        h.check(True, "fast-track SKIPPED: degree trait {0} not loaded "
                "(Discover University not installed; HiWi +4 verified offline)"
                .format(spec.FAST_TRACK_TRAIT_ID))
        return

    drv.remove_career()
    drv.remove_hiwi_career()
    time.sleep(0.2)
    h.check(drv.historian_entry() is None, "career removed before fast-track test")

    # Equip the degree trait first so the HiWi entry's availability test passes
    # and the periodic check doesn't evict the Sim after we force-join.
    got = drv.set_trait(spec.FAST_TRACK_TRAIT_ID, present=True)
    h.check(got.get("has") is True,
            "History-degree trait {0} equipped".format(spec.FAST_TRACK_TRAIT_ID),
            "has={0}".format(got.get("has")))
    r = drv.add_hiwi_career()
    time.sleep(0.3)
    h.check(r.get("present") is True, "HiWi fast-track career joined")
    h.eq(_as_int(r.get("level")), spec.FAST_TRACK_START_LEVEL,
         "HiWi entry starts at L{0}".format(spec.FAST_TRACK_START_LEVEL))
    # Clean up so later steps start from a known place.
    drv.remove_hiwi_career()
    drv.set_trait(spec.FAST_TRACK_TRAIT_ID, present=False)


def step_skill_gates(h, drv):
    print("\n== Skill gates: each transition BLOCKS below threshold, OPENS at it ==")
    guid = spec.SKILL_IDS
    for from_level in spec.gated_from_levels():
        reqs = spec.SKILL_GATES[from_level]  # {skill_key: min_required}
        to_level = from_level + 1
        label = "L{0}->L{1} {2}".format(from_level, to_level, reqs)
        print("\n  -- gate {0} --".format(label))

        # Only skills actually loaded in this install can be exercised. R&D is a
        # Discover University skill; on a base-game install it's absent, so a gate
        # that depends ONLY on R&D (L6->L7) can't be driven here -- skip it (its
        # tuning is verified offline). For a multi-skill gate we test via the
        # available skill(s): being below EITHER required skill blocks, so a
        # single available skill is enough to exercise the block/open behaviour.
        avail = {k: v for k, v in reqs.items() if drv.skill_exists(guid[k])}
        missing = [k for k in reqs if k not in avail]
        if not avail:
            h.check(True, "{0}: SKIPPED -- required skill(s) {1} not loaded "
                    "(EP missing); gate tuning verified offline".format(label, missing))
            continue
        if missing:
            print("     (note: {0} not loaded; testing via {1})".format(
                missing, sorted(avail)))

        # Arrive at the FROM level (skills maxed by _goto_level so the navigation
        # promotions are never gated; demotes carry us back down).
        reached = _goto_level(drv, from_level)
        if not h.eq(_as_int(reached), from_level,
                    "reached L{0} for gate test".format(from_level)):
            continue

        # 1) Knock the available gated skills BELOW their minimum -> must BLOCK.
        below = {guid[k]: spec.skill_max_value_for_block(v) for k, v in avail.items()}
        drv.set_skills(below)
        time.sleep(0.2)
        blk = drv.promotion_blocked()
        if blk.get("blocked") is None:
            h.check(False, "{0}: is_promotion_blocked evaluable below threshold".format(label),
                    "could not evaluate: {0}".format(blk.get("note")))
        else:
            h.check(blk.get("blocked") is True,
                    "{0}: BLOCKED while skills below threshold".format(label),
                    "blocked={0} note={1}".format(blk.get("blocked"), blk.get("note")))

        # 2) Raise the available gated skills TO their minimum -> must OPEN, and a
        #    promote then actually advances the level.
        at = {guid[k]: v for k, v in avail.items()}
        drv.set_skills(at)
        time.sleep(0.2)
        blk2 = drv.promotion_blocked()
        if blk2.get("blocked") is None:
            h.check(False, "{0}: is_promotion_blocked evaluable at threshold".format(label),
                    "could not evaluate: {0}".format(blk2.get("note")))
        else:
            h.check(blk2.get("blocked") is False,
                    "{0}: OPEN once skills reach threshold".format(label),
                    "blocked={0}".format(blk2.get("blocked")))
        r2 = drv.promote_once()
        time.sleep(0.3)
        h.eq(_as_int(r2.get("after")), to_level,
             "{0}: promote() advances once gate opens".format(label))


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

    # The Sim joined the career after zone-load, so trigger the rotation once
    # (it normally fires at spin-up / midnight for Sims already in the career).
    stash = drv.run_daily_rotation()
    h.check(stash.get("name") is not None,
            "daily-task rotation chose a task for the Historian Sim",
            "stash={0} error={1}".format(
                {k: stash.get(k) for k in ("name", "day")}, stash.get("error")))


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

    if not step_preflight(h, drv):
        print("\n(No zone / bridge -- live checks skipped; "
              "offline authoring results above still stand.)")
        ok = h.summary()
        return 0 if ok else 1

    # Run each live step in isolation so a transient bridge stall in one step
    # (e.g. the main thread briefly busy on a promotion notification) records a
    # single failure for that step instead of aborting the whole run.
    for step in (step_add_and_pay, step_fast_track, step_skill_gates,
                 step_affordance_bands, step_aspiration, step_wfh_and_rotation):
        try:
            step(h, drv)
        except BridgeTimeout as e:
            h.check(False, "{0}: bridge stayed responsive".format(step.__name__),
                    "timeout: {0}".format(e))
        except BridgeError as e:
            h.check(False, "{0}: bridge command succeeded".format(step.__name__),
                    "bridge error: {0}".format(e))

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
