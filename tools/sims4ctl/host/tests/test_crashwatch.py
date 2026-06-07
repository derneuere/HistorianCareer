"""crashwatch diff tests — bridge-free, against a temp user-data folder.

Covers: empty baseline, detecting a brand-new crash log, detecting a CHANGED
log (grown size / new mtime), mark/since-mark persistence across CrashWatch
instances (simulating two separate CLI invocations), and that a vanished log is
NOT reported as new.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sims4ctl.crashwatch import CrashWatch  # noqa: E402


class CrashWatchTest(unittest.TestCase):
    def setUp(self):
        self.ud = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.ud, ignore_errors=True)

    def _write(self, name, content):
        p = Path(self.ud) / name
        p.write_text(content, encoding="utf-8")
        return p

    def _bump_mtime(self, path, delta=10):
        """Force a distinct mtime so diff detects the change deterministically
        (size-only changes on the same second could otherwise alias)."""
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + delta))

    def test_empty_snapshot(self):
        watch = CrashWatch(self.ud)
        self.assertEqual(watch.snapshot(), {})
        self.assertEqual(watch.since_mark(), [])

    def test_mark_then_no_change_is_clean(self):
        self._write("lastException.txt", "boom")
        watch = CrashWatch(self.ud)
        watch.mark()
        self.assertEqual(watch.since_mark(), [])

    def test_new_log_after_mark_detected(self):
        watch = CrashWatch(self.ud)
        watch.mark()  # clean baseline (no logs yet)
        self._write("lastException.txt", "crash!")
        self.assertEqual(watch.since_mark(), ["lastException.txt"])

    def test_changed_log_detected(self):
        p = self._write("lastUIException.txt", "first")
        watch = CrashWatch(self.ud)
        watch.mark()
        # Append + bump mtime: simulates the game logging another exception.
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("second")
        self._bump_mtime(p)
        self.assertEqual(watch.since_mark(), ["lastUIException.txt"])

    def test_both_families_globbed(self):
        watch = CrashWatch(self.ud)
        watch.mark()
        self._write("lastException_abc123.txt", "x")
        self._write("lastUIException.txt", "y")
        self.assertEqual(
            watch.since_mark(),
            ["lastException_abc123.txt", "lastUIException.txt"],
        )

    def test_vanished_log_not_reported(self):
        p = self._write("lastException.txt", "x")
        watch = CrashWatch(self.ud)
        watch.mark()
        os.remove(p)
        # A deleted log is not a fresh crash.
        self.assertEqual(watch.since_mark(), [])

    def test_mark_persists_across_instances(self):
        self._write("lastException.txt", "x")
        CrashWatch(self.ud).mark()
        # A separate instance (= separate CLI invocation) reads the same mark.
        other = CrashWatch(self.ud)
        self.assertEqual(other.since_mark(), [])
        # Now a new crash appears; the second instance still sees it.
        self._write("lastUIException.txt", "new")
        self.assertEqual(other.since_mark(), ["lastUIException.txt"])

    def test_since_mark_without_prior_mark_reports_all(self):
        self._write("lastException.txt", "x")
        # No mark() ever called -> conservative: every present log is "new".
        self.assertEqual(CrashWatch(self.ud).since_mark(), ["lastException.txt"])

    def test_mark_file_under_sims4ctl_subdir(self):
        watch = CrashWatch(self.ud)
        watch.mark()
        self.assertTrue(
            (Path(self.ud) / "sims4ctl" / ".crashmark.json").is_file()
        )

    def test_corrupt_mark_treated_as_none(self):
        watch = CrashWatch(self.ud)
        watch.mark_path.parent.mkdir(parents=True, exist_ok=True)
        watch.mark_path.write_text("{not json", encoding="utf-8")
        self._write("lastException.txt", "x")
        # Unreadable mark -> behaves like no mark -> reports present logs.
        self.assertEqual(watch.since_mark(), ["lastException.txt"])


if __name__ == "__main__":
    unittest.main()
