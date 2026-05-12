// buildSimData(schema, tree) — pure transformation from a TdescSchema and a
// parsed TuningTree to a SimDataIR.
//
// In its general form, this function:
//   1. Constructs (or reuses cached) SimDataSchemas for every Object/Tuple type
//      referenced by the schema's columns.
//   2. Walks the tuning tree's top-level children, matching each to a column
//      by name, and emits a Cell for each persisted column.
//   3. Wraps the root cells in a SimDataInstance whose name is the tuning's
//      `n=` attribute.
//
// The caller supplies a BuildContext with resolvers for STBL keys and tuning-
// reference name → instance ID. This keeps the build layer free of I/O — the
// resolvers are pure once given their pre-computed lookups.

import { SimDataInstance } from "@s4tk/models/lib/resources/simdata/fragments.js";
import { ObjectCell } from "@s4tk/models/lib/resources/simdata/cells.js";
import type { TdescSchema } from "../tdesc/types.js";
import type { TuningTree, TuningNode } from "../tuning/types.js";
import type { BuildContext, SimDataIR } from "./types.js";
import { buildCell, buildSchema } from "./cells.js";

/** Default no-op resolvers. Used in tests where no STBL or tuning context is needed. */
export const NOOP_BUILD_CONTEXT: BuildContext = Object.freeze({
  schemaCache: new Map(),
  resolveStblKey: (token: string) => {
    throw new Error(`STBL token "${token}" requested but no resolver provided.`);
  },
  resolveTuningRef: (name: string) => {
    throw new Error(`Tuning reference "${name}" requested but no resolver provided.`);
  },
});

/**
 * Create a fresh BuildContext. Always call this rather than reusing one
 * across SimData builds: the schemaCache must be per-resource so that
 * cross-class symbol collisions don't leak.
 */
export function createBuildContext(
  partial: Partial<BuildContext> = {},
): BuildContext {
  return {
    schemaCache: new Map(),
    resolveStblKey:
      partial.resolveStblKey ??
      ((token: string) => {
        throw new Error(`STBL token "${token}" requested but no resolver provided.`);
      }),
    resolveTuningRef:
      partial.resolveTuningRef ??
      ((name: string) => {
        // Fallback: zero out unresolvable refs. The caller probably wants to
        // wire in `fnv64(name, true)` from `@s4tk/hashing`.
        throw new Error(`Tuning reference "${name}" requested but no resolver provided.`);
      }),
    ...(partial.resolveResourceKey !== undefined
      ? { resolveResourceKey: partial.resolveResourceKey }
      : {}),
    ...(partial.knownSchemaHashes !== undefined
      ? { knownSchemaHashes: partial.knownSchemaHashes }
      : {}),
  };
}

/**
 * Generic build: applies the TdescSchema directly. Per-class builders may call
 * this if their class is fully described by a TDESC; otherwise they hand-craft
 * the IR using the lower-level helpers in `./cells.ts`.
 */
export function buildSimData(
  schema: TdescSchema,
  tree: TuningTree,
  ctx: BuildContext = createBuildContext(),
): SimDataIR {
  // Schema first — this populates the cache and produces the top-level
  // SimDataSchema we'll attach to the instance.
  const topSchema = buildSchema(
    schema.className,
    schema.rootColumns,
    ctx,
  );

  // Build the row from the tuning tree.
  const childrenByName = new Map<string, TuningNode>();
  for (const child of tree.children) {
    if ("name" in child && child.name) {
      childrenByName.set(child.name, child);
    }
  }

  const row: Record<string, ReturnType<typeof buildCell>> = {};
  for (const col of schema.rootColumns) {
    if (!col.persistedToSimData) continue;
    const node = childrenByName.get(col.name);
    row[col.name] = buildCell(col, node, ctx);
  }

  const objCell = new ObjectCell(topSchema, row);
  const instance = SimDataInstance.fromObjectCell(tree.instanceName, objCell);

  // Collect all schemas referenced — they may include nested ones from
  // the cache. EA's SimData binary requires every referenced schema to
  // appear in the Schemas array.
  const schemas = Array.from(ctx.schemaCache.values());

  return Object.freeze({
    version: 0x101,
    unused: 0,
    schemas,
    instances: [instance],
  });
}
