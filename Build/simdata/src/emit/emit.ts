// emitSimDataBuffer(ir) — wrap our IR in a `SimDataResource` and serialize.
//
// This is the only function in the pipeline that produces bytes. We treat the
// returned Buffer as a value (it's immutable for our purposes — Node's Buffer
// is technically mutable but the caller has no reason to mutate it).

// SimDataResource is a TS-style default export. With our NodeNext + esModuleInterop
// settings, importing via the package's main entry gives us a named binding that
// TypeScript correctly treats as a class.
import { SimDataResource } from "@s4tk/models";
import type { SimDataIR } from "../build/types.js";

export function emitSimDataBuffer(ir: SimDataIR): Buffer {
  const resource = new SimDataResource({
    version: ir.version,
    unused: ir.unused,
    schemas: [...ir.schemas],
    instances: [...ir.instances],
  });
  return resource.getBuffer();
}

/**
 * Parse a SimData buffer back through `@s4tk/models`. Useful for round-trip
 * tests of our pipeline.
 */
export function parseSimDataBuffer(buffer: Buffer): SimDataResource {
  return SimDataResource.from(buffer);
}
