# simdata

A small TypeScript library that converts a Sims 4 tuning XML resource into the
corresponding SimData binary that the game expects to ship alongside it. This
replaces the last step in our HistorianCareer build pipeline that previously
required Sims 4 Studio.

## What this does

EA's tuning system pairs many tuning resources with a SimData binary:
`Career`, `CareerTrack`, `CareerLevel`, `Aspiration`, `AspirationTrack`,
`AspirationCareer`, `Trait`, `Objective`, `CareerChanceCard`, `Buff`, and a
handful of others. The SimData contains the fields the UI reads at runtime —
typically display name, description, icon refs, a handful of typed values. The
XML and SimData must agree, and the game refuses to load a tuning that declares
it has a SimData companion but doesn't.

`simdata` consumes a tuning XML and produces a SimData buffer, leaning on the
upstream `@s4tk/models` library for the binary-level format and supplying our
own per-class schema mapping for the 10 classes in scope (the 9 from the
HistorianCareer plan plus `Buff`).

## Quickstart (programmatic)

```ts
import { promises as fs } from "node:fs";
import { fnv32, fnv64 } from "@s4tk/hashing/hashing.js";
import {
  parseTuning,
  buildSimDataForTuning,
  createBuildContext,
  emitSimDataBuffer,
  KNOWN_SCHEMA_HASHES,
} from "simdata";

const xml = await fs.readFile("trait_HabilitationRenown.xml", "utf8");
const tree = parseTuning(xml);

const ctx = createBuildContext({
  // STBL keys (placeholder tokens like `0xTBD_STBL_KEY_FOO` in tuning XML).
  resolveStblKey: (token) => fnv32(token),
  // Tuning references — when a SimData column is a TableSetReference,
  // we resolve the tuning name to its FNV-64 instance ID.
  resolveTuningRef: (name) => fnv64(name, true),
  // Use EA's canonical schema_hash where we know it (Trait, Buff).
  knownSchemaHashes: KNOWN_SCHEMA_HASHES,
});

const ir = buildSimDataForTuning(tree, ctx);
const simData = emitSimDataBuffer(ir);
await fs.writeFile("trait_HabilitationRenown.simdata", simData);
```

## CLI

```bash
npx simdata trait_HabilitationRenown.xml --strings strings.json -o trait.simdata
npx simdata --list-classes
```

`--strings` points at a JSON file in the format used by HistorianCareer's
`Build/s4tk-builder/strings.json` (top-level keys are locale names like
`en`/`de`, each mapping STBL key tokens to translation strings).

## Supported classes

See `docs/supported-classes.md` for the full list and per-class notes. Briefly:

| Class | Coverage | Real EA fixture? |
|---|---|---|
| `Trait` | full, custom builder | yes — byte-tested |
| `Buff` | schema-driven | yes — schema-tested |
| `Aspiration` | schema-driven | no |
| `AspirationCareer` | schema-driven | no |
| `AspirationTrack` | schema-driven (with `aspiration_category` enum) | no |
| `Career` | schema-driven (with `career_category` enum) | no |
| `CareerTrack` | schema-driven | no |
| `CareerLevel` | schema-driven | no |
| `CareerChanceCard` | schema-driven, minimal columns | no |
| `Objective` | schema-driven | no |

## Architecture

```
parseTdesc       (or)  hand-authored schema
                          \
parseTuning  -->  buildSimData  -->  SimDataIR  -->  emitSimDataBuffer  -->  Buffer
                                                  (via @s4tk/models)
```

- `src/tdesc/` — `parseTdesc(xml)` and `TdescSchema` types. Pure.
- `src/tuning/` — `parseTuning(xml)` and `TuningTree` types. Pure.
- `src/build/` — `buildSimData(schema, tree, ctx)` and `buildSimDataForTuning(tree, ctx)`.
  - `cells.ts` — TdescType → `@s4tk/models` Cell factories.
  - `classes/` — per-class hand-authored schemas and (where needed) custom builders.
- `src/emit/` — `emitSimDataBuffer(ir)` — the only function that produces bytes.
- `src/io/`, `src/cli/` — side effects (file I/O, CLI).

## License

MIT. We depend only on MIT-licensed code (`@s4tk/models`, `@s4tk/hashing`,
`@s4tk/xml-dom`). Behavioral references from non-MIT sources (Mod-Constructor-5,
s4py) are read for understanding only; nothing is copy-pasted. Per-class
`*.NOTES.md` documents what was learned from each.

## Status

v0.1. Goldens are synthetic (round-trip through `@s4tk/models`) for everything
except Trait/Buff, where we have real EA binaries. Real game-loadability has
been verified for Trait+Buff structurally; the Career family produces packages
that load into a Package container, but in-game testing depends on a Sims 4
install we don't have in this environment.

The plan called for byte-equality with EA goldens for all 9 classes. We
achieved that for Trait (column-for-column structural equality against the
EA-canonical schema with hash `0xDE2EAF66`) and Buff (same approach against
`0x0D045687`). For the rest, the SimData round-trips cleanly through
`@s4tk/models` but cannot be byte-compared to an EA reference we don't have.
