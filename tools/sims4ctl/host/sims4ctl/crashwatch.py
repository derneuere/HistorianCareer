"""crashwatch.py — detect new/changed Sims 4 crash logs WITHOUT a bridge.

The game writes ``lastException*.txt`` (Python tracebacks) and
``lastUIException*.txt`` (UI/script-call exceptions) into the user-data folder.
We snapshot each matching file's ``(mtime, size)``; a later snapshot that
differs — a new file, or an existing file that grew/was rewritten — means the
game logged a fresh crash since the mark.

This is deliberately bridge-free: it only stats files on disk, so an agent can
gate a test on "0 new exceptions" even if the in-game bridge never loaded.

The mark is persisted to ``<USERDATA>/sims4ctl/.crashmark.json`` so ``--mark``
in one CLI invocation and ``--since-mark`` in a later one correlate across
processes.
"""

import glob
import json
import os
from pathlib import Path

# Glob patterns for the two crash-log families the game writes at the user-data
# root. Matches both the bare ``lastException.txt`` and numbered siblings like
# ``lastException_<hash>.txt`` that the game rotates.
CRASH_GLOBS = ("lastException*.txt", "lastUIException*.txt")

MARK_FILENAME = ".crashmark.json"


class CrashWatch(object):
    """Snapshot / diff crash logs under a user-data folder.

    ``userdata`` is the resolved Sims 4 user-data folder; the mark file lives in
    its ``sims4ctl/`` subdirectory (created on demand).
    """

    def __init__(self, userdata):
        if userdata is None:
            raise ValueError(
                "userdata is None — could not resolve the Sims 4 user folder. "
                "Pass --userdata or set SIMS4CTL_USERDATA."
            )
        self.userdata = Path(userdata)

    @property
    def mark_path(self):
        return self.userdata / "sims4ctl" / MARK_FILENAME

    # -- snapshotting --------------------------------------------------------

    def snapshot(self):
        """Return ``{relative_name: {"mtime": float, "size": int}}`` for every
        crash log currently present. Keyed by filename (the logs live flat at
        the user-data root). Missing folder => empty snapshot."""
        snap = {}
        if not self.userdata.is_dir():
            return snap
        for pattern in CRASH_GLOBS:
            for path in glob.glob(str(self.userdata / pattern)):
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                snap[os.path.basename(path)] = {
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                }
        return snap

    @staticmethod
    def diff(old, new):
        """Return the sorted list of filenames that are NEW or CHANGED in
        ``new`` relative to ``old``.

        A file is "changed" when its ``(mtime, size)`` differs — either the game
        rewrote it (new mtime) or appended to it (new size). Files that vanished
        are NOT reported (a deleted log is not a fresh crash). ``old`` of
        ``None`` (no mark ever set) means every present log counts as new.
        """
        old = old or {}
        changed = []
        for name, meta in new.items():
            prev = old.get(name)
            if prev is None or prev.get("mtime") != meta["mtime"] or prev.get(
                "size"
            ) != meta["size"]:
                changed.append(name)
        return sorted(changed)

    # -- mark persistence ----------------------------------------------------

    def mark(self):
        """Persist the current snapshot as the baseline. Returns the snapshot.

        Atomic write (``.tmp`` then ``os.replace``) so a concurrent reader never
        sees a half-written mark.
        """
        snap = self.snapshot()
        path = self.mark_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snap, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))
        return snap

    def load_mark(self):
        """Return the persisted mark snapshot, or ``None`` if no mark exists or
        it is unreadable/corrupt (treated as "never marked")."""
        try:
            with open(self.mark_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def since_mark(self):
        """Return the sorted list of crash-log filenames new/changed since the
        last :meth:`mark`. With no prior mark, returns every present log (so the
        first ``--since-mark`` without a ``--mark`` is conservative, not empty).
        """
        return self.diff(self.load_mark(), self.snapshot())
