"""gamestate.py -- a file + process + window state machine for the game.

The autonomous loop (docs/RECIPE_B.md) needs a single source of truth for "where
is the game right now?" so each step can wait for the right condition before
acting. This module reduces three observable signals -- the OS process table,
the game window, and the bridge heartbeat -- into one of four states:

    DOWN         no TS4_x64.exe process is running.
    MENU         the process is up (and a window exists), but there is no FRESH
                 zone heartbeat -- i.e. we're at the main menu (or still
                 launching). This is the state the orchestrator must click out of.
    LOADING      transient: the process is up and a heartbeat exists but it is
                 stale or zone_loaded is false while a load is in progress. We
                 surface it as a distinct (best-effort) state so a long load
                 isn't mistaken for a hang; callers usually just wait through it.
    ZONE_LOADED  a save is loaded: heartbeat says ``zone_loaded: true`` AND it is
                 FRESH (per :meth:`Client.heartbeat_age`). This is the only state
                 in which the in-game bridge can touch ``services`` and run a
                 scenario.

Crashes are orthogonal -- use :mod:`crashwatch` for those.

Process detection uses ``tasklist`` (always present on Windows) with a pure
ctypes ``CreateToolhelp32Snapshot`` fallback, so there is **no psutil
dependency** and the module imports with zero third-party packages. On non-
Windows (CI) ``tasklist`` is absent; the process check then reports "not
running", which keeps the unit tests deterministic.
"""

import os
import subprocess
import sys
import time

from . import gamepaths
from .client import Client

# The four machine states, as plain string constants (stable wire/CLI values).
DOWN = "DOWN"
MENU = "MENU"
LOADING = "LOADING"
ZONE_LOADED = "ZONE_LOADED"

ALL_STATES = (DOWN, MENU, LOADING, ZONE_LOADED)

# The game's process image name. Matches the Steam/EA Windows executable.
TS4_PROCESS_NAME = "TS4_x64.exe"

# A heartbeat older than this (seconds) is "stale" -- the bridge isn't ticking,
# so even zone_loaded:true can't be trusted as the *current* state. The bridge
# refreshes ~2x/sec, so a couple of seconds of slack is generous.
HEARTBEAT_FRESH_S = 5.0


# ---------------------------------------------------------------------------
# process detection (no psutil)
# ---------------------------------------------------------------------------

def is_process_running(image_name=TS4_PROCESS_NAME):
    """Return True iff a process with ``image_name`` is in the process table.

    Tries ``tasklist`` first (built into Windows), then a ctypes Toolhelp32
    snapshot. On a platform with neither (POSIX CI), returns False so callers
    treat the game as DOWN -- exactly what we want when no game is installed.
    The check is name-based and case-insensitive.
    """
    if _tasklist_has(image_name):
        return True
    # tasklist absent or errored -> try the ctypes snapshot before giving up.
    return _toolhelp_has(image_name)


def _tasklist_has(image_name):
    """Process-table check via ``tasklist /FI "IMAGENAME eq <name>"``.

    Returns True/False. Any failure (not Windows, tasklist missing, non-zero
    exit) returns False so the ctypes fallback gets a turn.
    """
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq {0}".format(image_name), "/NH"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
        )
    except (OSError, ValueError):
        return False
    if out.returncode != 0 or not out.stdout:
        return False
    # When nothing matches, tasklist prints "INFO: No tasks are running...".
    return image_name.lower() in out.stdout.lower()


