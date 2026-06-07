# protocol.py - file-channel paths + atomic read/write helpers for the
# sims4ctl in-game bridge.
#
# This module is the byte-for-byte counterpart of the host CLI's client. It
# owns:
#   1. resolving <USERDATA> (the Sims 4 user folder, localized) and the
#      <USERDATA>/sims4ctl/ channel directory,
#   2. atomic read/write of request.json / response.json / heartbeat.json
#      (write <name>.tmp then os.replace() so a reader never sees a torn file),
#   3. a tiny append-only debug log (bridge.log) next to the channel files.
#
# CPython 3.7-safe, stdlib only (os, json, traceback, time). Every filesystem
# touch is wrapped so the bridge can never crash the game over IO.

import json
import os
import time
import traceback

BRIDGE_VERSION = "0.1.0"

# Channel sub-directory name under <USERDATA>. The host CLI uses the same name.
CHANNEL_DIRNAME = "sims4ctl"

# Environment override for <USERDATA>, mirroring the host CLI's
# gamepaths.ENV_USERDATA. NEVER set inside the running game (so in-game
# resolution is unaffected); it exists so an OFFLINE wire-protocol harness /
# CI can point BOTH sides at a shared temp dir without a real game folder.
ENV_USERDATA = "SIMS4CTL_USERDATA"

# File names within the channel directory (LAW per _BUILD_SPEC.md).
REQUEST_NAME = "request.json"
RESPONSE_NAME = "response.json"
HEARTBEAT_NAME = "heartbeat.json"
LOG_NAME = "bridge.log"

# Localized Sims 4 user-folder leaf names. The game localizes the folder by
# language: "The Sims 4" (EN), "Die Sims 4" (DE), "Les Sims 4" (FR),
# "Los Sims 4" (ES). We accept all four and prefer the one with Options.ini
# (the marker that the game has actually been launched/configured there),
# matching HistorianCareer's build-side detection.
_USERDATA_LEAF_NAMES = (
    "The Sims 4",
    "Die Sims 4",
    "Les Sims 4",
    "Los Sims 4",
)

# Cached resolved paths (resolved lazily, once). None until first resolve.
_userdata_dir = None
_channel_dir = None


def _electronic_arts_dir():
    """Return ~/Documents/Electronic Arts or None if it does not exist."""
    try:
        ea = os.path.join(
            os.path.expanduser("~"), "Documents", "Electronic Arts"
        )
        if os.path.isdir(ea):
            return ea
    except Exception:
        pass
    return None


def resolve_userdata_dir():
    """Resolve <USERDATA>: the Sims 4 user folder under
    Documents/Electronic Arts whose leaf name is one of the localized
    "{The|Die|Les|Los} Sims 4" variants. Prefer a candidate that contains
    Options.ini; otherwise fall back to the first localized match.

    Returns an absolute path string, or None if nothing plausible is found.
    Cached after the first successful resolve.

    The SIMS4CTL_USERDATA env var (if set) overrides everything and is returned
    as-is WITHOUT requiring the folder to exist -- this is the host CLI's same
    override, and the only way an offline harness can point this in-game module
    at a shared temp dir. The game never sets this var, so live behavior is
    unchanged."""
    global _userdata_dir
    if _userdata_dir is not None:
        return _userdata_dir
    try:
        env = os.environ.get(ENV_USERDATA)
    except Exception:
        env = None
    if env:
        _userdata_dir = os.path.expanduser(env)
        return _userdata_dir
    ea = _electronic_arts_dir()
    if ea is None:
        return None
    try:
        entries = os.listdir(ea)
    except Exception:
        return None
    candidates = []
    for entry in entries:
        full = os.path.join(ea, entry)
        try:
            if not os.path.isdir(full):
                continue
        except Exception:
            continue
        if entry in _USERDATA_LEAF_NAMES:
            candidates.append(full)
    # Prefer the candidate that has Options.ini.
    for c in candidates:
        try:
            if os.path.isfile(os.path.join(c, "Options.ini")):
                _userdata_dir = c
                return _userdata_dir
        except Exception:
            pass
    if candidates:
        _userdata_dir = candidates[0]
        return _userdata_dir
    # Last-ditch fuzzy fallback: any folder name containing "sims 4"/"sims4".
    for entry in entries:
        low = entry.lower()
        if "sims 4" in low or "sims4" in low:
            full = os.path.join(ea, entry)
            try:
                if os.path.isdir(full):
                    _userdata_dir = full
                    return _userdata_dir
            except Exception:
                pass
    return None


