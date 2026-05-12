// Per-class schemas for the 9 supported tuning classes.
//
// v0.2: schemas are parsed from real EA TDESC fixtures committed under
// `test/fixtures/tdescs/`. File I/O happens once at module load — pure-function
// discipline is preserved for downstream consumers (the resulting frozen
// schemas are pure data).
//
// Some classes need supplemental hand-authored knowledge:
//   - Buff: the s4tk EA fixture is from an older game version with 10 columns;
//     the current TDESC marks ~12 columns persisted. We intersect with the
//     10-column allow-list to keep byte-match against the EA fixture.
//   - Trait: same story (17 EA columns vs more in the current TDESC); see
//     `Trait.ts` which uses the TRAIT_TDESC_SCHEMA exported here together with
//     a custom builder that maps trait_type to Int64 + supplies defaults.
//   - CareerChanceCard: no standalone EA TDESC; we keep a small hand-authored
//     schema with title + description + per-response option text fields.
//
// LICENSE DISCIPLINE: every schema is derived from the EA-published TDESC JSON
// in `test/fixtures/tdescs/` (factual data) plus our own EA binary inspection
// of `@s4tk/models`'s MIT test fixtures. No copy-paste from Mod-Constructor-5
// or s4py.

import { deepFreeze } from "../../tdesc/types.js";
import type { TdescColumn, TdescSchema, TdescType } from "../../tdesc/types.js";
import { loadTdescFixture, selectColumns, withClassName } from "./loadSchema.js";

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
// Objective. Five columns per the real EA TDESC. Notably v0.1's `goal_value`
// and `icon` are NOT in EA's current Objective schema — they're tuning-only.
//   display_age_list      OptionalTunable wrapping a DisplayAgeListOptionalTunable tuple
//   display_text          LocalizationKey
//   satisfaction_points   Int32
//   show_progress         Boolean (default True)
//   tooltip               LocalizationKey
// ---------------------------------------------------------------------------
export const OBJECTIVE_SCHEMA: TdescSchema = loadTdescFixture("Objective.tdesc.json");

// ---------------------------------------------------------------------------
// Aspiration. TDESC says 4 persisted columns:
//   aspiration_valid_age_type   Int64 enum
//   descriptive_text            LocalizationKey
//   display_name                LocalizationKey
//   objectives                  Vector<TableSetReference>
// ---------------------------------------------------------------------------
export const ASPIRATION_SCHEMA: TdescSchema = loadTdescFixture("Aspiration.tdesc.json");

// ---------------------------------------------------------------------------
// AspirationCareer. TDESC says ONLY `objectives` is persisted — display
// fields live under the inherited `_display_data` OptionalTunable which is
// only marked `client_binary` if the field's `display_data` slot has explicit
// export modes (it doesn't on AspirationCareer).
//
// In practice the HistorianCareer tuning XML still sets `display_name` and
// `display_description` at the top level — those are read by the game's
// Python from XML, not from SimData. So we lose them from SimData but the
// game's Python reads them anyway.
// ---------------------------------------------------------------------------
export const ASPIRATION_CAREER_SCHEMA: TdescSchema = loadTdescFixture(
  "AspirationCareer.tdesc.json",
);

