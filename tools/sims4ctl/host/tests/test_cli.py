"""CLI-level tests: duration parsing, exit codes, and a full loopback ping
through ``cli.main`` (no game). These prove scripts can gate on the exit code.
"""

import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sims4ctl import cli  # noqa: E402
from sims4ctl.cli import CliError, parse_duration  # noqa: E402
from test_client import _LoopbackBridge  # noqa: E402  (reuse the mock bridge)


class DurationParseTest(unittest.TestCase):
    def test_hours_only(self):
        self.assertEqual(parse_duration("4h"), (4, 0))

    def test_minutes_only(self):
        self.assertEqual(parse_duration("30m"), (0, 30))

    def test_hours_and_minutes(self):
        self.assertEqual(parse_duration("2h30m"), (2, 30))

    def test_whitespace_and_case(self):
        self.assertEqual(parse_duration(" 1H 15M "), (1, 15))

    def test_zero_rejected(self):
        with self.assertRaises(CliError):
            parse_duration("0h0m")

    def test_garbage_rejected(self):
        for bad in ("", "soon", "4x", "h", "m30h"):
            with self.assertRaises(CliError):
                parse_duration(bad)


class CrashesCliTest(unittest.TestCase):
    """`crashes` must work with NO bridge and gate via exit code."""

    def setUp(self):
        self.ud = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.ud, ignore_errors=True)

    def test_mark_then_clean_exits_zero(self):
        rc = cli.main(["--userdata", self.ud, "crashes", "--mark"])
        self.assertEqual(rc, 0)
        rc = cli.main(["--userdata", self.ud, "crashes", "--since-mark"])
        self.assertEqual(rc, 0)

    def test_new_crash_exits_nonzero(self):
        cli.main(["--userdata", self.ud, "crashes", "--mark"])
        with open(os.path.join(self.ud, "lastException.txt"), "w") as fh:
            fh.write("crash")
        rc = cli.main(["--userdata", self.ud, "crashes"])
        self.assertEqual(rc, 1)


class PingCliLoopbackTest(unittest.TestCase):
    """Drive the whole CLI ping path against the mock bridge."""

    def setUp(self):
        self.ud = tempfile.mkdtemp()
        # The CLI computes the bridge dir as <USERDATA>/sims4ctl; create it so
        # the loopback thread and the client share the same directory.
        self.bridge_dir = os.path.join(self.ud, "sims4ctl")
        os.makedirs(self.bridge_dir, exist_ok=True)
        self.bridge = _LoopbackBridge(
            self.bridge_dir,
            lambda verb, args: (
                True,
                {"pong": True, "zone_loaded": True, "active_sim": None,
                 "bridge_version": "0.1.0"},
                None,
            ),
        )
        self.bridge.start()

    def tearDown(self):
        self.bridge.stop()
        import shutil

        shutil.rmtree(self.ud, ignore_errors=True)

    def test_ping_exits_zero(self):
        rc = cli.main(
            ["--userdata", self.ud, "--poll-interval", "0.01", "ping"]
        )
        self.assertEqual(rc, 0)

    def test_ping_json_exits_zero(self):
        rc = cli.main(
            ["--userdata", self.ud, "--poll-interval", "0.01", "--json", "ping"]
        )
        self.assertEqual(rc, 0)


class TimeoutExitCodeTest(unittest.TestCase):
    def test_ping_timeout_exits_three(self):
        ud = tempfile.mkdtemp()
        try:
            rc = cli.main(
                ["--userdata", ud, "--timeout", "0.2", "--poll-interval", "0.01", "ping"]
            )
            self.assertEqual(rc, 3)
        finally:
            import shutil

            shutil.rmtree(ud, ignore_errors=True)


class DoctorCliTest(unittest.TestCase):
    def test_doctor_runs_with_no_game(self):
        ud = tempfile.mkdtemp()
        try:
            rc = cli.main(["--userdata", ud, "doctor"])
            # USERDATA resolves (we passed it) so doctor succeeds even though
            # there's no heartbeat.
            self.assertEqual(rc, 0)
        finally:
            import shutil

            shutil.rmtree(ud, ignore_errors=True)


class RecipeBCliTest(unittest.TestCase):
    """The Recipe B subcommands must parse + run dep-free with no game.

    These are hermetic regardless of whether a real game is running on the dev
    box: the menu-aware/wait-for tests monkeypatch the process check, and the
    window-dependent tests point at a temp config whose title substring CANNOT
    match any real window (so find_game_window returns None -> CliError -> 2).
    We never drive the live game.
    """

    NO_MATCH_TITLE = "ZZZ_NO_SUCH_WINDOW_TITLE_XYZ"

    def setUp(self):
        self.ud = tempfile.mkdtemp()
        # A temp automation config whose window title never matches a real
        # window, so window-backed commands fail deterministically.
        import json

        self.cfg_path = os.path.join(self.ud, "automation_config.json")
        with open(self.cfg_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "window_title_substr": self.NO_MATCH_TITLE,
                    "templates_dir": "templates",
                    "targets": {
                        "continue": {"norm": [0.5, 0.45]},
                        "mods_dialog_dismiss": {"enabled": False, "norm": [0.5, 0.6]},
                    },
                },
                fh,
            )
        # Force the process check to report DOWN for the state-machine tests so
        # they don't depend on whether TS4 is actually running here.
        from sims4ctl import gamestate

        self._orig_proc = gamestate.is_process_running
        gamestate.is_process_running = lambda name=gamestate.TS4_PROCESS_NAME: False

    def tearDown(self):
        from sims4ctl import gamestate

        gamestate.is_process_running = self._orig_proc
        import shutil

        shutil.rmtree(self.ud, ignore_errors=True)

    def test_state_menu_aware_reports_down_with_no_game(self):
        # Process forced DOWN, no heartbeat -> DOWN, and it must NOT block on a
        # bridge timeout (menu-aware path never calls the bridge).
        rc = cli.main(["--userdata", self.ud, "state", "--menu-aware"])
        self.assertEqual(rc, 0)

    def test_state_menu_aware_json(self):
        rc = cli.main(["--userdata", self.ud, "--json", "state", "--menu-aware"])
        self.assertEqual(rc, 0)

    def test_wait_for_rejects_unknown_state(self):
        rc = cli.main(["--userdata", self.ud, "wait-for", "BOGUS"])
        self.assertEqual(rc, 2)  # CliError -> exit 2

    def test_wait_for_times_out_nonzero(self):
        # Wait for ZONE_LOADED with the process forced DOWN -> times out -> exit 2.
        rc = cli.main(
            ["--userdata", self.ud, "--timeout", "0.3", "--poll", "0.05",
             "wait-for", "ZONE_LOADED"]
        )
        self.assertEqual(rc, 2)

    def test_load_save_without_window_fails_cleanly(self):
        # No matching game window -> find_game_window None -> CliError -> exit 2.
        rc = cli.main(
            ["--userdata", self.ud, "load-save", "--continue", "--config", self.cfg_path]
        )
        self.assertEqual(rc, 2)

    def test_calibrate_without_window_fails_cleanly(self):
        rc = cli.main(
            ["--userdata", self.ud, "calibrate", "--config", self.cfg_path]
        )
        self.assertEqual(rc, 2)

    def test_run_scenario_unknown_name_fails_cleanly(self):
        rc = cli.main(["--userdata", self.ud, "run-scenario", "no_such_scenario_xyz"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
