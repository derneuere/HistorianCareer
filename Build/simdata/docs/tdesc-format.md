# TDESC format — what we discovered (v0.3 update)

> Owner: simdata agent. Status: TDESCs are committed under
> `test/fixtures/tdescs/` as JSON. EA SimData goldens are committed under
> `test/golden/`. This document is the v0.3 rewrite based on comparing nine
> real EA SimData goldens (live game extraction at 1.124.55) against the
> TDESC-derived schemas.

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

**Operational rule (v0.3): a top-level tunable is persisted to SimData iff its
`:@.export_modes` attribute contains the COMPLETE triple
`client_binary,server_binary,server_xml` (order-independent, parsed as a set).**

The v0.2 rule (substring `client_binary`) over-generated dozens of columns
that EA marks `client_binary` only — those are NOT actually persisted to the
SimData binary. The current TDESCs (1.124.55) have 14 such columns across
our 9 classes (e.g. `build_buy_info`, `call_costar_interaction` on Career;
`timeout_string`, `timeout_string_no_next_buff` on Buff; `ideal_mood` on
CareerLevel). Comparing against real EA SimData goldens confirms they are
NOT in the binary output.

### Empirical validation

Cross-referencing each TDESC's `:@.export_modes` against the actual columns
present in each EA SimData golden in `test/golden/`:

| Class | EA golden cols | Full-triple cols in TDESC | Persist rule "just works"? |
|---|---|---|---|
| Career | 2 | 5 | No — TDESC over-generates 3 cols not in golden |
| CareerTrack | 8 | 10 | No — TDESC adds 2 newer-game cols |
| CareerLevel | 7 | 8 | No — TDESC misses `ideal_mood` (only `client_binary`), `simoleons_per_hour` (renamed to `pay_type`); adds `agents_available`, `pay_type`, `pto_per_day` |
| Aspiration | 5 | 4 | No — TDESC misses `disabled` (parent class), `is_child_aspiration` (no export_modes); adds `aspiration_valid_age_type` |
| AspirationCareer | 2 | 1 | No — TDESC misses `disabled` (parent class) |
| AspirationTrack | 9 | 11 | No — TDESC adds 2 newer-game cols |
| Buff | 10 | 9 | No — TDESC misses `icon_highlight` entirely; adds `plumbob_vfx` |
| Trait | 13 | ~11 | No — TDESC misses `ages`, `genders` (TunableSet without export_modes); adds 7 newer-game cols |
| Objective | 3 | 5 | No — TDESC adds 2 newer-game cols |

**Pattern**: every class needs per-class adjustments. The TDESC's persistence
rule alone is necessary but not sufficient. We need both:
1. **Persistence rule**: full export_modes triple (`client_binary,server_binary,server_xml`).
2. **Per-class allow-list / extras**: in `src/build/classes/schemas.ts`, each
   class either `selectColumns()`s the persisted set down to the golden's
   columns, or `withAdditionalColumns()`s in golden-only columns (like
   `disabled` from `AspirationBasic` parent class or `icon_highlight` missing
   from TDESC).

### Why per-class lists are necessary

EA's SimData persistence is essentially **per-game-version** snapshots. The
TDESCs we have come from version 1.124.55, but our goldens were extracted
from a slightly different game build with slightly different column sets.
Without per-class adjustments, the TDESC alone would either over-generate
(adding newer columns not in older goldens) or under-generate (missing
parent-class columns or fields that EA-internally treats as "always
persisted").

Two more EA-specific behaviors discovered empirically:

1. **`AspirationBasic` parent class fields**: `disabled` and `is_child_aspiration`
   live on the parent class. The per-class TDESC doesn't redeclare them, but
   EA persists them in every subclass (Aspiration, AspirationCareer).

2. **Resource type rewriting**: EA's SimData binary rewrites
   `0x2F7D0004` (icon reference) → `0x00B2D882` (PNG) when serializing
   `ResourceKey` cells. Other resource types (audio `0x39B2AA4A`, etc.) are
   preserved. We replicate this in `src/build/cells.ts` via the
   `RESOURCE_TYPE_REWRITES` table.

### SimData version

EA writes SimData v0x100. v0x101 also parses fine but produces different
byte layout. We use 0x100 for byte-equality with goldens.

### Tuple schema-name disambiguation

Anonymous `TunableTuple` nodes in TDESC have `class="TunableTuple"` — many of
them throughout a complex schema like `CareerLevel.work_schedule`. Our build
layer interns SimDataSchemas by name; using the literal class string would
collide every nested tuple together and produce mismatched row/column data at
serialization time (issue #10's CareerLevel crash). The fix is in
`parseTuple()`: prefer the `name` slot, fall back to a synthesized
`AnonTuple_<col1>_<col2>_…` so structurally-distinct tuples get distinct
schema names.

The **`muid` attribute is NOT a hash we care about.** It's an EA-internal stable
ID for the tunable, unrelated to FNV-32 of any string we can derive.

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

EA SimData schema hashes are EA-internal layout checksums; **none of them are
an FNV-32 of a name we can construct from the TDESC.** We have empirically
extracted the canonical hashes for all 9 classes from the EA goldens:

| Class | EA hash |
|---|---|
| Trait | `0x992BFA76` |
| Buff | `0x83A7824A` |
| Career | `0x7A1FE1E2` |
| CareerTrack | `0x9A6E55E8` |
| CareerLevel | `0x82D9B9A3` |
| Aspiration | `0x72ABCA6F` |
| AspirationCareer | `0x4E53725B` |
| AspirationTrack | `0x54FDB5FC` |
| Objective | `0xD5CFEBA5` |

Earlier values in `KNOWN_SCHEMA_HASHES` for Trait (`0xDE2EAF66`) and Buff
(`0x0D045687`) came from the s4tk-models MIT fixtures, which are from an
older Sims 4 version with different column sets. The above hashes reflect
the current game (1.124.55) and our per-class column lists.

The actual mechanism is that EA's exporter computes the hash as a checksum
over the **serialized schema layout** (column names, types, offsets) — not a
hash of the name. Without re-implementing EA's exporter we cannot regenerate
this hash from a TDESC. The `KNOWN_SCHEMA_HASHES` map in
`src/build/classes/schemas.ts` holds the EA-canonical hashes we've
extracted. For unsupported classes we fall back to `(fnv32(className) |
0x80000000)` which the game accepts because dispatch is by tuning class, not
schema hash.

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

- The 9 EA-canonical schema hashes in `KNOWN_SCHEMA_HASHES` — extracted from
  the goldens, not derivable from TDESCs.
- The Trait `customBuild` function (`src/build/classes/Trait.ts`) — it
  handles the `trait_type` enum-to-Int64 mapping (PERSONALITY=0, HIDDEN=4, …)
  and supplies defaults for the 13 columns even when tuning XML omits most
  of them.
- Per-class column lists in `src/build/classes/schemas.ts`. Some classes use
  `selectColumns()` to narrow the TDESC's persisted set to what the EA
  goldens contain; others use `withAdditionalColumns()` to add columns the
  TDESC doesn't include (parent-class fields like `disabled`, or missing
  fields like Buff's `icon_highlight`).
- The enum value tables in `src/build/enums.ts` — needed because the TDESC
  declares which enum class each field belongs to but doesn't enumerate its
  members. We hand-code the ~10 enums our 9 classes use (Age, TraitType,
  AspirationTrackLevels, CareerCategory, …).
- The resource-type rewriting table in `src/build/cells.ts` —
  `0x2F7D0004 → 0x00B2D882` mirrors EA's binary-serialization behavior.
