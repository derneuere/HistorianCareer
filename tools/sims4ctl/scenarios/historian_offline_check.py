#!/usr/bin/env python3
"""historian_offline_check.py -- verify the Historian career's AUTHORING.

The in-game scenario (`historian_career.py`) can only confirm runtime BEHAVIOUR
when a Sims 4 is actually running. This checker confirms the other half --- that
the shipped tuning XML and the script-side gates ENCODE exactly the spec the
in-game checks assert against --- and it needs **no game running at all**. It is
the static, repeatable, CI-friendly companion to the live scenario, and it doubles
as a regression guard: if a tuning value drifts from `historian_spec.py`, this
fails loudly.

What it cross-checks (each against `historian_spec.py`, the single source of truth):

  1. Pay schedule   -- Tuning/career_level_Adult_Historian_L{1..10}.xml
  2. Fast-track     -- Tuning/career_Adult_Historian_HiWi.xml (separate entry)
  3. Skill gates    -- Tuning/career_Adult_Historian.xml block_promotion_tests
                       (all 5 gated transitions + the 4 ungated ones)
  4. Affordances    -- Scripts/historian_career/level_gate.py _LEVEL_REQUIREMENTS
                       + affordance_injector.py surface groups (15 = 5 + 8 + 2 overlays)
  5. Aspiration     -- Tuning/aspiration_track_HistorianCalling.xml
                       + Tuning/trait_HabilitationRenown.xml
  6. WFH + rotation -- career_early_warning_alarm (enabled + work_from_home_text)
                       + daily_task_rotation.py _FALLBACK_POOLS (10 levels)
  7. Consistency    -- spec.TITLES == historian_career.py TIERS (English titles)

Run it:
    python scenarios/historian_offline_check.py
    python scenarios/historian_offline_check.py --repo-root C:/path/to/HistorianCareer
    sims4ctl run-scenario historian_offline_check     # (no game needed)

Exit code is 0 only when EVERY check passes; non-zero otherwise. Stdlib only.
"""

import argparse
import ast
import os
import re
import sys
import xml.etree.ElementTree as ET

# Import the shared spec. When run as a script the scenarios dir is on the path
# via __file__; when imported as a module it's already importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import historian_spec as spec  # noqa: E402


# ---------------------------------------------------------------------------
# A tiny PASS/FAIL harness, shared with the live scenario (which imports it).
# Records every check; never aborts the run on a single failed assertion.
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

    def summary(self, header="OVERALL"):
        total = len(self.checks)
        nfail = len(self.failed)
        npass = total - nfail
        print("")
        print("=" * 64)
        if nfail == 0:
            print("{0}: PASS  ({1}/{1} checks)".format(header, total))
        else:
            print("{0}: FAIL  ({1}/{2} checks passed)".format(header, npass, total))
            print("Failed checks:")
            for ok, label, detail in self.failed:
                print("  - {0}  ({1})".format(label, detail))
        print("=" * 64)
        return nfail == 0


# ---------------------------------------------------------------------------
# Repo / file resolution. scenarios/ lives at <repo>/tools/sims4ctl/scenarios,
# so the HistorianCareer repo root is three parents up.
# ---------------------------------------------------------------------------

def find_repo_root(override=None):
    if override:
        return os.path.abspath(override)
    # .../tools/sims4ctl/scenarios/historian_offline_check.py
    return os.path.abspath(os.path.join(_HERE, "..", "..", ".."))


def _tuning_dir(repo_root):
    return os.path.join(repo_root, "Tuning")


def _scripts_dir(repo_root):
    return os.path.join(repo_root, "Scripts", "historian_career")


def _parse_xml(path):
    """Parse a tuning XML file, returning the root element (or raising)."""
    return ET.parse(path).getroot()


# ---------------------------------------------------------------------------
# Extract a top-level literal assignment from a .py file WITHOUT importing it
# (so we never trigger the module-level zone hooks / log writes in the scripts).
# ---------------------------------------------------------------------------

