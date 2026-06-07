"""gamepaths.py — resolve the Sims 4 user-data folder, Mods folder, and the
sims4ctl bridge directory.

The game localizes its user-data folder name by language
(``The Sims 4`` / ``Die Sims 4`` / ``Les Sims 4`` / ``Los Sims 4`` / …) under
``~/Documents/Electronic Arts``. We prefer the sibling that has an
``Options.ini`` (the marker that the game has actually been launched and
configured there). This is a straight port of HistorianCareer's
``findSims4UserDataFolder`` from ``Build/build.mjs`` — same regex, same
Options.ini preference.

Everything is overridable for tests/CI that run without the game installed:
pass ``userdata=`` explicitly, set the ``SIMS4CTL_USERDATA`` environment
variable, or (for the Mods folder) ``SIMS4CTL_MODS``. The override never
requires the folder to exist, so a temp fixture tree works.
"""

import os
import re
from pathlib import Path

# Matches the four shipped localizations of the user-data folder name. EA only
# ships these four spellings (en/de/fr/es); anything else uses one of them.
_SIMS4_FOLDER_RE = re.compile(r"^(The|Die|Les|Los) Sims 4$")

# Environment overrides so tests + CI work with no game installed.
ENV_USERDATA = "SIMS4CTL_USERDATA"
ENV_MODS = "SIMS4CTL_MODS"

# Default Steam install location of the game executable (Windows-first).
DEFAULT_TS4_EXE = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\The Sims 4\Game\Bin\TS4_x64.exe"
)

# Steam appid for The Sims 4 (the base game). Used to build a
# ``steam://rungameid/<appid>`` launch URL when the raw exe path won't entitle
# the Steam/EA copy on its own. We prefer to read the real value from the game's
# ``steam_appid.txt`` (sits next to TS4_x64.exe) and fall back to this constant.
DEFAULT_TS4_APPID = "1222670"


def ea_documents_dir():
    """Return ``~/Documents/Electronic Arts`` as a Path (may not exist)."""
    return Path(os.path.expanduser("~")) / "Documents" / "Electronic Arts"


def find_userdata(userdata=None):
    """Resolve the Sims 4 user-data folder (the one containing ``Options.ini``).

    Resolution order:
      1. explicit ``userdata=`` argument (used by ``--userdata`` and tests),
      2. the ``SIMS4CTL_USERDATA`` environment variable,
      3. auto-detection under ``~/Documents/Electronic Arts``.

    For (1) and (2) the path is returned as-is (expanded) WITHOUT requiring it
    to exist — that is what lets a temp fixture / CI path work. For (3) we only
    return a real, existing directory, preferring the one with ``Options.ini``;
    if none qualifies we return ``None``.
    """
    if userdata:
        return Path(os.path.expanduser(str(userdata)))
    env = os.environ.get(ENV_USERDATA)
    if env:
        return Path(os.path.expanduser(env))
    return _autodetect_userdata()


def _autodetect_userdata():
    """Scan ``~/Documents/Electronic Arts`` for a ``{The|Die|Les|Los} Sims 4``
    folder, preferring one with ``Options.ini``. Returns a Path or ``None``."""
    ea = ea_documents_dir()
    if not ea.is_dir():
        return None
    candidates = []
    try:
        for entry in sorted(os.listdir(ea)):
            full = ea / entry
            if full.is_dir() and _SIMS4_FOLDER_RE.match(entry):
                candidates.append(full)
    except OSError:
        return None
    # Prefer the one with Options.ini; else the first match; else None.
    for c in candidates:
        if (c / "Options.ini").is_file():
            return c
    return candidates[0] if candidates else None


def find_mods(userdata=None):
    """Return the Mods folder = ``<USERDATA>/Mods``.

    The ``SIMS4CTL_MODS`` env var overrides this outright (rare; mostly for
    odd installs). Otherwise it is derived from the resolved user-data folder.
    Returns ``None`` only when the user-data folder can't be resolved.
    """
    env = os.environ.get(ENV_MODS)
    if env:
        return Path(os.path.expanduser(env))
    ud = find_userdata(userdata)
    if ud is None:
        return None
    return ud / "Mods"


def find_bridge_dir(userdata=None):
    """Return the file-IPC channel directory = ``<USERDATA>/sims4ctl/``.

    This is where ``request.json`` / ``response.json`` / ``heartbeat.json`` live
    (the path both the host and the in-game bridge agree on). Returns ``None``
    when the user-data folder can't be resolved.
    """
    ud = find_userdata(userdata)
    if ud is None:
        return None
    return ud / "sims4ctl"


def find_ts4_exe():
    """Return the path to ``TS4_x64.exe`` if it exists at the default Steam Bin
    location, else ``None`` (the CLI's ``launch`` reports a helpful error)."""
    return DEFAULT_TS4_EXE if DEFAULT_TS4_EXE.is_file() else None


def find_steam_appid(exe=None):
    """Return the Steam appid string for The Sims 4.

    Reads ``steam_appid.txt`` from the game's Bin folder (next to
    ``TS4_x64.exe``) when present -- that file contains just the numeric appid --
    and falls back to :data:`DEFAULT_TS4_APPID` when the file or exe is absent.
    Never raises; always returns a usable string so ``start`` can build a
    ``steam://rungameid/<appid>`` URL.
    """
    exe_path = Path(exe) if exe else DEFAULT_TS4_EXE
    appid_file = exe_path.parent / "steam_appid.txt"
    try:
        text = appid_file.read_text(encoding="utf-8").strip()
        if text:
            return text.splitlines()[0].strip()
    except OSError:
        pass
    return DEFAULT_TS4_APPID


def resolve_all(userdata=None):
    """Resolve everything at once for ``doctor`` / diagnostics.

    Returns a dict with the four resolved paths (any of which may be ``None``)
    and how the user-data folder was resolved (``arg`` / ``env`` / ``auto`` /
    ``none``) so ``doctor`` can explain itself.
    """
    if userdata:
        source = "arg"
    elif os.environ.get(ENV_USERDATA):
        source = "env"
    else:
        source = "auto"
    ud = find_userdata(userdata)
    if ud is None:
        source = "none"
    return {
        "userdata": ud,
        "mods": find_mods(userdata),
        "bridge_dir": find_bridge_dir(userdata),
        "ts4_exe": find_ts4_exe(),
        "userdata_source": source,
    }
