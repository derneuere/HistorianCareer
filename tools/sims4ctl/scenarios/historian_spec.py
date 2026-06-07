#!/usr/bin/env python3
"""historian_spec.py -- the LAW for the ten-rank Historian career, in one place.

This module is the single source of truth that BOTH the offline tuning verifier
(`historian_offline_check.py`, which parses the mod's XML/Python with no game
running) AND the live in-game scenario (`historian_career.py`, which drives a
running Sims 4 through the sims4ctl bridge) assert against. Keeping the numbers
here -- not duplicated in each checker -- means the two can never silently drift,
and a future tuning change only has to be reflected in one place.

Every constant below is cross-checked against the shipped tuning by
`historian_offline_check.py`; see each field's comment for its source file.

Pure data + pure functions: stdlib only, NO game imports, NO host-package
imports. Importable from anywhere (Python 3.7+ for parity with the bridge).
"""

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

CAREER_NAME = "career_Adult_Historian"          # Tuning/career_Adult_Historian.xml
TRACK_NAME = "career_track_Adult_Historian"     # Tuning/career_track_Adult_Historian.xml

# The HiWi fast-track is now a SEPARATE find-a-job entry (its own Career + Track)
# instead of an in-place start-level modifier on the regular career.
HIWI_CAREER_NAME = "career_Adult_Historian_HiWi"        # Tuning/career_Adult_Historian_HiWi.xml
HIWI_TRACK_NAME = "career_track_Adult_Historian_HiWi"   # Tuning/career_track_Adult_Historian_HiWi.xml

# ---------------------------------------------------------------------------
# Pay schedule + titles (1-indexed by user_level).
# Source: Tuning/career_level_Adult_Historian_L{1..10}.xml (simoleons_per_hour)
#         Scripts/historian_career/historian_career.py TIERS (English titles).
# NOTE: the schedule is intentionally NOT monotonic -- L2=22 (part-time, long
# hours) dips to L3=18 (intern) before climbing. We assert the exact schedule.
# ---------------------------------------------------------------------------

PAY = {
    1: 14, 2: 22, 3: 18, 4: 30, 5: 40,
    6: 60, 7: 90, 8: 140, 9: 220, 10: 340,
}

TITLES = {
    1: "Hobby Historian",
    2: "Museum Attendant",
    3: "Intern",
    4: "Trainee",
    5: "Research Assistant (HiWi)",
    6: "PhD Candidate",
    7: "Postdoctoral Researcher",
    8: "Junior Professor",
    9: "Full Professor",
    10: "Institute Director",
}

MAX_LEVEL = 10

# ---------------------------------------------------------------------------
# Discover University fast-track.
# Source: Tuning/career_Adult_Historian_HiWi.xml (a SEPARATE find-a-job entry).
# The HiWi entry is degree-gated via career_availablity_tests on the hidden
# History-degree trait (230331 = trait_University_DegreeTraits_History) and
# carries an UNCONDITIONAL start_level_modifiers +4 on the base start level of 1,
# so a degree holder who joins it starts at L5 (HiWi). The regular career_Adult_
# Historian entry now always starts at L1 (its old in-place +4 modifier was
# removed so degree holders aren't shown two entries that both jump to L5).
# ---------------------------------------------------------------------------

FAST_TRACK_TRAIT_ID = 230331
FAST_TRACK_MODIFIER = 4
BASE_START_LEVEL = 1
FAST_TRACK_START_LEVEL = BASE_START_LEVEL + FAST_TRACK_MODIFIER  # == 5

# ---------------------------------------------------------------------------
# Skill gates (block_promotion_tests).
# Source: Tuning/career_Adult_Historian.xml <L n="block_promotion_tests">.
#
# The EA mechanic BLOCKS a promotion when any test-group PASSES; a group that
# requires "skill >= N at the FROM level" is encoded as a career_level test for
# the FROM level AND a skill test that passes only while skill <= N-1
# (`max_value` = N-1). A multi-skill AND requirement is encoded as TWO groups
# (one per skill) for the same FROM level, since being below EITHER skill blocks.
#
# Skill statistic GUIDs (EA, University majors):
#   Writing = 16714, Charisma = 16699, Research & Debate = 221014.
# ---------------------------------------------------------------------------

SKILL_IDS = {
    "writing": 16714,
    "charisma": 16699,
    "research_debate": 221014,
}

# from_level -> {skill_key: minimum_required_level}. A promotion FROM `from_level`
# to `from_level + 1` is blocked until EVERY listed skill reaches its minimum.
SKILL_GATES = {
    1: {"writing": 2, "charisma": 1},               # L1->L2
    6: {"research_debate": 7},                       # L6->L7
    7: {"writing": 7},                               # L7->L8
    8: {"research_debate": 10, "writing": 10},       # L8->L9 (Habilitation)
    9: {"charisma": 5},                              # L9->L10
}

# Transitions that are PERFORMANCE-only (no skill gate). L10 has no outgoing
# transition. Used by the offline checker to assert these have NO gate groups.
UNGATED_FROM_LEVELS = (2, 3, 4, 5)


def gated_from_levels():
    """The FROM levels that carry a skill gate (sorted)."""
    return tuple(sorted(SKILL_GATES))


def skill_max_value_for_block(min_required):
    """The highest skill level that still BLOCKS, given a required minimum.

    The EA skill_test's `skill_range` upper_bound is `min_required - 1` (it
    passes -> blocks while skill <= upper_bound). This is also the value the live
    scenario sets a skill to in order to sit just *below* the gate threshold.
    """
    return min_required - 1


