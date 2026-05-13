// Per-class schemas for the 9 supported tuning classes.
//
// v0.3: schemas come from real EA TDESC fixtures (committed under
// `test/fixtures/tdescs/`) PLUS per-class adjustments derived from the EA
// SimData goldens in `test/golden/`. The TDESC alone is not enough because:
//   1. The current TDESC marks some columns `client_binary` (only) — the
//      persistence rule rejects these (see parseJson.ts isPersisted) so the
//      TDESC-driven schema is already a sane "current game" approximation.
//   2. The EA goldens are from a specific game build; some columns EA persists
//      (e.g. Aspiration.disabled, Aspiration.is_child_aspiration) come from
//      *parent classes* (AspirationBasic) which our per-class TDESC doesn't
//      include. We add them as "extra columns" below.
//   3. Some columns the TDESC marks persisted (full export_modes triple) are
//      NOT in the goldens (e.g. plumbob_vfx on Buff, aspiration_valid_age_type
//      on Aspiration). These are newer additions that didn't exist when the
//      golden was extracted. We drop them via `selectColumns()` when we want
//      byte-equal goldens, OR keep them when we want current-game behavior.
//
// CareerChanceCard has no standalone EA TDESC; we keep a small hand-authored
// schema with title + description + per-response option text fields.
//
// LICENSE DISCIPLINE: every schema is derived from the EA-published TDESC JSON
// in `test/fixtures/tdescs/` (factual data) plus our own inspection of EA
// SimData goldens. No copy-paste from Mod-Constructor-5 or s4py.

import { deepFreeze } from "../../tdesc/types.js";
import type { TdescColumn, TdescSchema, TdescType } from "../../tdesc/types.js";
import { loadTdescFixture, selectColumns, selectNestedColumns, withAdditionalColumns } from "./loadSchema.js";

// ---------------------------------------------------------------------------
// Helpers — concise column constructors used by the small hand-authored schemas
// (CareerChanceCard only at v0.2).
// ---------------------------------------------------------------------------

const col = (name: string, type: TdescType, defaultValue?: unknown): TdescColumn => ({
  name,
  type,
  ...(defaultValue !== undefined ? { defaultValue } : {}),
  persistedToSimData: true,
});

const STRING_KEY: TdescType = { kind: "string-key" };
const REF: TdescType = { kind: "table-set-reference" };
const REF_VEC: TdescType = { kind: "vector", elem: REF };

// ---------------------------------------------------------------------------
// Objective. EA golden has 3 columns; TDESC marks 5 with the full
// export_modes triple. We narrow to the 3-column EA-canonical set:
//   display_text          LocalizationKey
//   satisfaction_points   Int32
//   tooltip               LocalizationKey
// (display_age_list and show_progress are newer-game additions; the EA golden
// at test/golden/Objective/objective_Asp_Family_B4_3.simdata doesn't have
// them.)
// ---------------------------------------------------------------------------
const OBJECTIVE_EA_COLUMNS = [
  "display_text",
  "satisfaction_points",
  "tooltip",
] as const;

export const OBJECTIVE_SCHEMA: TdescSchema = selectColumns(
  loadTdescFixture("Objective.tdesc.json"),
  OBJECTIVE_EA_COLUMNS,
);

// ---------------------------------------------------------------------------
// Aspiration. EA golden has 5 columns:
//   descriptive_text       LocalizationKey
//   disabled               Boolean    (inherited from AspirationBasic — NOT in our TDESC fixture)
//   display_name           LocalizationKey
//   is_child_aspiration    Boolean    (in TDESC but with no `export_modes` — still persisted)
//   objectives             Vector<TableSetReference>
//
// TDESC marks `aspiration_valid_age_type` as fully persisted (full
// export_modes triple), but the EA golden doesn't have it — it's a newer-game
// addition. We exclude via selectColumns and add `disabled` as an extra.
// ---------------------------------------------------------------------------
const ASPIRATION_BASE_COLUMNS = [
  "descriptive_text",
  "display_name",
  "is_child_aspiration",
  "objectives",
] as const;

