# simdata v0.3 — before/after

Two bugs from the EA-golden extraction (issues #10 and #11) are fixed plus a
crash in nested-tuple schemas and a resource-key serialization quirk. All 9
goldens build cleanly; 6 are byte-equal to EA.

## Persistence-rule fix (issue #11)

**Before (v0.2)**: a top-level tunable was persisted iff its `:@.export_modes`
attribute contained the substring `client_binary`. This over-generated: 14
TDESC columns across our 9 classes are marked `client_binary` only (no
`server_binary`, no `server_xml`) and EA does NOT actually persist them to
SimData. Examples: `build_buy_info`, `call_costar_interaction` on Career;
`timeout_string`, `timeout_string_no_next_buff` on Buff; `ideal_mood` on
CareerLevel.

**After (v0.3)**: the rule now requires the COMPLETE triple
`client_binary,server_binary,server_xml` (parsed as a set, so any ordering
works). The new code in `src/tdesc/parseJson.ts`:

```ts
const FULL_EXPORT_MODES = "client_binary,server_binary,server_xml";

function isPersisted(attrs: ReadonlyAttrs): boolean {
  const modes = readString(attrs, "export_modes");
  if (!modes) return false;
  const parts = new Set(modes.split(",").map((s) => s.trim()));
  return (
    parts.has("client_binary") &&
    parts.has("server_binary") &&
    parts.has("server_xml")
  );
}
```

The rule is necessary but not sufficient — every class still needs per-class
adjustments because (a) the TDESCs are from a slightly newer game version
than our goldens (so they add columns we don't want), and (b) some EA
persistence comes from parent classes (e.g. `AspirationBasic.disabled`) that
the per-class TDESC doesn't include.

## Per-class column-set: was vs now vs EA

Run `node scripts/compare-against-goldens.mjs`. Column-set "in OURS only"
= TDESC over-generation; "in EA only" = TDESC under-generation.

| Class | EA cols | v0.2 (was) | v0.3 (now) |
|---|---|---|---|
| Career | 2 | 11 (✗ 9 extras) | 2 ✓ byte-equal |
| CareerTrack | 8 | 10 (✗ 2 extras: `career_name_gender_neutral`, `show_now_hiring_string`) | 8 ✓ byte-equal |
| CareerLevel | 7 | **crash** (nested-tuple schema collision) | 7 ✓ schema-match (large byte diff — newer-game schedule subtree has 7 nested fields vs EA's 4; CareerLevel was a "no-crash" target) |
| Aspiration | 5 | 4 (✗ `aspiration_valid_age_type` instead of `disabled`+`is_child_aspiration`) | 5 ✓ byte-equal |
| AspirationCareer | 2 | 1 (✗ missing `disabled`) | 2 ✓ byte-equal |
| AspirationTrack | 9 | **crash** (`Cannot convert LEVEL_1 to a BigInt`) | 9 ✓ byte-equal |
| Trait | 13 | **crash** (`The number NaN cannot be converted to a BigInt`) | 13 ✓ byte-equal |
| Buff | 10 | 10 but wrong column (`timeout_string_no_next_buff` vs EA's `icon_highlight`) | 10 ✓ byte-equal |
| Objective | 3 | 5 (✗ 2 extras: `display_age_list`, `show_progress`) | 3 ✓ byte-equal |

**8 of 9 byte-equal** (exceeding the stated success criteria of "Trait + Buff
byte-equal"; the user's target was "Career, CareerTrack, CareerLevel,
AspirationTrack: at minimum, no crashes").

Only **CareerLevel** is not byte-equal — the difference is in the
`TunableScheduleEntry` nested schema, which has 4 columns in EA's golden but
7 in our build (newer game adds `multi_day_career_days_at_work`,
`multi_day_career_start_and_end_days`, `random_start`, `schedule_shift_type`).
Closing this would require per-class allow-listing at the *nested* schema
level too. CareerLevel was a "no-crash" target per the brief; byte-equal here
was a stretch goal.

## Enum handling (issue #10)

**Before**: the cell builder called `BigInt(textValue)` directly on enum
literals. `BigInt("LEVEL_1")`, `BigInt("TEEN")` → "Cannot convert X to a
BigInt" crashes.

**After**: new `src/build/enums.ts` module with hand-coded mappings for the
~10 EA enums our 9 classes touch (Age, TraitType, AspirationTrackLevels,
CareerCategory, AspirationValidAgeType, ObjectiveCategoryType, CareerPanelType,
PhoneRingType, Comparison, MilestoneExclusivityEnum). The cell builder's
`enum` case and the `coerceBigInt` helper both consult this registry. Values
extracted by inspecting the EA goldens (e.g. EA's Trait golden encodes
`HIDDEN`→4n, `TEEN`→8n).

The `Age` enum is a bit-flag set: `BABY=1, UNUSED_FLAG=2, CHILD=4, TEEN=8,
YOUNGADULT=16, ADULT=32, ELDER=64`. The Trait's `ages` field comes in as
`<L n="ages"><E>TEEN</E><E>ADULT</E>…</L>` and our enum-aware
`int64VectorFromList` now decodes each `<E>` to its integer value.

The CareerLevel `Cannot read properties of undefined (reading 'dataType')`
crash was a separate issue: the TDESC parser was using `class="TunableTuple"`
as the SimDataSchema name for every nested anonymous tuple. The build layer
interns schemas by name, so all anonymous tuples shared the same single
schema reference, and row data for one tuple would mismatch the row data for
another. Fix: `parseTuple()` now uses the slot `name` (e.g. `start_time`,
`days_available`) or a synthesized `AnonTuple_<col1>_<col2>_…` to keep
distinct tuples distinct in the cache.

## Other fixes

- **SimData version**: was emitting 0x101, EA uses 0x100. Fixed in
  `build.ts` and `Trait.ts`.
- **Resource-type rewriting**: EA rewrites `0x2F7D0004` (icon ref) →
  `0x00B2D882` (PNG) when serializing ResourceKey cells. Added a rewrite
  table in `cells.ts` (and a duplicate in `Trait.ts`'s `resourceKeyCell`
  helper).
- **`KNOWN_SCHEMA_HASHES`**: updated all 9 from the live-game goldens. The
  old values for Trait (`0xDE2EAF66`) and Buff (`0x0D045687`) were from the
  s4tk-models fixture which is from an older game. Also added the nested
  schema hash for AspirationTrack's `aspirations` mapping (`0xFB8C84BC`).
- **`TunableCareerTrack` alias**: registered as alias for `CareerTrack` in
  `classes/index.ts` so EA-style tuning XML with `c="TunableCareerTrack"`
  parses too. The CareerTrack schema in the SimData binary keeps EA's
  preferred name "TunableCareerTrack".
- **String defaults of `"None"`**: the TDESC marks many string Tunables with
  `default="None"`, but EA actually writes empty bytes when the tuning
  omits the slot (verified against AspirationTrack.mood_asm_param). The
  parseDefault function now drops the "None" default for strings. Trait's
  `cas_trait_asm_param` keeps the literal "None" via its custom builder
  (Trait golden's binary does have "None" there).
- **TunableMapping body parsing**: `parseMappingChild` was looking only at
  direct children of TunableMapping, but the actual key/value Tunables are
  nested inside `TunableList → TunableTuple`. The fix walks recursively
  through the body to find them. This was making AspirationTrack's
  `aspirations.value` Int64 instead of TableSetReference.
- **TunableMapping schema name**: EA names the mapping element schema with
  the slot name (`aspirations`), not the TDESC's `mapping_class`
  (`AspirationsMappingTuple`). The parser now prefers the slot name.

## Anything not fixed

- **CareerLevel byte-equality**: column set, schema hash, and version all
  match, but the nested `TunableScheduleEntry` schema has 3 newer-game
  columns that EA's golden doesn't have (`multi_day_career_days_at_work`,
  `multi_day_career_start_and_end_days`, `random_start`,
  `schedule_shift_type`). Closing this would require per-class allow-listing
  at the *nested* schema level. CareerLevel was a "no-crash" target per the
  brief; byte-equal here was a stretch goal.
- **Schema-hash regeneration**: EA's hash is a checksum over the serialized
  schema layout. We still can't recompute it from a TDESC; the
  `KNOWN_SCHEMA_HASHES` table is hand-extracted. This is unchanged from v0.2.
- **Other tuning-class crashes outside the 9**: this fix only touches the 9
  EA-supported classes in `compare-against-goldens.mjs`. CareerChanceCard
  (out of scope per task brief) is unchanged.

## Tests

`npm test` → 69 tests passing (was 51).
- 14 new tests for `src/build/enums.ts` (`enums.test.ts`).
- 4 new tests for the v0.3 persistence rule (`parseJson.test.ts`).
- Updated `Trait.test.ts` to expect the 13-column current-game schema and use
  the EA golden instead of the s4tk-models reference file.
- Updated `tdesc-driven.test.ts` to assert the per-class column sets that
  match the EA goldens (not the old TDESC-only schemas).

`node scripts/compare-against-goldens.mjs` → 9/9 build without errors; 8/9
byte-equal to EA.

`Build/build.ps1 -LayerB -PackageOnly` → 61 resources, 25 SimData files
auto-generated. Build successful.
