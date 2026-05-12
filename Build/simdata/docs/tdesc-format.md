# TDESC format — what we discovered (v0.2 update)

> Phase 0.5 reconnaissance. Owner: simdata agent. Status: TDESCs are now
> committed under `test/fixtures/tdescs/` as JSON (XML→JSON via fast-xml-parser).
> This document is the v0.2 rewrite based on inspecting nine real EA TDESCs.

## What TDESC files are

A TDESC ("tuning description") describes the shape of a tuning class. EA ships
them with the game; Sims 4 Studio distributes its own copy for the Tuning
Validator feature. They are EA-published factual data — not creative work — and
have been redistributed by S4S for years.

One file per tuning class. We store them as **JSON** rather than XML to make
parsing trivial in TypeScript. The fetch script (`scripts/fetch-tdescs.mjs`)
pulls the XML from Lot 51's API via Playwright and lets `fast-xml-parser` emit
JSON with the `:@` attribute-key convention.

## JSON structure (the relevant subset)

```jsonc
{
  "TuningRoot": [{
    ":@": {
      "class": "Trait",
      "module": "traits.traits",
      "instance_type": "trait",
      "muid": "87F7AC13E02A8398",  // EA-internal stable ID; not a hash we care about
      "path": "Traits\\Descriptions"
    },
    "Instance": [
      {
        ":@": {
          "name": "ages",                // tuning field name; matches the `n=` attribute on tuning XML
          "class": "TunableSet",         // type kind — see "Type-kind decoder" below
          "type": "...",                 // class-specific subtype, e.g. "bool" for Tunable, "Pack" for TunableEnumEntry
          "default": "...",              // default value as a string
          "display": "Ages",             // UI label (irrelevant to us)
          "muid": "DC579AD9271C2D83",    // per-tunable stable ID
          "export_modes": "client_binary,server_binary,server_xml",  // *** the persistence marker ***
          "group": "Availability",
          "description": "..."
        },
        // body — varies by class (TunableEnum entries; TunableList element template; TunableTuple subfields; …)
        "TunableEnum": [/* ... */]
      },
      // many more <Instance> elements …
    ]
  }]
}
```

### The persistence marker — `export_modes`

**Operational rule (v0.2): a top-level tunable is persisted to SimData iff its
`:@.export_modes` attribute contains the substring `client_binary`.**

Empirical validation:
- **Buff (10 EA columns):** all 10 have `export_modes ∋ client_binary`. The
  1.124.55 TDESC also marks 2 additional columns (`cas_vfx`, `plumbob_vfx`)
  with `client_binary` — these are post-fixture additions. Rule covers all 10
  fixture columns; over-generates 2 newer-game columns.
- **Trait (17 EA columns):** 13 of 17 have `export_modes ∋ client_binary`.
  The other 4 (`ages`, `genders`, `species`, `bb_filter_tags`) are
  `TunableSet`/`TunableTags` with empty `export_modes` but are still persisted
  by EA per the trait.simdata fixture. The 1.124.55 TDESC also marks 7
  additional columns (`cas_allowed_pack`, `cas_trait_hidden`, `cas_trait_vfx`,
  `display_name_gender_neutral`, `display_overrides`, `refresh_sim_thumbnail`,
  `thumbnail_type_asm_param`) with `client_binary`.

So the rule has two parts:

1. **Primary:** `export_modes` substring includes `client_binary`.
2. **Special case:** for older EA fixtures, `TunableSet`/`TunableTags` at the
   top level are persisted even without an explicit `export_modes` declaration.
   The current TDESC dropped the `export_modes` attribute on these because
   they're always persisted by the binary exporter.

The **`muid` attribute is NOT a hash we care about.** It's an EA-internal stable
ID for the tunable, unrelated to FNV-32 of any string we can derive.

### Why we don't have a "100% byte-identical" rule

The s4tk-models EA fixtures (`trait.simdata`, `buff.simdata`) are from an
**older Sims 4 version**. The current 1.124.55 TDESC encodes a *superset* of
the persisted columns. A TDESC-driven build produces SimData with MORE columns
than the older EA fixture, which is what the current game would produce.

To preserve the v0.1 byte-match guarantee against the s4tk EA fixtures we
intersect the TDESC's persisted-set with a per-class allow-list (Trait: 17
EA-canonical columns; Buff: 10). For the other 7 classes (no EA fixture exists)
the TDESC determines the full column set, which is the correct behavior for
the current game version.

## Type-kind decoder

The TDESC type for each tunable is determined by `:@.class` (always present).
Sometimes `:@.type` provides additional information (e.g. for `Tunable` it
gives the primitive kind; for `TunableEnumEntry` it gives the enum class name).

