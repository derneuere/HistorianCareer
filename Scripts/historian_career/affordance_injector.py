# affordance_injector.py — adds the Historian career interactions to in-game computers
# without requiring Scumbumbo's XML Injector as a dependency.
#
# How it works:
#   1. We monkey-patch zone.Zone.do_zone_spin_up so that just before the first zone loads,
#      we walk the loaded OBJECT and INTERACTION tunings and append our affordances to
#      every "computer" object's _super_affordances tuple.
#   2. Appending (rather than replacing) means we co-exist with any other mod that touches
#      the same objects — exactly the property XML Injector was added to provide.
#   3. Injection is idempotent: a module-level flag prevents double-add on zone reloads.
#
# Reference for the pattern: this mirrors what Scumbumbo's XML Injector does internally
# (the public XML-Injector tunable wrapper is just sugar over this).

try:
    import services
    from sims4.resources import Types
    import zone
except Exception:
    services = None
    Types = None
    zone = None

MOD_NAME = "HistorianCareer"

# The five Historian SuperInteractions we want on the computer.
_HC_AFFORDANCE_NAMES = (
    "HC_Interaction_TranscribeManuscript",
    "HC_Interaction_AnalyzePrimarySource",
    "HC_Interaction_PresentAtSymposium",
    "HC_Interaction_HabilitationLecture",
    "HC_Interaction_SuperviseDissertation",
)

# Computer object tunings to extend. Names confirmed against the live game's
# CombinedTuning (patch 1.124.55). EA also adds new computer variants in patches,
# so we additionally fuzzy-match on the `object_computer*` / `object_Computer*`
# name prefix (case-insensitive).
_HC_COMPUTER_TUNINGS = (
    "object_computerLOW_01",
    "object_computerDesktopMED_01",
    "object_Computer_High",
    "object_Computer_Tesla",
    "object_Computer_DS",
    "object_Computer_CrimSuitcase",
)

# Fallback: any object tuning whose name starts with this prefix (case-insensitive)
# is also treated as a computer. Catches future variants without code changes.
_HC_COMPUTER_NAME_PREFIX_LOWER = "object_computer"

_injected = False


# ---------------------------------------------------------------------------
# Debug logging — writes to a file in the game's user folder so we can
# actually see what the injector is doing in-game. Falls back silently if
# anything goes wrong (we never want logging to break gameplay).
# ---------------------------------------------------------------------------

import os
import traceback

_LOG_PATH = None


def _resolve_log_path():
    """Find the game's user-data folder (localized: Die Sims 4 / The Sims 4 / Les Sims 4)
    and return a path to historiancareer_debug.log inside it."""
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
    """Print to Sims 4's stdout AND append to a debug file. Never raises."""
    line = f"[{MOD_NAME}] {msg}"
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


_log("=== affordance_injector module imported ===")