const ASPIRATION_EXTRA_COLUMNS: readonly TdescColumn[] = Object.freeze([
  {
    name: "disabled",
    type: { kind: "bool" },
    defaultValue: false,
    persistedToSimData: true,
  },
  // is_child_aspiration is in the TDESC but lacks export_modes; we have to
  // surface it explicitly. selectColumns below will pull it out of the TDESC
  // (it was preserved with persistedToSimData=false; we override below).
]);

export const ASPIRATION_SCHEMA: TdescSchema = (() => {
  // is_child_aspiration is in the TDESC but lacks the full export_modes; the
  // parser marked it persistedToSimData=false. To bring it into the schema,
  // we use withAdditionalColumns to override it (the later entry wins).
  const tdesc = loadTdescFixture("Aspiration.tdesc.json");
  // Note: selectColumns requires the named columns to exist; if
  // `is_child_aspiration` is present in the TDESC but marked
  // persistedToSimData=false, selectColumns still finds it by name and re-
  // marks it as persisted. So this works.
  const base = selectColumns(tdesc, ASPIRATION_BASE_COLUMNS);
  return withAdditionalColumns(base, ASPIRATION_EXTRA_COLUMNS);
})();

// ---------------------------------------------------------------------------
// AspirationCareer. EA golden has 2 columns:
//   disabled    Boolean   (inherited from AspirationBasic; not in our TDESC fixture)
//   objectives  Vector<TableSetReference>
//
// TDESC only marks `objectives` as having the full export_modes triple. We
// add `disabled` as an extra column.
// ---------------------------------------------------------------------------
const ASPIRATION_CAREER_BASE_COLUMNS = ["objectives"] as const;

const ASPIRATION_CAREER_EXTRA_COLUMNS: readonly TdescColumn[] = Object.freeze([
  {
    name: "disabled",
    type: { kind: "bool" },
    defaultValue: false,
    persistedToSimData: true,
  },
]);

export const ASPIRATION_CAREER_SCHEMA: TdescSchema = (() => {
  const tdesc = loadTdescFixture("AspirationCareer.tdesc.json");
  const base = selectColumns(tdesc, ASPIRATION_CAREER_BASE_COLUMNS);
  return withAdditionalColumns(base, ASPIRATION_CAREER_EXTRA_COLUMNS);
})();

// ---------------------------------------------------------------------------
// AspirationTrack. EA golden has 9 columns. TDESC marks 11 with full
// export_modes (adds `is_hidden_unlockable` and `override_traits` which the
// golden doesn't have — newer-game additions).
// ---------------------------------------------------------------------------
const ASPIRATION_TRACK_EA_COLUMNS = [
  "aspirations",
  "category",
  "description_text",
  "display_text",
  "icon",
  "icon_high_res",
  "mood_asm_param",
  "primary_trait",
  "reward",
] as const;

export const ASPIRATION_TRACK_SCHEMA: TdescSchema = selectColumns(
  loadTdescFixture("AspirationTrack.tdesc.json"),
  ASPIRATION_TRACK_EA_COLUMNS,
);

// ---------------------------------------------------------------------------
// CareerChanceCard. EA does NOT have a standalone TDESC for this class —
// chance cards are tuning-XML-only with custom shape. We keep a hand-authored
// minimal schema that matches the HistorianCareer chance card XML.
//
// v0.1 had just title+description. v0.2 expands to include per-response
// option display text (the FINAL_REPORT "What doesn't" gap).
// ---------------------------------------------------------------------------
const CHANCE_CARD_OPTION: TdescType = {
  kind: "object",
  schemaName: "CareerChanceCardOption",
  columns: [
    col("display_text", STRING_KEY),
    col("outcome_loot", REF_VEC),
  ],
};

