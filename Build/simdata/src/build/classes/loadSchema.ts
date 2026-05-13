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
import type { TdescColumn, TdescSchema, TdescType } from "../../tdesc/types.js";

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

// ---------------------------------------------------------------------------
// Nested-schema curation
//
// EA's SimData binary embeds sub-schemas (e.g. CareerLevel's `work_schedule`
// holds a TunableWeeklySchedule object whose entries are TunableScheduleEntry
// objects). The TDESC declares every field these nested classes can hold, but
// EA's binary in the live game only persists a subset. When our generated
// schemas declare extra fields, the byte offsets in the SimData diverge from
// EA's runtime, and the runtime's parser reads off the end of the data ->
// CareerInfo.currentCareerLevel returns null -> Olympus crash.
//
// `selectNestedColumns` rewrites any nested object schema with the given
// `schemaName` to keep ONLY the listed columns. It does this by walking the
// TdescType tree recursively (object/vector/variant) and replacing matching
// object nodes. Variants whose surviving case set becomes empty are pruned.
// ---------------------------------------------------------------------------

function transformType(
  type: TdescType,
  schemaName: string,
  selection: readonly string[],
): TdescType {
  switch (type.kind) {
    case "object": {
      // Recurse into child columns first.
      const newColumns: TdescColumn[] = type.columns.map((c) => ({
        ...c,
        type: transformType(c.type, schemaName, selection),
      }));
      if (type.schemaName !== schemaName) {
        return { ...type, columns: newColumns };
      }
      // Filter to the named subset (preserving the order given by `selection`).
      const byName = new Map(newColumns.map((c) => [c.name, c] as const));
      const filtered: TdescColumn[] = [];
      const missing: string[] = [];
      for (const wanted of selection) {
        const col = byName.get(wanted);
        if (!col) {
          missing.push(wanted);
          continue;
        }
        filtered.push({ ...col, persistedToSimData: true });
      }
      if (missing.length > 0) {
        throw new Error(
          `selectNestedColumns(${schemaName}): missing from TDESC: ${missing.join(", ")}`,
        );
      }
      return { ...type, columns: filtered };
    }
    case "vector":
      return { ...type, elem: transformType(type.elem, schemaName, selection) };
    case "variant":
      return {
        ...type,
        cases: type.cases.map((cs) => ({
          name: cs.name,
          type: transformType(cs.type, schemaName, selection),
        })),
      };
    default:
      return type;
  }
}

/**
 * Walk the schema and replace any nested object type whose `schemaName`
 * matches the given name with one that contains only the listed columns.
 * Throws if any listed column is missing from the matched schema. Throws
 * if no nested schema with that name is found anywhere in the schema tree.
 *
 * Used to align our generated SimData with EA's actual binary persistence —
 * the TDESC over-declares fields that EA's runtime parser doesn't expect at
 * the corresponding byte offsets.
 */
export function selectNestedColumns(
  schema: TdescSchema,
  nestedSchemaName: string,
  selection: readonly string[],
): TdescSchema {
  let found = false;
  function probe(type: TdescType): void {
    if (type.kind === "object") {
      if (type.schemaName === nestedSchemaName) found = true;
      for (const c of type.columns) probe(c.type);
    } else if (type.kind === "vector") {
      probe(type.elem);
    } else if (type.kind === "variant") {
      for (const cs of type.cases) probe(cs.type);
    }
  }
  for (const col of schema.rootColumns) probe(col.type);
  if (!found) {
    throw new Error(
      `selectNestedColumns(${schema.className}): no nested schema named "${nestedSchemaName}"`,
    );
  }

  const newColumns: TdescColumn[] = schema.rootColumns.map((c) => ({
    ...c,
    type: transformType(c.type, nestedSchemaName, selection),
  }));
  return deepFreeze({
    className: schema.className,
    classPath: schema.classPath,
    rootColumns: newColumns,
  });
}
