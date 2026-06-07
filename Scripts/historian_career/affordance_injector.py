# affordance_injector.py — adds the Historian career interactions to in-game
# objects (computers + bookshelves) and Sims (social), without requiring
# Scumbumbo's XML Injector as a dependency.
#
# How it works:
#   1. We monkey-patch zone.Zone.do_zone_spin_up so that just before the first zone loads,
#      we walk the loaded OBJECT and INTERACTION tunings and append our affordances to:
#        - every "object_computer*" object's _super_affordances (computer affordances),
#        - every "object_book*" object's _super_affordances (bookshelf affordances;
#          Objektgeschichte also rides here per DESIGN open-Q#2),
#        - the Sim class's _super_affordances (social affordances; best-effort).
#   2. Appending (rather than replacing) means we co-exist with any other mod that touches
#      the same objects — exactly the property XML Injector was added to provide.
#   3. Injection is idempotent: module-level flags prevent double-add on zone reloads.
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

# Historian SuperInteractions grouped by injection SURFACE. Names are LAW per
# _BUILD_SPEC.md slice C AFFORDANCES table. Each affordance is band-gated by
# level_gate.py once installed; injection here just makes it *reachable* on the
# right object/Sim. We deliberately inject the full set and let the per-Sim
# band gate filter the pie menu, rather than gating by surface.

# COMPUTER object affordances (the 5 existing + 4 new computer ones).
_HC_COMPUTER_AFFORDANCE_NAMES = (
    "HC_Interaction_TranscribeManuscript",   # existing, band 4-6
    "HC_Interaction_AnalyzePrimarySource",   # existing, band 5-7
    "HC_Interaction_PresentAtSymposium",     # existing, band 7-8
    "HC_Interaction_HabilitationLecture",    # existing, band 8-9
    "HC_Interaction_SuperviseDissertation",  # existing, band 9-10
    "HC_Interaction_Blogeintrag",            # new, band 1-2
    "HC_Interaction_Bildrechte",             # new, band 4-4
    "HC_Interaction_OnlineFortbildung",      # new, band 4-4
    "HC_Interaction_Drittmittel",            # new, band 10-10
)

# BOOKSHELF object affordances (new; injected via fuzzy "object_book" prefix).
# Objektgeschichte ships on the bookshelf surface (DESIGN open-Q#2: no clean
# museum-exhibit object to inject onto), framed as cataloguing.
_HC_BOOKSHELF_AFFORDANCE_NAMES = (
    "HC_Interaction_Objektgeschichte",       # new, band 2-2
    "HC_Interaction_BuecherregalRecherche",  # new, band 3-9
    "HC_Interaction_CrossReference",         # new, band 3-4
)

# SOCIAL affordances injected onto Sims (best-effort; see _inject_social_once).
_HC_SOCIAL_AFFORDANCE_NAMES = (
    "HC_Interaction_Zeitzeugen",             # new, band 4-8 (Elder target)
    "HC_Interaction_DropHistoryFact",        # new overlay, band 1-10
    "HC_Interaction_HistoricalJoke",         # new overlay, band 1-10
)

