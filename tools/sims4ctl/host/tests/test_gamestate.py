"""gamestate state-machine tests -- fully offline, no game, no deps.

We inject a fake heartbeat *client* and monkeypatch the process check so every
DOWN/MENU/LOADING/ZONE_LOADED transition is exercised deterministically, plus
``wait_for`` success and timeout. None of the automation deps are required.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sims4ctl import gamestate  # noqa: E402
from sims4ctl.gamestate import (  # noqa: E402
    DOWN, MENU, LOADING, ZONE_LOADED, GameState, StateTimeout,
)


class _FakeClient(object):
    """Stand-in for client.Client exposing just read_heartbeat/heartbeat_age."""

    def __init__(self, hb):
        self._hb = hb

    def read_heartbeat(self):
        return self._hb

    def heartbeat_age(self, now=None):
        if not self._hb or "ts" not in self._hb:
            return None
        return (now if now is not None else 0.0) - self._hb["ts"]


class _ProcPatch(object):
    """Monkeypatch gamestate.is_process_running for the duration of a block."""

    def __init__(self, running):
        self.running = running

    def __enter__(self):
        self._orig = gamestate.is_process_running
        gamestate.is_process_running = lambda name=gamestate.TS4_PROCESS_NAME: self.running
        return self

    def __exit__(self, *exc):
        gamestate.is_process_running = self._orig


NOW = 1000.0


def _gs(hb, running=True):
    """Build a GameState with a fake heartbeat + fixed clock (process patched by
    the caller's _ProcPatch)."""
    return GameState(client=_FakeClient(hb), now=lambda: NOW)


class StateTransitionTest(unittest.TestCase):
    def test_down_when_no_process(self):
        with _ProcPatch(False):
            self.assertEqual(_gs(None).current_state(), DOWN)

    def test_zone_loaded_when_fresh_and_zone(self):
        with _ProcPatch(True):
            hb = {"zone_loaded": True, "ts": NOW - 0.5, "active_sim": "Bella"}
            self.assertEqual(_gs(hb).current_state(), ZONE_LOADED)

    def test_menu_when_fresh_but_no_zone(self):
        with _ProcPatch(True):
            hb = {"zone_loaded": False, "ts": NOW - 0.5}
            self.assertEqual(_gs(hb).current_state(), MENU)

    def test_loading_when_stale_but_last_zone_true(self):
        with _ProcPatch(True):
            hb = {"zone_loaded": True, "ts": NOW - 100.0}  # stale
            self.assertEqual(_gs(hb).current_state(), LOADING)

    def test_menu_when_stale_and_no_zone_signal(self):
        with _ProcPatch(True):
            hb = {"zone_loaded": False, "ts": NOW - 100.0}
            self.assertEqual(_gs(hb).current_state(), MENU)

    def test_menu_when_process_up_but_no_heartbeat(self):
        with _ProcPatch(True):
            self.assertEqual(_gs(None).current_state(), MENU)

    def test_snapshot_reports_signals(self):
        with _ProcPatch(True):
            hb = {"zone_loaded": True, "ts": NOW - 0.5, "active_sim": "Bob"}
            snap = _gs(hb).snapshot()
            self.assertEqual(snap["state"], ZONE_LOADED)
            self.assertTrue(snap["process_running"])
            self.assertTrue(snap["heartbeat_fresh"])
            self.assertEqual(snap["active_sim"], "Bob")


class WaitForTest(unittest.TestCase):
    def test_wait_for_returns_immediately_when_already_there(self):
        with _ProcPatch(True):
            hb = {"zone_loaded": True, "ts": NOW - 0.5, "active_sim": "X"}
            snap = _gs(hb).wait_for(ZONE_LOADED, timeout=1.0, poll=0.01)
            self.assertEqual(snap["state"], ZONE_LOADED)

    def test_wait_for_times_out(self):
        with _ProcPatch(False):
            # Process down -> state is DOWN forever; waiting for MENU must time out
            # FAST and raise (we use a real but tiny timeout/poll).
            g = GameState(client=_FakeClient(None))  # real time clock
            with self.assertRaises(StateTimeout):
                g.wait_for(MENU, timeout=0.2, poll=0.02)

    def test_wait_for_rejects_unknown_state(self):
        with _ProcPatch(True):
            with self.assertRaises(ValueError):
                _gs(None).wait_for("BOGUS", timeout=0.1, poll=0.01)


class ProcessDetectionTest(unittest.TestCase):
    def test_is_process_running_false_for_absurd_name(self):
        # A name that can't exist must report False (and never raise), on any OS.
        self.assertFalse(
            gamestate.is_process_running("definitely_not_a_real_process_zzz.exe")
        )


if __name__ == "__main__":
    unittest.main()
