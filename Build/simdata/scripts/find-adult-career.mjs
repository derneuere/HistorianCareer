// scripts/find-adult-career.mjs
// Find an Adult Career and print its career_affordance, go_home_to_work_affordance,
// and career_messages references.

import { promises as fs } from "node:fs";
import path from "node:path";

const { Package, CombinedTuningResource } = await import("@s4tk/models");
const { BinaryResourceType } = await import("@s4tk/models/enums.js");

const COMBINED_TUNING_TYPES = new Set([BinaryResourceType.CombinedTuning, 0x62E94D38]);

function readClass(x) { return x.match(/<I\s+[^>]*\bc="([^"]+)"/)?.[1] ?? null; }
function readInstance(x) { try { return BigInt(x.match(/<I\s+[^>]*\bs="([^"]+)"/)?.[1]); } catch { return null; } }
function readName(x) { return x.match(/<I\s+[^>]*\bn="([^"]+)"/)?.[1] ?? null; }

async function main() {
    const args = process.argv.slice(2);
    const gameDir = args[args.indexOf("--game-dir") + 1];
    const targetName = args[args.indexOf("--name") + 1] ?? null;
    const pkgPath = path.join(gameDir, "Data", "Simulation", "SimulationFullBuild0.package");
    const buf = await fs.readFile(pkgPath);
    const pkg = Package.from(buf);
    const ctEntry = pkg.entries.find(e => COMBINED_TUNING_TYPES.has(e.key.type));
    const xmls = CombinedTuningResource.extractTuning(ctEntry.value.getBuffer());

    const careers = [];
    for (const xml of xmls) {
        const c = xml.content;
        if (readClass(c) !== "Career") continue;
        const name = readName(c) ?? "";
        if (targetName && name !== targetName) continue;
        const inst = readInstance(c);
        const categoryMatch = c.match(/<E n="career_category">([^<]+)<\/E>/);
        const cat = categoryMatch?.[1];
        if (cat !== "CAREER" && !targetName) continue; // adult-only careers
        const careerAffordance = c.match(/<T n="career_affordance">(\d+)<\/T>/)?.[1];
        const goHome = c.match(/<T n="go_home_to_work_affordance">(\d+)<\/T>/)?.[1];
        careers.push({ name, inst: inst?.toString() ?? "?", cat, careerAffordance, goHome, body: c });
    }

    console.log(`[find] ${careers.length} adult Career(s):`);
    for (const c of careers.slice(0, 20)) {
        console.log(`  - ${c.name.padEnd(32)} s=${c.inst.padEnd(6)} cat=${c.cat?.padEnd(15)} aff=${c.careerAffordance} goHome=${c.goHome}`);
    }
    if (targetName && careers.length === 1) {
        console.log("\n=== body ===");
        console.log(careers[0].body);
    }
}

main().catch(err => { console.error(err); process.exit(1); });
