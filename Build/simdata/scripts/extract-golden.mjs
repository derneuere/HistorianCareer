// scripts/extract-golden.mjs
//
// Pull paired (tuning XML, SimData binary) fixtures from a Sims 4 game install.
// For each target tuning class we extract ONE example resource and write both
// the XML and the SimData binary to test/golden/<className>/.
//
// These goldens turn round-trip SimData tests into byte-equality tests against
// EA's actual binaries — the gold standard for validating our simdata library.
//
// Usage:
//   node scripts/extract-golden.mjs --game-dir "C:/Program Files (x86)/Steam/steamapps/common/The Sims 4"
//   node scripts/extract-golden.mjs --game-dir <path> --class Career --class Trait
//
// Output layout (per class):
//   test/golden/Career/career_Adult_Astronaut.tuning.xml
//   test/golden/Career/career_Adult_Astronaut.simdata

import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const { Package, CombinedTuningResource } = await import("@s4tk/models");
const { BinaryResourceType } = await import("@s4tk/models/enums.js");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const GOLDEN_DIR = path.resolve(__dirname, "../test/golden");

// The 9 classes our simdata library currently builds for. We want one
// example per class. List is also the order in which we report results.
const DEFAULT_CLASSES = [
    "Trait", "Buff",
    "Career", "CareerTrack", "CareerLevel",
    "Aspiration", "AspirationCareer", "AspirationTrack",
    "Objective",
];

// The CombinedTuning resource type. @s4tk/models has a value in its enum but
// EA's actual data uses a different hex (varies per game/version), so accept
// either: anything whose value matches the enum OR these known variants.
const COMBINED_TUNING_TYPES = new Set([
    BinaryResourceType.CombinedTuning, // 0x62ECC59A per @s4tk
    0x62E94D38, // observed in current Steam install of base game
]);

const HELP = `Usage: node scripts/extract-golden.mjs --game-dir <path-to-game> [--class Career] [--class Trait] ...

Extracts paired (tuning XML, SimData binary) fixtures from a Sims 4 game
install and writes them under test/golden/<className>/.

Flags:
  --game-dir <path>    Path to your Sims 4 install (the folder containing Data/).
  --class <Name>       Restrict to one or more classes. May repeat. Default: all 9.
  --package <name>     Which Data/Simulation/*.package to read. Default: SimulationFullBuild0.package.
  --help, -h           This text.
`;

// ---------------- pure helpers ---------------------------------------------

function parseArgs(argv) {
    const out = {};
    for (let i = 0; i < argv.length; i++) {
        const a = argv[i];
        if (a === "--game-dir") out.gameDir = argv[++i];
        else if (a === "--class") (out.classes ??= []).push(argv[++i]);
        else if (a === "--package") out.pkgName = argv[++i];
        else if (a === "--help" || a === "-h") out.help = true;
    }
    return out;
}

/** Read the class name from the root <I c="..."> attribute. */
export function readClass(xmlContent) {
    const m = xmlContent.match(/<I\s+[^>]*\bc="([^"]+)"/);
    return m?.[1] ?? null;
}

/** Read the tuning instance ID from <I s="..."> (decimal in EA's XML). */
export function readInstance(xmlContent) {
    const m = xmlContent.match(/<I\s+[^>]*\bs="([^"]+)"/);
    if (!m) return null;
    try { return BigInt(m[1]); } catch { return null; }
}

/** Read the tuning name from <I n="..."> (used for the output filename). */
export function readName(xmlContent) {
    const m = xmlContent.match(/<I\s+[^>]*\bn="([^"]+)"/);
    return m?.[1] ?? null;
}

// ---------------- main -----------------------------------------------------

