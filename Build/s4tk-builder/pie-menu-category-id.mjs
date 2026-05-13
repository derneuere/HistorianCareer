// pie-menu-category-id.mjs — compute a small (≤ 2^31) instance ID for a
// PieMenuCategory tuning, plus the matching `category` reference value for a
// SuperInteraction that points at it.
//
// Why this exists (issue #14):
//
//   EA's PieMenuCategory instance IDs are 16–32 bit (e.g. computer_Handiness =
//   37041 = 0x90B1). When a SuperInteraction carries
//
//       <T n="category">{decimal_instance_id}</T>
//
//   the pie-menu generator looks up the referenced PieMenuCategory by ID.
//
//   In v0.2.1, adding `<T n="category">` to our SIs with the value of our
//   PieMenuCategory's instance ID (which the standard builder computes as
//   fnv64(tuningName, highBit=true) — a 64-bit number) crashes the pie-menu
//   generator with no `lastException` entry. Hypothesis 1 in issue #14: the
//   `category` field is a `TunableReference` constrained to 32 bits and the
//   resolver chokes on 64-bit values.
//
//   This module provides:
//     - smallInstanceIdFor(tuningName): a deterministic 31-bit ID derived from
//       fnv64 (low 31 bits — clears bit 31 to stay positive in signed-int32
//       land too, matching EA's <2^31 IDs).
//     - assertNoCollisions(map): throws if multiple tuning names hash to the
//       same small ID across the package.
//
//   The s4tk-builder (Build/s4tk-builder/build-package.mjs, owned by issue #15
//   in parallel) is expected to import this helper and call
//   smallInstanceIdFor() instead of fnv64() **specifically for tuning names
//   whose root <I c="..."> is `PieMenuCategory`**. See
//   Docs/NOTE_pie_menu_category_ids.md for the integration contract.
//
//   For now, this module is a sibling helper script — issue #15's agent owns
//   build-package.mjs and will wire it in.

import { fnv64 } from "@s4tk/hashing/hashing.js";

/**
 * Mask used to clamp a fnv64 value to 31 bits. EA's PieMenuCategory IDs are
 * 16-32 bit; staying ≤ 2^31 - 1 keeps the value safely inside the signed-int32
 * range that EA's TunableReference resolver almost certainly uses internally.
 *
 * 0x7FFFFFFF = 2147483647 = 2^31 - 1.
 */
export const PIE_MENU_CATEGORY_ID_MASK = 0x7FFFFFFFn;

/**
 * Tuning class names that should receive a small (31-bit) instance ID instead
 * of the default 64-bit fnv64 hash.
 *
 * Rationale per class family:
 *
 * - PieMenuCategory (issue #14): EA's <T n="category"> TunableReference field
 *   silently rejects 64-bit values. EA-shipped category IDs are 16–32 bit.
 *
 * - Career / TunableCareerTrack / CareerLevel / Aspiration / AspirationTrack /
 *   AspirationCareer / Objective: Surfaced when our HC career was visibly
 *   added but its display strings/icons rendered as "@" / default-icon. EA's
 *   own careers ship with 16-bit instance IDs (Writer = 27933, GradeSchool
 *   Track = 12900). Mod-author library lot51-core ships a runtime patch
 *   (custom_filter_career_fix.py) that explicitly removes 64-bit career IDs
 *   from EA's sim-filter system with the comment "A 64 bit career was
 *   removed". Without that patch installed, 64-bit Career/CareerTrack IDs
 *   silently fail the same way `category` did for PieMenuCategory: the
 *   tuning loads, cross-refs to other resources work, but downstream
 *   systems (UI display lookups against the SimData LocalizationKey columns,
 *   icon resolver, CAS aspiration enumerator) drop 64-bit references.
 *
 *   Switching the whole career family to 31-bit IDs sidesteps the bug, the
 *   same way it did for PieMenuCategory. Cross-references all resolve through
 *   the global name→instance map in resolve-names.mjs, so emitting both ends
 *   of a reference as 31-bit keeps everything consistent.
 */