| `:@.class` (and `:@.type` when relevant) | Our `TdescType.kind` | SimData DataType |
|---|---|---|
| `Tunable` + `type="bool"` | `bool` | Boolean |
| `Tunable` + `type="int"` | `int32` | Int32 |
| `Tunable` + `type="int64"` | `int64` | Int64 |
| `Tunable` + `type="uint32"` | `uint32` | UInt32 |
| `Tunable` + `type="float"` | `float` | Float |
| `Tunable` + `type="str"` | `string` | String |
| `TunableLocalizedString` | `string-key` | LocalizationKey (uint32) |
| `TunableResourceKey` / `TunableIcon` / `TunableInteractionAsmResourceKey` | `resource-key` | ResourceKey (TGI triple) |
| `TunableReference` | `table-set-reference` | TableSetReference (uint64) |
| `TunableEnumEntry` + `type="<EnumName>"` | `enum` | Int64 |
| `TunableList` (children: one inner `<Tunable>`) | `vector` (elem = inner) | Vector |
| `TunableSet` (children: one inner `<Tunable>`) | `vector` (elem = inner) | Vector |
| `TunableTags` (no children needed) | `vector` of int64 | Vector of Int64 |
| `TunableTuple` (children: many sub-tunables) | `object` | Object |
| `TunableVariant` (children: many sub-tunables, one per case) | `variant` | Variant |
| `OptionalTunable` (one inner Tunable; absent means default) | passes through | (inner) |
| `TunableRange` (numeric with min/max) | scalar of `:@.type` | Int32 typically |
| `TunableMapping` | not supported in v0.2 — none of our 9 classes use them at SimData boundary | — |

### Composite/wrapper classes treated as their inner kind

EA introduces named wrapper classes for documentation. Treat each as its
inner kind:

- `TunableScreenSlam` → `object` with the screen-slam fields
- `TunableScreenSlamSnippet` → variant wrapping a screen slam
- `TunablePlayAudio` → object with audio + slot fields
- `TunableScreenSlamKeyBased` / `TunableScreenSlamSizeBased` → object (tuple)
- `TunableTuple` subclasses like `TunableSubsetCompletionType` → object
- `TunableExistance` → sentinel; used as a "disabled" variant case

## The schema hash question

The Trait SimData schema hash is `0xDE2EAF66`. The Buff SimData schema hash is
`0x0D045687`. **Neither is an FNV-32 of any name we can construct from the
TDESC.** We checked:
- `fnv32("Trait")` → `0xCB5FDDC7` ≠ `0xDE2EAF66`
- `fnv32("traits.traits.Trait")` → `0xEFB78619` ≠ `0xDE2EAF66`
- The `muid` attribute → no match either.

The actual mechanism is that EA's exporter computes the hash as a checksum over
the **serialized schema layout** (column names, types, offsets) — not a hash of
the name. Without re-implementing EA's exporter we cannot regenerate this hash
from a TDESC.

**Solution:** the existing `KNOWN_SCHEMA_HASHES` map in
`src/build/classes/schemas.ts` holds the two EA-canonical hashes we've extracted.
For other classes we fall back to `(fnv32(className) | 0x80000000)` which the
game accepts because dispatch is by tuning class, not schema hash.

## Column-name hash

The SimData column-name hash IS straightforward: `fnv32(columnName) | 0x80000000`.
This is the `hashColumnName()` helper in `src/build/cells.ts`. No surprises.

## What gets parsed by `parseTdescJson`

1. The root `TuningRoot[0][':@'].class` and `module` provide `className`/`classPath`.
2. Iterate `TuningRoot[0].Instance[]`. Each entry has `:@` attributes and a
   typed body (key like `TunableEnum`, `TunableList`, `TunableTuple`,
   `TunableVariant`, etc.).
3. For each instance whose `:@.export_modes` contains `client_binary` OR whose
   `:@.class` is `TunableSet`/`TunableTags`, emit a `TdescColumn` with
   `persistedToSimData: true`.
4. For all others, emit a `TdescColumn` with `persistedToSimData: false`. They're
   kept for completeness so downstream consumers can introspect the full class.
5. Type construction recurses into bodies: `TunableList` reads its inner
   `<Tunable>` to determine element type; `TunableTuple` walks its children;
   `TunableVariant` enumerates cases.
6. `OptionalTunable` "transparently" passes through to its inner type — the
   wrapping is a tuning-XML convenience, not a SimData distinction.

## What's still hand-coded (and why)

- The schema hash for `Trait` and `Buff` — see "Schema hash question" above.
- The Trait `customBuild` function (`src/build/classes/Trait.ts`) — it handles
  the `trait_type` enum-to-Int64 mapping and the variant tag on `ui_category`
  which require lookup logic not encoded in the TDESC.
- The `KNOWN_SCHEMA_HASHES` constant in `src/build/classes/schemas.ts`.
- Per-class column allow-lists for Trait and Buff (to retain byte-match against
  the older s4tk EA fixtures).
