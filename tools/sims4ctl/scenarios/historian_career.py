#!/usr/bin/env python3
"""historian_career.py -- end-to-end example scenario for sims4ctl.

Drives the sims4ctl HOST client against a RUNNING The Sims 4 to test the
HistorianCareer mod from outside the game. This is the worked example the
_BUILD_SPEC.md promises: it walks the Historian career L1..L10, exercises the
Discover-University fast-track, pokes a skill gate, adds the aspiration track,
and finally asserts the run produced no NEW UI exceptions.

PREREQUISITES (this script CANNOT create them -- there is no headless mode):
  1. The Sims 4 (patch 1.124.55) is RUNNING.
  2. A save is LOADED with an active adult Sim in a loaded zone (not CAS/Build,
     not paused on a modal) -- the bridge can only touch `services` on the main
     thread during normal play.
  3. The sims4ctl in-game bridge is INSTALLED (build + copy to <MODS>/sims4ctl/;
     see `sims4ctl install`) and the game has been (re)launched so it loaded.
  4. The HistorianCareer mod (.package + .ts4script) is installed and loaded, so
     `careers.add_career career_Adult_Historian` resolves.
  5. `testingcheats true` is allowed (this script enables it first).

Run it:
    python scenarios/historian_career.py
    python scenarios/historian_career.py --userdata "C:/path/to/The Sims 4"

Exit code is 0 only when EVERY assertion passes; non-zero otherwise, so a CI
job or agent can gate on it. A clear PASS/FAIL summary is printed at the end.

This script talks ONLY through the documented host client (client.Client +
crashwatch.CrashWatch + gamepaths) -- it imports nothing from the in-game
bridge. Stdlib + the host package only.
"""

import argparse
import os
import sys
import time

# --- make the host package importable (sys.path -> <repo>/host) -------------
# scenarios/historian_career.py  ->  ../host
_HERE = os.path.dirname(os.path.abspath(__file__))
_HOST_DIR = os.path.join(os.path.dirname(_HERE), "host")
if _HOST_DIR not in sys.path:
    sys.path.insert(0, _HOST_DIR)

try:
    from sims4ctl import gamepaths
    from sims4ctl.client import BridgeError, BridgeTimeout, Client
    from sims4ctl.crashwatch import CrashWatch
