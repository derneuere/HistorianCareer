# aspiration_diag.py — runtime diagnostic for issue #17.
#
# Purpose: after the build-time guard (commit a5351e9) and the TEEN_OR_OLDER
# enum fix (commit 6b4e72f), the user reports the AspirationTrack still does
# not appear in the CAS aspiration picker under Wissen. We've ruled out:
#   - tuning XML registration (instance manager picks it up; see
#     Docs/NOTE_aspiration_track_registration.md).
#   - SimData TGI / schema (byte-equal to EA's pattern; see
#     Docs/NOTE_cas_aspiration_picker_swf.md §4).
#   - CAS-picker binary-index hypothesis (the picker delegates to native
#     engine RPCs that DO enumerate mod packages; see §3 of the same note).
#
# That leaves: a runtime AS3 desync in EA's Olympus client, OR a stale local
# cache. The user's lastUIException shows a #1009 null-reference fire at
# `AspirationTrackStaticData.INIT_DATA()` — possibly tied to our track's
# serialisation, possibly to leftover save state from earlier builds.
#
# This script can't fix either. What it CAN do is dump the relevant Python
# manager state at game start to a per-mod log file, so we can confirm:
#
#   1. Our AspirationTrack is in
#      `services.get_instance_manager(Types.ASPIRATION_TRACK).types`.
#   2. Each tier (aspiration_HistorianCalling_T1..T4) is in the ASPIRATION
#      instance manager.
#   3. The runtime value of `aspiration_valid_age_type` on T1 is
#      `TEEN_OR_OLDER` (= 120), not the silently-defaulted `INVALID` (= 0).
#   4. `track.is_valid_for_sim(synthetic_adult)` returns True.
#
# Output: `Documents/Electronic Arts/Die Sims 4/historiancareer_aspiration_diag.log`
# (German install) or the equivalent localized folder. Falls back silently
# if anything fails — diagnostics must never break gameplay.
#
# Pattern: `services.get_instance_manager(<resource_type>).add_on_load_complete(cb)`
# is the canonical EA hook for "instance manager is fully loaded, ready to
# inspect", used by lot51-core and MC5. The callback fires once at game start.

try:
    import os
    import traceback
    import services
    import sims4.log
    from sims4.resources import Types
except Exception:
    services = None
    Types = None
    sims4 = None


MOD_NAME = "HistorianCareer"

# Track name (the `n=` attribute in the tuning XML).
HC_TRACK_NAME = "aspiration_track_HistorianCalling"
# Tier names. Order matters — T1 is what gates CAS visibility per
# AspirationTrack.is_valid_for_sim (see Docs/NOTE_aspiration_track_registration.md).
HC_TIER_NAMES = (
    "aspiration_HistorianCalling_T1",
    "aspiration_HistorianCalling_T2",
    "aspiration_HistorianCalling_T3",
    "aspiration_HistorianCalling_T4",
)


# ---------------------------------------------------------------------------
# Log routing — write to a per-mod file in the user's Documents/Electronic
# Arts/Die Sims 4/ (or localized equivalent) folder. Same pattern as
# affordance_injector._log for consistency.
# ---------------------------------------------------------------------------


_LOG_PATH = None


def _resolve_log_path():
    try:
        ea = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts")
        if not os.path.isdir(ea):
            return None
        for entry in os.listdir(ea):
            low = entry.lower()
            if "sims 4" in low or "sims4" in low:
                return os.path.join(ea, entry, "historiancareer_aspiration_diag.log")
    except Exception:
        pass
    return None


def _log(msg):
    """Write a single line to the diag log. Also mirror to stdout. Never raises."""
    line = "[{}] {}".format(MOD_NAME, msg)
    try:
        print(line)
    except Exception:
        pass
    global _LOG_PATH
    if _LOG_PATH is None:
        _LOG_PATH = _resolve_log_path()
    if _LOG_PATH:
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass


def _reset_log():
    """Truncate the log file at game start so each session is self-contained."""
    global _LOG_PATH
    if _LOG_PATH is None:
        _LOG_PATH = _resolve_log_path()
    if _LOG_PATH:
        try:
            with open(_LOG_PATH, "w", encoding="utf-8") as fh:
                fh.write("[{}] === diag session start ===\n".format(MOD_NAME))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Diagnostic body — runs after both ASPIRATION_TRACK and ASPIRATION instance
