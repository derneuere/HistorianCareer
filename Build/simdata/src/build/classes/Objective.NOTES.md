# Objective.NOTES.md

## Sources

- `reference/mod-constructor-5/Constructor5.Elements/Objectives/` (no LICENSE) — read-only.
- `HistorianCareer/Tuning/objective_HC_*.xml`.

## Schema

| Column | Type |
|---|---|
| `display_text` | LocalizationKey |
| `goal_value` | Int32 (default 1) |
| `icon` | ResourceKey |

EA's real Objective tuning has many more fields — `objective_test` (a Variant
selecting a test type), `tested_per_sim`, `disabled_states`, etc. — but
S4S's Objective SimData typically exposes only the trio above, with the test
logic remaining tuning-only.

## Mapping rules

The tuning XML pattern `<V n="goal_value" t="absolute"><T n="absolute">N</T></V>`
collapses to `goal_value = N` in SimData. Our generic build doesn't follow the
variant indirection cleanly; for v0.1 it emits the default (1). If your
objectives rely on non-trivial goal_values, set them via the SimData column
directly after build, or extend the Objective builder.

## Notes for HistorianCareer

Our 6 objective_HC_*.xml files each yield ~250-byte SimData. The display text
keys (HC_OBJ_READ_BOOK, etc.) are defined in `Build/s4tk-builder/strings.json`
and resolved via FNV-32 by the integration layer.
