"""Tests for the HistorianCareer verification scenario + offline checker.

These run with NO game: they exercise the shared spec's internal consistency,
prove the offline authoring checker passes on the real repo AND actually catches
drift, and syntax-check every in-game Python snippet the live Driver sends
through the bridge (a fake bridge compiles each snippet exactly as the real
bridge's exec verb would, so a typo in an in-game snippet fails here instead of
only surfacing against a running game).
"""

import json
import os
import sys
import unittest

# Make both the host package and the sibling scenarios/ dir importable.
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SIMS4CTL_DIR = os.path.dirname(os.path.dirname(_TESTS_DIR))  # tools/sims4ctl
_SCENARIOS_DIR = os.path.join(_SIMS4CTL_DIR, "scenarios")
for _p in (os.path.join(_SIMS4CTL_DIR, "host"), _SCENARIOS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import historian_spec as spec  # noqa: E402
import historian_offline_check as offline  # noqa: E402
import historian_career as scenario  # noqa: E402


# ---------------------------------------------------------------------------
# spec internal consistency
# ---------------------------------------------------------------------------

class SpecConsistencyTest(unittest.TestCase):
    def test_pay_and_titles_cover_ten_ranks(self):
        self.assertEqual(sorted(spec.PAY), list(range(1, 11)))
        self.assertEqual(sorted(spec.TITLES), list(range(1, 11)))
        self.assertEqual(spec.MAX_LEVEL, 10)

    def test_fast_track_math(self):
        self.assertEqual(spec.FAST_TRACK_MODIFIER, 4)
        self.assertEqual(
            spec.BASE_START_LEVEL + spec.FAST_TRACK_MODIFIER,
            spec.FAST_TRACK_START_LEVEL,
        )
        self.assertEqual(spec.FAST_TRACK_START_LEVEL, 5)

    def test_gates_and_ungated_partition_the_transitions(self):
        gated = set(spec.SKILL_GATES)
        ungated = set(spec.UNGATED_FROM_LEVELS)
        self.assertEqual(gated, {1, 6, 7, 8, 9})
        self.assertEqual(ungated, {2, 3, 4, 5})
        # No transition is both gated and ungated.
        self.assertEqual(gated & ungated, set())
        # Together they account for every FROM level 1..9 (L10 has no outgoing).
        self.assertEqual(gated | ungated, set(range(1, 10)))

    def test_block_max_value_is_min_minus_one(self):
        for n in (1, 2, 5, 7, 10):
            self.assertEqual(spec.skill_max_value_for_block(n), n - 1)

    def test_gate_skill_keys_are_known(self):
        for reqs in spec.SKILL_GATES.values():
            for key in reqs:
                self.assertIn(key, spec.SKILL_IDS)

    def test_affordance_counts(self):
        self.assertEqual(len(spec.AFFORDANCES), 15)
        self.assertEqual(len(spec.affordances_by_kind("existing")), 5)
        self.assertEqual(len(spec.affordances_by_kind("new")), 8)
        self.assertEqual(len(spec.affordances_by_kind("overlay")), 2)
        self.assertEqual(spec.NEW_AFFORDANCE_COUNT, 8)
        self.assertEqual(spec.OVERLAY_COUNT, 2)
        # AFFORDANCE_BANDS is derived from AFFORDANCES with no loss.
        self.assertEqual(len(spec.AFFORDANCE_BANDS), len(spec.AFFORDANCES))

    def test_affordance_offered_logic(self):
        # Blogeintrag is a 1-2 band; offered at 1 and 2, not at 3.
        self.assertTrue(spec.affordance_offered_at("HC_Interaction_Blogeintrag", 1))
        self.assertTrue(spec.affordance_offered_at("HC_Interaction_Blogeintrag", 2))
        self.assertFalse(spec.affordance_offered_at("HC_Interaction_Blogeintrag", 3))
        # Drittmittel is only at L10.
        self.assertEqual(
            [lvl for lvl in range(1, 11)
             if spec.affordance_offered_at("HC_Interaction_Drittmittel", lvl)],
            [10],
        )
        # The two overlays are offered at every rank.
        for name in spec.affordances_by_kind("overlay"):
            for lvl in range(1, 11):
                self.assertTrue(spec.affordance_offered_at(name, lvl))

    def test_affordances_offered_at_set(self):
        at1 = spec.affordances_offered_at(1)
        self.assertIn("HC_Interaction_Blogeintrag", at1)
        self.assertNotIn("HC_Interaction_Drittmittel", at1)
        at10 = spec.affordances_offered_at(10)
        self.assertIn("HC_Interaction_Drittmittel", at10)
        self.assertIn("HC_Interaction_SuperviseDissertation", at10)

    def test_aspiration_tiers(self):
        self.assertEqual(len(spec.ASPIRATION_TIERS), 4)
        self.assertEqual(spec.REWARD_TRAIT_NAME, "trait_HabilitationRenown")


# ---------------------------------------------------------------------------
# offline authoring checker against the real repo + drift detection
# ---------------------------------------------------------------------------

class OfflineCheckerTest(unittest.TestCase):
    def test_passes_on_real_repo(self):
        h = offline.Harness()
        offline.run_offline_checks(h)
        # There must be a healthy number of checks and ZERO failures.
        self.assertGreaterEqual(len(h.checks), 30)
        self.assertEqual(h.failed, [], "offline authoring drift: {0}".format(h.failed))

    def test_detects_pay_drift(self):
        # Temporarily corrupt the spec's expectation; the checker must notice the
        # shipped tuning no longer matches. Proves the comparison is real.
        original = spec.PAY[5]
        spec.PAY[5] = original + 999
        try:
            h = offline.Harness()
            offline.run_offline_checks(h)
            self.assertTrue(
                any("L5 simoleons_per_hour" in label for _ok, label, _d in h.failed),
                "checker failed to catch a pay drift",
            )
        finally:
            spec.PAY[5] = original

    def test_detects_gate_drift(self):
        original = dict(spec.SKILL_GATES[1])
        spec.SKILL_GATES[1] = {"writing": 9, "charisma": 9}  # wrong thresholds
        try:
            h = offline.Harness()
            offline.run_offline_checks(h)
            self.assertTrue(
                any("L1->L2" in label for _ok, label, _d in h.failed),
                "checker failed to catch a gate-threshold drift",
            )
        finally:
            spec.SKILL_GATES[1] = original


# ---------------------------------------------------------------------------
# in-game snippet syntax + Driver round-trip via a fake bridge
# ---------------------------------------------------------------------------

class _FakeBridge(object):
    """Stands in for the in-game bridge. Compiles every `eval` snippet exactly
    as the real bridge's exec verb does (so SyntaxError surfaces here), and
    answers reads with canned shapes. Records the snippets it received."""

    def __init__(self):
        self.eval_codes = []

    def send(self, verb, args=None, timeout=None):
        args = args or {}
        if verb == "ping":
            return {"pong": True, "zone_loaded": True, "active_sim": "Test Sim"}
        if verb == "state":
            return [{
                "name": spec.CAREER_NAME,
                "user_level": 3,
                "simoleons_per_hour": spec.PAY[3],
            }]
        if verb == "eval":
            code = args.get("code", "")
            self.eval_codes.append(code)
            # The bridge compiles in exec mode; a malformed snippet raises here.
            compile(code, "<fake-bridge>", "exec")
            return {"stdout": scenario._RESULT_MARKER + json.dumps({"echo": True})}
        raise AssertionError("unexpected verb {0!r}".format(verb))


class DriverSnippetTest(unittest.TestCase):
    def setUp(self):
        self.bridge = _FakeBridge()
        self.drv = scenario.Driver(self.bridge, timeout=1)

    def test_preamble_compiles(self):
        compile(scenario._IN_GAME_PREAMBLE, "<preamble>", "exec")

    def test_build_code_compiles_with_params(self):
        code = scenario.Driver.build_code(
            'RESULT = {"x": GUID, "y": LEVEL}', {"GUID": 16714, "LEVEL": 5})
        compile(code, "<built>", "exec")
        self.assertIn("GUID = 16714", code)
        self.assertIn("LEVEL = 5", code)

    def test_every_mutation_and_probe_snippet_is_valid_python(self):
        # Each call assembles a snippet and sends it; the fake bridge compiles
        # it. A SyntaxError in any in-game body fails this test.
        self.drv.capture_sim_id()
        self.drv.add_career()
        self.drv.remove_career()
        self.drv.promote_once()
        self.drv.demote_once()
        self.drv.set_skill(spec.SKILL_IDS["writing"], 5)
        self.drv.set_skills({g: 10 for g in spec.SKILL_IDS.values()})
        self.drv.set_trait(spec.FAST_TRACK_TRAIT_ID, present=True)
        self.drv.set_trait(spec.REWARD_TRAIT_NAME, present=False)
        self.drv.has_trait(spec.REWARD_TRAIT_NAME)
        self.drv.trait_exists(spec.FAST_TRACK_TRAIT_ID)
        self.drv.skill_exists(spec.SKILL_IDS["research_debate"])
        self.drv.set_aspiration_track(spec.ASPIRATION_TRACK_NAME)
        self.drv.promotion_blocked()
        self.drv.affordance_gate_state()
        self.drv.daily_task_stash()
        self.drv.run_daily_rotation()
        self.drv.wfh_enabled()
        # Sanity: every snippet carried the RESULT print + the params we expect.
        self.assertTrue(self.bridge.eval_codes)
        for code in self.bridge.eval_codes:
            self.assertIn("RESULT", code)
            self.assertIn("print(_S + json.dumps(RESULT", code)

    def test_run_extracts_result_from_marker_line(self):
        out = self.drv._run('RESULT = {"hello": 1}')
        self.assertEqual(out, {"echo": True})  # fake echoes a fixed RESULT

    def test_career_reads_parse_state_verb(self):
        level, pay = self.drv.historian_level_pay()
        self.assertEqual(level, 3)
        self.assertEqual(pay, spec.PAY[3])
        entry = self.drv.historian_entry()
        self.assertEqual(entry["name"], spec.CAREER_NAME)

    def test_run_raises_without_marker(self):
        class _NoMarker(object):
            def send(self, verb, args=None, timeout=None):
                return {"stdout": "nothing useful here"}

        drv = scenario.Driver(_NoMarker(), timeout=1)
        from sims4ctl.client import BridgeError
        with self.assertRaises(BridgeError):
            drv._run('RESULT = 1')


if __name__ == "__main__":
    unittest.main()
