# daily_task_rotation.py — best-effort per-day rotation of the visible daily task.
#
# WHY THIS EXISTS
#
# Docs/DESIGN.md "Daily-task structure": each Historian rank has a small POOL of
# valid daily tasks; the *canonical* behaviour is that the script picks ONE from
# that pool at the start of each in-game day and shows it as the single visible
# daily task. The pure-tuning fallback (all pool items visible at once via the
# AspirationCareer.objectives list with complete_subset/number_required=1) is the
# WORKING FALLBACK and ships regardless of this script — see the
# aspiration_career_Historian_L{1..10}.xml files. This module is the canonical
# "feels different each day" layer on top of that fallback.
#
# BEST-EFFORT CONTRACT
#
# Everything here is wrapped in try/except and must NEVER break gameplay. If any
# hook, lookup, or apply step fails we log and return; the tuning pool keeps the
# career fully playable. We do NOT mutate EA's career-objective internals (those
# are fragile across patches); we deterministically *choose* the day's objective
# from the live pool and record it (logged + stored on the career for any future
# UI hook). The choice is stable within a given in-game day for a given Sim.
#
# HOW IT HOOKS
#
# We register a repeating daily alarm (canonical EA modder pattern:
# alarms.add_alarm(owner, time_till_first_callback, callback, repeating=True,
# repeating_time_span=...)). The alarm fires once per in-game day at ~00:00 and
# rotates the visible task for every Sim currently in the Historian career. We
# also rotate once immediately on zone spin-up so a freshly-loaded lot shows a
# task without waiting for the next midnight. The alarm lives behind the same
# zone.Zone.do_zone_spin_up window the affordance injector uses, but installs its
# OWN idempotent hook so the two modules stay independent.
#
# Python 3.7 compatible (no f-strings-in-format edge cases, no walrus, etc.).

try:
    import services
    from sims4.resources import Types
    import zone
except Exception:
    services = None
    Types = None
    zone = None

import os
import traceback

MOD_NAME = "HistorianCareer"

# The Historian career tuning names (the `n=` attribute). Must match the
# career_Adult_Historian*.xml resources so career_tracker lookups line up. Both
# the regular entry and the degree-gated HiWi fast-track entry share the same
# CareerLevels (and thus the same daily-task pools), so we rotate Sims in either.
HC_CAREER_NAME = "career_Adult_Historian"
HC_CAREER_NAMES = ("career_Adult_Historian", "career_Adult_Historian_HiWi")

# Per-rank daily-task pool, mirrored from the AspirationCareer.objectives lists
# in aspiration_career_Historian_L{n}.xml. This is the documented FALLBACK pool:
# at runtime we prefer the LIVE objectives off the career's current AspirationCareer
# (so it always matches whatever the tuning ships), and only fall back to this map
# if the live read fails. Keyed by user_level (1-indexed).
_FALLBACK_POOLS = {
    1:  ("objective_HC_RunBlogeintrag", "objective_HC_ReadNonfictionBook"),
    2:  ("objective_HC_RunBlogeintrag", "objective_HC_RunGeschichtsSozial"),
    3:  ("objective_HC_RunBuecherregalRecherche", "objective_HC_RunGeschichtsSozial"),
    4:  ("objective_HC_RunTranscribeManuscript", "objective_HC_RunZeitzeugen"),
    5:  ("objective_HC_RunTranscribeManuscript", "objective_HC_RunZeitzeugen"),
    6:  ("objective_HC_RunAnalyzePrimarySource", "objective_HC_RunTranscribeManuscript", "objective_HC_RunZeitzeugen"),
    7:  ("objective_HC_RunPresentAtSymposium", "objective_HC_RunAnalyzePrimarySource", "objective_HC_RunZeitzeugen"),
    8:  ("objective_HC_RunHabilitationLecture", "objective_HC_RunPresentAtSymposium", "objective_HC_RunZeitzeugen"),
    9:  ("objective_HC_RunSuperviseDissertation", "objective_HC_RunHabilitationLecture"),
    10: ("objective_HC_RunDrittmittel", "objective_HC_RunSuperviseDissertation"),
}

_hooked = False


# ---------------------------------------------------------------------------
# Logging — same routing as affordance_injector._log (per-mod file in the
# localized Documents/Electronic Arts/<Sims 4>/ folder). Never raises.
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
                return os.path.join(ea, entry, "historiancareer_debug.log")
    except Exception:
        pass
    return None


