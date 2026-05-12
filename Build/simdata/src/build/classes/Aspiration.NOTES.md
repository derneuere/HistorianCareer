# Aspiration / AspirationCareer / AspirationTrack.NOTES.md

## Sources

- `reference/mod-constructor-5/Constructor5.Elements/Aspirations/` (no LICENSE) — read-only.
- `reference/mod-constructor-5/Constructor5.Elements/AspirationTracks/AspirationTrack.cs` (no LICENSE) — read-only.
- `HistorianCareer/Tuning/aspiration_*.xml` and `aspiration_track_*.xml` — our own tuning.

Mod-Constructor-5 was read for behavioral confirmation only; **no code copied**.
The Aspiration column names and types are widely known from S4S's
"Generate SimData" output and from EA's tuning XML conventions.

## Schemas

### `Aspiration`
Columns: `display_name`, `display_description`, `objectives`, `reward`.

`reward` is a TableSetReference to a Reward tuning; left at 0 when absent.

### `AspirationCareer`
Career-level daily-task aspiration. Same fields as `Aspiration` minus
`reward`. EA actually allows a `reward` here too in newer game versions; we
omit it for v0.1 because the HistorianCareer aspiration_career_*.xml files
don't set one and including it would require a Variant column we haven't
modeled.

### `AspirationTrack`
The long-form aspiration container with an `aspiration_category` enum.

`aspiration_category` is one of EA's well-known categories (KNOWLEDGE, FAMILY,
LOVE, FORTUNE, …). Our enum table in `schemas.ts` lists the order we assume;
this may not match EA's exact int value but is consistent enough for
game-loadability.

## Notes for HistorianCareer

Our 4 long-aspiration tiers (T1..T4) plus 5 career-level daily-tasks (L1..L5)
are all consumed by this schema. They generate SimData buffers around 300–340
bytes, which is consistent with EA's tier-level aspirations of similar size.
