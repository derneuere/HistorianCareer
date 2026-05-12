// scripts/find-knowledge-track.mjs
// Find a knowledge-themed AspirationTrack and report its category, icon, reward.

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
    const pkgPath = path.join(gameDir, "Data", "Simulation", "SimulationFullBuild0.package");
    const buf = await fs.readFile(pkgPath);
    const pkg = Package.from(buf);
    const ctEntry = pkg.entries.find(e => COMBINED_TUNING_TYPES.has(e.key.type));
    const xmls = CombinedTuningResource.extractTuning(ctEntry.value.getBuffer());

    const tracks = [];
    for (const xml of xmls) {
        const c = xml.content;
        if (readClass(c) !== "AspirationTrack") continue;
        const name = readName(c) ?? "";
        const inst = readInstance(c);
        const catMatch = c.match(/<T n="category">(\d+)<\/T>/);
        const rewardMatch = c.match(/<T n="reward">(\d+)<\/T>/);
        const iconMatch = c.match(/<T n="icon"[^>]*>([0-9a-fA-F:]+)<\/T>/);
        tracks.push({ name, inst: inst?.toString() ?? "?", cat: catMatch?.[1], reward: rewardMatch?.[1], icon: iconMatch?.[1] });
    }

    console.log(`[find] ${tracks.length} AspirationTracks:`);
    for (const t of tracks) {
        // Asp_Cat_Knowledge id is 25385
        const isKnowledge = t.cat === "25385";
        console.log(`${isKnowledge ? "** " : "   "}${t.name.padEnd(36)} cat=${(t.cat ?? "?").padEnd(6)} reward=${(t.reward ?? "?").padEnd(6)} icon=${t.icon ?? "?"}`);
    }
}

main().catch(err => { console.error(err); process.exit(1); });