export const CAREER_CHANCE_CARD_SCHEMA: TdescSchema = deepFreeze<TdescSchema>({
  className: "CareerChanceCard",
  classPath: "careers.career_event_zone_director.CareerChanceCard",
  rootColumns: [
    col("title", STRING_KEY),
    col("description", STRING_KEY),
    col("response_option_a", CHANCE_CARD_OPTION),
    col("response_option_b", CHANCE_CARD_OPTION),
  ],
});

// ---------------------------------------------------------------------------
// CareerLevel. EA golden has 7 columns:
//   aspiration            TableSetReference
//   ideal_mood            TableSetReference   (TDESC only marks `client_binary`; golden persists it)
//   performance_stat      TableSetReference
//   simoleons_per_hour    Int32               (NOT in current TDESC — replaced by `pay_type` variant)
//   title                 LocalizationKey
//   title_description     LocalizationKey
//   work_schedule         Object<TunableWeeklySchedule>
//
// The current TDESC marks `agents_available`, `pay_type`, `pto_per_day`
// persisted but the golden doesn't have them — newer-game additions.
//
// Nested-schema curation (fix #16): EA's binary persists a SMALLER set of
// columns in `TunableScheduleEntry` than the current TDESC declares. The
// TDESC has 7 fields per schedule entry; EA's runtime expects only 4
// (`days_available, duration, random_start, start_time`). When the extra
// fields are present in our binary the parser reads bytes at the wrong
// offsets, currentCareerLevel returns null, and Olympus crashes. Drop:
//   - `multi_day_career_days_at_work`  OptionalTunable<TunableAvailableDays>
//   - `multi_day_career_start_and_end_days`  OptionalTunable<{start_day,end_day}>
//   - `schedule_shift_type`  TunableEnumEntry<CareerShiftType>
// Dropping `multi_day_career_start_and_end_days` also removes the only
// reference to the anonymous "enabled" tuple schema, so that schema falls out
// of `ctx.schemaCache.values()` and isn't emitted.
// ---------------------------------------------------------------------------
const CAREER_LEVEL_BASE_COLUMNS = [
  "aspiration",
  "performance_stat",
  "title",
  "title_description",
  "work_schedule",
] as const;

const CAREER_LEVEL_EXTRA_COLUMNS: readonly TdescColumn[] = Object.freeze([
  // ideal_mood is in the TDESC but with only `client_binary` export_modes —
  // EA's golden persists it, so we re-include it as an explicit extra.
  {
    name: "ideal_mood",
    type: { kind: "table-set-reference" },
    persistedToSimData: true,
  },
  // simoleons_per_hour was replaced by `pay_type` in the current TDESC but is
  // still in many older-version EA goldens (and our HC career-level tunings
  // emit it for compatibility).
  {
    name: "simoleons_per_hour",
    type: { kind: "int32" },
    defaultValue: 0,
    persistedToSimData: true,
  },
]);

// EA's TunableScheduleEntry has exactly these 4 columns, in this alphabetical
// order (EA sorts schema columns by name when emitting). Confirmed by
// extracting career_SecretAgent_Villain_Level3 in the live game.
const TUNABLE_SCHEDULE_ENTRY_EA_COLUMNS = [
  "days_available",
  "duration",
  "random_start",
  "start_time",
] as const;

export const CAREER_LEVEL_SCHEMA: TdescSchema = (() => {
  const tdesc = loadTdescFixture("CareerLevel.tdesc.json");
  const base = selectColumns(tdesc, CAREER_LEVEL_BASE_COLUMNS);
  const withExtras = withAdditionalColumns(base, CAREER_LEVEL_EXTRA_COLUMNS);
  // Curate the nested TunableScheduleEntry to match EA's actual binary.
  return selectNestedColumns(
    withExtras,
    "TunableScheduleEntry",
    TUNABLE_SCHEDULE_ENTRY_EA_COLUMNS,
  );
})();