def _log(msg):
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


_log("=== daily_task_rotation module imported ===")


# ---------------------------------------------------------------------------
# Pool resolution. Prefer the live AspirationCareer.objectives off the Sim's
# current career level; fall back to _FALLBACK_POOLS keyed by user_level.
# ---------------------------------------------------------------------------


def _objective_name(obj_tuning):
    """Best-effort tuning name for an objective class (for logging/selection)."""
    return getattr(obj_tuning, "__name__", None) or repr(obj_tuning)


def _live_pool_for_career(career):
    """Return the live objective-class tuple for the career's current level, or
    None if it can't be resolved. The pool is CareerLevel.aspiration.objectives."""
    try:
        level_tuning = getattr(career, "current_level_tuning", None)
        if level_tuning is None:
            return None
        aspiration = getattr(level_tuning, "aspiration", None)
        if aspiration is None:
            return None
        objectives = tuple(getattr(aspiration, "objectives", ()) or ())
        return objectives if objectives else None
    except Exception as e:
        _log("  live pool read failed: {}".format(e))
        return None


def _fallback_pool_for_level(user_level):
    """Return the fallback objective-NAME tuple for a user_level, or ()."""
    try:
        return _FALLBACK_POOLS.get(int(user_level), ())
    except Exception:
        return ()


def _current_sim_day():
    """Integer index of the current in-game day, used to make the rotation stable
    within a day. Falls back to 0 if the clock isn't readable."""
    try:
        ts = services.time_service()
        now = ts.sim_now
        # absolute_days() is the canonical day index on DateAndTime.
        return int(now.absolute_days())
    except Exception:
        try:
            import clock
            return int(services.game_clock_service().now().absolute_days())
        except Exception:
            return 0


def _pick_for_day(pool, day_index, salt):
    """Deterministically pick one item from `pool` for a given day.

    Stable within the day for a given Sim (salt = Sim id) so re-fires on the same
    day don't flip the task, but it varies day-to-day and Sim-to-Sim. Returns the
    chosen item or None for an empty pool."""
    if not pool:
        return None
    try:
        idx = (int(day_index) + int(salt)) % len(pool)
    except Exception:
        idx = 0
    return pool[idx]


# ---------------------------------------------------------------------------
# Rotation core. For each Sim in the Historian career, choose the day's task
# from the live pool (or fallback) and record it. We deliberately do NOT splice
# EA's career-objective internals — the tuning pool already drives gameplay; we
# stash the choice on the career object (`_hc_daily_task_name`) so any future UI
# hook can read it, and log it for verification.
# ---------------------------------------------------------------------------


def _resolve_historian_career_uids():
    """Resolve the guid64s of all Historian careers (regular + HiWi fast-track).

    Returns a tuple of uids (possibly empty). Both careers may not be present on
    every install, so missing ones are simply skipped."""
    if services is None or Types is None:
        return ()
    try:
        mgr = services.get_instance_manager(Types.CAREER)
        if mgr is None:
            return ()
        uids = []
        for name in HC_CAREER_NAMES:
            cls = None
            try:
                cls = mgr.get(name)
            except (ValueError, TypeError):
                cls = None
            if cls is None:
                for c in mgr.types.values():
                    if getattr(c, "__name__", None) == name:
                        cls = c
                        break
            if cls is not None:
                uid = getattr(cls, "guid64", None)
                if uid is not None:
                    uids.append(uid)
        return tuple(uids)
    except Exception as e:
        _log("  career uid resolve failed: {}".format(e))
        return ()


def _iter_sim_infos():
    """Yield all sim_infos we can reach. Best-effort across patches."""
    if services is None:
        return
    try:
        sim_info_manager = services.sim_info_manager()
        if sim_info_manager is None:
            return
        for sim_info in tuple(sim_info_manager.get_all()):
            yield sim_info
    except Exception as e:
        _log("  sim_info iteration failed: {}".format(e))
        return


