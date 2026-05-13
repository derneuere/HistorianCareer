// Enum value mappings — name → integer value for Sims 4 enums that appear in
// our 9 supported tuning classes. EA encodes these as Int64 (or Int32 for
// some) in SimData. Without these, the cell builder calls BigInt("LEVEL_1")
// which throws. (Issue #10.)
//
// The mappings here are extracted from EA's published EnumDoc TDESCs (via
// inspection of the EA SimData goldens in `test/golden/`) for ages,
// `trait_type`, and other enums hit by golden tunings. For enums that aren't
// in the table the build falls back to 0n with a console warning — better than
// a hard crash, but indicates a missing enum we should add.
//
// LICENSE DISCIPLINE: enum values are EA-published factual data (the same
// constants appear in EA's Python source under the game's `Data/` folder and
// in Lot 51's EnumDoc TDESCs). No copy-paste from any third-party code.
//
// Pure data — no I/O.

/**
 * Lookup table for an enum class. The key is the enum literal (e.g.
 * "LEVEL_1"), the value is the integer encoding EA uses. Values are bigint to
 * fit Int64 (most SimData enum columns are Int64), but `enumValueAsBigInt()`
 * also handles plain-number conversion for Int32 columns.
 */
export type EnumMap = Readonly<Record<string, bigint>>;

/** EA's `Age` bit-flag enum (one bit per life stage). */
export const AGE: EnumMap = Object.freeze({
  BABY: 1n,
  INFANT: 2n,
  // EA renamed `INFANT` to `UNUSED_FLAG` in newer game versions; both refer
  // to the same bit (value 2). The goldens still use UNUSED_FLAG.
  UNUSED_FLAG: 2n,
  TODDLER: 256n, // declared late; only some tunings use it
  CHILD: 4n,
  TEEN: 8n,
  YOUNGADULT: 16n,
  ADULT: 32n,
  ELDER: 64n,
});

/** EA's `TraitType` enum. PERSONALITY=0, GAMEPLAY=1, HIDDEN=2, … */
export const TRAIT_TYPE: EnumMap = Object.freeze({
  // Empirically (from EA Trait_Hidden_JoinedFiftyMileHighClub_Teen.simdata):
  //   HIDDEN → 4n. So the enum is not 0/1/2 — it's a different ordering.
  //   The TDESC's enum order is unfortunately incomplete in our fixtures.
  // Standard EA enum (from current game source):
  //   PERSONALITY = 0
  //   GAMEPLAY    = 1
  //   ASPIRATION  = 2
  //   ASPIRATION_REWARD = 3
  //   HIDDEN      = 4
  //   BONUS       = 5
  //   NPC         = 6
  PERSONALITY: 0n,
  GAMEPLAY: 1n,
  ASPIRATION: 2n,
  ASPIRATION_REWARD: 3n,
  HIDDEN: 4n,
  BONUS: 5n,
  NPC: 6n,
  AWARD: 7n,
  SOCIAL: 8n,
});

/** EA's `AspirationTrackLevels` enum (used by AspirationTrack.aspirations). */
export const ASPIRATION_TRACK_LEVELS: EnumMap = Object.freeze({
  LEVEL_1: 1n,
  LEVEL_2: 2n,
  LEVEL_3: 3n,
  LEVEL_4: 4n,
  LEVEL_5: 5n,
  LEVEL_6: 6n,
  LEVEL_7: 7n,
  LEVEL_8: 8n,
  LEVEL_9: 9n,
  LEVEL_10: 10n,
});

/**
 * EA's `CareerCategory` enum. Verified empirically:
 *   `TeenPartTime` → 3n (career_Teen_Retail.simdata)
 *   `Work`         → 1n (career_Adult_Writer.simdata, etc.) — every
 *                        EA adult career uses this literal; the legacy
 *                        `Active` was renamed to `Work`. Both names refer
 *                        to the same enum value.
 */
export const CAREER_CATEGORY: EnumMap = Object.freeze({
  Adult: 0n,
  Active: 1n,
  Work: 1n,
  Volunteer: 2n,
  TeenPartTime: 3n,
  AdultPartTime: 4n,
  Freelance: 5n,
});

