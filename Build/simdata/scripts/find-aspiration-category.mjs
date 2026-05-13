// scripts/find-aspiration-category.mjs
//
// One-shot helper: enumerate AspirationCategory tunings from the live game's
// CombinedTuning and print {name, instance(hex), instance(dec)}. Used to find
// the KNOWLEDGE category's instance ID for the HistorianCareer Bug D fix.
//
// Usage:
//   node scripts/find-aspiration-category.mjs --game-dir "C:/Program Files (x86)/Steam/steamapps/common/The Sims 4"

import { promises as fs } from "node:fs";
import path from "node:path";

const { Package, CombinedTuningResource } = await import("@s4tk/models");
const { BinaryResourceType } = await import("@s4tk/models/enums.js");

const COMBINED_TUNING_TYPES = new Set([
    BinaryResourceType.CombinedTuning,
    0x62E94D38,
]);

function parseArgs(argv) {
    const out = {};
    for (let i = 0; i < argv.length; i++) {
        const a = argv[i];
        if (a === "--game-dir") out.gameDir = argv[++i];
        else if (a === "--package") out.pkgName = argv[++i];
    }
    return out;
}

function readClass(xml) {
    const m = xml.match(/<I\s+[^>]*\bc="([^"]+)"/);
    return m?.[1] ?? null;
}
function readInstance(xml) {
    const m = xml.match(/<I\s+[^>]*\bs="([^"]+)"/);
    if (!m) return null;
    try { return BigInt(m[1]); } catch { return null; }
}
function readName(xml) {
    const m = xml.match(/<I\s+[^>]*\bn="([^"]+)"/);
    return m?.[1] ?? null;
}
function readModule(xml) {
    const m = xml.match(/<I\s+[^>]*\bm="([^"]+)"/);
    return m?.[1] ?? null;
}
function readI(xml) {
    const m = xml.match(/<I\s+[^>]*\bi="([^"]+)"/);
    return m?.[1] ?? null;
}

async function main() {
    const args = parseArgs(process.argv.slice(2));
    if (!args.gameDir) {
        console.error("Usage: node find-aspiration-category.mjs --game-dir <path>");
        process.exit(2);
    }
    const pkgName = args.pkgName ?? "SimulationFullBuild0.package";
    const pkgPath = path.join(args.gameDir, "Data", "Simulation", pkgName);

    console.log(`[find] opening ${pkgPath}`);
    const buf = await fs.readFile(pkgPath);
    const pkg = Package.from(buf);

    const ctEntry = pkg.entries.find(e => COMBINED_TUNING_TYPES.has(e.key.type));
    if (!ctEntry) throw new Error("No CombinedTuning resource");
    const xmls = CombinedTuningResource.extractTuning(ctEntry.value.getBuffer());

    const matches = [];
    const classes = new Map(); // diagnostic
    for (const xml of xmls) {
        const c = xml.content;
        const cls = readClass(c);
        if (!cls) continue;
        classes.set(cls, (classes.get(cls) ?? 0) + 1);
        const iAttr = readI(c);
        const mod = readModule(c);
        const name = readName(c) ?? "";
        // Match anything that looks like an aspiration category — try several heuristics
        const looksCategoryClass = /AspirationCategory|aspiration_category/i.test(cls);
        const looksCategoryI = iAttr && /aspiration.?category/i.test(iAttr);
        const looksCategoryMod = mod && /aspiration.*category|aspirations\.aspiration_categories/i.test(mod);
        const looksCategoryName = /aspiration_category|^Category_|category.*Knowledge|knowledge.*category/i.test(name);
        if (looksCategoryClass || looksCategoryI || looksCategoryMod || looksCategoryName) {
            const inst = readInstance(c);
            matches.push({ cls, iAttr, mod, name, instance: inst?.toString() ?? "?", instHex: inst?.toString(16) ?? "?" });
        }
    }

    console.log(`[find] ${matches.length} candidate tunings:`);
    for (const m of matches) {
        console.log(`  - c=${m.cls.padEnd(28)} i=${(m.iAttr ?? "?").padEnd(20)} n=${m.name.padEnd(40)} s=${m.instance} (0x${m.instHex})`);
    }

    // Print top class names containing 'aspiration' for diagnostics.
    const aspClasses = [...classes.entries()].filter(([k]) => /aspiration/i.test(k));
    console.log(`\n[find] all 'aspiration' classes:`);
    for (const [k, n] of aspClasses) {
        console.log(`  - ${k} (${n})`);
    }
}

main().catch(err => { console.error(err); process.exit(1); });