def _inject_once():
    """Walk the tuning managers and append our affordances to every computer object."""
    global _injected
    _log("_inject_once called")
    if _injected:
        _log("  already injected, skipping")
        return
    if services is None or Types is None:
        _log("  services/Types not available, skipping")
        return
    try:
        aff_mgr = services.get_instance_manager(Types.INTERACTION)
        obj_mgr = services.get_instance_manager(Types.OBJECT)
        _log(f"  aff_mgr={aff_mgr is not None} obj_mgr={obj_mgr is not None}")
        # Sims 4 distinguishes OBJECT (DefinitionManager, keyed by int) from
        # the object-tuning instance manager. The tuning-class manager is
        # available under a different resource type; try both. The Types
        # enum has these values; not all are documented identically across
        # game versions, so probe what's available.
        all_managers = {}
        try:
            for t in dir(Types):
                if t.startswith("_"): continue
                val = getattr(Types, t, None)
                if val is None: continue
                try:
                    m = services.get_instance_manager(val)
                    if m is not None:
                        n_types = len(getattr(m, "types", {}))
                        all_managers[t] = (val, n_types, m)
                except Exception:
                    pass
            # Log managers with the most loaded tunings — gives us a feel for which is which.
            sorted_mgrs = sorted(all_managers.items(), key=lambda kv: -kv[1][1])[:10]
            _log("  top instance managers by tuning count:")
            for name, (val, n, m) in sorted_mgrs:
                _log(f"    Types.{name} (val={val}): {n} tunings")
        except Exception as e:
            _log(f"  manager enumeration failed: {e}")
        if aff_mgr is None or obj_mgr is None:
            _log("  Instance managers not ready; deferring injection.")
            return

        # First, enumerate what HC_Interaction_* IS registered. This tells us if
        # the tunings actually loaded; if the lookup-by-name fails for some, then
        # we can find them in this enumeration and use their objects directly.
        registered_hc = {}
        try:
            for key, cls in aff_mgr.types.items():
                cls_name = getattr(cls, "__name__", "")
                if isinstance(cls_name, str) and cls_name.startswith("HC_Interaction_"):
                    registered_hc[cls_name] = (cls, key)
            _log(f"  registered HC_Interaction_* count: {len(registered_hc)}")
            for n in sorted(registered_hc):
                _, key = registered_hc[n]
                _log(f"    REGISTERED: {n}  key={key}")
        except Exception as e:
            _log(f"  registry enumeration failed: {e}\n{traceback.format_exc()}")

        # Resolve each affordance. Prefer registry lookup by name; fall back to
        # the by-classname dictionary we just built.
        affordances = []
        for name in _HC_AFFORDANCE_NAMES:
            aff = aff_mgr.get(name)
            if aff is None and name in registered_hc:
                aff = registered_hc[name][0]
                _log(f"  affordance {name}: FOUND via fallback enumeration")
            else:
                _log(f"  affordance {name}: {'FOUND' if aff is not None else 'MISSING'} via aff_mgr.get()")
            if aff is not None:
                affordances.append(aff)
        affordances = tuple(affordances)
        if not affordances:
            _log("  No affordances resolved; nothing to inject.")
            return

        # 1. Allow-list lookup by name — wrap individually because the OBJECT
        #    manager (DefinitionManager) only accepts integer instance IDs,
        #    not name strings (unlike the INTERACTION manager). A string lookup
        #    raises ValueError. The fuzzy iteration below is the actual workhorse.
        target_objects = set()
        for obj_name in _HC_COMPUTER_TUNINGS:
            try:
                obj = obj_mgr.get(obj_name)
                if obj is not None:
                    target_objects.add(obj)
                    _log(f"  computer allow-list {obj_name}: FOUND (by name)")
            except (ValueError, TypeError):
                # Expected for DefinitionManager. We'll find it via fuzzy iteration.
                pass

        # 2. Fuzzy fallback: any tuning whose canonical name starts with
        #    "object_computer" (case-insensitive). EA's actual names mix
        #    capitalisations (`object_computerLOW_01`, `object_Computer_Tesla`).
        # NOTE: obj_mgr.types is a dict {ResourceKey -> class}. The class
        # itself does NOT carry the tuning name as __name__; the tuning name
        # lives elsewhere. Use the resource key's instance ID inverted via
        # the manager's _id_to_obj_class or iterate get_ordered_types() if
        # available. As a robust fallback, iterate the manager and try to
        # extract the tuning name from instance.__name__ or instance.__tuning_name__.
        fuzzy_total = 0
        fuzzy_matched = 0
        try:
            all_types = list(obj_mgr.types.values()) if hasattr(obj_mgr, "types") else []
            fuzzy_total = len(all_types)
            for obj_cls in all_types:
                # The tuning name in Sims 4 is on the class via several possible attrs.
                name_candidates = (
                    getattr(obj_cls, "__name__", None),
                    getattr(obj_cls, "TUNING_NAME", None),
                    str(getattr(obj_cls, "__tuning_class_name__", "")),
                )
                for n in name_candidates:
                    if isinstance(n, str) and n.lower().startswith(_HC_COMPUTER_NAME_PREFIX_LOWER):
                        target_objects.add(obj_cls)
                        fuzzy_matched += 1
                        break
        except Exception as e:
            _log(f"  Fuzzy lookup failed: {e}\n{traceback.format_exc()}")
        _log(f"  Fuzzy scan: examined {fuzzy_total} object tunings, matched {fuzzy_matched}")
        _log(f"  Total target_objects: {len(target_objects)}")

        # Sample what __name__ actually looks like on a few of these so we know
        # whether our fuzzy filter is even looking at the right attribute.
        if obj_mgr is not None and hasattr(obj_mgr, "types"):
            sample = list(obj_mgr.types.values())[:5]
            for cls in sample:
                _log(f"  sample obj class: __name__={getattr(cls,'__name__',None)!r} "
                     f"TUNING_NAME={getattr(cls,'TUNING_NAME',None)!r}")

        injected_into = 0
        for obj_cls in target_objects:
            existing = tuple(getattr(obj_cls, "_super_affordances", ()))
            if all(a in existing for a in affordances):
                continue
            obj_cls._super_affordances = existing + tuple(
                a for a in affordances if a not in existing
            )
            injected_into += 1

        _log(f"Injected {len(affordances)} affordances into {injected_into} computer objects.")
        _injected = True
    except Exception as e:
        _log(f"Injection error: {e}\n{traceback.format_exc()}")


def _install_hook():
    """Hook our injector onto the zone-spinup so it runs once before the first lot loads."""
    if zone is None:
        return
    try:
        original = zone.Zone.do_zone_spin_up
        if getattr(original, "_hc_patched", False):
            return  # already hooked (e.g. module re-imported)

        def patched(self, *args, **kwargs):
            _inject_once()
            return original(self, *args, **kwargs)

        patched._hc_patched = True
        zone.Zone.do_zone_spin_up = patched
        _log("Affordance injector hook installed.")
    except Exception as e:
        _log(f"Failed to install hook: {e}")


# Auto-install on import. Importing this module from the package's __init__ is enough.
_install_hook()
