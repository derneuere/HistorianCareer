// scripts/compare-against-goldens.mjs
// For each golden pair (tuning.xml, simdata) extracted from the live game:
//   1. Run our pipeline on the tuning XML to produce SimData.
//   2. Read EA's SimData with `@s4tk/models` and compare schema + structure.
//   3. Report per-class: schema hash match, column-set diff, byte-size.
//
// This is the diagnostic that turns issue #3 (extract goldens) into actionable
// information for issue #7 (schema hashes) and issue #4 (field names).

import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const { SimDataResource } = await import("@s4tk/models");
const lib = await import("../dist/index.js");
const { parseTuning, buildSimDataForTuning, createBuildContext, emitSimDataBuffer, KNOWN_SCHEMA_HASHES } = lib;
const { fnv32, fnv64 } = await import("@s4tk/hashing/hashing.js");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const GOLDEN = path.resolve(__dirname, "../test/golden");

// IMPORTANT: createBuildContext() must be called FRESH per resource. The
// schemaCache inside is mutated during a build; reusing leaks schemas across
// resources and `schemas[0]` on the next build no longer points to that
// resource's schema.
const freshCtx = () => createBuildContext({
    resolveStblKey: (key) => fnv32(key),
    resolveTuningRef: (name) => fnv64(name, true),
    knownSchemaHashes: KNOWN_SCHEMA_HASHES,
});

const classes = ["Trait", "Buff", "Career", "CareerTrack", "CareerLevel",
                 "Aspiration", "AspirationCareer", "AspirationTrack", "Objective"];

function fmtHash(n) { return "0x" + (n >>> 0).toString(16).toUpperCase().padStart(8, "0"); }
function setDiff(a, b) { return { onlyInA: a.filter(x => !b.includes(x)), onlyInB: b.filter(x => !a.includes(x)) }; }

for (const cls of classes) {
    const dir = path.join(GOLDEN, cls);
    const files = await fs.readdir(dir).catch(() => []);
    const xmlFile = files.find(f => f.endsWith(".tuning.xml"));
    const sdFile = files.find(f => f.endsWith(".simdata"));
    if (!xmlFile || !sdFile) { console.log(`${cls.padEnd(20)} (no golden)`); continue; }

    const tuningXml = await fs.readFile(path.join(dir, xmlFile), "utf8");
    const eaBuf = await fs.readFile(path.join(dir, sdFile));
    const eaSD = SimDataResource.from(eaBuf);
    const eaSchema = eaSD.instance.schema; // not schemas[0]: that may be a nested schema
    const eaCols = eaSchema.columns.map(c => c.name).sort();

    let ours, oursSD, oursSchema, oursCols, byteEqual = false, error = null;
    try {
        const tree = parseTuning(tuningXml);
        const ir = buildSimDataForTuning(tree, freshCtx());
        ours = emitSimDataBuffer(ir);
        oursSD = SimDataResource.from(ours);
        // Use the instance's schema, not schemas[0] — schemas[] holds nested
        // schemas too and order isn't guaranteed to put the class schema first.
        oursSchema = oursSD.instance.schema;
        oursCols = oursSchema.columns.map(c => c.name).sort();
        byteEqual = ours.length === eaBuf.length && ours.equals(eaBuf);
    } catch (e) {
        error = e.message;
    }

    console.log(`\n=== ${cls} ===`);
    console.log(`  golden       : ${xmlFile.replace(".tuning.xml", "")}`);
    console.log(`  EA schema    : ${fmtHash(eaSchema.hash)}  ${eaSchema.columns.length} cols`);
    if (error) {
        console.log(`  our build    : ERROR — ${error}`);
        continue;
    }
    console.log(`  our schema   : ${fmtHash(oursSchema.hash)}  ${oursSchema.columns.length} cols`);
    console.log(`  hash match   : ${oursSchema.hash === eaSchema.hash ? "✓" : "✗"}`);
    console.log(`  byte-equal   : ${byteEqual ? "✓" : `✗  (${ours.length}B vs ${eaBuf.length}B)`}`);

    const diff = setDiff(oursCols, eaCols);
    if (diff.onlyInA.length || diff.onlyInB.length) {
        if (diff.onlyInA.length) console.log(`  in OURS only : ${diff.onlyInA.join(", ")}`);
        if (diff.onlyInB.length) console.log(`  in EA only   : ${diff.onlyInB.join(", ")}`);
    } else {
        console.log(`  columns      : identical set`);
    }
}