# All HC affordances we resolve from the INTERACTION manager. The level gate is
# installed on whatever subset resolves; surface injection uses the groups above.
_HC_AFFORDANCE_NAMES = (
    _HC_COMPUTER_AFFORDANCE_NAMES
    + _HC_BOOKSHELF_AFFORDANCE_NAMES
    + _HC_SOCIAL_AFFORDANCE_NAMES
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

# Bookshelf object tunings to extend. Confirmed against the live game's
# CombinedTuning (object_bookshelf=14837, object_bookshelf_library=100180,
# many object_bookcaseFloor*). We fuzzy-match the "object_book" prefix
# (case-insensitive) exactly like the computer path so future bookcase
# variants are caught without code changes.
_HC_BOOKSHELF_NAME_PREFIX_LOWER = "object_book"

# Sim object tuning name (the actor/target we attach social super-affordances
# to). EA's Sim object tuning is "sim". We also fuzzy-match any object whose
# name is exactly "sim" (case-insensitive) as a robustness fallback.
_HC_SIM_TUNING_NAME_LOWER = "sim"

_injected = False
_social_injected = False


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


def _tuning_name_candidates(obj_cls):
    """Return the possible tuning-name strings carried by an object/Sim class.

    The tuning name in Sims 4 is not reliably on a single attribute, so we
    probe the same set the original computer-fuzzy path used."""
    return (
        getattr(obj_cls, "__name__", None),
        getattr(obj_cls, "TUNING_NAME", None),
        str(getattr(obj_cls, "__tuning_class_name__", "")),
    )


def _fuzzy_match_objects(obj_mgr, prefix_lower):
    """Return the set of object tuning classes whose canonical name starts with
    `prefix_lower` (case-insensitive). Mirrors the existing computer scan so the
    bookshelf path behaves identically. Returns (matched_set, examined_count)."""
    matched = set()
    examined = 0
    try:
        all_types = list(obj_mgr.types.values()) if hasattr(obj_mgr, "types") else []
        examined = len(all_types)
        for obj_cls in all_types:
            for n in _tuning_name_candidates(obj_cls):
                if isinstance(n, str) and n.lower().startswith(prefix_lower):
                    matched.add(obj_cls)
                    break
    except Exception as e:
        _log(f"  Fuzzy lookup ({prefix_lower}) failed: {e}\n{traceback.format_exc()}")
    return matched, examined


def _append_affordances(target_objects, affordances, attr="_super_affordances"):
    """Idempotently append `affordances` to each target's `attr` tuple.

    Appending (not replacing) means we co-exist with other mods touching the
    same objects. Returns the number of objects actually modified."""
    if not affordances:
        return 0
    injected_into = 0
    for obj_cls in target_objects:
        existing = tuple(getattr(obj_cls, attr, ()))
        to_add = tuple(a for a in affordances if a not in existing)
        if not to_add:
            continue
        try:
            setattr(obj_cls, attr, existing + to_add)
            injected_into += 1
        except Exception as e:
            _log(f"  append to {getattr(obj_cls, '__name__', obj_cls)!r}.{attr} failed: {e}")
    return injected_into


def _resolve_sim_object_classes(obj_mgr):
    """Best-effort: return the set of object-tuning classes that represent a Sim.

    There is no single guaranteed accessor across patches, so we try, in order:
      1. obj_mgr.get("sim") by name (works on managers that accept string keys).
      2. The live Sim runtime class (sims.sim.Sim) — social super-affordances are
         read from `Sim.super_affordances`, which resolves `_super_affordances`.
      3. Fuzzy: any object tuning whose canonical name is exactly "sim"
         (case-insensitive).
    Any of these may yield nothing; the caller treats the social injection as
    best-effort. Returns a set (possibly empty)."""
    targets = set()
    # 1. by-name lookup
    if obj_mgr is not None:
        try:
            obj = obj_mgr.get(_HC_SIM_TUNING_NAME_LOWER)
            if obj is not None:
                targets.add(obj)
                _log("  sim object: FOUND via obj_mgr.get('sim')")
        except (ValueError, TypeError):
            pass
    # 2. live runtime Sim class (this is what actually serves the pie menu)
    try:
        from sims.sim import Sim as _SimClass
        if _SimClass is not None:
            targets.add(_SimClass)
            _log("  sim object: added sims.sim.Sim runtime class")
    except Exception as e:
        _log(f"  sim object: sims.sim.Sim import failed: {e}")
    # 3. fuzzy exact-name match
    if obj_mgr is not None and hasattr(obj_mgr, "types"):
        try:
            for obj_cls in obj_mgr.types.values():
                for n in _tuning_name_candidates(obj_cls):
                    if isinstance(n, str) and n.lower() == _HC_SIM_TUNING_NAME_LOWER:
                        targets.add(obj_cls)
                        break
        except Exception as e:
            _log(f"  sim object: fuzzy scan failed: {e}")
    return targets


def _inject_social(obj_mgr, social_affordances):
    """Attach the social super-affordances to Sims, best-effort.

    Zeitzeugen (Elder target) + the two career-wide overlays (Drop a History
    Fact / Historical Joke) are SocialSuperInteractions whose target is a Sim.
    Adding them to the Sim's `_super_affordances` makes them reachable from the
    Sim pie menu; the per-Sim band gate in level_gate.py then filters by rank.

    This is explicitly BEST-EFFORT (DESIGN/_BUILD_SPEC): if no Sim class
    resolves, we log and rely on the tuning-side HC_PieMenuCategory_Historian
    pie-menu placement as the working fallback. Idempotent."""
    global _social_injected
    if _social_injected:
        _log("  social already injected, skipping")
        return
    if not social_affordances:
        _log("  No social affordances resolved; skipping social injection.")
        return
    sim_targets = _resolve_sim_object_classes(obj_mgr)
    if not sim_targets:
        _log("  Social injection BEST-EFFORT: no Sim class resolved — relying "
             "on tuning-side pie-menu category fallback.")
        return
    n_social = _append_affordances(sim_targets, social_affordances)
    _log(f"Injected {len(social_affordances)} social affordances into "
         f"{n_social} Sim class(es).")
    _social_injected = True


def _inject_once():
    """Walk the tuning managers and append our affordances to the right surfaces
    (computer / bookshelf objects + Sims) and install the per-Sim level gate."""
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

        # Cross-manager HC_* enumeration. We're chasing a "careers.add_career
        # silently fails" symptom where the Python instance manager seems to
        # not have HC_Statistic_HistorianLevel; enumerating EVERY HC_*-prefixed
        # class across the relevant instance managers gives us a single ground-
        # truth list of what Sims 4's tuning loader actually accepted.
        try:
            for mgr_name, mgr_type in (
                ("STATISTIC", getattr(Types, "STATISTIC", None)),
                ("ASPIRATION", getattr(Types, "ASPIRATION", None)),
                ("ASPIRATION_TRACK", getattr(Types, "ASPIRATION_TRACK", None)),
                ("CAREER", getattr(Types, "CAREER", None)),
                ("CAREER_LEVEL", getattr(Types, "CAREER_LEVEL", None)),
                ("CAREER_TRACK", getattr(Types, "CAREER_TRACK", None)),
                ("TRAIT", getattr(Types, "TRAIT", None)),
                ("OBJECTIVE", getattr(Types, "OBJECTIVE", None)),
                ("PIE_MENU_CATEGORY", getattr(Types, "PIE_MENU_CATEGORY", None)),
                ("ACTION", getattr(Types, "ACTION", None)),
            ):
                if mgr_type is None: continue
                m = services.get_instance_manager(mgr_type)
                if m is None: continue
                hc_in_mgr = []
                for key, cls in m.types.items():
                    cls_name = getattr(cls, "__name__", "")
                    if isinstance(cls_name, str) and (cls_name.startswith("HC_") or cls_name.startswith("aspiration_HistorianCalling") or cls_name.startswith("aspiration_career_Historian") or cls_name.startswith("aspiration_track_HistorianCalling") or cls_name.startswith("career_Adult_Historian") or cls_name.startswith("career_level_Adult_Historian") or cls_name.startswith("career_track_Adult_Historian") or cls_name.startswith("trait_Habilitation") or cls_name.startswith("objective_HC_")):
                        hc_in_mgr.append(cls_name)
                _log(f"  HC_* in Types.{mgr_name}: count={len(hc_in_mgr)}")
                for n in sorted(hc_in_mgr):
                    _log(f"    {mgr_name}: {n}")
        except Exception as e:
            _log(f"  HC cross-manager enum failed: {e}\n{traceback.format_exc()}")

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
        # the by-classname dictionary we just built. We keep a name->class map so
        # each surface (computer / bookshelf / social) can pull just its subset.
        affordance_by_name = {}
        for name in _HC_AFFORDANCE_NAMES:
            aff = aff_mgr.get(name)
            if aff is None and name in registered_hc:
                aff = registered_hc[name][0]
                _log(f"  affordance {name}: FOUND via fallback enumeration")
            else:
                _log(f"  affordance {name}: {'FOUND' if aff is not None else 'MISSING'} via aff_mgr.get()")
            if aff is not None:
                affordance_by_name[name] = aff

        def _resolve_group(names):
            """Return the tuple of resolved affordance classes for a name group,
            preserving order and skipping any that failed to resolve."""
            return tuple(
                affordance_by_name[n] for n in names if n in affordance_by_name
            )

        computer_affordances = _resolve_group(_HC_COMPUTER_AFFORDANCE_NAMES)
        bookshelf_affordances = _resolve_group(_HC_BOOKSHELF_AFFORDANCE_NAMES)
        social_affordances = _resolve_group(_HC_SOCIAL_AFFORDANCE_NAMES)
        affordances = tuple(affordance_by_name.values())
        if not affordances:
            _log("  No affordances resolved; nothing to inject.")
            return
        _log(
            "  Resolved affordances: computer={} bookshelf={} social={}".format(
                len(computer_affordances),
                len(bookshelf_affordances),
                len(social_affordances),
            )
        )

        # ---- COMPUTER surface ------------------------------------------
        # 1. Allow-list lookup by name — wrap individually because the OBJECT
        #    manager (DefinitionManager) only accepts integer instance IDs,
        #    not name strings (unlike the INTERACTION manager). A string lookup
        #    raises ValueError. The fuzzy iteration below is the actual workhorse.
        computer_objects = set()
        for obj_name in _HC_COMPUTER_TUNINGS:
            try:
                obj = obj_mgr.get(obj_name)
                if obj is not None:
                    computer_objects.add(obj)
                    _log(f"  computer allow-list {obj_name}: FOUND (by name)")
            except (ValueError, TypeError):
                # Expected for DefinitionManager. We'll find it via fuzzy iteration.
                pass

        # 2. Fuzzy fallback: any tuning whose canonical name starts with
        #    "object_computer" (case-insensitive). EA's actual names mix
        #    capitalisations (`object_computerLOW_01`, `object_Computer_Tesla`).
        #    obj_mgr.types is a dict {ResourceKey -> class}; the tuning name is
        #    on the class via __name__ / TUNING_NAME / __tuning_class_name__.
        fuzzy_computers, fuzzy_total = _fuzzy_match_objects(
            obj_mgr, _HC_COMPUTER_NAME_PREFIX_LOWER
        )
        computer_objects |= fuzzy_computers
        _log(f"  Computer scan: examined {fuzzy_total} object tunings, "
             f"fuzzy-matched {len(fuzzy_computers)}, total targets {len(computer_objects)}")

        # Sample what __name__ actually looks like on a few of these so we know
        # whether our fuzzy filter is even looking at the right attribute.
        if obj_mgr is not None and hasattr(obj_mgr, "types"):
            sample = list(obj_mgr.types.values())[:5]
            for cls in sample:
                _log(f"  sample obj class: __name__={getattr(cls,'__name__',None)!r} "
                     f"TUNING_NAME={getattr(cls,'TUNING_NAME',None)!r}")

        n_comp = _append_affordances(computer_objects, computer_affordances)
        _log(f"Injected {len(computer_affordances)} affordances into "
             f"{n_comp} computer objects.")

        # ---- BOOKSHELF surface -----------------------------------------
        # Mirror the computer fuzzy path exactly: any object tuning whose name
        # starts with "object_book" (object_bookshelf, object_bookshelf_library,
        # object_bookcaseFloor*, ...). Objektgeschichte rides here too (DESIGN
        # open-Q#2: no clean museum-exhibit object to inject onto).
        bookshelf_objects, book_total = _fuzzy_match_objects(
            obj_mgr, _HC_BOOKSHELF_NAME_PREFIX_LOWER
        )
        _log(f"  Bookshelf scan: examined {book_total} object tunings, "
             f"fuzzy-matched {len(bookshelf_objects)}")
        n_book = _append_affordances(bookshelf_objects, bookshelf_affordances)
        _log(f"Injected {len(bookshelf_affordances)} affordances into "
             f"{n_book} bookshelf objects.")

        # ---- SOCIAL surface (best-effort) ------------------------------
        # Attach the social super-affordances (Zeitzeugen + the 2 overlays) to
        # the Sim object's _super_affordances. This is best-effort: if no Sim
        # tuning resolves we log and move on (the tuning-side pie-menu category
        # remains the working fallback). See _inject_social.
        try:
            _inject_social(obj_mgr, social_affordances)
        except Exception as e:
            _log(f"  Social injection error: {e}\n{traceback.format_exc()}")

        # Issue #26 — per-Sim career-level gating. The XML test_globals path
        # silently failed (commit bc530fd / revert 05bff8a), so the gate lives
        # in level_gate.py and patches each HC_Interaction_*'s `_test`
        # classmethod. We share this hook because the affordance classes are
        # already resolved (`affordance_by_name`) and the career/track managers
        # are guaranteed loaded by zone-spin-up time.
        #
        # NOTE: Not all Sims 4 instance managers honour `mgr.get(name)` for
        # string keys — the DefinitionManager (OBJECT) is integer-only, and
        # the first cut here found CAREER / CAREER_TRACK also returning None
        # via .get() despite the tunings being loaded (visible in the
        # diagnostic enumeration above). We use the same enumerate-and-match
        # fallback that already works for affordance resolution: walk
        # `mgr.types.values()` and match on `cls.__name__`.
        try:
            from historian_career.level_gate import install_level_gates

            def _find_tuning_by_name(manager, name):
                if manager is None:
                    return None
                try:
                    cls = manager.get(name)
                    if cls is not None:
                        return cls
                except (ValueError, TypeError):
                    pass  # integer-only manager; fall through
                try:
                    for cls in manager.types.values():
                        if getattr(cls, "__name__", None) == name:
                            return cls
                except Exception:
                    pass
                return None

            career_mgr = services.get_instance_manager(Types.CAREER) if services and Types else None
            track_mgr = services.get_instance_manager(Types.CAREER_TRACK) if services and Types else None
            career_cls = _find_tuning_by_name(career_mgr, "career_Adult_Historian")
            track_cls = _find_tuning_by_name(track_mgr, "career_track_Adult_Historian")
            # Degree-gated HiWi fast-track entry (separate Career + CareerTrack).
            # May be absent on older installs; resolved best-effort and only added
            # to the gate when present.
            hiwi_career_cls = _find_tuning_by_name(career_mgr, "career_Adult_Historian_HiWi")
            hiwi_track_cls = _find_tuning_by_name(track_mgr, "career_track_Adult_Historian_HiWi")
            career_clses = [c for c in (career_cls, hiwi_career_cls) if c is not None]
            track_clses = [t for t in (track_cls, hiwi_track_cls) if t is not None]
            if not career_clses or not track_clses:
                _log(
                    "  Level gates SKIPPED: career/track not resolvable "
                    f"(career_cls={career_cls!r} track_cls={track_cls!r} "
                    f"hiwi_career={hiwi_career_cls!r} hiwi_track={hiwi_track_cls!r}) "
                    "— affordances remain ungated for this session."
                )
            else:
                # affordance_by_name is keyed by tuning name; install_level_gates
                # pulls exactly the names present in _LEVEL_REQUIREMENTS and
                # leaves any others ungated. Both Historian entries (regular +
                # HiWi) are passed so a Sim in either is gated identically.
                n = install_level_gates(affordance_by_name, career_clses, track_clses, log=_log)
                _log(f"  Level gates installed on {n} HC_Interaction_* classes "
                     f"(careers={len(career_clses)} tracks={len(track_clses)}).")
        except Exception as e:
            _log(f"  Level-gate install error: {e}\n{traceback.format_exc()}")

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