export const SMALL_ID_CLASSES = new Set([
    "PieMenuCategory",
    "Career",
    "TunableCareerTrack",
    "CareerTrack",
    "CareerLevel",
    "Aspiration",
    "AspirationTrack",
    "AspirationCareer",
    "Objective",
    // Trait IDs in EA are all 16-bit (e.g. trait_Knowledge_BookWorm ≈ 27082,
    // Renaissance Sim's primary_trait = 27086). Our Habilitation Renown trait
    // is referenced from AspirationTrack.provided_traits — if that reference
    // is 64-bit it gets silently dropped by the same code path that filtered
    // 64-bit careers, blocking the whole track's CAS registration.
    "Trait",
    // Statistic IDs in EA are also 16-bit (e.g. Writer's career performance
    // stat = 27784, ranging up to ~100K). Our HC_Statistic_HistorianLevel is
    // referenced from CareerLevel.performance_stat — needs to be 31-bit.
    "Statistic",
    // Commodity extends Statistic and goes into the same STATISTIC instance
    // manager.  EA's CareerLevel.performance_stat description literally says
    // "Commodity used to track career performance" — so HC's stat is now a
    // Commodity to pass the consumer-side validation EA's runtime applies
    // (see Tuning/HC_Statistic_HistorianLevel.xml header for the empirical
    // 1157 → 1156 → 1157 manager-count evidence behind that switch).
    "Commodity",
]);

/**
 * Deterministically derive a ≤ 2^31 - 1 instance ID from a tuning name.
 *
 * Strategy: fnv64 with high-bit clear, then mask to 31 bits. This preserves
 * determinism (the same tuning name always yields the same ID) and avalanches
 * well — the low 31 bits of fnv64 are statistically uniform enough that
 * collisions across a handful of category names are vanishingly unlikely.
 *
 * @param {string} tuningName e.g. "HC_PieMenuCategory_Historian"
 * @returns {bigint} a positive bigint in [1, 2^31 - 1]
 */
export function smallInstanceIdFor(tuningName) {
    if (typeof tuningName !== "string" || tuningName.length === 0) {
        throw new TypeError(`smallInstanceIdFor: expected non-empty string, got ${typeof tuningName}`);
    }
    // fnv64 with highBit=false so we get the raw hash, then mask to 31 bits.
    // We deliberately don't use highBit=true here because that would set the
    // top bit of a 64-bit value, which we're about to throw away anyway.
    const full = fnv64(tuningName, false);
    let small = full & PIE_MENU_CATEGORY_ID_MASK;
    // Guarantee non-zero. The probability of fnv64 producing a value whose low
    // 31 bits are exactly zero is 2^-31, but guarding is free.
    if (small === 0n) small = 1n;
    return small;
}

/**
 * Verify that no two tuning names hash to the same small ID.
 *
 * The caller passes a map of tuningName → smallId (e.g. accumulated while
 * walking Tuning/*.xml). This function throws on the first collision so the
 * builder fails loudly at build time rather than producing a broken package
 * that silently mis-routes references at runtime.
 *
 * @param {Map<string, bigint>} idByTuningName
 */
export function assertNoCollisions(idByTuningName) {
    /** @type {Map<bigint, string>} */
    const seen = new Map();
    for (const [tuningName, id] of idByTuningName.entries()) {
        const prior = seen.get(id);
        if (prior !== undefined && prior !== tuningName) {
            throw new Error(
                `pie-menu-category-id: collision — "${prior}" and "${tuningName}" `
                + `both hash to small ID ${id.toString()} (0x${id.toString(16)}). `
                + `Rename one or extend the mask in pie-menu-category-id.mjs.`,
            );
        }
        seen.set(id, tuningName);
    }
}

/**
 * Test helper exposed for vitest coverage. Returns the raw fnv64 (highBit
 * cleared) of a tuning name as a bigint — useful for asserting we're masking
 * correctly without re-importing @s4tk/hashing into tests.
 *
 * @param {string} tuningName
 * @returns {bigint}
 */
export function _rawFnv64(tuningName) {
    return fnv64(tuningName, false);
}
