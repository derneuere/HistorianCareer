// Class registry entry point.
//
// Importing this module wires every supported class into the registry as a
// side effect. Downstream code calls `buildSimDataForTuning(tree, ctx)` to
// dispatch to the right per-class strategy.

import { buildSimData } from "../build.js";
import { registerClass, getRegisteredClass, listRegisteredClasses } from "../registry.js";
import type { BuildContext, SimDataIR } from "../types.js";
import type { TuningTree } from "../../tuning/types.js";
import { buildTraitSimData, TRAIT_TDESC_SCHEMA } from "./Trait.js";
import {
  OBJECTIVE_SCHEMA,
  ASPIRATION_SCHEMA,
  ASPIRATION_CAREER_SCHEMA,
  ASPIRATION_TRACK_SCHEMA,
  CAREER_CHANCE_CARD_SCHEMA,
  CAREER_LEVEL_SCHEMA,
  CAREER_TRACK_SCHEMA,
  CAREER_SCHEMA,
  BUFF_SCHEMA,
  KNOWN_SCHEMA_HASHES,
} from "./schemas.js";

let registered = false;

function registerAll(): void {
  if (registered) return;
  registered = true;

  // Trait has a custom builder (handles trait_type enum-to-Int64 mapping and
  // requires explicit defaults for 12+ EA columns the tuning doesn't set).
  registerClass({
    className: "Trait",
    schema: TRAIT_TDESC_SCHEMA,
    customBuild: buildTraitSimData,
  });

  // The remaining classes use the generic schema-driven build.
  registerClass({ className: "Objective", schema: OBJECTIVE_SCHEMA });
  registerClass({ className: "Aspiration", schema: ASPIRATION_SCHEMA });
  registerClass({ className: "AspirationCareer", schema: ASPIRATION_CAREER_SCHEMA });
  registerClass({ className: "AspirationTrack", schema: ASPIRATION_TRACK_SCHEMA });
  registerClass({ className: "CareerChanceCard", schema: CAREER_CHANCE_CARD_SCHEMA });
  registerClass({ className: "CareerLevel", schema: CAREER_LEVEL_SCHEMA });
  // CAREER_TRACK_SCHEMA has className="TunableCareerTrack" (matches EA's
  // binary). The registry key is the tuning XML's `c=` value — register both
  // "CareerTrack" (HC convention) and "TunableCareerTrack" (EA convention).
  registerClass({ className: "CareerTrack", schema: CAREER_TRACK_SCHEMA });
  registerClass({ className: "TunableCareerTrack", schema: CAREER_TRACK_SCHEMA });
  registerClass({ className: "Career", schema: CAREER_SCHEMA });
  registerClass({ className: "Buff", schema: BUFF_SCHEMA });
}

/**
 * Build the SimData IR for a tuning tree using the registered builder for its
 * class. Throws if the class is not registered.
 */
export function buildSimDataForTuning(
  tree: TuningTree,
  ctx: BuildContext,
): SimDataIR {
  registerAll();
  const entry = getRegisteredClass(tree.rootClass);
  if (!entry) {
    throw new Error(
      `simdata: no class registered for "${tree.rootClass}". Supported: ${listRegisteredClasses().join(", ")}`,
    );
  }
  if (entry.customBuild) return entry.customBuild(tree, ctx);
  return buildSimData(entry.schema, tree, ctx);
}

/** Get the list of class names that have a registered builder. */
export function supportedClasses(): readonly string[] {
  registerAll();
  return listRegisteredClasses();
}

/** Re-export the EA-canonical schema hashes for use in BuildContext.knownSchemaHashes. */
export { KNOWN_SCHEMA_HASHES };