// ---------------------------------------------------------------------------
// CareerTrack. EA golden has 8 columns; TDESC marks 10 with full export_modes
// (adds `career_name_gender_neutral` and `show_now_hiring_string` — newer-game
// additions).
//
// The TDESC's `:@.class` is "TunableCareerTrack" — and crucially EA's binary
// also names the schema "TunableCareerTrack", not "CareerTrack". So we DO
// keep the TDESC name. The tuning XML uses BOTH c="CareerTrack" (older HC
// convention) and c="TunableCareerTrack" (EA's convention in their goldens)
// — we register the schema under both names in classes/index.ts so either
// tuning XML form works.
// ---------------------------------------------------------------------------
const CAREER_TRACK_EA_COLUMNS = [
  "branches",
  "busy_time_situation_picker_tooltip",
  "career_description",
  "career_levels",
  "career_name",
  "icon",
  "icon_high_res",
  "image",
] as const;

export const CAREER_TRACK_SCHEMA: TdescSchema = selectColumns(
  loadTdescFixture("CareerTrack.tdesc.json"),
  CAREER_TRACK_EA_COLUMNS,
);

// ---------------------------------------------------------------------------
// Career. EA golden has only 2 columns:
//   career_category   Int64 enum
//   start_track       TableSetReference
//
// TDESC has many more columns marked with the full export_modes triple
// (career_panel_type, reputation_stat, show_ideal_mood, etc) — those are
// newer-game additions not in our golden. The fact that the EA golden only
// emits 2 fields demonstrates that EA's persistence rule is even tighter than
// "full export_modes triple" for Career — but for HC's purposes, matching
// the 2-column golden is the goal.
// ---------------------------------------------------------------------------
const CAREER_EA_COLUMNS = ["career_category", "start_track"] as const;

export const CAREER_SCHEMA: TdescSchema = selectColumns(
  loadTdescFixture("Career.tdesc.json"),
  CAREER_EA_COLUMNS,
);

// ---------------------------------------------------------------------------
// Buff. EA golden has 10 columns:
//   audio_sting_on_add, audio_sting_on_remove, buff_description, buff_name,
//   icon, icon_highlight, mood_type, mood_weight, timeout_string,
//   ui_sort_order
//
// The current TDESC is missing `icon_highlight` entirely — it was added in a
// game version after the TDESC we fetched. We supply it as an extra column.
// The current TDESC also marks `timeout_string_no_next_buff` and `plumbob_vfx`
// as persisted; the EA golden has neither.
// ---------------------------------------------------------------------------
const BUFF_BASE_COLUMNS = [
  "audio_sting_on_add",
  "audio_sting_on_remove",
  "buff_description",
  "buff_name",
  "icon",
  "mood_type",
  "mood_weight",
  "timeout_string",
  "ui_sort_order",
] as const;

const BUFF_EXTRA_COLUMNS: readonly TdescColumn[] = Object.freeze([
  // icon_highlight is the highlighted-state icon (e.g. for hover); not in our
  // TDESC fixture but present in the EA golden.
  {
    name: "icon_highlight",
    type: { kind: "resource-key" },
    persistedToSimData: true,
  },
]);

export const BUFF_SCHEMA: TdescSchema = (() => {
  const tdesc = loadTdescFixture("Buff.tdesc.json");
  const base = selectColumns(tdesc, BUFF_BASE_COLUMNS);
  return withAdditionalColumns(base, BUFF_EXTRA_COLUMNS);
})();

