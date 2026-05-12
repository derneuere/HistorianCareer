// Helper: load a TDESC JSON fixture once at module init and parse it into a
// frozen TdescSchema. File I/O at module init is acceptable per the project's
// pure-functional discipline rules (the resulting schema object is pure).
//
// The path is resolved relative to this file so it works from both source and
// compiled `dist/` builds (test/fixtures/ is committed and stays at the project
// root).

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseTdescJson } from "../../tdesc/parseJson.js";
import { deepFreeze } from "../../tdesc/types.js";
import type { TdescColumn, TdescSchema } from "../../tdesc/types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

// Walk up from /src/build/classes/ (or /dist/build/classes/) to the simdata
// project root, then into test/fixtures/tdescs/.
const TDESC_DIR = join(__dirname, "..", "..", "..", "test", "fixtures", "tdescs");

/** Load and parse one TDESC fixture by filename (e.g. "Aspiration.tdesc.json"). */
export function loadTdescFixture(filename: string): TdescSchema {
  const path = join(TDESC_DIR, filename);
  const json = readFileSync(path, "utf8");
  return parseTdescJson(json);
}

/**
 * Helper: produce a new TdescSchema with the className overridden. Useful
 * when the TDESC's `class` attribute doesn't match the tuning XML's `c=` (e.g.
 * CareerTrack.tdesc declares class="TunableCareerTrack" but tuning uses
 * c="CareerTrack").
 */
export function withClassName(schema: TdescSchema, className: string): TdescSchema {
  return deepFreeze({
    className,
    classPath: schema.classPath,
    rootColumns: schema.rootColumns,
  });
}

/**
 * Helper: produce a new TdescSchema with extra columns appended to the
 * existing rootColumns (typically for columns that the TDESC doesn't cover but
 * the SimData binary requires, e.g. `ages`/`genders`/`species`/`bb_filter_tags`
 * for Trait which EA persists despite missing `export_modes`).
 */
export function withAdditionalColumns(
  schema: TdescSchema,
  extras: readonly TdescColumn[],
): TdescSchema {
  return deepFreeze({
    className: schema.className,
    classPath: schema.classPath,
    rootColumns: [...schema.rootColumns, ...extras],
  });
}

/**
 * Helper: produce a new TdescSchema that includes ONLY the named columns
 * (and marks them all `persistedToSimData: true`, preserving the parsed type
 * info). Drops everything else. Used to bridge from "everything the TDESC
 * declares" to "exactly the v0.1 column set" for byte-match preservation.
 */
export function selectColumns(
  schema: TdescSchema,
  selection: readonly string[],
): TdescSchema {
  const byName = new Map(schema.rootColumns.map((c) => [c.name, c] as const));
  const missing: string[] = [];
  const cols: TdescColumn[] = [];
  for (const name of selection) {
    const col = byName.get(name);
    if (!col) {
      missing.push(name);
      continue;
    }
    cols.push({ ...col, persistedToSimData: true });
  }
  if (missing.length > 0) {
    throw new Error(
      `selectColumns(${schema.className}): missing from TDESC: ${missing.join(", ")}`,
    );
  }
  return deepFreeze({
    className: schema.className,
    classPath: schema.classPath,
    rootColumns: cols,
  });
}
