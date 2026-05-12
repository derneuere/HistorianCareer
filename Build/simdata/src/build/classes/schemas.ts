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
import { loadTdescFixture, selectColumns, withAdditionalColumns } from "./loadSchema.js";

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

export const CAREER_LEVEL_SCHEMA: TdescSchema = (() => {
  const tdesc = loadTdescFixture("CareerLevel.tdesc.json");
  const base = selectColumns(tdesc, CAREER_LEVEL_BASE_COLUMNS);
  return withAdditionalColumns(base, CAREER_LEVEL_EXTRA_COLUMNS);
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
  // Nested schema for AspirationTrack.aspirations (mapping key→value tuple).
  // EA extracts this from the live game; we can't derive it from a name hash.
  aspirations: 0xfb8c84bc,
});

// ---------------------------------------------------------------------------
// Trait's TDESC schema is exported by Trait.ts itself (it builds it from
// TRAIT_COLUMNS, the 17-column EA-canonical allow-list). The Trait class
// uses a custom builder (`buildTraitSimData`) that handles trait_type
// enum-to-Int64 mapping and the ui_category variant.
// ---------------------------------------------------------------------------