// ---------------------------------------------------------------------------
// PieMenuCategory. Hand-authored (no TDESC fixture for this class) — the
// Olympus UI registers PieMenuCategory entries by enumerating SimData
// resources at boot; without the companion SimData our custom category fails
// to register and the right-click pie menu silently aborts with
//   "Failed to locate category info for interaction category with key: …".
// See Docs/NOTE_pie_menu_category_registration.md for the full diagnosis.
//
// Schema is extracted from EA's `computer_Handiness.simdata` (and verified
// against `computer_Programming`, `cheat_emotionintensity`, `computer_PlayGame`).
// Hash 0x022065c1 — the runtime won't recognize the row without this exact
// value, which can't be derived from the schema name alone (registered in
// KNOWN_SCHEMA_HASHES below).
//
// The nested schemas (`mood_to_override_data`, `text_overrides`) are only
// emitted if `mood_overrides` is non-empty; our HC tuning leaves the vector
// empty, but the schemas must still be declared so the schema-cache produces
// the right structure for any future use.
// ---------------------------------------------------------------------------
const PMC_TEXT_OVERRIDES: TdescType = {
  kind: "object",
  schemaName: "text_overrides",
  columns: [
    col("name_override", STRING_KEY),
    col("tooltip", STRING_KEY),
  ],
};

const PMC_MOOD_OVERRIDE_ROW: TdescType = {
  kind: "object",
  schemaName: "mood_to_override_data",
  columns: [
    col("mood", REF),
    col("override_data", PMC_TEXT_OVERRIDES),
  ],
};

export const PIE_MENU_CATEGORY_SCHEMA: TdescSchema = deepFreeze<TdescSchema>({
  className: "PieMenuCategory",
  classPath: "interactions.pie_menu_category.PieMenuCategory",
  rootColumns: [
    col("_collapsible",      { kind: "bool" },                                true),
    col("_display_name",     STRING_KEY,                                      0),
    col("_display_priority", { kind: "int32" },                               1),
    col("_icon",             { kind: "resource-key" }),
    col("_parent",           REF),
    // SpecialPieMenuCategoryType.NO_CATEGORY = 0. Stored as UInt32 (matches
    // EA's binary layout — verified in computer_Handiness.simdata).
    col("_special_category", { kind: "uint32" },                              0),
    col("mood_overrides",    { kind: "vector", elem: PMC_MOOD_OVERRIDE_ROW }, []),
  ],
});

// ---------------------------------------------------------------------------
// Statistic. Hand-authored (no TDESC fixture for this class).
//
// CRITICAL: this companion SimData is REQUIRED for any Statistic that drives
// the Career Performance bar. Without it, the C++ runtime constructs the
// in-game `PerformanceStaticData` (referenced from `CareerLevel.performance`
// in AS3) with min_value=0 and max_value=0, and the Olympus Career Panel
// throws:
//
//   Error: ProgressBar: Maximum cannot be equal to minimum
//       at olympus.gui.progressbars::ProgressBar/SetRange()
//       at widgets.Gameplay.SimInfoHUD.CareerPanel::PerformanceDetails/Draw()
//
// when the user expands the career panel.  The Olympus `PerformanceDetails`
// AS3 builds the range from `currentCareerLevel.performance.min_value /
// .max_value` (PerformanceDetails.as:93), and the engine populates those
// fields by following each CareerLevel SimData's `performance_stat`
// TableSetReference → Statistic SimData row → `min_value_tuning` /
// `max_value_tuning` columns. No Statistic SimData → no usable range.
//
// EA's runtime emits a 3-column row per Statistic — verified by extracting
// `statistic_Career_Performance_Writer` (instance 0x6c88) from EA's
// SimulationFullBuild0.package:
//
//   schema: Statistic (hash 0x8273c673)
//     max_value_tuning   Int32           = +100
//     min_value_tuning   Int32           = -100
//     stat_name          LocalizationKey = 0
//
// Hand-extracted from a real EA SimData. Columns are alphabetically ordered
// (SimData convention). Schema hash is registered in KNOWN_SCHEMA_HASHES.
// ---------------------------------------------------------------------------
export const STATISTIC_SCHEMA: TdescSchema = deepFreeze<TdescSchema>({
  className: "Statistic",
  classPath: "statistics.statistic.Statistic",
  rootColumns: [
    // The runtime reads these as `cls.min_value_tuning` / `cls.max_value_tuning`
    // (see simulation/statistics/statistic.pyc: Statistic.min_value /
    // Statistic.max_value). EA's Career-performance stats use -100..+100.
    // Defaults below mirror EA's `statistic_Career_Performance` (instance
    // 0x4116), which only declares `min_value_tuning` in tuning and lets
    // `max_value_tuning` fall back to its TDESC default of 100.
    col("max_value_tuning", { kind: "int32" }, 100),
    col("min_value_tuning", { kind: "int32" }, -100),
    // EA's binary stores `stat_name` even when the tuning XML omits it — the
    // default is the empty-string LocalizationKey (0).
    col("stat_name",        STRING_KEY,        0),
  ],
});

