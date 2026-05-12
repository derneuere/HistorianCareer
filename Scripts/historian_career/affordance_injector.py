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

# Computer object tunings to extend. The exact tuning names vary between EA patches;
# the list below covers the standard base-game computer variants. If a name no longer
# resolves in your install, find the current ones in Sims 4 Studio's Game File Cruiser
# under Object Tuning → filter "computer".
_HC_COMPUTER_TUNINGS = (
    "object_computerEconomic_2x1",
    "object_computerBasic_2x1",
    "object_computerHighEnd_2x1",
    "object_computerGaming_2x1",
)

# Fallback: any object tuning whose name starts with this prefix is also treated as a computer.
_HC_COMPUTER_NAME_PREFIX = "object_computer"

_injected = False


def _log(msg):
    try:
        print(f"[{MOD_NAME}] {msg}")
    except Exception:
        pass


def _inject_once():
    """Walk the tuning managers and append our affordances to every computer object."""
    global _injected
    if _injected or services is None or Types is None:
        return
    try:
        aff_mgr = services.get_instance_manager(Types.INTERACTION)
        obj_mgr = services.get_instance_manager(Types.OBJECT)
        if aff_mgr is None or obj_mgr is None:
            _log("Instance managers not ready; deferring injection.")
            return

        # Resolve each affordance; drop any that don't load (so a missing one doesn't
        # take the whole injector down with it).
        affordances = []
        for name in _HC_AFFORDANCE_NAMES:
            aff = aff_mgr.get(name)
            if aff is None:
                _log(f"WARN: affordance not found: {name}")
                continue
            affordances.append(aff)
        affordances = tuple(affordances)
        if not affordances:
            _log("No affordances resolved; nothing to inject.")
            return

        injected_into = 0

        # 1. Explicit allow-list (exact tuning names we expect to exist).
        target_objects = set()
        for obj_name in _HC_COMPUTER_TUNINGS:
            obj = obj_mgr.get(obj_name)
            if obj is not None:
                target_objects.add(obj)

        # 2. Fuzzy fallback: any tuning whose canonical name starts with the prefix.
        #    `types` is a dict { resource_key -> class }; iterate values.
        try:
            for obj_cls in tuple(obj_mgr.types.values()):
                cls_name = getattr(obj_cls, "__name__", "")
                if isinstance(cls_name, str) and cls_name.startswith(_HC_COMPUTER_NAME_PREFIX):
                    target_objects.add(obj_cls)
        except Exception as e:
            _log(f"Fuzzy lookup failed (continuing with allow-list): {e}")

        for obj_cls in target_objects:
            existing = tuple(getattr(obj_cls, "_super_affordances", ()))
            # Skip already-injected (idempotency on zone reload).
            if all(a in existing for a in affordances):
                continue
            obj_cls._super_affordances = existing + tuple(
                a for a in affordances if a not in existing
            )
            injected_into += 1

        _log(f"Injected {len(affordances)} affordances into {injected_into} computer objects.")
        _injected = True
    except Exception as e:
        _log(f"Injection error: {e}")


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
