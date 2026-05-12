# historian_career.py — minimal script-side helpers for the Historian Career (Layer A).
#
# Mirrors the structure of the upstream reference (UXMod-Sims4, MIT, Rea Havari):
# notification on level-up, fired from a tracker that watches the custom statistic.
# Five tiers, modelled on the German academic Karriereleiter.

try:
    import sims4
    import services
    from sims4.localization import LocalizationHelperTuning
except Exception:
    sims4 = None
    services = None

MOD_NAME = "HistorianCareer"

# Maps statistic value -> (English title, German title)
TIERS = {
    1: ("Research Assistant",        "Wissenschaftliche Hilfskraft"),
    2: ("PhD Candidate",             "Doktorand:in"),
    3: ("Postdoctoral Researcher",   "Postdoktorand:in"),
    4: ("Junior Professor",          "Juniorprofessor:in"),
    5: ("Full Professor (W3)",       "Professor:in (W3)"),
}


def log(msg):
    try:
        print(f"[{MOD_NAME}] {msg}")
    except Exception:
        pass


def show_basic_notification(title, text):
    """Pop a simple in-game notification. Safe to call when services aren't ready (returns silently)."""
    if services is None:
        return
    try:
        from ui.ui_dialog_notification import UiDialogNotification
        client = services.client_manager().get_first_client()
        if client is None:
            return
        title_loc = LocalizationHelperTuning.get_raw_text(title)
        text_loc = LocalizationHelperTuning.get_raw_text(text)
        dialog = UiDialogNotification.TunableFactory().default(
            client.active_sim, text=text_loc, title=title_loc,
        )
        dialog.show_dialog()
    except Exception as e:
        log(f"Notification error: {e}")


def check_and_notify_promotion(sim_info, current_level):
    """Called when the Historian level statistic changes. Fires a notification on tier-up."""
    if services is None or sim_info is None:
        return
    try:
        tier = TIERS.get(int(current_level))
        if tier is None:
            return
        en, de = tier
        show_basic_notification(
            "Beförderung! / Promotion!",
            f"Sie sind jetzt: {de}\nYou have been promoted to: {en}.",
        )
    except Exception as e:
        log(f"Promotion check error: {e}")


# --- Optional: enforce the History-major prerequisite from Python as a safety net. -----------
# If the trait_test in HC_Interaction_TranscribeManuscript.xml doesn't resolve cleanly in S4S
# (the trait name there is a placeholder), this function can be wired into the interaction's
# `additional_tests` via a snippet at build time.

HISTORY_DEGREE_TRAIT_NAMES = (
    # Try these in order; the first match in the Sim's trait_tracker wins.
    "trait_University_Major_History_Completed",
    "trait_University_Major_History",
    "trait_University_Graduated_History",
)


def sim_has_history_degree(sim_info):
    if sim_info is None or services is None:
        return False
    try:
        trait_manager = services.trait_manager()
        if trait_manager is None:
            return False
        for name in HISTORY_DEGREE_TRAIT_NAMES:
            trait = trait_manager.get(name)
            if trait is not None and sim_info.has_trait(trait):
                return True
        return False
    except Exception as e:
        log(f"Degree check error: {e}")
        return False