// ---------------------------------------------------------------------------
// EA-canonical schema hashes. These are EA-internal layout checksums; we can't
// regenerate them from TDESCs (see docs/tdesc-format.md). Extracted from the
// real EA SimData goldens in `test/golden/` (1.124.55 game build).
// ---------------------------------------------------------------------------
export const KNOWN_SCHEMA_HASHES: Readonly<Record<string, number>> = Object.freeze({
  Trait: 0x992bfa76,
  Buff: 0x83a7824a,
  Career: 0x7a1fe1e2,
  // The CareerTrack schema is emitted with name "TunableCareerTrack" (EA's
  // binary convention) — the schema-cache key is the className, so the hash
  // is looked up by the class string.
  TunableCareerTrack: 0x9a6e55e8,
  CareerLevel: 0x82d9b9a3,
  Aspiration: 0x72abca6f,
  AspirationCareer: 0x4e53725b,
  AspirationTrack: 0x54fdb5fc,
  Objective: 0xd5cfeba5,
  // PieMenuCategory + nested schemas. The Olympus UI uses these exact hashes
  // to identify the row at boot — without 0x022065c1 the row is silently
  // ignored. Extracted from EA's computer_Handiness/computer_Programming
  // SimData. See Docs/NOTE_pie_menu_category_registration.md.
  PieMenuCategory: 0x022065c1,
  mood_to_override_data: 0xeac32ff0,
  text_overrides: 0x9c77ff5d,
  // Statistic schema hash — required for the C++ engine to recognize the
  // SimData row as a Statistic and populate `PerformanceStaticData.min_value
  // / .max_value` for the Career Panel ProgressBar. Extracted from EA's
  // `statistic_Career_Performance_Writer` (instance 0x6c88). Without this
  // exact hash, the row is silently dropped and the panel crashes with
  // "Error: ProgressBar: Maximum cannot be equal to minimum".
  Statistic: 0x8273c673,
  // Nested schema for AspirationTrack.aspirations (mapping key→value tuple).
  // EA extracts this from the live game; we can't derive it from a name hash.
  aspirations: 0xfb8c84bc,
  // CareerLevel.work_schedule nested schemas. EA's schema hashes for these
  // appear to be derived from the schema's binary layout (column names+types
  // hashed together) rather than just FNV32(name) — empirically the simple
  // name hash does NOT reproduce them. Extracted from the live game's
  // career_SecretAgent_Villain_Level3 SimData golden. Without these, the
  // CareerInfo runtime parser computes wrong byte offsets and
  // currentCareerLevel returns null (issue #16 / Olympus crash).
  TunableWeeklySchedule: 0xc897ddb0,
  TunableScheduleEntry: 0x6b21f952,
  TunableAvailableDays: 0x5bcfcd54,
  TunableTimeOfDay: 0x1bd2886e,
});

// ---------------------------------------------------------------------------
// Trait's TDESC schema is exported by Trait.ts itself (it builds it from
// TRAIT_COLUMNS, the 17-column EA-canonical allow-list). The Trait class
// uses a custom builder (`buildTraitSimData`) that handles trait_type
// enum-to-Int64 mapping and the ui_category variant.
// ---------------------------------------------------------------------------

