"""saves.py -- enumerate Sims 4 saves and back up / restore a RESERVED test slot.

The autonomous loop loads a save and then mutates the world (adds careers,
promotes, sets skills). To keep runs **repeatable** and to **never clobber a
player's save**, we dedicate one disposable slot to automation and restore it to
a pristine baseline before each run.

Save file layout (observed on this install)
-------------------------------------------
Saves live under ``<USERDATA>/saves/`` and are named ``Slot_XXXXXXXX.save`` where
``XXXXXXXX`` is an 8-hex slot id. Each active slot also has rotated backups
``.ver0``..``.ver4`` and a ``.day.ver0`` companion. The 8-hex in the *filename*
identifies the slot; the blob inside is a DBPF package.

THE RESERVED TEST SLOT
----------------------
We reserve slot id ``0x000000FF`` -> ``Slot_000000FF.save``. It is high in the
range and not used by the player here (observed player slots: ``00000002`` and
``00000003``). Rationale for FF: memorable, clearly "special", and far from the
low ids the game hands out for normal new saves. If FF is ever taken on a given
machine, pass a different id to the helpers / CLI (``--slot``) -- nothing here
hard-codes FF except the default constant below.

Safety model
------------
* :func:`backup_test_slot` copies the live ``Slot_000000FF.save`` (and its
  rotated siblings) into a baseline dir you own (default
  ``<USERDATA>/sims4ctl/saves_baseline/``) and marks the copies **read-only** so
  a stray write can't corrupt the golden baseline.
* :func:`restore_test_slot` ``os.replace``-s the baseline back over the live slot
  before a run, so each run starts byte-identical.
* Both refuse to operate on the player slots (a guard list) unless explicitly
  forced, so a fat-fingered id can't nuke a real save.
"""

import os
import re
import shutil
import stat
from pathlib import Path

from . import gamepaths

# The reserved disposable automation slot (see module docstring). 8-hex id.
TEST_SLOT_ID = 0xFF

# Slot ids we refuse to back up/restore over without force=True. These are the
# player's saves observed on this machine; the guard makes an accidental
# --slot 2 a no-op instead of a data-loss event.
PROTECTED_SLOT_IDS = (0x02, 0x03)

# Default location for the read-only golden baseline of the test slot.
BASELINE_DIRNAME = "saves_baseline"

_SLOT_RE = re.compile(r"^Slot_([0-9A-Fa-f]{8})\.save$")


def slot_filename(slot_id):
    """``0xFF`` -> ``'Slot_000000FF.save'`` (8-hex, upper-case, like the game)."""
    return "Slot_{0:08X}.save".format(int(slot_id))


def saves_dir(userdata=None):
    """Return ``<USERDATA>/saves`` as a Path, or ``None`` if userdata unresolved.

    The folder need not exist yet (a brand-new install has none); callers that
    enumerate handle a missing dir as "no saves".
    """
    ud = gamepaths.find_userdata(userdata)
    if ud is None:
        return None
    return ud / "saves"


def list_saves(userdata=None):
    """List the primary save files (``Slot_XXXXXXXX.save``) under the saves dir.

    Returns a list of dicts ``{slot_id: int, slot_hex: str, name: str,
    path: str, size: int, mtime: float}`` sorted by slot id. Rotated backups
    (``.ver0`` etc.) and the ``.day`` companions are intentionally excluded --
    they aren't independently loadable slots. Missing/unresolved dir -> ``[]``.
    """
    sdir = saves_dir(userdata)
    if sdir is None or not sdir.is_dir():
        return []
    out = []
    for entry in sorted(os.listdir(sdir)):
        m = _SLOT_RE.match(entry)
        if not m:
            continue
        full = sdir / entry
        try:
            st = full.stat()
        except OSError:
            continue
        out.append({
            "slot_id": int(m.group(1), 16),
            "slot_hex": m.group(1).upper(),
            "name": entry,
            "path": str(full),
            "size": st.st_size,
            "mtime": st.st_mtime,
        })
    out.sort(key=lambda d: d["slot_id"])
    return out


def _slot_files(sdir, slot_id):
    """All on-disk files for a slot: the ``.save`` plus any ``.save.*`` siblings.

    Globs ``Slot_XXXXXXXX.save*`` so the rotated ``.ver0..4`` and ``.day.ver0``
    backups travel with the primary blob during backup/restore.
    """
    base = slot_filename(slot_id)
    return sorted(sdir.glob(base + "*"))