def _extract_literal(path, varname):
    """Return ast.literal_eval of the value assigned to `varname` at module
    scope in `path`. Raises KeyError if the assignment isn't found."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == varname:
                    return ast.literal_eval(node.value)
    raise KeyError("{0} not found in {1}".format(varname, path))


_LEVEL_RE = re.compile(r"_L(\d+)$")


def _level_from_career_level_name(name):
    """'career_level_Adult_Historian_L7' -> 7 (or None)."""
    if not name:
        return None
    m = _LEVEL_RE.search(name.strip())
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Individual check groups. Each appends to the shared Harness `h`.
# ---------------------------------------------------------------------------

def check_pay_schedule(h, repo_root):
    print("\n-- Pay schedule: career_level_Adult_Historian_L{1..10}.xml --")
    tdir = _tuning_dir(repo_root)
    for level in range(1, spec.MAX_LEVEL + 1):
        path = os.path.join(tdir, "career_level_Adult_Historian_L{0}.xml".format(level))
        if not os.path.isfile(path):
            h.check(False, "L{0} tuning present".format(level), path)
            continue
        root = _parse_xml(path)
        node = root.find(".//T[@n='simoleons_per_hour']")
        got = int(node.text) if node is not None and node.text else None
        h.eq(got, spec.PAY[level], "L{0} simoleons_per_hour".format(level))


def check_fast_track(h, repo_root):
    print("\n-- DU fast-track: separate degree-gated HiWi entry (+4 -> L5) --")
    tdir = _tuning_dir(repo_root)

    # 1. The regular career must NO LONGER carry an in-place start_level_modifiers
    #    block — degree holders are not auto-bumped on the main entry anymore, so
    #    they get a real choice (grind from L1, or take the HiWi entry to L5).
    main = _parse_xml(os.path.join(tdir, "career_Adult_Historian.xml"))
    h.check(main.find(".//U[@n='start_level_modifiers']") is None,
            "regular career has no start_level_modifiers (always starts at L1)")

    # 2. The HiWi fast-track is a SEPARATE Career resource with an UNCONDITIONAL
    #    +4 start_level_modifiers (the degree-gating lives in availability tests,
    #    not inside the modifier).
    hiwi_path = os.path.join(tdir, "career_Adult_Historian_HiWi.xml")
    if not os.path.isfile(hiwi_path):
        h.check(False, "HiWi career file present", "missing career_Adult_Historian_HiWi.xml")
        return
    hiwi = _parse_xml(hiwi_path)
    slm = hiwi.find(".//U[@n='start_level_modifiers']")
    if slm is None:
        h.check(False, "HiWi start_level_modifiers present", "missing block")
        return
    mod_node = slm.find(".//L[@n='modifiers']/U/T[@n='modifier']")
    got_mod = int(mod_node.text) if mod_node is not None and mod_node.text else None
    h.eq(got_mod, spec.FAST_TRACK_MODIFIER, "HiWi fast-track modifier == +4")
    h.check(slm.find(".//L[@n='modifiers']/U/L[@n='tests']/L") is None,
            "HiWi modifier is unconditional (degree-gating is in availability)")
    h.eq(spec.BASE_START_LEVEL + (got_mod or 0), spec.FAST_TRACK_START_LEVEL,
         "degree holder starts at L5 via the HiWi entry")

    # 3. The HiWi entry is degree-gated via career_availablity_tests (so it only
    #    appears in the find-a-job picker for History-degree holders).
    avail = hiwi.find(".//L[@n='career_availablity_tests']")
    trait_node = avail.find(".//L[@n='whitelist_traits']/T") if avail is not None else None
    got_trait = int(trait_node.text) if trait_node is not None and trait_node.text else None
    h.eq(got_trait, spec.FAST_TRACK_TRAIT_ID,
         "HiWi entry gated on History-degree trait 230331")

    # 4. The HiWi career points at its own track (its own find-a-job label), and
    #    that track file exists.
    st = hiwi.find(".//T[@n='start_track']")
    h.eq(st.text if st is not None else None, spec.HIWI_TRACK_NAME,
         "HiWi career start_track -> HiWi track")
    h.check(os.path.isfile(os.path.join(tdir, "career_track_Adult_Historian_HiWi.xml")),
            "HiWi track file present")


def _parse_block_promotion_gates(repo_root):
    """Parse career_Adult_Historian.xml block_promotion_tests into
    {from_level: {skill_key: min_required}}. Raises on a malformed group."""
    root = _parse_xml(os.path.join(_tuning_dir(repo_root), "career_Adult_Historian.xml"))
    bpt = root.find(".//L[@n='block_promotion_tests']")
    guid_to_key = {gid: key for key, gid in spec.SKILL_IDS.items()}
    gates = {}
    if bpt is None:
        return gates
    for group in bpt.findall("L"):  # each <L> is one AND group
        cl_node = group.find(".//T[@n='career_level']")
        from_level = _level_from_career_level_name(
            cl_node.text if cl_node is not None else None)
        # EA skill test variant is `skill_test` with a `skill_range` interval
        # whose `upper_bound` is the highest skill level that still BLOCKS the
        # promotion (so required minimum == upper_bound + 1). The earlier
        # `<V t="skill">` + `max_value` form did not resolve in-game (issue #32).
        skill_node = group.find(".//V[@t='skill_test']//T[@n='skill']")
        ub_node = group.find(".//V[@t='skill_test']//T[@n='upper_bound']")
        if from_level is None or skill_node is None or ub_node is None:
            raise ValueError("malformed block_promotion_tests group")
        skill_key = guid_to_key.get(int(skill_node.text))
        min_required = int(ub_node.text) + 1  # block while skill <= upper_bound
        gates.setdefault(from_level, {})[skill_key] = min_required
    return gates


def check_skill_gates(h, repo_root):
    print("\n-- Skill gates: block_promotion_tests (5 gated transitions) --")
    try:
        gates = _parse_block_promotion_gates(repo_root)
    except (ValueError, OSError) as e:
        h.check(False, "parse block_promotion_tests", str(e))
        return

    # Every documented gate is present with the exact skill thresholds.
    for from_level in spec.gated_from_levels():
        want = spec.SKILL_GATES[from_level]
        got = gates.get(from_level)
        h.eq(got, want,
             "L{0}->L{1} gate {2}".format(from_level, from_level + 1, want))

    # No EXTRA gates leaked onto a performance-only transition.
    for from_level in spec.UNGATED_FROM_LEVELS:
        leaked = from_level in gates
        h.check(not leaked,
                "L{0}->L{1} is performance-only (no gate)".format(
                    from_level, from_level + 1),
                "unexpected gate: {0}".format(gates.get(from_level)) if leaked else "")

    # The tuning gates exactly the documented set -- nothing more, nothing less.
    h.eq(set(gates), set(spec.SKILL_GATES), "gated transitions == spec set")


def check_affordance_bands(h, repo_root):
    print("\n-- Affordance bands: level_gate.py + affordance_injector.py --")
    sdir = _scripts_dir(repo_root)
    try:
        bands = _extract_literal(
            os.path.join(sdir, "level_gate.py"), "_LEVEL_REQUIREMENTS")
    except (KeyError, OSError, SyntaxError) as e:
        h.check(False, "read _LEVEL_REQUIREMENTS", str(e))
        return

    # level_gate bands == spec bands, exactly.
    bands_t = {k: tuple(v) for k, v in bands.items()}
    h.eq(bands_t, spec.AFFORDANCE_BANDS, "level_gate bands == spec (15 entries)")

    # Counts match the issue's wording: 5 existing + 8 new + 2 overlays = 15.
    h.eq(len(spec.AFFORDANCES), len(bands_t), "affordance count matches")
    h.eq(len(spec.affordances_by_kind("new")), spec.NEW_AFFORDANCE_COUNT,
         "8 new affordances")
    h.eq(len(spec.affordances_by_kind("overlay")), spec.OVERLAY_COUNT,
         "2 social overlays")
    h.eq(len(spec.affordances_by_kind("existing")), spec.EXISTING_AFFORDANCE_COUNT,
         "5 existing affordances re-banded")

    # Injector surface groups agree with the spec's surface tagging.
    try:
        inj = os.path.join(sdir, "affordance_injector.py")
        comp = _extract_literal(inj, "_HC_COMPUTER_AFFORDANCE_NAMES")
        book = _extract_literal(inj, "_HC_BOOKSHELF_AFFORDANCE_NAMES")
        social = _extract_literal(inj, "_HC_SOCIAL_AFFORDANCE_NAMES")
    except (KeyError, OSError, SyntaxError) as e:
        h.check(False, "read affordance_injector surface groups", str(e))
        return
    h.eq(set(comp), set(spec.affordances_by_surface("computer")),
         "computer surface group matches spec")
    h.eq(set(book), set(spec.affordances_by_surface("bookshelf")),
         "bookshelf surface group matches spec")
    h.eq(set(social), set(spec.affordances_by_surface("social")),
         "social surface group matches spec")
    # Every banded affordance is injected on exactly one surface.
    injected = set(comp) | set(book) | set(social)
    h.eq(injected, set(spec.AFFORDANCE_BANDS),
         "every banded affordance is injected on a surface")


def check_aspiration(h, repo_root):
    print("\n-- Aspiration track + Habilitation Renown reward trait --")
    tdir = _tuning_dir(repo_root)
    root = _parse_xml(os.path.join(tdir, "aspiration_track_HistorianCalling.xml"))

    # 4 tiers T1..T4.
    asp_list = root.find(".//L[@n='aspirations']")
    tier_values = []
    if asp_list is not None:
        for u in asp_list.findall("U"):
            v = u.find("T[@n='value']")
            if v is not None and v.text:
                tier_values.append(v.text.strip())
    h.eq(tuple(tier_values), spec.ASPIRATION_TIERS, "4 aspiration tiers T1..T4")

    # provided_traits includes trait_HabilitationRenown.
    provided = [t.text.strip() for t in root.findall(".//L[@n='provided_traits']/T")
                if t.text]
    h.check(spec.REWARD_TRAIT_NAME in provided,
            "track provides {0}".format(spec.REWARD_TRAIT_NAME),
            "provided_traits={0}".format(provided))

    # reward chain id.
    reward = root.find(".//T[@n='reward']")
    got_reward = int(reward.text) if reward is not None and reward.text else None
    h.eq(got_reward, spec.ASPIRATION_REWARD_ID, "final-tier reward chain id")

    # The reward trait itself: GAMEPLAY type + the focused-low loot.
    trait_path = os.path.join(tdir, "trait_HabilitationRenown.xml")
    if not os.path.isfile(trait_path):
        h.check(False, "trait_HabilitationRenown.xml present", trait_path)
        return
    troot = _parse_xml(trait_path)
    ttype = troot.find(".//E[@n='trait_type']")
    h.eq(ttype.text.strip() if ttype is not None and ttype.text else None,
         spec.REWARD_TRAIT_TYPE, "reward trait_type == GAMEPLAY")
    loot = [t.text.strip() for t in troot.findall(".//L[@n='loot_on_trait_add']/T")
            if t.text]
    h.check(spec.REWARD_TRAIT_LOOT in loot,
            "reward trait applies {0}".format(spec.REWARD_TRAIT_LOOT),
            "loot={0}".format(loot))


def check_wfh_and_rotation(h, repo_root):
    print("\n-- Work-From-Home + daily-task rotation --")
    root = _parse_xml(os.path.join(_tuning_dir(repo_root), "career_Adult_Historian.xml"))
    alarm = root.find(".//V[@n='career_early_warning_alarm']")
    if alarm is None:
        h.check(False, "career_early_warning_alarm present", "missing")
    else:
        h.eq(alarm.get("t"), spec.WFH_EARLY_WARNING_VARIANT,
             "career_early_warning_alarm uses the 'enabled' variant")
        wfh_text = alarm.find(".//T[@n='{0}']".format(spec.WFH_TEXT_FIELD))
        h.check(wfh_text is not None,
                "WFH offered (work_from_home_text present)",
                "" if wfh_text is not None else "field missing -> WFH not enabled")

    # Daily-task rotation pools cover all 10 ranks.
    try:
        pools = _extract_literal(
            os.path.join(_scripts_dir(repo_root), "daily_task_rotation.py"),
            "_FALLBACK_POOLS")
    except (KeyError, OSError, SyntaxError) as e:
        h.check(False, "read _FALLBACK_POOLS", str(e))
        return
    missing = [lvl for lvl in spec.DAILY_TASK_POOL_LEVELS
               if not pools.get(lvl)]
    h.check(not missing, "daily-task pool for all 10 ranks",
            "levels with empty/no pool: {0}".format(missing) if missing else "")


def check_title_consistency(h, repo_root):
    print("\n-- Consistency: spec titles == historian_career.py TIERS --")
    try:
        tiers = _extract_literal(
            os.path.join(_scripts_dir(repo_root), "historian_career.py"), "TIERS")
    except (KeyError, OSError, SyntaxError) as e:
        h.check(False, "read TIERS", str(e))
        return
    english = {lvl: pair[0] for lvl, pair in tiers.items()}
    h.eq(english, spec.TITLES, "English titles match across spec and script")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_offline_checks(h, repo_root=None):
    """Run every offline authoring check, appending results to `h`. Returns the
    repo root used (so a caller can reuse it). Never raises on a check failure;
    only a totally-missing repo aborts."""
    repo_root = find_repo_root(repo_root)
    tdir = _tuning_dir(repo_root)
    if not os.path.isdir(tdir):
        h.check(False, "HistorianCareer Tuning/ dir found",
                "not a directory: {0}".format(tdir))
        return repo_root
    print("HistorianCareer offline authoring check")
    print("  repo root  : {0}".format(repo_root))
    check_pay_schedule(h, repo_root)
    check_fast_track(h, repo_root)
    check_skill_gates(h, repo_root)
    check_affordance_bands(h, repo_root)
    check_aspiration(h, repo_root)
    check_wfh_and_rotation(h, repo_root)
    check_title_consistency(h, repo_root)
    return repo_root


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="historian_offline_check.py",
        description="Verify the HistorianCareer tuning/scripts encode the "
        "documented ten-rank spec. No running game required.",
    )
    parser.add_argument(
        "--repo-root", default=None,
        help="HistorianCareer repo root (default: auto-detect from this file).",
    )
    # Accept --userdata so `sims4ctl run-scenario` (which passes it) doesn't choke.
    parser.add_argument("--userdata", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    h = Harness()
    run_offline_checks(h, repo_root=args.repo_root)
    ok = h.summary(header="OFFLINE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