except ImportError as exc:  # pragma: no cover - surfaced as a clear failure
    sys.stderr.write(
        "FATAL: could not import the sims4ctl host package from {0}\n"
        "       ({1})\n"
        "       Make sure the host slice exists under host/sims4ctl/.\n".format(
            _HOST_DIR, exc
        )
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Domain facts (LAW per HistorianCareer tuning, cross-checked against
# Tuning/career_level_Adult_Historian_L*.xml and the mod README).
# ---------------------------------------------------------------------------

CAREER_NAME = "career_Adult_Historian"

# English titles per rank (1-indexed). From historian_career.py TIERS table.
TITLES = {
    1: "Hobby Historian",
    2: "Museum Attendant",
    3: "Intern",
    4: "Trainee",
    5: "Research Assistant (HiWi)",
    6: "PhD Candidate",
    7: "Postdoctoral Researcher",
    8: "Junior Professor",
    9: "Full Professor",
    10: "Institute Director",
}

# simoleons_per_hour per rank (1-indexed). EXACT tuning values -- note this is
# NOT strictly monotonic: L2=22 (part-time, longer hours) dips to L3=18 (intern)
# before climbing. We assert the exact schedule, not "always increasing".
PAY = {
    1: 14, 2: 22, 3: 18, 4: 30, 5: 40,
    6: 60, 7: 90, 8: 140, 9: 220, 10: 340,
}

# Discover University fast-track: holding 230331 (trait_University_DegreeTraits_
# History) gives +4 start-level, so a degree holder begins at L5 instead of L1.
HISTORY_DEGREE_TRAIT = "trait_University_DegreeTraits_History"
FAST_TRACK_START_LEVEL = 5

# Skill gate around L8->L9: the two University major skills the career checks.
SKILL_WRITING = "Major_Writing"
SKILL_RESEARCH_DEBATE = "Major_ResearchDebate"

ASPIRATION_TRACK = "aspiration_track_HistorianCalling"


# ---------------------------------------------------------------------------
# A tiny PASS/FAIL harness. Records every check; never aborts the whole run on
# a single failed assertion (so one bad rank doesn't hide the rest), but DOES
# abort a step on an infrastructure error (timeout / bridge error) since the
# rest of that step can't meaningfully proceed.
# ---------------------------------------------------------------------------

class Harness(object):
    def __init__(self):
        self.checks = []  # list of (ok: bool, label: str, detail: str)

    def check(self, ok, label, detail=""):
        self.checks.append((bool(ok), label, detail))
        mark = "PASS" if ok else "FAIL"
        line = "  [{0}] {1}".format(mark, label)
        if detail:
            line += "  -- {0}".format(detail)
        print(line)
        return bool(ok)

    def eq(self, got, want, label):
        return self.check(
            got == want, label, "got {0!r}, want {1!r}".format(got, want)
        )

    @property
    def failed(self):
        return [c for c in self.checks if not c[0]]

    def summary(self):
        total = len(self.checks)
        nfail = len(self.failed)
        npass = total - nfail
        print("")
        print("=" * 60)
        if nfail == 0:
            print("OVERALL: PASS  ({0}/{0} checks)".format(total))
        else:
            print("OVERALL: FAIL  ({0}/{1} checks passed)".format(npass, total))
            print("Failed checks:")
            for ok, label, detail in self.failed:
                print("  - {0}  ({1})".format(label, detail))
        print("=" * 60)
        return nfail == 0


# ---------------------------------------------------------------------------
# Bridge helpers built on the host Client.
# ---------------------------------------------------------------------------

class Driver(object):
    """Thin convenience layer over client.Client for the scenario's verbs."""

    def __init__(self, client, timeout):
        self.client = client
        self.timeout = timeout

    def cmd(self, command):
        """Run a cheat via the bridge `cmd` verb. Returns the result dict."""
        return self.client.send("cmd", {"command": command}, timeout=self.timeout)

    def career_state(self):
        """Return the list of the active sim's careers (each a dict with
        name/user_level/simoleons_per_hour/track/title_stbl)."""
        result = self.client.send(
            "state", {"topic": "career"}, timeout=self.timeout
        )
        # Per the spec the career topic yields a list. Some bridge builds may
        # wrap it as {"career": [...]} -- accept either shape defensively.
        if isinstance(result, dict) and "career" in result:
            result = result["career"]
        if not isinstance(result, list):
            return []
        return result

    def historian_entry(self):
        """Return the Historian career dict from the live career state, or None.

        Matches on the career `name` (the tuning name `career_Adult_Historian`)
        with a fuzzy fallback on any name containing 'Historian'."""
        careers = self.career_state()
        for c in careers:
            if not isinstance(c, dict):
                continue
            if c.get("name") == CAREER_NAME:
                return c
        for c in careers:
            if isinstance(c, dict) and "historian" in str(c.get("name", "")).lower():
                return c
        return None

    def historian_level_pay(self):
        """Return (user_level, simoleons_per_hour, title_stbl) for the Historian
        career, or (None, None, None) if it isn't present."""
        entry = self.historian_entry()
        if entry is None:
            return None, None, None
        return (
            entry.get("user_level"),
            entry.get("simoleons_per_hour"),
            entry.get("title_stbl"),
        )


# ---------------------------------------------------------------------------
# scenario steps
# ---------------------------------------------------------------------------

def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def step_preflight(h, drv):
    """Verify the bridge answers and a zone is loaded before we touch anything."""
    print("\n-- Preflight: bridge reachable + zone loaded --")
    try:
        pong = drv.client.send("ping", {}, timeout=drv.timeout)
    except (BridgeTimeout, BridgeError) as e:
        h.check(False, "ping the bridge", str(e))
        return False
    h.check(isinstance(pong, dict) and pong.get("pong") is True,
            "ping the bridge", "result={0!r}".format(pong))
    zone_loaded = pong.get("zone_loaded") if isinstance(pong, dict) else None
    h.check(bool(zone_loaded), "a zone is loaded",
            "zone_loaded={0} active_sim={1}".format(
                zone_loaded, pong.get("active_sim") if isinstance(pong, dict) else None))
    return bool(zone_loaded)


def step_enable_cheats_and_add(h, drv):
    """testingcheats true; add the Historian career; assert L1 / 14/h."""
    print("\n-- Add career: L1, 14 simoleons/hour --")
    drv.cmd("testingcheats true")
    drv.cmd("careers.add_career {0}".format(CAREER_NAME))
    # Give the sim panel a beat to reflect the add (the bridge re-queries live,
    # but the career system applies on the main-thread tick after our cmd).
    time.sleep(0.5)
    level, pay, _title = drv.historian_level_pay()
    h.eq(_as_int(level), 1, "career level == 1 after add")
    h.eq(_as_int(pay), PAY[1], "simoleons_per_hour == 14 at L1")
    return level is not None


def step_promote_to_top(h, drv):
    """Promote x9, asserting the title and pay climb to L10 / 340."""
    print("\n-- Promote L1 -> L10: titles + pay climb to 340 --")
    # Clear skill/objective promotion gates the whole way up so a `promote`
    # never silently no-ops (block_promotion_tests). Charisma is also gated at
    # some ranks per the mod README.
    drv.cmd("stats.set_skill_level {0} 10".format(SKILL_RESEARCH_DEBATE))
    drv.cmd("stats.set_skill_level {0} 10".format(SKILL_WRITING))
    drv.cmd("stats.set_skill_level Major_Charisma 10")

    for target in range(2, 11):  # promote into L2..L10 (9 promotions)
        drv.cmd("careers.promote {0}".format(CAREER_NAME))
        time.sleep(0.35)
        level, pay, _title = drv.historian_level_pay()
        lvl_i = _as_int(level)
        ok_level = h.eq(lvl_i, target, "promoted to L{0}".format(target))
        h.eq(_as_int(pay), PAY[target],
             "pay == {0} at L{1}".format(PAY[target], target))
        if not ok_level:
            # If the level didn't advance, a gate is firing; record it and stop
            # climbing (the remaining ranks would all cascade-fail noisily).
            h.check(False, "promotion chain stalled at target L{0}".format(target),
                    "stuck at level {0!r}".format(level))
            return False
    # Endpoint sanity: top rank pay is exactly 340.
    _l, pay, _t = drv.historian_level_pay()
    h.eq(_as_int(pay), 340, "top-rank pay == 340")
    return True


def step_fast_track(h, drv):
    """Remove career, grant the History-degree trait, re-add: starts at L5."""
    print("\n-- Fast-track: degree trait -> re-add starts at L5 --")
    drv.cmd("careers.remove_career {0}".format(CAREER_NAME))
    time.sleep(0.3)
    after_remove = drv.historian_entry()
    h.check(after_remove is None, "career removed",
            "still present: {0!r}".format(after_remove))

    drv.cmd("traits.equip_trait {0}".format(HISTORY_DEGREE_TRAIT))
    time.sleep(0.3)
    drv.cmd("careers.add_career {0}".format(CAREER_NAME))
    time.sleep(0.5)
    level, _pay, _title = drv.historian_level_pay()
    h.eq(_as_int(level), FAST_TRACK_START_LEVEL,
         "degree holder fast-tracks to L{0}".format(FAST_TRACK_START_LEVEL))
    return _as_int(level) == FAST_TRACK_START_LEVEL


def step_skill_gate(h, drv):
    """Skill-gate check around L8->L9.

    Promote up to L8, then with the two major skills at 9 the L9 promotion is
    gated (should NOT advance); raising both to 10 clears the gate and L9 lands.
    This exercises block_promotion_tests on the L8->L9 transition.
    """
    print("\n-- Skill gate around L8 -> L9 --")
    # Make sure we're at L8: re-add fresh and walk up with skills maxed so we
    # arrive precisely at L8, then knock the gate skills back down to 9.
    drv.cmd("careers.remove_career {0}".format(CAREER_NAME))
    time.sleep(0.3)
    drv.cmd("traits.remove_trait {0}".format(HISTORY_DEGREE_TRAIT))
    drv.cmd("stats.set_skill_level {0} 10".format(SKILL_RESEARCH_DEBATE))
    drv.cmd("stats.set_skill_level {0} 10".format(SKILL_WRITING))
    drv.cmd("stats.set_skill_level Major_Charisma 10")
    drv.cmd("careers.add_career {0}".format(CAREER_NAME))
    time.sleep(0.4)
    # Walk to L8.
    for _ in range(7):
        drv.cmd("careers.promote {0}".format(CAREER_NAME))
        time.sleep(0.3)
    level, _pay, _t = drv.historian_level_pay()
    if not h.eq(_as_int(level), 8, "reached L8 for gate test"):
        return False

    # Drop the gate skills to 9 -> the L9 promotion should be BLOCKED.
    drv.cmd("stats.set_skill_level {0} 9".format(SKILL_RESEARCH_DEBATE))
    drv.cmd("stats.set_skill_level {0} 9".format(SKILL_WRITING))
    time.sleep(0.2)
    drv.cmd("careers.promote {0}".format(CAREER_NAME))
    time.sleep(0.35)
    level_gated, _p, _t = drv.historian_level_pay()
    h.eq(_as_int(level_gated), 8, "L9 promotion BLOCKED while skills < 10")

    # Raise to 10 -> the L9 promotion should now SUCCEED.
    drv.cmd("stats.set_skill_level {0} 10".format(SKILL_RESEARCH_DEBATE))
    drv.cmd("stats.set_skill_level {0} 10".format(SKILL_WRITING))
    time.sleep(0.2)
    drv.cmd("careers.promote {0}".format(CAREER_NAME))
    time.sleep(0.35)
    level_open, _p2, _t2 = drv.historian_level_pay()
    h.eq(_as_int(level_open), 9, "L9 promotion SUCCEEDS once skills == 10")
    return _as_int(level_open) == 9


def step_aspiration(h, drv):
    """Add the Historian aspiration track via cheat."""
    print("\n-- Aspiration track --")
    try:
        drv.cmd("aspirations.add_aspiration {0}".format(ASPIRATION_TRACK))
        h.check(True, "added aspiration {0}".format(ASPIRATION_TRACK))
    except BridgeError as e:
        h.check(False, "added aspiration {0}".format(ASPIRATION_TRACK), str(e))
    return True


def step_no_new_crashes(h, userdata, baseline_count):
    """`crashes --since-mark`: assert 0 new UI exceptions since the mark."""
    print("\n-- Crash check: 0 new UI exceptions since mark --")
    try:
        watch = CrashWatch(userdata)
    except ValueError as e:
        h.check(False, "crash watch available", str(e))
        return False
    new = watch.since_mark()
    h.check(len(new) == 0, "no new/changed crash logs since mark",
            "new={0}".format(new) if new else "clean")
    return len(new) == 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def run(userdata=None, timeout=15.0, poll_interval=0.1):
    """Run the whole scenario. Returns 0 on full PASS, non-zero otherwise."""
    bridge_dir = gamepaths.find_bridge_dir(userdata)
    resolved_userdata = gamepaths.find_userdata(userdata)
    if bridge_dir is None or resolved_userdata is None:
        sys.stderr.write(
            "FATAL: could not resolve <USERDATA>/sims4ctl/. Pass --userdata or "
            "set SIMS4CTL_USERDATA, and make sure the game has run once.\n"
        )
        return 2

    print("sims4ctl scenario: HistorianCareer end-to-end")
    print("  userdata   : {0}".format(resolved_userdata))
    print("  bridge dir : {0}".format(bridge_dir))

    client = Client(bridge_dir, poll_interval=poll_interval)
    drv = Driver(client, timeout)
    h = Harness()

    # Mark the crash baseline up-front so `--since-mark` at the end only sees
    # exceptions THIS run produced.
    try:
        baseline = CrashWatch(resolved_userdata).mark()
        print("  crash mark : {0} existing log(s) baselined".format(len(baseline)))
    except ValueError as e:
        sys.stderr.write("FATAL: could not set crash mark: {0}\n".format(e))
        return 2

    try:
        if not step_preflight(h, drv):
            # No zone / no bridge: the rest can't run. Summarize and bail.
            h.summary()
            return 1

        step_enable_cheats_and_add(h, drv)
        step_promote_to_top(h, drv)
        step_fast_track(h, drv)
        step_skill_gate(h, drv)
        step_aspiration(h, drv)
    except BridgeTimeout as e:
        h.check(False, "bridge stayed responsive", "timeout: {0}".format(e))
    except BridgeError as e:
        h.check(False, "bridge command succeeded", "bridge error: {0}".format(e))

    # Crash check runs regardless -- it's bridge-free and is the whole point of
    # gating on "did this run break the UI".
    step_no_new_crashes(h, resolved_userdata, len(baseline))

    ok = h.summary()
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="historian_career.py",
        description="sims4ctl example scenario: drive the HistorianCareer mod "
        "end-to-end against a running Sims 4.",
    )
    parser.add_argument(
        "--userdata", default=None,
        help="override the Sims 4 user-data folder (else $SIMS4CTL_USERDATA or "
        "auto-detect).",
    )
    parser.add_argument(
        "--timeout", type=float, default=15.0,
        help="bridge response timeout in seconds (default 15).",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=0.1,
        help="how often to poll response.json, in seconds (default 0.1).",
    )
    args = parser.parse_args(argv)
    return run(
        userdata=args.userdata,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )


if __name__ == "__main__":
    sys.exit(main())