def resolve_channel_dir():
    """Resolve <USERDATA>/sims4ctl/ and ensure it exists. Returns the absolute
    path string, or None if <USERDATA> could not be resolved. Cached."""
    global _channel_dir
    if _channel_dir is not None:
        return _channel_dir
    userdata = resolve_userdata_dir()
    if userdata is None:
        return None
    channel = os.path.join(userdata, CHANNEL_DIRNAME)
    try:
        if not os.path.isdir(channel):
            os.makedirs(channel)
    except Exception:
        # makedirs can race or fail; if the dir exists anyway, use it.
        if not os.path.isdir(channel):
            return None
    _channel_dir = channel
    return _channel_dir


def _channel_file(name):
    """Return the absolute path of `name` inside the channel dir, or None."""
    channel = resolve_channel_dir()
    if channel is None:
        return None
    return os.path.join(channel, name)


# ---------------------------------------------------------------------------
# Logging (append-only bridge.log). Never raises.
# ---------------------------------------------------------------------------

def log(msg):
    """Append a timestamped line to bridge.log and echo to stdout. Best-effort;
    swallows every error so logging can never break the game."""
    line = "[sims4ctl {0:.3f}] {1}".format(time.time(), msg)
    try:
        print(line)
    except Exception:
        pass
    path = _channel_file(LOG_NAME)
    if path is None:
        return
    try:
        fh = open(path, "a", encoding="utf-8")
        try:
            fh.write(line + "\n")
        finally:
            fh.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Atomic JSON IO. Writes go to <name>.tmp then os.replace() to the final name
# so a concurrent reader on the host side never observes a partial file.
# ---------------------------------------------------------------------------

def _atomic_write_json(name, obj):
    """Write `obj` as JSON to the channel file `name` atomically. Returns True
    on success, False on any failure (logged)."""
    path = _channel_file(name)
    if path is None:
        return False
    tmp = path + ".tmp"
    try:
        data = json.dumps(obj)
    except Exception as e:
        log("json.dumps failed for {0}: {1}".format(name, e))
        # Last resort: emit a minimal error payload so the host sees something.
        try:
            data = json.dumps(
                {"ok": False, "error": "unserializable result: " + str(e)}
            )
        except Exception:
            return False
    try:
        fh = open(tmp, "w", encoding="utf-8")
        try:
            fh.write(data)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                # fsync may be unavailable / fail on some filesystems; the
                # os.replace below is still atomic for our purposes.
                pass
        finally:
            fh.close()
        os.replace(tmp, path)
        return True
    except Exception as e:
        log("atomic write failed for {0}: {1}\n{2}".format(
            name, e, traceback.format_exc()))
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def _read_json(name):
    """Read and parse the channel file `name`. Returns the parsed object, or
    None if the file is absent / empty / unparseable (never raises)."""
    path = _channel_file(name)
    if path is None:
        return None
    try:
        if not os.path.isfile(path):
            return None
        fh = open(path, "r", encoding="utf-8")
        try:
            raw = fh.read()
        finally:
            fh.close()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        # A torn or mid-write file: ignore this cycle; the next poll retries.
        return None


# ---- typed convenience wrappers ------------------------------------------

def read_request():
    """Return the parsed request.json dict, or None. Shape (host->bridge):
    {"seq": <int>, "verb": <str>, "args": <object>}."""
    return _read_json(REQUEST_NAME)


def write_response(seq, ok, result, error, ts=None):
    """Atomically write response.json. Shape (bridge->host):
    {"seq", "ok", "result", "error", "ts"}."""
    if ts is None:
        ts = time.time()
    payload = {
        "seq": seq,
        "ok": bool(ok),
        "result": result,
        "error": error,
        "ts": ts,
    }
    return _atomic_write_json(RESPONSE_NAME, payload)


def read_response():
    """Return the parsed response.json dict, or None. Used to recover
    last_handled_seq across a reload so we don't re-execute an old request."""
    return _read_json(RESPONSE_NAME)


def write_heartbeat(tick, zone_loaded, active_sim, ts=None):
    """Atomically write heartbeat.json. Shape (bridge->host, ~2x/sec):
    {"tick", "zone_loaded", "active_sim", "bridge_version", "ts"}."""
    if ts is None:
        ts = time.time()
    payload = {
        "tick": tick,
        "zone_loaded": bool(zone_loaded),
        "active_sim": active_sim,
        "bridge_version": BRIDGE_VERSION,
        "ts": ts,
    }
    return _atomic_write_json(HEARTBEAT_NAME, payload)