// ---------------------------------------------------------------------------
// AspirationTrack. TDESC says 12 persisted columns (a major expansion vs.
// v0.1's 5-column hand-authored schema). Key columns: aspirations
// (TunableMapping), category (TunableReference), description_text,
// display_text, icon, icon_high_res, is_hidden_unlockable, mood_asm_param,
// override_traits, primary_trait, provided_traits, reward.
// ---------------------------------------------------------------------------
export const ASPIRATION_TRACK_SCHEMA: TdescSchema = loadTdescFixture(
  "AspirationTrack.tdesc.json",
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
// CareerLevel. TDESC says 11 persisted columns:
//   agents_available, aspiration, end_of_day_loot, ideal_mood, pay_type
//   (TunableVariant), performance_stat, pto_per_day, super_affordances,
//   title, title_description, work_schedule.
//
// Note: v0.1's `level_title`, `level_description`, `schedule`,
// `level_aspiration`, `simoleons_per_hour`, `gameplay_unlocks` are NOT the
// EA names — the real names are `title`, `title_description`, `work_schedule`,
// `aspiration`, (pay is now inside `pay_type` variant), and v0.1's
// `gameplay_unlocks` does not exist in current EA TDESC. HistorianCareer's
// CareerLevel tunings will need to use the new names; the simdata library
// just produces what the TDESC says.
// ---------------------------------------------------------------------------
export const CAREER_LEVEL_SCHEMA: TdescSchema = loadTdescFixture("CareerLevel.tdesc.json");

// ---------------------------------------------------------------------------
// CareerTrack. TDESC's `:@.class` is "TunableCareerTrack" (the EA naming
// convention); tuning XML uses c="CareerTrack". We override the className so
// the registry can find it by tuning name.
//
// TDESC's 10 persisted columns: branches, busy_time_situation_picker_tooltip,
// career_description, career_levels, career_name, career_name_gender_neutral,
// icon, icon_high_res, image, show_now_hiring_string.
//
// Note: career_name and career_description live HERE, not on Career.
// ---------------------------------------------------------------------------
export const CAREER_TRACK_SCHEMA: TdescSchema = withClassName(
  loadTdescFixture("CareerTrack.tdesc.json"),
  "CareerTrack",
);

// ---------------------------------------------------------------------------
// Career. TDESC says 11 persisted columns. The v0.1 hand-authored
// `career_name`, `career_description` are NOT here — they're on CareerTrack.
//   build_buy_info, call_costar_interaction, cancel_audition_interaction,
//   cancel_gig_interaction, career_category, career_panel_type,
//   find_audition_interaction, hire_agent_interaction, reputation_stat,
//   show_ideal_mood, start_track.
//
// v0.1 mentioned `ages` — it's NOT in the current Career TDESC. The HC tuning's
// `<T n="ages">YOUNGADULT,ADULT,ELDER</T>` is read by the game's Python from
// XML, not from SimData.
// ---------------------------------------------------------------------------
export const CAREER_SCHEMA: TdescSchema = loadTdescFixture("Career.tdesc.json");

// ---------------------------------------------------------------------------
// Buff. The s4tk EA fixture has 10 columns with schema_hash 0x0D045687. The
// current 1.124.55 TDESC marks ~12 columns persisted (adding `cas_vfx` and
// `plumbob_vfx`). To preserve byte-match against the EA fixture, we intersect
// the TDESC with the 10-column allow-list.
//
// (If a future game patch settles the column set, drop the selectColumns call
// and the schema_hash will need updating.)
// ---------------------------------------------------------------------------
const BUFF_EA_COLUMNS = [
  "audio_sting_on_add",
  "audio_sting_on_remove",
  "buff_description",
  "buff_name",
  "icon",
  "mood_type",
  "mood_weight",
  "timeout_string",
  "timeout_string_no_next_buff",
  "ui_sort_order",
] as const;

export const BUFF_SCHEMA: TdescSchema = selectColumns(
  loadTdescFixture("Buff.tdesc.json"),
  BUFF_EA_COLUMNS,
);

// ---------------------------------------------------------------------------
// EA-canonical schema hashes. These are EA-internal layout checksums; we can't
// regenerate them from TDESCs (see docs/tdesc-format.md). Provided for the
// classes where we have a real EA binary fixture.
// ---------------------------------------------------------------------------
export const KNOWN_SCHEMA_HASHES: Readonly<Record<string, number>> = Object.freeze({
  Trait: 0xde2eaf66,
  Buff: 0x0d045687,
});

// ---------------------------------------------------------------------------
// Trait's TDESC schema is exported by Trait.ts itself (it builds it from
// TRAIT_COLUMNS, the 17-column EA-canonical allow-list). The Trait class
// uses a custom builder (`buildTraitSimData`) that handles trait_type
// enum-to-Int64 mapping and the ui_category variant.
// ---------------------------------------------------------------------------