# managers have loaded. Both must be ready to inspect both sides of the join.
# We use a simple ref-count gate.
# ---------------------------------------------------------------------------


_managers_ready_count = 0
_EXPECTED_MANAGERS = 2  # ASPIRATION_TRACK + ASPIRATION


def _safe_attr(obj, name, default=None):
    """Return getattr(obj, name) or `default` on any exception."""
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _format_track(track_cls):
    """One-line summary of an AspirationTrack class for the log."""
    parts = []
    parts.append("name={}".format(_safe_attr(track_cls, "__name__", "?")))
    parts.append("guid64=0x{:X}".format(int(_safe_attr(track_cls, "guid64", 0) or 0)))
    try:
        sorted_asps = _safe_attr(track_cls, "_sorted_aspirations", ())
        parts.append("tier_count={}".format(len(sorted_asps)))
    except Exception:
        parts.append("tier_count=ERR")
    try:
        cat = _safe_attr(track_cls, "category", None)
        cat_guid = _safe_attr(cat, "guid64", None) if cat is not None else None
        parts.append("category={}".format(
            "guid64=0x{:X}".format(int(cat_guid)) if cat_guid else repr(cat)
        ))
    except Exception:
        parts.append("category=ERR")
    try:
        is_hidden = _safe_attr(track_cls, "is_hidden_unlockable", "?")
        parts.append("is_hidden_unlockable={}".format(is_hidden))
    except Exception:
        pass
    return ", ".join(parts)


def _format_aspiration(asp_cls):
    """One-line summary of an Aspiration class for the log."""
    parts = []
    parts.append("name={}".format(_safe_attr(asp_cls, "__name__", "?")))
    parts.append("guid64=0x{:X}".format(int(_safe_attr(asp_cls, "guid64", 0) or 0)))
    age_type = _safe_attr(asp_cls, "aspiration_valid_age_type", None)
    try:
        parts.append("aspiration_valid_age_type={!r} (int={})".format(
            age_type, int(age_type) if age_type is not None else "None"
        ))
    except Exception:
        parts.append("aspiration_valid_age_type={!r}".format(age_type))
    cat = _safe_attr(asp_cls, "category", None)
    cat_guid = _safe_attr(cat, "guid64", None) if cat is not None else None
    parts.append("category={}".format(
        "guid64=0x{:X}".format(int(cat_guid)) if cat_guid else repr(cat)
    ))
    return ", ".join(parts)


def _try_is_valid_for_sim(track_cls):
    """Synthesize an `adult` sim_info shim and call track.is_valid_for_sim.
    Returns (result_or_None, error_str_or_None)."""
    try:
        # `Aspiration.is_valid_for_sim(sim_info)` returns `sim_info.age & self.aspiration_valid_age_type`.
        # `AspirationTrack.is_valid_for_sim(sim_info)` delegates to its LEVEL_1 aspiration's.
        # We synthesize a Sim with age=YOUNG_ADULT (=16). If the bitmask is
        # correct, the AND gives non-zero (truthy).
        # We don't need a full SimInfo — duck-typing on `age` suffices.
        class _ShimSim:
            age = 16  # Age.YOUNGADULT
        return (bool(track_cls.is_valid_for_sim(_ShimSim())), None)
    except Exception as e:
        return (None, "{}: {}".format(type(e).__name__, e))


