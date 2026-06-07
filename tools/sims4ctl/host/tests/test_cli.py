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


if __name__ == "__main__":
    unittest.main()
