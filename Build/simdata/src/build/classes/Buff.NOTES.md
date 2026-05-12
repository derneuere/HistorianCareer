# Buff.NOTES.md

## Sources

- `reference/s4tk-models/test/data/simdatas/xml/buff.xml` (MIT) — S4S-rendered
  view of `Buff_Memory_scared`. Authoritative for column list.
- `reference/s4tk-models/test/data/simdatas/binary/buff.simdata` (MIT) — the
  matching binary; decoded with `@s4tk/models` to read schema hash
  (`0x0D045687`) and column data types.
- `reference/mod-constructor-5/Constructor5.Elements/Buffs/Buff.cs` (no LICENSE) —
  read-only. Behavioral confirmation of column meaning; not copied.

## Schema (EA-canonical)

- Schema hash: `0x0D045687`.
- Columns (10): `audio_sting_on_add`, `audio_sting_on_remove`,
  `buff_description`, `buff_name`, `icon`, `mood_type`, `mood_weight`,
  `timeout_string`, `timeout_string_no_next_buff`, `ui_sort_order`.

## Mapping rules

| Tuning slot | SimData column | Type |
|---|---|---|
| `<T n="buff_name">0xXXXX</T>` | `buff_name` | LocalizationKey |
| `<T n="buff_description">…</T>` | `buff_description` | LocalizationKey |
| `<T n="icon">type-group-instance</T>` | `icon` | ResourceKey |
| `<T n="mood_type">…</T>` | `mood_type` | TableSetReference (mood tuning) |
| `<T n="mood_weight">1</T>` | `mood_weight` | Int32 |
| `<T n="ui_sort_order">1</T>` | `ui_sort_order` | Int32 |
| audio stings | `audio_sting_on_{add,remove}` | ResourceKey |
| timeout strings | `timeout_string{,_no_next_buff}` | LocalizationKey |

All other tuning fields on Buff (effects, broadcasters, autonomy modifiers,
etc.) are tuning-only — they do not appear in SimData.

## Notes

The HistorianCareer mod does NOT define a custom Buff in v0.1 (it reuses
EA's `loot.buff_Focused_Low` from `trait_HabilitationRenown.xml`'s
`loot_on_trait_add`). The Buff schema is shipped for users of `simdata`
who DO author custom buffs; we have no internal use case to test it.
