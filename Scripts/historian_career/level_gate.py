# level_gate.py — per-Sim level-gating for the five HC SuperInteractions.
#
# WHY THIS EXISTS
#
# Issue #26 asked us to gate the HC_Interaction_* affordances by the actor's
# Historian career level. The natural EA path is `<L n="test_globals">` in the
# interaction tuning XML with `<V t="career_test">` carrying a CareerTrackTest.
# We tried that (commit bc530fd) and the affordances vanished from the pie menu
# for ALL Sims — career-having or not. The deployed XML extracted from the
# built package looked structurally correct (matching the FACTORY_TUNABLES
# bytecode for TunableCareerTest / CareerTrackTestFactory in
# event_testing/test_variants.pyc), but the test was returning False at
# runtime for everyone and nothing surfaced in `lastException`. Rather than
# keep guessing at XML shape, we revert to test_globals being empty and apply
# the gate in Python — which is what EA itself does for `is_work_time` in
# `careers/career_interactions.pyc::CareerSuperInteraction._test`.
#
# HOW IT WORKS
#
# Every Interaction subclass exposes a classmethod `_test(cls, target, context,
# **kwargs)` that the pie menu builder calls per-Sim per-open via the chain:
#   ScriptObject.super_affordances -> Interaction.test -> cls._test(...)
# Returning `TestResult(False, reason)` silently drops the affordance from the
# Sim's pie menu. We install one such `_test` per HC_Interaction_* class,
# capturing the required user_level as a per-class attribute.
#
# DESIGN NOTES
#
# - Identity comparison on `current_track_tuning` is correct: tuning classes
#   are singletons within their InstanceManager, so `is` is the EA-canonical
#   check (verified in CareerTrackTestFactory.__call__ bytecode at offset 56).
# - Simless interactions and pre-CAS sim states are passed through with
#   TestResult.TRUE so we never block engine paths that have no Sim context.
# - The patch is idempotent: re-installing simply overwrites `_test` with the
#   same classmethod and rewrites the same per-class attributes.
# - The actual install is called from affordance_injector._inject_once() so
#   it shares the existing zone-spinup hook and the same already-resolved
#   affordance class objects. No second monkey-patch site.

# Required Historian user_level (1-indexed) per HC affordance. Matches the
# career_level tuning progression: L1 Research Assistant -> L5 Full Professor.
_LEVEL_REQUIREMENTS = {
    "HC_Interaction_TranscribeManuscript":  1,  # L1+ Research Assistant
    "HC_Interaction_AnalyzePrimarySource":  2,  # L2+ PhD Candidate
    "HC_Interaction_PresentAtSymposium":    3,  # L3+ Postdoc
    "HC_Interaction_HabilitationLecture":   4,  # L4+ Junior Prof
    "HC_Interaction_SuperviseDissertation": 5,  # L5+ Full Prof (W3)
}


def _gated_test(cls, target, context, **kwargs):
    """Classmethod swapped onto HC_Interaction_* SuperInteractions.

    Mirrors EA's `CareerSuperInteraction._test` shape:
      - Resolve the actor Sim's Historian career via `career_tracker.get_career_by_uid`.
      - Identity-compare `current_track_tuning` to ensure the Sim is on our
        career track (not a re-imagined branch — we only have one track today,
        but the check costs nothing and future-proofs the gate).
      - Compare `career.user_level` against the per-class minimum stored on
        `cls._hc_min_user_level`.
    Any failure returns `TestResult(False, ...)` so the affordance is filtered
    out of the pie menu without raising.

    Imports are local because this module is imported at script package init
    time, before any zone has loaded. `event_testing.results` is loaded by then
    in practice (it's an EA core module), but keeping the import local matches
    the rest of the codebase's defensive style and means a stale build that
    somehow ships without `event_testing` can't take the whole package down at
    import.
    """
    try:
        from event_testing.results import TestResult
    except Exception:
        # If TestResult isn't importable we can't return a structured failure.
        # Pass-through is safer than killing the pie menu open.
        return True

    sim = getattr(context, "sim", None)
    if sim is None:
        # Simless or autonomy-without-actor: don't gate (EA pattern).
        return TestResult.TRUE

    sim_info = getattr(sim, "sim_info", None)
    tracker = getattr(sim_info, "career_tracker", None) if sim_info is not None else None
    if tracker is None:
        return TestResult(False, "Sim has no career_tracker.")

    career = tracker.get_career_by_uid(cls._hc_career_uid)
    if career is None:
        return TestResult(False, "Sim is not in the Historian career.")

    if career.current_track_tuning is not cls._hc_required_track:
        return TestResult(False, "Sim is on a different Historian track.")

    if career.user_level < cls._hc_min_user_level:
        return TestResult(
            False,
            "Requires Historian level {} (Sim is at {}).",
            cls._hc_min_user_level,
            career.user_level,
        )

    return TestResult.TRUE


def install_level_gates(affordance_by_name, career_cls, required_track_cls, log=None):
    """Patch `_test` on each HC_Interaction_* tuning class.

    affordance_by_name: dict[str, type] — the 5 HC_Interaction_* tuning
        classes keyed by tuning name. Caller (affordance_injector) already
        resolved these.
    career_cls:         the `career_Adult_Historian` tuning class.
    required_track_cls: the `career_track_Adult_Historian` tuning class.
    log:                optional callable for diagnostic lines; receives a
        single string. Used by the injector's _log helper.

    Returns the number of classes patched. A class missing from
    `affordance_by_name` is skipped silently — the injector already logs
    affordance-resolution failures.
    """
    career_uid = getattr(career_cls, "guid64", None)
    if career_uid is None:
        # Defensive: if guid64 isn't set yet, we'd patch all 5 classes to
        # always fail. Better to do nothing and let the affordance stay
        # ungated than to break it for every Sim including the L5 Prof.
        if log:
            log("install_level_gates: career_cls has no guid64 — skipping.")
        return 0

    installed = 0
    for name, min_level in _LEVEL_REQUIREMENTS.items():
        cls = affordance_by_name.get(name)
        if cls is None:
            continue
        cls._hc_min_user_level = min_level
        cls._hc_required_track = required_track_cls
        cls._hc_career_uid = career_uid
        cls._test = classmethod(_gated_test)
        cls._hc_gate_installed = True
        installed += 1
        if log:
            log(
                "  gated {} -> requires user_level >= {}".format(name, min_level)
            )
    return installed
