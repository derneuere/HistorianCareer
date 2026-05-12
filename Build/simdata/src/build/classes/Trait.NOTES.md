# Trait.NOTES.md

Behavioral notes on the `Trait` tuning class, written from research and binary
reverse-engineering. **No copy-paste from non-MIT sources.**

## Sources consulted

- `reference/s4tk-models/test/data/simdatas/xml/trait.xml` — MIT, S4S-style XML
  rendering of `trait_HotHeaded.simdata`. Authoritative for the column list.
- `reference/s4tk-models/test/data/simdatas/binary/trait.simdata` — MIT,
  decoded with `@s4tk/models` to verify schema hash and column data types.
- `reference/mod-constructor-5/Constructor5.Elements/Traits/Trait.cs` — no
  LICENSE, read-only behavioral reference. (Mod-Constructor-5 stamps values
  into a pre-built template `.simdata` rather than constructing the schema
  from scratch, so it's less useful for understanding the schema than the
  binary itself. Read for confirmation, did not copy.)

## Schema layout (per EA binary)

Schema name: `Trait`. Hash: `0xDE2EAF66`.

| Column | DataType | Notes |
|---|---|---|
| `ages` | Vector<Int64> | One Int64 per supported age bitmask (e.g. 8=YA, 32=A, …) |
| `bb_filter_styles` | Vector | Build-mode filter; usually empty |
| `bb_filter_tags` | Vector | Same |
| `cas_idle_asm_key` | ResourceKey | CAS animation key |
| `cas_idle_asm_state` | String | Animation state name |
| `cas_selected_icon` | ResourceKey | Icon shown in CAS when selected |
| `cas_trait_asm_param` | String | Animation param |
| `conflicting_traits` | Vector<TableSetReference> | Trait instance IDs that conflict |
| `display_name` | LocalizationKey | STBL key |
| `genders` | Vector | Usually empty |
| `icon` | ResourceKey | Trait icon shown in UI |
| `species` | Vector<Int64> | 1=Human, 2=Cat, … |
| `tags` | Vector<Int64> | Tag IDs |
| `trait_description` | LocalizationKey | STBL key |
| `trait_origin_description` | LocalizationKey | Where the trait came from |
| `trait_type` | Int64 | 0=Personality, 1=Gameplay, 2=Hidden, … |
| `ui_category` | Variant | Wraps an Int64 inside a 0x603EAA6C-tagged variant |

## Mapping rules from tuning XML

| Tuning slot | SimData column |
|---|---|
| `<T n="display_name">0xXXXX</T>` | `display_name` = STBL key |
| `<T n="trait_description">…</T>` | `trait_description` |
| `<T n="is_personality_trait">True/False</T>` | NOT directly mapped — EA derives `trait_type` from this and the `<T n="trait_type">` enum |
| `<T n="trait_type">GAMEPLAY</T>` | `trait_type` (Int64): GAMEPLAY=1, PERSONALITY=0, HIDDEN=2 |
| `<L n="loot_on_trait_add">…</L>` | Tuning-only; NOT in SimData |
| `<T n="icon">…</T>` | `icon` (ResourceKey); if absent → 0 key |

## Notes for the HistorianCareer.trait_HabilitationRenown case

Our tuning XML only declares `display_name`, `trait_description`,
`is_personality_trait`, `trait_type`, `loot_on_trait_add`. The other 12+
columns of the SimData schema must fall back to sensible defaults
(empty vectors, zero keys, empty strings) — the same defaults EA uses when
its own tuning XML omits them.
