# Supported tuning classes

Each class has a registered builder in `src/build/classes/`. Adding a new class
is mechanical:

1. Look at an EA SimData XML for the class (or extract one with `@s4tk/extraction`).
2. Author a `TdescSchema` listing the columns and their types in
   `src/build/classes/schemas.ts`.
3. Register it in `src/build/classes/index.ts`.
4. (Optional) Add a custom builder if the class has fields that need
   non-trivial value mapping (enums, sub-tuples, variants).

## v0.1 coverage

### `Trait` — custom builder
- Schema hash `0xDE2EAF66` (EA-canonical, extracted from EA's `trait_HotHeaded`).
- 17 columns including `display_name`, `trait_description`, `trait_type`,
  vectors of `conflicting_traits`, the `ui_category` variant, …
- Source: `Trait.ts` (full hand-built cell row).
- Real EA fixture: `reference/s4tk-models/test/data/simdatas/binary/trait.simdata`.

### `Buff` — schema-driven
- Schema hash `0x0D045687` (EA-canonical, extracted from EA's `Buff_Memory_scared`).
- 10 columns: `buff_name`, `buff_description`, `icon`, `mood_type`,
  `mood_weight`, `ui_sort_order`, two audio resource keys, two timeout strings.
- Source: `schemas.ts` (`BUFF_SCHEMA`).

### `Career` — schema-driven (with `career_category` enum)
- Schema hash computed via FNV-32 of "Career" (we lack an EA fixture for the
  exact EA hash; the game tolerates a non-canonical hash as long as the
  schema is well-formed).
- Columns: `career_name`, `career_description`, `start_track`, `career_category`.
- `ages` is omitted from SimData (EA stores it as Vector<Int64>, derived from a
  CSV string in tuning; non-trivial to compute without a TDESC).

### `CareerTrack` — schema-driven
- One column: `career_levels` (Vector<TableSetReference>).

### `CareerLevel` — schema-driven
- 7 columns: `level_title`, `level_description`, `simoleons_per_hour`,
  `work_performance_progress_per_completion`, `schedule`, `level_aspiration`,
  `gameplay_unlocks`.

### `Aspiration` — schema-driven
- 4 columns: `display_name`, `display_description`, `objectives`, `reward`.

### `AspirationCareer` — schema-driven
- 3 columns: `display_name`, `display_description`, `objectives`. (`reward` is
  Aspiration-only; the career-level variant doesn't expose it in SimData.)

### `AspirationTrack` — schema-driven (with `aspiration_category` enum)
- 5 columns: `display_text`, `description_text`, `aspirations`,
  `aspiration_category`, `reward_trait`.

### `CareerChanceCard` — schema-driven (minimal)
- 2 columns: `title`, `description`. EA's full schema has nested
  `response_option_a/b` tuples and outcome lists — these are tuning-only and
  do not appear in SimData by EA convention (the game reads option text from
  the tuning XML).

### `Objective` — schema-driven
- 3 columns: `display_text`, `goal_value`, `icon`.

## Adding new classes

The framework is structured for cheap class addition. Most additions are:
1. A `TdescSchema` literal (10–20 lines).
2. One `registerClass({...})` call.

Custom builders are only needed for the kind of edge cases Trait hits:
enum-to-Int64 mapping that doesn't follow the value-index convention, or
variant cells with EA-specific type hashes (`0x603EAA6C` for trait UI
categories).