def rotate_daily_tasks():
    """Pick today's visible daily task for every Historian Sim. Best-effort."""
    try:
        if services is None or Types is None:
            return
        career_uids = _resolve_historian_career_uids()
        if not career_uids:
            _log("  rotate: Historian career not resolvable; skipping (tuning pool still active).")
            return
        day_index = _current_sim_day()
        rotated = 0
        for sim_info in _iter_sim_infos():
            try:
                tracker = getattr(sim_info, "career_tracker", None)
                if tracker is None:
                    continue
                # The Sim may be in either Historian entry (regular or HiWi).
                career = None
                for uid in career_uids:
                    career = tracker.get_career_by_uid(uid)
                    if career is not None:
                        break
                if career is None:
                    continue
                user_level = getattr(career, "user_level", 0) or 0
                # Prefer the live pool; fall back to the static name map.
                live = _live_pool_for_career(career)
                if live:
                    pool = live
                    names = tuple(_objective_name(o) for o in pool)
                else:
                    pool = _fallback_pool_for_level(user_level)
                    names = pool  # already names
                if not pool:
                    continue
                salt = getattr(sim_info, "id", 0) or 0
                chosen = _pick_for_day(pool, day_index, salt)
                chosen_name = _objective_name(chosen) if live else chosen
                # Stash for any future UI hook; never raises into gameplay.
                try:
                    career._hc_daily_task_name = chosen_name
                    career._hc_daily_task_day = day_index
                except Exception:
                    pass
                rotated += 1
                _log("  rotate: sim={} level={} pool={} -> today='{}'".format(
                    salt, user_level, list(names), chosen_name
                ))
            except Exception as e:
                _log("  rotate(sim) error: {}".format(e))
        _log("Daily-task rotation done: {} Historian Sim(s), day_index={}.".format(
            rotated, day_index
        ))
    except Exception as e:
        _log("rotate_daily_tasks error: {}\n{}".format(e, traceback.format_exc()))


# ---------------------------------------------------------------------------
# Alarm wiring. Register a repeating daily alarm at zone spin-up. The alarm
# fires once per in-game day; we also rotate immediately so a freshly-loaded
# lot shows a task without waiting for midnight.
# ---------------------------------------------------------------------------


_alarm_handle = None


def _register_daily_alarm():
    global _alarm_handle
    if _alarm_handle is not None:
        return
    try:
        import alarms
        import clock
    except Exception as e:
        _log("  alarm modules unavailable ({}); rotation runs once per load only.".format(e))
        return
    try:
        # Fire the first callback ~1 sim-minute out (so the timeline is live),
        # then repeat every sim-day. use_sleep_time keeps it firing while the
        # household sleeps. The owner=None form is the standard module-level
        # alarm owner used by service-level modder alarms.
        time_till_first = clock.interval_in_sim_minutes(1)
        repeat = clock.interval_in_sim_days(1)

        def _on_alarm(_handle):
            rotate_daily_tasks()

        _alarm_handle = alarms.add_alarm(
            None,
            time_till_first,
            _on_alarm,
            repeating=True,
            repeating_time_span=repeat,
            use_sleep_time=True,
        )
        _log("Daily-task rotation alarm registered (repeat=1 sim day).")
    except Exception as e:
        _log("  daily alarm registration failed: {}\n{}".format(e, traceback.format_exc()))


def on_zone_spin_up():
    """Entry point invoked from the zone-spinup hook. Best-effort; never raises."""
    try:
        _register_daily_alarm()
        # Immediate first rotation so the panel has a task without waiting for
        # the alarm's first fire.
        rotate_daily_tasks()
    except Exception as e:
        _log("on_zone_spin_up error: {}".format(e))


def _install_hook():
    """Idempotently patch zone.Zone.do_zone_spin_up to drive the rotation.

    Independent of affordance_injector's hook (different sentinel attribute) so
    the two modules don't interfere. Wrapped defensively."""
    global _hooked
    if _hooked or zone is None:
        return
    try:
        original = zone.Zone.do_zone_spin_up
        if getattr(original, "_hc_daily_patched", False):
            _hooked = True
            return

        def patched(self, *args, **kwargs):
            # Run EA's real spin-up FIRST so the timeline/services are live, then
            # register our alarm and do the first rotation.
            result = original(self, *args, **kwargs)
            try:
                on_zone_spin_up()
            except Exception as e:
                _log("zone-spinup rotation hook error: {}".format(e))
            return result

        patched._hc_daily_patched = True
        zone.Zone.do_zone_spin_up = patched
        _hooked = True
        _log("Daily-task rotation zone hook installed.")
    except Exception as e:
        _log("Failed to install daily-task hook: {}".format(e))


# Auto-install on import (mirrors affordance_injector). Importing this module
# from the package __init__ is enough.
_install_hook()