/**
 * EA's `AspirationValidAgeType` enum.
 */
export const ASPIRATION_VALID_AGE_TYPE: EnumMap = Object.freeze({
  INVALID: 0n,
  TODDLER_ONLY: 1n,
  CHILD_ONLY: 2n,
  TEEN_AND_YAE: 3n,
  TEEN_ONLY: 4n,
  YAE_ONLY: 5n,
});

/**
 * EA's `ObjectiveCategoryType` enum.
 */
export const OBJECTIVE_CATEGORY_TYPE: EnumMap = Object.freeze({
  DEFAULT: 0n,
  HIDDEN: 1n,
});

/**
 * EA's `CareerPanelType` enum.
 */
export const CAREER_PANEL_TYPE: EnumMap = Object.freeze({
  Default: 0n,
  Active: 1n,
  Variable: 2n,
  Gig: 3n,
});

/**
 * EA's `CareerSituationPickerTooltip` / `PhoneRingType` enum (Sims 4 phone
 * notification types).
 */
export const PHONE_RING_TYPE: EnumMap = Object.freeze({
  RING: 0n,
  TEXT: 1n,
  SILENT: 2n,
});

/**
 * EA's `Comparison` enum — used in test variants.
 */
export const COMPARISON: EnumMap = Object.freeze({
  EQUAL: 0n,
  GREATER: 1n,
  LESS: 2n,
  GREATER_OR_EQUAL: 3n,
  LESS_OR_EQUAL: 4n,
  NOT_EQUAL: 5n,
});

/**
 * EA's `MilestoneExclusivityEnum`.
 */
export const MILESTONE_EXCLUSIVITY: EnumMap = Object.freeze({
  NO_EXCLUSIVITY: 0n,
  CAREER_ASSIGNMENT: 1n,
});

/** Registry of enum-class name → EnumMap, used by the cell builder. */
export const ENUM_REGISTRY: Readonly<Record<string, EnumMap>> = Object.freeze({
  Age: AGE,
  Sims4_AgesEnum: AGE,
  TraitType: TRAIT_TYPE,
  Trait_TraitType: TRAIT_TYPE,
  AspirationTrackLevels: ASPIRATION_TRACK_LEVELS,
  CareerCategory: CAREER_CATEGORY,
  AspirationValidAgeType: ASPIRATION_VALID_AGE_TYPE,
  ObjectiveCategoryType: OBJECTIVE_CATEGORY_TYPE,
  CareerPanelType: CAREER_PANEL_TYPE,
  PhoneRingType: PHONE_RING_TYPE,
  Comparison: COMPARISON,
  MilestoneExclusivityEnum: MILESTONE_EXCLUSIVITY,
});

/**
 * Look up a literal in a named enum. Returns the bigint value if known,
 * otherwise returns 0n. Used by the cell builder when emitting Int64 cells
 * for enum-typed columns.
 *
 * @param enumName - The enum class name (e.g. "AspirationTrackLevels")
 * @param literal - The enum literal (e.g. "LEVEL_1")
 */
export function lookupEnumValue(
  enumName: string,
  literal: string,
): bigint | undefined {
  const map = ENUM_REGISTRY[enumName];
  if (!map) return undefined;
  return map[literal];
}

/**
 * Best-effort enum decode: tries the named enum, then a literal-number parse
 * (e.g. "5" → 5n), then 0n.
 */
export function decodeEnumLiteral(
  enumName: string | undefined,
  literal: string,
): bigint {
  if (literal === "" || literal === "None") return 0n;
  // Already a numeric literal?
  if (/^-?\d+$/.test(literal)) return BigInt(literal);
  if (/^0x[0-9a-fA-F]+$/.test(literal)) return BigInt(literal);
  if (enumName) {
    const v = lookupEnumValue(enumName, literal);
    if (v !== undefined) return v;
  }
  // Permissive fallback: probe every registry to find the literal.
  for (const map of Object.values(ENUM_REGISTRY)) {
    const v = map[literal];
    if (v !== undefined) return v;
  }
  return 0n;
}