# ---------------------------------------------------------------------------
# Affordances + social overlays, with their per-rank level BANDS (inclusive).
# Source: Scripts/historian_career/level_gate.py _LEVEL_REQUIREMENTS and
#         Scripts/historian_career/affordance_injector.py surface groups.
#
# kind:    "existing" (5 pre-existing, re-banded), "new" (8 new affordances),
#          or "overlay" (2 career-wide social overlays).
# surface: where the affordance is injected ("computer"/"bookshelf"/"social").
# Issue #32 wording: "8 new affordances + 2 social overlays" (+ 5 existing).
# ---------------------------------------------------------------------------

# (name, (min_level, max_level), surface, kind)
AFFORDANCES = (
    # --- 5 existing computer affordances, re-banded -----------------------
    ("HC_Interaction_TranscribeManuscript",  (4, 6),  "computer", "existing"),
    ("HC_Interaction_AnalyzePrimarySource",  (5, 7),  "computer", "existing"),
    ("HC_Interaction_PresentAtSymposium",    (7, 8),  "computer", "existing"),
    ("HC_Interaction_HabilitationLecture",   (8, 9),  "computer", "existing"),
    ("HC_Interaction_SuperviseDissertation", (9, 10), "computer", "existing"),
    # --- 4 new computer affordances ---------------------------------------
    ("HC_Interaction_Blogeintrag",           (1, 2),  "computer", "new"),
    ("HC_Interaction_Bildrechte",            (4, 4),  "computer", "new"),
    ("HC_Interaction_OnlineFortbildung",     (4, 4),  "computer", "new"),
    ("HC_Interaction_Drittmittel",           (10, 10), "computer", "new"),
    # --- 3 new bookshelf affordances --------------------------------------
    ("HC_Interaction_Objektgeschichte",      (2, 2),  "bookshelf", "new"),
    ("HC_Interaction_BuecherregalRecherche", (3, 9),  "bookshelf", "new"),
    ("HC_Interaction_CrossReference",        (3, 4),  "bookshelf", "new"),
    # --- 1 new social affordance + 2 social overlays ----------------------
    ("HC_Interaction_Zeitzeugen",            (4, 8),  "social", "new"),
    ("HC_Interaction_DropHistoryFact",       (1, 10), "social", "overlay"),
    ("HC_Interaction_HistoricalJoke",        (1, 10), "social", "overlay"),
)

# name -> (min, max), the shape level_gate.py stores.
AFFORDANCE_BANDS = {name: band for (name, band, _surface, _kind) in AFFORDANCES}

NEW_AFFORDANCE_COUNT = 8       # issue #32: "8 new affordances"
OVERLAY_COUNT = 2              # issue #32: "2 social overlays"
EXISTING_AFFORDANCE_COUNT = 5  # the 5 pre-existing computer affordances


def affordances_by_kind(kind):
    return tuple(name for (name, _b, _s, k) in AFFORDANCES if k == kind)


def affordances_by_surface(surface):
    return tuple(name for (name, _b, s, _k) in AFFORDANCES if s == surface)


def affordance_offered_at(name, level):
    """True iff affordance `name` should appear in the pie menu at career `level`.

    Mirrors level_gate._gated_test: offered iff min <= level <= max. Raises
    KeyError for an unknown affordance name (callers know the set)."""
    lo, hi = AFFORDANCE_BANDS[name]
    return lo <= level <= hi


def affordances_offered_at(level):
    """The set of affordance names that should be offered at career `level`."""
    return frozenset(n for n in AFFORDANCE_BANDS if affordance_offered_at(n, level))


# ---------------------------------------------------------------------------
# "Historian's Calling" aspiration track.
# Source: Tuning/aspiration_track_HistorianCalling.xml,
#         Tuning/trait_HabilitationRenown.xml.
# ---------------------------------------------------------------------------

ASPIRATION_TRACK_NAME = "aspiration_track_HistorianCalling"
ASPIRATION_TRACK_ID = 40651            # 0x9ECB
ASPIRATION_PRIMARY_TRAIT_ID = 27086    # EA Knowledge primary trait (stand-in)
ASPIRATION_REWARD_ID = 27489           # EA Renaissance-Sim reward chain (stand-in)

ASPIRATION_TIERS = (
    "aspiration_HistorianCalling_T1",
    "aspiration_HistorianCalling_T2",
    "aspiration_HistorianCalling_T3",
    "aspiration_HistorianCalling_T4",
)

# Reward trait granted while the track is the Sim's primary aspiration
# (provided_traits on the track), also the L5/W3 award trait.
REWARD_TRAIT_NAME = "trait_HabilitationRenown"
REWARD_TRAIT_TYPE = "GAMEPLAY"
REWARD_TRAIT_LOOT = "loot.buff_Focused_Low"

# ---------------------------------------------------------------------------
# Work-From-Home + daily-task rotation.
# Source: Tuning/career_Adult_Historian.xml career_messages
#         (career_early_warning_alarm = the `enabled` variant with a
#         work_from_home_text -> WFH is offered), and
#         Scripts/historian_career/daily_task_rotation.py (_FALLBACK_POOLS).
# WFH is ENABLED iff career_early_warning_alarm tunes the `enabled` variant AND
# carries a work_from_home_text field.
# ---------------------------------------------------------------------------

WFH_ENABLED = True
WFH_EARLY_WARNING_VARIANT = "enabled"
WFH_TEXT_FIELD = "work_from_home_text"

# The career object stashes the chosen daily task here for any UI hook; the live
# scenario reads these to confirm rotation ran. See daily_task_rotation.py.
DAILY_TASK_STASH_NAME_ATTR = "_hc_daily_task_name"
DAILY_TASK_STASH_DAY_ATTR = "_hc_daily_task_day"

# All 10 ranks must have a non-empty daily-task pool.
DAILY_TASK_POOL_LEVELS = tuple(range(1, 11))