def _make_readonly(path):
    """Best-effort chmod a file to read-only (so the golden baseline is safe)."""
    try:
        os.chmod(str(path), stat.S_IREAD)
    except OSError:
        pass


def _make_writable(path):
    """Best-effort restore write permission (needed before overwrite/replace)."""
    try:
        os.chmod(str(path), stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def baseline_dir(userdata=None):
    """Return the baseline directory (``<USERDATA>/sims4ctl/saves_baseline``)."""
    bridge = gamepaths.find_bridge_dir(userdata)
    if bridge is None:
        return None
    return bridge / BASELINE_DIRNAME


def _guard(slot_id, force):
    """Raise unless ``slot_id`` is safe to write over (or ``force``)."""
    if not force and int(slot_id) in PROTECTED_SLOT_IDS:
        raise SaveSafetyError(
            "refusing to operate on protected player slot {0} "
            "(Slot_{1:08X}); pass force=True only if you really mean it".format(
                int(slot_id), int(slot_id)
            )
        )


def backup_test_slot(slot_id=TEST_SLOT_ID, userdata=None, dest=None, force=False):
    """Copy the live test slot (+ rotated siblings) into a READ-ONLY baseline.

    Reads ``<saves>/Slot_<id>.save*`` and writes copies into ``dest`` (default
    :func:`baseline_dir`), marking each copy read-only. Existing baseline copies
    are overwritten (temporarily made writable first). Returns the list of
    baseline file paths created.

    Raises :class:`SaveSafetyError` on a protected slot (unless ``force``) and
    :class:`FileNotFoundError` if the slot has no ``.save`` on disk (you must
    create the test save once in-game first -- see docs/RECIPE_B.md).
    """
    _guard(slot_id, force)
    sdir = saves_dir(userdata)
    if sdir is None:
        raise SaveSafetyError("could not resolve the saves dir (unresolved userdata)")
    primary = sdir / slot_filename(slot_id)
    if not primary.is_file():
        raise FileNotFoundError(
            "test slot {0} not found at {1}; create it once in-game "
            "(persistence save-as) before backing up".format(
                slot_filename(slot_id), primary
            )
        )
    dest_dir = Path(dest) if dest else baseline_dir(userdata)
    if dest_dir is None:
        raise SaveSafetyError("could not resolve the baseline dir")
    dest_dir.mkdir(parents=True, exist_ok=True)

    created = []
    for src in _slot_files(sdir, slot_id):
        dst = dest_dir / src.name
        if dst.exists():
            _make_writable(dst)  # so copy2 can overwrite a prior read-only copy
        shutil.copy2(str(src), str(dst))
        _make_readonly(dst)
        created.append(str(dst))
    return created


def restore_test_slot(slot_id=TEST_SLOT_ID, userdata=None, source=None, force=False):
    """Restore the test slot from its baseline so a run starts pristine.

    For each baseline file, copy it to a temp name in the saves dir and
    ``os.replace`` it over the live name (atomic on Windows). The restored live
    files are made writable so the game can rotate them. Returns the list of
    restored live paths.

    Raises :class:`SaveSafetyError` on a protected slot (unless ``force``) and
    :class:`FileNotFoundError` if no baseline exists (call
    :func:`backup_test_slot` first).
    """
    _guard(slot_id, force)
    sdir = saves_dir(userdata)
    if sdir is None:
        raise SaveSafetyError("could not resolve the saves dir (unresolved userdata)")
    src_dir = Path(source) if source else baseline_dir(userdata)
    if src_dir is None or not src_dir.is_dir():
        raise FileNotFoundError(
            "no baseline at {0}; run backup_test_slot first".format(src_dir)
        )
    base = slot_filename(slot_id)
    baseline_files = sorted(src_dir.glob(base + "*"))
    if not baseline_files:
        raise FileNotFoundError(
            "baseline dir {0} has no files for slot {1}".format(src_dir, base)
        )
    sdir.mkdir(parents=True, exist_ok=True)

    restored = []
    for src in baseline_files:
        live = sdir / src.name
        tmp = sdir / (src.name + ".sims4ctl.tmp")
        shutil.copy2(str(src), str(tmp))
        _make_writable(tmp)
        if live.exists():
            _make_writable(live)
        os.replace(str(tmp), str(live))  # atomic swap over the live slot
        restored.append(str(live))
    return restored


class SaveSafetyError(Exception):
    """A saves operation was refused for safety (protected slot / unresolved dir)."""
