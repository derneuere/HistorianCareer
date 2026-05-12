// In-memory IR for one SimData resource, in the exact shape `@s4tk/models`'s
// SimDataResource constructor expects.
//
// We keep this distinct from `SimDataDto` (the upstream type) so we have a
// stable, frozen, pure-data surface for our pipeline. The emit layer is the
// only place that touches @s4tk/models' classes.

import type { SimDataSchema, SimDataInstance } from "@s4tk/models/lib/resources/simdata/fragments.js";

/**
 * The output of `buildSimData()`. Hand this to `emitSimDataBuffer()` to get a
 * serializable Buffer.
 *
 * The shape mirrors `SimDataDto`: an array of schemas and an array of named
 * instances. The schemas and instances reference each other; they're produced
 * together by the build layer and shouldn't be edited after the fact.
 */
export interface SimDataIR {
  readonly version: number; // typically 0x101
  readonly unused: number; // typically 0
  readonly schemas: readonly SimDataSchema[];
  readonly instances: readonly SimDataInstance[];
}

/**
 * Context passed through the build recursion. Lets the recursive walker
 * share interned schemas across all uses in one SimData and resolve STBL/
 * resource keys uniformly.
 */
export interface BuildContext {
  /** Schemas already constructed, keyed by name. */
  readonly schemaCache: Map<string, SimDataSchema>;
  /** STBL key resolver: takes a `0xTBD_STBL_KEY_FOO` token and returns a uint32 STBL key. */
  readonly resolveStblKey: (token: string) => number;
  /** Tuning name → instance ID resolver: takes a tuning resource name and returns the FNV-64. */
  readonly resolveTuningRef: (name: string) => bigint;
  /** Resource type → uint32 (used for TGI triples). Optional; falls back to ResourceKeyResolver. */
  readonly resolveResourceKey?: (token: string) => {
    type: number;
    group: number;
    instance: bigint;
  };
  /**
   * Per-schema-name override hashes. If set for a given schema name, the
   * `buildSchema()` helper uses this value instead of FNV-32(name)|0x80000000.
   * Used to match EA's exact schema_hash for byte-identical SimData output
   * on classes where we have a real binary fixture (Trait=0xDE2EAF66,
   * Buff=0x0D045687).
   */
  readonly knownSchemaHashes?: Readonly<Record<string, number>>;
}

/** Convenience: a class-name → schema definition lookup for the per-class registry. */
export interface ClassSchemaDef {
  /** The class name as it appears in the tuning XML's `c=` attribute. */
  readonly className: string;
  /**
   * A function that builds the SimData IR from a TuningTree. Each
   * supported class implements this. The function MUST be pure given its inputs.
   */
  readonly build: (
    tree: import("../tuning/types.js").TuningTree,
    ctx: BuildContext,
  ) => SimDataIR;
}
