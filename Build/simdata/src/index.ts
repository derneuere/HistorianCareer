// simdata — convert Sims 4 tuning XML into SimData binaries.
//
// Public API:
//   parseTdesc(xml: string): TdescSchema
//   parseTuning(xml: string): TuningTree
//   buildSimData(schema: TdescSchema, tree: TuningTree): SimDataIR
//   emitSimDataBuffer(ir: SimDataIR): Buffer
//
// The pipeline is deliberately split into pure transforms so each stage is
// trivially testable. Side effects (file I/O, fetches) live under `./io`.

export { parseTdesc } from "./tdesc/parse.js";
export type {
  TdescSchema,
  TdescType,
  TdescColumn,
  TdescScalarKind,
} from "./tdesc/types.js";

export { parseTuning } from "./tuning/parse.js";
export type {
  TuningTree,
  TuningNode,
  TuningTNode,
  TuningENode,
  TuningVNode,
  TuningUNode,
  TuningLNode,
} from "./tuning/types.js";

export { buildSimData, createBuildContext } from "./build/build.js";
export type { SimDataIR, BuildContext } from "./build/types.js";

export {
  buildSimDataForTuning,
  supportedClasses,
  KNOWN_SCHEMA_HASHES,
} from "./build/classes/index.js";

export { emitSimDataBuffer, parseSimDataBuffer } from "./emit/emit.js";
