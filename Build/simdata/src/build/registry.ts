// Per-class registry. Each supported tuning class has an entry that maps it to
// (a) a hand-authored schema and (b) optionally a custom build function for
// edge cases the schema-driven generic build can't handle.
//
// The registry is populated lazily by side-effect of importing the per-class
// modules under `./classes/`. We don't auto-import the whole directory to keep
// the dependency graph explicit and tree-shakable.

import type { TdescSchema } from "../tdesc/types.js";
import type { ClassSchemaDef } from "./types.js";

const REGISTRY = new Map<string, RegistryEntry>();

export interface RegistryEntry {
  /** The class name as it appears in `c=` on a tuning <I> root. */
  readonly className: string;
  /**
   * The hand-authored schema for this class. Generated from EA-style SimData
   * XML samples or from reading EA-equivalent reference material. Treat as
   * canonical for our build pipeline.
   */
  readonly schema: TdescSchema;
  /**
   * Optional override of the generic schema-driven build. If present, used
   * instead of `buildSimData(schema, tree)`.
   */
  readonly customBuild?: ClassSchemaDef["build"];
}

/** Register a class. Call once per class on module load. */
export function registerClass(entry: RegistryEntry): void {
  if (REGISTRY.has(entry.className)) {
    throw new Error(`Class "${entry.className}" already registered.`);
  }
  REGISTRY.set(entry.className, entry);
}

/** Look up a registered class by its tuning `c=` name. */
export function getRegisteredClass(className: string): RegistryEntry | undefined {
  return REGISTRY.get(className);
}

/** Get the names of all registered classes (in insertion order). */
export function listRegisteredClasses(): readonly string[] {
  return Array.from(REGISTRY.keys());
}

/** Test-only: reset the registry. */
export function _resetRegistry(): void {
  REGISTRY.clear();
}
