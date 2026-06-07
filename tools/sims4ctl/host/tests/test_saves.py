"""saves enumeration + test-slot backup/restore tests -- offline, tmp dir.

We build a fake ``<USERDATA>/saves`` tree, enumerate it, then back up and
restore the reserved test slot, asserting: the right files travel, the baseline
is read-only, a restore reproduces the baseline bytes over a mutated live slot,
and the protected player slots are guarded.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sims4ctl import saves  # noqa: E402
from sims4ctl.saves import SaveSafetyError  # noqa: E402


class _Tree(object):
    """A temp userdata tree with a saves/ folder; cleans up on exit."""

    def __enter__(self):
        self.ud = tempfile.mkdtemp()
        self.saves = Path(self.ud) / "saves"
        self.saves.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *exc):
        import shutil
        # Some baseline files are read-only; force-remove.
        for root, _dirs, files in os.walk(self.ud):
            for f in files:
                try:
                    os.chmod(os.path.join(root, f), 0o600)
                except OSError:
                    pass
        shutil.rmtree(self.ud, ignore_errors=True)

    def write_slot(self, slot_id, content, with_backups=True):
        name = saves.slot_filename(slot_id)
        (self.saves / name).write_text(content, encoding="utf-8")
        if with_backups:
            (self.saves / (name + ".ver0")).write_text(content + "_v0", encoding="utf-8")
            (self.saves / (name + ".day.ver0")).write_text(content + "_d0", encoding="utf-8")


class ListSavesTest(unittest.TestCase):
    def test_enumerates_only_primary_slots(self):
        with _Tree() as t:
            t.write_slot(0x02, "p2")
            t.write_slot(0xFF, "test")
            got = saves.list_saves(userdata=t.ud)
            ids = [s["slot_id"] for s in got]
            self.assertEqual(ids, [0x02, 0xFF])  # sorted, no .ver* entries
            names = {s["name"] for s in got}
            self.assertNotIn("Slot_00000002.save.ver0", names)

    def test_missing_saves_dir_is_empty(self):
        with _Tree() as t:
            import shutil
            shutil.rmtree(str(t.saves))
            self.assertEqual(saves.list_saves(userdata=t.ud), [])

    def test_slot_filename_format(self):
        self.assertEqual(saves.slot_filename(0xFF), "Slot_000000FF.save")
        self.assertEqual(saves.slot_filename(2), "Slot_00000002.save")


class BackupRestoreTest(unittest.TestCase):
    def test_backup_copies_siblings_and_is_readonly(self):
        with _Tree() as t:
            t.write_slot(saves.TEST_SLOT_ID, "pristine")
            baseline = Path(t.ud) / "baseline"
            created = saves.backup_test_slot(userdata=t.ud, dest=str(baseline))
            # Primary + .ver0 + .day.ver0 all backed up.
            self.assertEqual(len(created), 3)
            primary = baseline / saves.slot_filename(saves.TEST_SLOT_ID)
            self.assertTrue(primary.is_file())
            # Baseline primary must be read-only (no owner write bit).
            mode = os.stat(str(primary)).st_mode
            self.assertFalse(mode & 0o200, "baseline should be read-only")

    def test_restore_reproduces_baseline_over_mutation(self):
        with _Tree() as t:
            t.write_slot(saves.TEST_SLOT_ID, "pristine", with_backups=False)
            baseline = Path(t.ud) / "baseline"
            saves.backup_test_slot(userdata=t.ud, dest=str(baseline))

            # Mutate the live slot (simulate a run that dirtied the world).
            live = t.saves / saves.slot_filename(saves.TEST_SLOT_ID)
            live.write_text("DIRTY", encoding="utf-8")
            self.assertEqual(live.read_text(encoding="utf-8"), "DIRTY")

            restored = saves.restore_test_slot(userdata=t.ud, source=str(baseline))
            self.assertEqual(len(restored), 1)
            self.assertEqual(live.read_text(encoding="utf-8"), "pristine")
            # Restored live file must be writable again (game rotates it).
            self.assertTrue(os.stat(str(live)).st_mode & 0o200)

    def test_backup_missing_slot_raises(self):
        with _Tree() as t:
            with self.assertRaises(FileNotFoundError):
                saves.backup_test_slot(userdata=t.ud, dest=str(Path(t.ud) / "b"))

    def test_restore_without_baseline_raises(self):
        with _Tree() as t:
            t.write_slot(saves.TEST_SLOT_ID, "x")
            with self.assertRaises(FileNotFoundError):
                saves.restore_test_slot(
                    userdata=t.ud, source=str(Path(t.ud) / "no_baseline")
                )

    def test_protected_slot_guarded(self):
        with _Tree() as t:
            t.write_slot(0x02, "player")
            with self.assertRaises(SaveSafetyError):
                saves.backup_test_slot(
                    slot_id=0x02, userdata=t.ud, dest=str(Path(t.ud) / "b")
                )
            with self.assertRaises(SaveSafetyError):
                saves.restore_test_slot(
                    slot_id=0x02, userdata=t.ud, source=str(Path(t.ud) / "b")
                )

    def test_protected_slot_allowed_with_force(self):
        with _Tree() as t:
            t.write_slot(0x02, "player")
            baseline = Path(t.ud) / "b"
            # force=True bypasses the guard (used only deliberately).
            created = saves.backup_test_slot(
                slot_id=0x02, userdata=t.ud, dest=str(baseline), force=True
            )
            self.assertTrue(created)


if __name__ == "__main__":
    unittest.main()