def _run_aspiration_track_diag(mgr):
    """Inspect the loaded ASPIRATION_TRACK instance manager."""
    _log("ASPIRATION_TRACK manager loaded.")
    try:
        types = mgr.types
        _log("  total tracks: {}".format(len(types)))
    except Exception as e:
        _log("  ERROR reading mgr.types: {}".format(e))
        return

    our_track = None
    for (_key, track_cls) in list(types.items()):
        name = _safe_attr(track_cls, "__name__", "")
        if name == HC_TRACK_NAME or "HistorianCalling" in name:
            our_track = track_cls
            _log("  * FOUND OUR TRACK: {}".format(_format_track(track_cls)))

    if our_track is None:
        _log("  ! OUR TRACK NOT IN mgr.types. Listing first 5 EA tracks for sanity:")
        ea_sample = list(types.items())[:5]
        for (_k, t) in ea_sample:
            _log("    - {}".format(_format_track(t)))
        return

    # Try is_valid_for_sim with a synthetic adult.
    (valid, err) = _try_is_valid_for_sim(our_track)
    if err is not None:
        _log("  is_valid_for_sim(YA_shim): ERROR {}".format(err))
    else:
        _log("  is_valid_for_sim(YA_shim): {}".format(valid))

    # Print each tier from _sorted_aspirations.
    try:
        sa = our_track._sorted_aspirations
        _log("  _sorted_aspirations len={}".format(len(sa)))
        for (level, asp_cls) in sa:
            _log("    LEVEL_{}: {}".format(level, _format_aspiration(asp_cls)))
    except Exception as e:
        _log("  _sorted_aspirations: ERROR {}".format(e))


def _run_aspiration_diag(mgr):
    """Inspect the loaded ASPIRATION instance manager."""
    _log("ASPIRATION manager loaded.")
    try:
        types = mgr.types
        _log("  total aspirations: {}".format(len(types)))
    except Exception as e:
        _log("  ERROR reading mgr.types: {}".format(e))
        return

    found = []
    for (_key, asp_cls) in list(types.items()):
        name = _safe_attr(asp_cls, "__name__", "")
        if name in HC_TIER_NAMES or "HistorianCalling" in name:
            found.append(asp_cls)
            _log("  * FOUND OUR TIER: {}".format(_format_aspiration(asp_cls)))

    missing = [n for n in HC_TIER_NAMES if not any(
        _safe_attr(a, "__name__", "") == n for a in found
    )]
    if missing:
        _log("  ! MISSING TIERS: {}".format(", ".join(missing)))


def _maybe_finalize():
    """Called once after each manager loads. When both are ready, emit summary."""
    global _managers_ready_count
    _managers_ready_count += 1
    if _managers_ready_count >= _EXPECTED_MANAGERS:
        _log("=== diag complete ===")


def _on_aspiration_track_loaded(mgr):
    try:
        _run_aspiration_track_diag(mgr)
    except Exception:
        _log("UNHANDLED in _on_aspiration_track_loaded:\n{}".format(traceback.format_exc()))
    finally:
        _maybe_finalize()


def _on_aspiration_loaded(mgr):
    try:
        _run_aspiration_diag(mgr)
    except Exception:
        _log("UNHANDLED in _on_aspiration_loaded:\n{}".format(traceback.format_exc()))
    finally:
        _maybe_finalize()


# ---------------------------------------------------------------------------
# Registration. The hook is `mgr.add_on_load_complete(cb)`. We wire both
# managers at module-import time. The .ts4script bundle is imported once by
# `historian_career/__init__.py` at game start — well before the managers
# finish loading — so the callbacks land at the right moment.
#
# Defensive guards:
#   - if `services` or `Types` failed to import (e.g. running outside Sims 4),
#     this whole module is a no-op.
#   - if an instance manager isn't available at registration time (very early
#     module-import), we skip silently — the user can re-test and the script
#     just won't fire.
# ---------------------------------------------------------------------------


def _register():
    if services is None or Types is None:
        return
    _reset_log()
    _log("aspiration_diag.py loaded; registering on_load_complete hooks")
    try:
        track_mgr = services.get_instance_manager(Types.ASPIRATION_TRACK)
        if track_mgr is not None:
            track_mgr.add_on_load_complete(_on_aspiration_track_loaded)
            _log("hook registered on ASPIRATION_TRACK manager")
        else:
            _log("WARN: ASPIRATION_TRACK manager not available at registration")
    except Exception as e:
        _log("ERROR registering ASPIRATION_TRACK hook: {}".format(e))
    try:
        asp_mgr = services.get_instance_manager(Types.ASPIRATION)
        if asp_mgr is not None:
            asp_mgr.add_on_load_complete(_on_aspiration_loaded)
            _log("hook registered on ASPIRATION manager")
        else:
            _log("WARN: ASPIRATION manager not available at registration")
    except Exception as e:
        _log("ERROR registering ASPIRATION hook: {}".format(e))


_register()
