# CareerChanceCard.NOTES.md

## Sources

- `reference/mod-constructor-5/Constructor5.Elements/CareerEvents/` (no LICENSE) — read-only.
- `HistorianCareer/Tuning/career_chance_card_Historian_Plagiarism.xml`.

## Schema (v0.1 minimal)

| Column | Type |
|---|---|
| `title` | LocalizationKey |
| `description` | LocalizationKey |

The full EA CareerChanceCard tuning has `response_option_a/b` tuples each
containing display text and outcome loot lists. These are tuning-only in the
sense that EA stores the option text inside the tuning XML (the game reads
them at runtime); the SimData minimal pair is what S4S generates.

## Notes

The HistorianCareer plagiarism card has a nested `<V t="random">` outcome
randomizer (50/50 stonewall result). This nested logic is fully tuning-side
and not exposed to SimData.

If a future v1.x needs `response_option_a`/`response_option_b` as nested
Object cells in SimData, extend the schema with two TunableTuple columns
and add a custom builder to walk the tuning <U n="response_option_a"> /
<U n="response_option_b"> children.
