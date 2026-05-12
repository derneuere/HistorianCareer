// scripts/find-aspiration-reward.mjs
// One-shot helper to find AspirationReward tunings that look knowledge-themed.

import { promises as fs } from "node:fs";
import path from "node:path";

const { Package, CombinedTuningResource } = await import("@s4tk/models");
const { BinaryResourceType } = await import("@s4tk/models/enums.js");

const COMBINED_TUNING_TYPES = new Set([
    BinaryResourceType.CombinedTuning,
    0x62E94D38,
]);

function readClass(xml) { return xml.match(/<I\s+[^>]*\bc="([^"]+)"/)?.[1] ?? null; }
function readInstance(xml) { try { return BigInt(xml.match(/<I\s+[^>]*\bs="([^"]+)"/)?.[1]); } catch { return null; } }
function readName(xml) { return xml.match(/<I\s+[^>]*\bn="([^"]+)"/)?.[1] ?? null; }
function readI(xml) { return xml.match(/<I\s+[^>]*\bi="([^"]+)"/)?.[1] ?? null; }

async function main() {
    const args = process.argv.slice(2);
    const gameDir = args[args.indexOf("--game-dir") + 1];
    const pkgPath = path.join(gameDir, "Data", "Simulation", "SimulationFullBuild0.package");
    const buf = await fs.readFile(pkgPath);
    const pkg = Package.from(buf);
    const ctEntry = pkg.entries.find(e => COMBINED_TUNING_TYPES.has(e.key.type));
    const xmls = CombinedTuningResource.extractTuning(ctEntry.value.getBuffer());

    const classCounts = new Map();
    const motorRewardCandidate = []; // Track_Motor referenced reward 27500 — let's see what it is
    const trackMotorRewardId = 27500n;
    const interesting = []; // anything reward-class
    for (const xml of xmls) {
        const c = xml.content;
        const cls = readClass(c) ?? "?";
        classCounts.set(cls, (classCounts.get(cls) ?? 0) + 1);
        const inst = readInstance(c);
        const name = readName(c) ?? "";
        const iAttr = readI(c);
        if (inst === trackMotorRewardId) {
            motorRewardCandidate.push({ cls, iAttr, name, instance: inst.toString() });
        }
        if (/reward/i.test(cls) && /knowledge|university|school|study|learn|smart|academic|book|library/i.test(name)) {
            interesting.push({ cls, iAttr, name, inst: inst?.toString() ?? "?" });
        }
    }

    console.log("[find] Track_Motor reward (id=27500) found:");
    for (const m of motorRewardCandidate) console.log("  -", JSON.stringify(m));

    console.log("\n[find] reward classes available:");
    for (const [k, v] of [...classCounts.entries()].filter(([k]) => /reward/i.test(k)).sort()) {
        console.log(`  - ${k} (${v})`);
    }

    console.log("\n[find] knowledge-themed rewards:");
    for (const r of interesting.slice(0, 30)) {
        console.log(`  - cls=${r.cls.padEnd(36)} n=${r.name.padEnd(50)} s=${r.inst}`);
    }
}

main().catch(err => { console.error(err); process.exit(1); });
