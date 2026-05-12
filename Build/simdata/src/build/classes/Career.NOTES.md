# Career / CareerTrack / CareerLevel.NOTES.md

## Sources consulted

- `reference/mod-constructor-5/Constructor5.Elements/Careers/Career.cs` (no LICENSE) —
  read-only. Read for understanding; **not copied**. MC5 stamps values into
  pre-built `.data` templates rather than constructing schemas from scratch,
  so it's of limited help here — but it does confirm field names
  (`career_name`, `career_description`, `start_track`) match the tuning XML.
- `reference/mod-constructor-5/Constructor5.Elements/CareerLevels/CareerLevelSimDataPositions.cs` —
  read-only. Confirms the existence of `Name` (`level_title`), `Description`
  (`level_description`), `PerformanceStat`, `ObjectiveSet` fields in EA's
  CareerLevel SimData. Position offsets are not used by our pipeline.
- `HistorianCareer/Tuning/career_*.xml` and `career_level_*.xml` — our own
  tuning files; the column names came from these.

## Schemas

### `Career`
Columns: `career_name` (LocalizationKey), `career_description`
(LocalizationKey), `start_track` (TableSetReference), `career_category`
(enum mapped to Int64).

Not currently exported to SimData: `ages` (tuning is a CSV string;
EA SimData stores Vector<Int64> derived from a bitmask. We omit it for v0.1.).

### `CareerTrack`
One column: `career_levels` (Vector<TableSetReference>).

### `CareerLevel`
Columns: `level_title` (LocalizationKey), `level_description`
(LocalizationKey), `simoleons_per_hour` (Int32),
`work_performance_progress_per_completion` (Int32),
`schedule` (TableSetReference, points at a CareerSchedule snippet),
`level_aspiration` (TableSetReference, points at an AspirationCareer),
`gameplay_unlocks` (Vector<TableSetReference>).

Not currently exported: `outfit` — tuning XML's `<V n="outfit" t="default"/>`
is tuning-only; outfit assignment goes through a parallel CAS pipeline.

## Limitations

We have NO EA golden SimData binary for Career/CareerTrack/CareerLevel in this
environment. Our schema_hash is computed by `FNV-32(name) | 0x80000000`, not
EA's canonical hash. The game accepts this for game-loadability but won't
byte-match an EA reference.

If/when a maintainer extracts EA goldens (see `docs/extracting-goldens.md`),
they should add the canonical schema hashes to `KNOWN_SCHEMA_HASHES` in
`schemas.ts`.