def _toolhelp_has(image_name):
    """ctypes CreateToolhelp32Snapshot fallback. False off-Windows/on any error."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * MAX_PATH),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == -1 or snapshot == 0:
        return False
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snapshot, ctypes.byref(entry)):
            return False
        target = image_name.lower().encode("ascii", "ignore")
        while True:
            name = entry.szExeFile.lower()
            if name == target:
                return True
            if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                return False
    finally:
        kernel32.CloseHandle(snapshot)


# ---------------------------------------------------------------------------
# window detection (best-effort; never requires the automation deps)
# ---------------------------------------------------------------------------

def is_window_present(title_substr="Sims"):
    """Return True iff a game window is found, False otherwise.

    Delegates to :func:`winauto.find_game_window`, which itself prefers pywin32
    but falls back to pure ctypes. If even that path is unavailable (or raises),
    we report False -- window presence is only a *refinement* of the MENU state,
    never the sole determinant, so its absence degrades gracefully.
    """
    try:
        from . import winauto
        return winauto.find_game_window(title_substr) is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# the state machine
# ---------------------------------------------------------------------------

class GameState(object):
    """Compute and wait on the game's current state.

    ``userdata`` (optional) is forwarded to :mod:`gamepaths` to locate the bridge
    dir for the heartbeat read; ``process_name`` / ``window_title`` are
    overridable for tests. ``client`` is injectable so tests can supply a fake
    heartbeat source with NO game and NO files. ``now`` is an injectable clock
    for deterministic age math.
    """

    def __init__(self, userdata=None, process_name=TS4_PROCESS_NAME,
                 window_title="Sims", client=None, now=None,
                 fresh_s=HEARTBEAT_FRESH_S):
        self.userdata = userdata
        self.process_name = process_name
        self.window_title = window_title
        self.fresh_s = fresh_s
        self._now = now or time.time
        if client is not None:
            self.client = client
        else:
            bridge_dir = gamepaths.find_bridge_dir(userdata)
            # bridge_dir may be None (unresolved userdata); the heartbeat read
            # then simply yields None and we report DOWN/MENU from the process.
            self.client = Client(bridge_dir) if bridge_dir is not None else None

    # -- single-shot evaluation ---------------------------------------------

    def _heartbeat(self):
        """(heartbeat_dict_or_None, age_seconds_or_None)."""
        if self.client is None:
            return None, None
        hb = self.client.read_heartbeat()
        if not hb:
            return None, None
        age = self.client.heartbeat_age(now=self._now())
        return hb, age

    def current_state(self):
        """Reduce process + heartbeat into one of :data:`ALL_STATES`.

        Logic (process first, then heartbeat freshness):
          * no process                          -> DOWN
          * process up, fresh hb, zone_loaded   -> ZONE_LOADED
          * process up, fresh hb, NOT zone_loaded
                -> MENU   (the menu-tick-hook, if present, refreshes the
                           heartbeat at the menu with zone_loaded:false)
          * process up, stale/absent hb but zone_loaded last said true
                -> LOADING (a load is probably in flight; the bridge alarm is
                            mid-transition) -- best effort.
          * process up, stale/absent hb, no zone signal -> MENU
        """
        if not is_process_running(self.process_name):
            return DOWN

        hb, age = self._heartbeat()
        fresh = age is not None and 0 <= age <= self.fresh_s
        zone = bool(hb.get("zone_loaded")) if hb else False

        if fresh:
            return ZONE_LOADED if zone else MENU

        # Not fresh. If the last heartbeat we *did* see claimed a zone, a load is
        # most likely transitioning (bridge alarm restarting) -> LOADING.
        if hb is not None and zone:
            return LOADING
        # Otherwise the process is up with no usable zone signal: main menu /
        # still launching.
        return MENU

    def snapshot(self):
        """Return a diagnostic dict: state + the raw signals it was derived from.

        Handy for ``state --menu-aware`` and for debugging a flaky load.
        """
        running = is_process_running(self.process_name)
        hb, age = self._heartbeat()
        fresh = age is not None and 0 <= age <= self.fresh_s
        return {
            "state": self.current_state(),
            "process_running": running,
            "process_name": self.process_name,
            "window_present": is_window_present(self.window_title) if running else False,
            "heartbeat": hb,
            "heartbeat_age_s": round(age, 2) if age is not None else None,
            "heartbeat_fresh": fresh,
            "zone_loaded": bool(hb.get("zone_loaded")) if hb else False,
            "active_sim": hb.get("active_sim") if hb else None,
        }

    # -- waiting -------------------------------------------------------------

    def wait_for(self, state, timeout=120.0, poll=1.0):
        """Block until :meth:`current_state` equals ``state`` or ``timeout``.

        Returns the snapshot dict on success. Raises :class:`StateTimeout` if the
        deadline passes first -- so the CLI exits non-zero and a stuck load fails
        loudly instead of hanging a CI job. ``poll`` is the inter-check sleep.

        ``ZONE_LOADED`` is the usual target; ``MENU`` is used right after launch
        to know the click step can begin.
        """
        if state not in ALL_STATES:
            raise ValueError(
                "unknown state {0!r}; expected one of {1}".format(state, ALL_STATES)
            )
        deadline = self._now() + timeout
        last = None
        while True:
            last = self.current_state()
            if last == state:
                return self.snapshot()
            if self._now() >= deadline:
                raise StateTimeout(
                    "timed out after {0}s waiting for state {1!r}; last state was "
                    "{2!r}".format(timeout, state, last)
                )
            time.sleep(poll)


class StateTimeout(Exception):
    """:meth:`GameState.wait_for` did not reach the target state in time."""
