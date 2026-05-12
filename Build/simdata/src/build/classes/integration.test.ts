// Integration test: walk every HistorianCareer tuning XML that the game
// expects to have a SimData companion, run it through our pipeline, and
// verify the resulting buffer round-trips cleanly through @s4tk/models.
//
// This is the "does the build pipeline produce a loadable SimData?" test
// for Layer B. Byte-equality with EA is checked separately for Trait/Buff
// where we have ground-truth binaries.

import { describe, expect, it } from "vitest";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fnv32, fnv64 } from "@s4tk/hashing/hashing.js";
import { parseTuning } from "../../tuning/parse.js";
import { createBuildContext } from "../build.js";
import { emitSimDataBuffer, parseSimDataBuffer } from "../../emit/emit.js";
import { buildSimDataForTuning, KNOWN_SCHEMA_HASHES, supportedClasses } from "./index.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const HC_TUNING_DIR = path.resolve(__dirname, "../../../../../Tuning");

const CLASSES_THAT_NEED_SIMDATA = new Set([
  "Career", "CareerTrack", "CareerLevel",
  "Aspiration", "AspirationTrack", "AspirationCareer",
  "Trait", "Objective", "CareerChanceCard",
]);

describe("class registry — Layer B integration", () => {
  it("registers all 9 v0.1 classes", () => {
    const classes = supportedClasses();
    expect(classes).toContain("Trait");
    expect(classes).toContain("Buff");
    expect(classes).toContain("Career");
    expect(classes).toContain("CareerTrack");
    expect(classes).toContain("CareerLevel");
    expect(classes).toContain("Aspiration");
    expect(classes).toContain("AspirationTrack");
    expect(classes).toContain("AspirationCareer");
    expect(classes).toContain("CareerChanceCard");
    expect(classes).toContain("Objective");
  });

  it("builds and round-trips a SimData for every Layer-B HistorianCareer tuning", async () => {
    const files = (await fs.readdir(HC_TUNING_DIR)).filter(
      (f) => f.endsWith(".xml") && !f.startsWith("_"),
    );
    const ctx = createBuildContext({
      resolveStblKey: (token) => fnv32(token),
      resolveTuningRef: (name) => fnv64(name, true),
      knownSchemaHashes: KNOWN_SCHEMA_HASHES,
    });

    let processed = 0;
    let skipped = 0;
    const failures: { file: string; error: string }[] = [];

    for (const file of files) {
      const xml = await fs.readFile(path.join(HC_TUNING_DIR, file), "utf8");
      const tree = parseTuning(xml);
      if (!CLASSES_THAT_NEED_SIMDATA.has(tree.rootClass)) {
        skipped++;
        continue;
      }

      try {
        // Fresh schemaCache per build (don't leak schemas across resources).
        const localCtx = createBuildContext({
          resolveStblKey: ctx.resolveStblKey,
          resolveTuningRef: ctx.resolveTuningRef,
          knownSchemaHashes: KNOWN_SCHEMA_HASHES,
        });
        const ir = buildSimDataForTuning(tree, localCtx);
        const buffer = emitSimDataBuffer(ir);
        expect(buffer.byteLength).toBeGreaterThan(0);
        const parsed = parseSimDataBuffer(buffer);
        expect(parsed.schemas.length).toBeGreaterThanOrEqual(1);
        expect(parsed.instances).toHaveLength(1);
        expect(parsed.instances[0]!.name).toBe(tree.instanceName);
        processed++;
      } catch (err) {
        failures.push({
          file,
          error: (err as Error).message,
        });
      }
    }

    if (failures.length > 0) {
      throw new Error(
        `${failures.length} Layer-B tunings failed to build:\n` +
          failures.map((f) => `  - ${f.file}: ${f.error}`).join("\n"),
      );
    }

    // Sanity: we expect a non-trivial number of Layer-B files.
    expect(processed).toBeGreaterThanOrEqual(15);
    // And the skipped count should be > 0 (we have Layer A files too).
    expect(skipped).toBeGreaterThan(0);
  });
});