async function main() {
    const args = parseArgs(process.argv.slice(2));
    if (args.help || !args.gameDir) {
        process.stdout.write(HELP);
        process.exit(args.help ? 0 : 2);
    }
    const wantedClasses = new Set(args.classes ?? DEFAULT_CLASSES);
    const pkgName = args.pkgName ?? "SimulationFullBuild0.package";
    const pkgPath = path.join(args.gameDir, "Data", "Simulation", pkgName);

    console.log(`[extract] opening ${pkgPath}`);
    const buf = await fs.readFile(pkgPath);
    const pkg = Package.from(buf);
    console.log(`[extract] ${pkg.size} resources in package`);

    // Step 1: find the CombinedTuning entry and extract all tuning XMLs.
    const ctEntry = pkg.entries.find(e => COMBINED_TUNING_TYPES.has(e.key.type));
    if (!ctEntry) {
        throw new Error(`No CombinedTuning resource found (expected one of types ${[...COMBINED_TUNING_TYPES].map(t => "0x" + t.toString(16)).join(", ")})`);
    }
    console.log(`[extract] CombinedTuning at type=0x${ctEntry.key.type.toString(16)} instance=0x${ctEntry.key.instance.toString(16)}`);

    console.log(`[extract] expanding combined tuning…`);
    const xmls = CombinedTuningResource.extractTuning(ctEntry.value.getBuffer());
    console.log(`[extract] ${xmls.length} individual tuning XML resources extracted`);

    // Step 2: index by instance ID and bucket by class.
    /** Map<bigint instance, {className, name, xml, content}> */
    const byInstance = new Map();
    /** Map<className, Array<{instance, name, content}>> */
    const byClass = new Map();
    let unparsable = 0;
    for (const xml of xmls) {
        const content = xml.content;
        const className = readClass(content);
        const instance = readInstance(content);
        const name = readName(content);
        if (!className || instance == null) { unparsable++; continue; }
        const rec = { className, name, instance, content };
        byInstance.set(instance, rec);
        if (!byClass.has(className)) byClass.set(className, []);
        byClass.get(className).push(rec);
    }
    if (unparsable) console.log(`[extract] ${unparsable} XMLs missing class or instance, skipped`);
    console.log(`[extract] distinct classes in package: ${byClass.size}`);

    // Step 3: index SimData entries by instance.
    /** Map<bigint instance, Buffer> */
    const simdataByInstance = new Map();
    for (const e of pkg.entries) {
        if (e.key.type === BinaryResourceType.SimData) {
            simdataByInstance.set(e.key.instance, e.value.getBuffer());
        }
    }
    console.log(`[extract] ${simdataByInstance.size} SimData entries`);

    // Step 4: per wanted class, find the first entry that ALSO has a matching SimData.
    await fs.mkdir(GOLDEN_DIR, { recursive: true });
    let saved = 0, missingSimData = 0, missingClass = 0;
    const summary = [];

    for (const klass of wantedClasses) {
        const records = byClass.get(klass);
        if (!records || records.length === 0) {
            console.log(`[X] ${klass.padEnd(20)} no tunings of this class found in package`);
            missingClass++;
            summary.push({ klass, status: "no-tuning" });
            continue;
        }

        // Prefer ones that ALSO have SimData. There's usually many; pick one.
        const withSimData = records.find(r => simdataByInstance.has(r.instance));
        if (!withSimData) {
            console.log(`[X] ${klass.padEnd(20)} ${records.length} tunings, but NONE have a paired SimData in this package`);
            missingSimData++;
            summary.push({ klass, status: "no-simdata", count: records.length });
            continue;
        }

        const outDir = path.join(GOLDEN_DIR, klass);
        await fs.mkdir(outDir, { recursive: true });
        const slug = (withSimData.name ?? `instance_${withSimData.instance.toString(16)}`).replace(/[^A-Za-z0-9_.-]/g, "_");
        const xmlPath = path.join(outDir, `${slug}.tuning.xml`);
        const sdPath  = path.join(outDir, `${slug}.simdata`);
        await fs.writeFile(xmlPath, withSimData.content, "utf8");
        await fs.writeFile(sdPath, simdataByInstance.get(withSimData.instance));

        const sdSize = simdataByInstance.get(withSimData.instance).length;
        console.log(`[ok] ${klass.padEnd(20)} ${slug.padEnd(45)} xml=${withSimData.content.length}B simdata=${sdSize}B  (${records.length} candidates)`);
        saved++;
        summary.push({ klass, status: "ok", slug, name: withSimData.name, instance: withSimData.instance.toString(16) });
    }

    console.log("");
    console.log(`[summary] saved=${saved}  no-tuning=${missingClass}  no-simdata=${missingSimData}  (of ${wantedClasses.size} wanted)`);

    // Persist a manifest of what we found for any consumer.
    const manifestPath = path.join(GOLDEN_DIR, "_extracted.json");
    await fs.writeFile(manifestPath, JSON.stringify({ pkgPath, when: new Date().toISOString(), summary }, null, 2), "utf8");
    console.log(`[summary] wrote manifest → ${path.relative(path.dirname(__dirname), manifestPath)}`);
}

main().catch(err => {
    console.error(err);
    process.exit(1);
});
