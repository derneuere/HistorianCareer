// extract-writer-ref.mjs — pull every Writer-related EA tuning XML + matching
// SimData binary out of the user's Sims 4 install into Build/_research_tmp/
// for byte-level comparison against our HistorianCareer files. Gitignored.
//
// Sources:
//   Data/Simulation/SimulationFullBuild0.package  — CombinedTuning (all tuning XMLs)
//   Data/Client/ClientFullBuild0.package          — SimData binaries
//
// Usage (from Build/simdata, where @s4tk/models is installed):
//   node ../_research_tmp/extract-writer-ref.mjs

import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const { Package, CombinedTuningResource } = await import("@s4tk/models");
const { BinaryResourceType } = await import("@s4tk/models/enums.js");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, "..", "..", "_research_tmp", "writer-ref");
const SIM_PKG = "C:/Program Files (x86)/Steam/steamapps/common/The Sims 4/Data/Simulation/SimulationFullBuild0.package";
const CLI_PKG = "C:/Program Files (x86)/Steam/steamapps/common/The Sims 4/Data/Client/ClientFullBuild0.package";

const COMBINED_TUNING_TYPES = new Set([BinaryResourceType.CombinedTuning, 0x62E94D38]);
const SIMDATA_TYPE = 0x545AC67A;

const readClass    = x => x.match(/<I\s+[^>]*\bc="([^"]+)"/)?.[1] ?? null;
const readInstance = x => { try { return BigInt(x.match(/<I\s+[^>]*\bs="([^"]+)"/)?.[1]); } catch { return null; } };
const readName     = x => x.match(/<I\s+[^>]*\bn="([^"]+)"/)?.[1] ?? null;

function safeFilename(s) {
    return s.replace(/[^a-zA-Z0-9._-]/g, "_");
}

async function main() {
    await fs.mkdir(OUT_DIR, { recursive: true });

    // --- 1. Pull every tuning XML from the CombinedTuning blob -------------
    console.log(`[1/3] Reading ${path.basename(SIM_PKG)}`);
    const simBuf = await fs.readFile(SIM_PKG);
    const simPkg = Package.from(simBuf);
    const ctEntry = simPkg.entries.find(e => COMBINED_TUNING_TYPES.has(e.key.type));
    if (!ctEntry) throw new Error("CombinedTuning entry not found");
    const xmls = CombinedTuningResource.extractTuning(ctEntry.value.getBuffer());
    console.log(`      ${xmls.length} tuning XMLs in CombinedTuning`);

    // Collect any name matching "Writer", and also widen to references walked
    // from those. First pass: greedy name match. Second pass: scan for refs.
    const byName = new Map();        // name -> { name, cls, inst, content }
    const byInst = new Map();        // bigint inst -> entry
    for (const x of xmls) {
        const c = x.content;
        const name = readName(c);
        if (!name) continue;
        const cls = readClass(c);
        const inst = readInstance(c);
        const entry = { name, cls, inst, content: c };
        byName.set(name, entry);
        if (inst != null) byInst.set(inst, entry);
    }

    // Greedy "writer" filter, case-insensitive, for the initial seed set.
    // Also include the canonical CareerLevel/CareerTrack/Career classes for
    // ANY adult career that uses Writer-shape data (we'll only ship the writer
    // ones into the reference folder, but want everything that referenced
    // each other for the dependency walk).
    const SEED_PATTERNS = [
        /writer/i,
        /journalism/i,
        /author/i,
    ];
    const seedNames = new Set();
    for (const [name, e] of byName.entries()) {
        if (SEED_PATTERNS.some(rx => rx.test(name))) {
            seedNames.add(name);
        }
    }
    console.log(`      seed set (writer/journalism/author): ${seedNames.size} tunings`);

    // Walk references from the seed set. Each tuning XML mentions other
    // tunings by integer instance ID (e.g. `<T n="career_affordance">12345</T>`).
    // Collect those integers and look them up.
    const wanted = new Set(seedNames);
    let frontier = new Set(seedNames);
    for (let depth = 0; depth < 3 && frontier.size > 0; depth++) {
        const next = new Set();
        for (const n of frontier) {
            const entry = byName.get(n);
            if (!entry) continue;
            const refs = entry.content.match(/\b\d{4,20}\b/g) ?? [];
            for (const r of refs) {
                try {
                    const id = BigInt(r);
                    const refEntry = byInst.get(id);
                    if (!refEntry) continue;
                    if (wanted.has(refEntry.name)) continue;
                    // Only follow references whose classes are likely-relevant
                    // (avoids dragging in arbitrary skills/buffs).
                    const interestingClasses = new Set([
                        "Career", "CareerTrack", "TunableCareerTrack", "CareerLevel",
                        "Aspiration", "AspirationCareer", "AspirationTrack",
                        "Statistic", "Commodity", "Skill",
                        "Objective", "ObjectiveSet",
                        "LootActions", "LootActionSet",
                        "Buff",
                        "Trait",
                        "PieMenuCategory",
                    ]);
                    if (interestingClasses.has(refEntry.cls)) {
                        next.add(refEntry.name);
                        wanted.add(refEntry.name);
                    }
                } catch { /* not a valid int */ }
            }
        }
        frontier = next;
        console.log(`      walk depth ${depth + 1}: +${next.size} (total ${wanted.size})`);
    }

    // --- 2. Write the tuning XMLs ------------------------------------------
    console.log(`[2/3] Writing ${wanted.size} tuning XMLs to ${path.relative(process.cwd(), OUT_DIR)}/`);
    const tuningDir = path.join(OUT_DIR, "Tuning");
    await fs.mkdir(tuningDir, { recursive: true });
    // Also build a class-keyed index for easy lookup.
    const byClass = new Map();
    for (const name of wanted) {
        const e = byName.get(name);
        if (!e) continue;
        if (!byClass.has(e.cls)) byClass.set(e.cls, []);
        byClass.get(e.cls).push(e);
        const file = path.join(tuningDir, `${safeFilename(name)}.xml`);
        await fs.writeFile(file, e.content, "utf8");
    }
    // Print summary per class.
    for (const [cls, items] of [...byClass.entries()].sort((a,b) => b[1].length - a[1].length)) {
        console.log(`      ${cls.padEnd(22)} ${items.length}`);
    }

    // --- 3. Pull paired SimData binaries -----------------------------------
    console.log(`[3/3] Reading ${path.basename(CLI_PKG)} for SimData`);
    const cliBuf = await fs.readFile(CLI_PKG);
    const cliPkg = Package.from(cliBuf);
    // SimData instance IDs equal their tuning instance IDs.
    const simdataDir = path.join(OUT_DIR, "SimData");
    await fs.mkdir(simdataDir, { recursive: true });
    let sdMatches = 0;
    for (const e of cliPkg.entries) {
        if (e.key.type !== SIMDATA_TYPE) continue;
        const entry = byInst.get(e.key.instance);
        if (!entry || !wanted.has(entry.name)) continue;
        const sdName = `${safeFilename(entry.name)}.simdata`;
        const buf = e.value.getBuffer ? e.value.getBuffer() : e.value.buffer;
        if (!buf) continue;
        await fs.writeFile(path.join(simdataDir, sdName), buf);
        sdMatches++;
    }
    // Also try SimulationFullBuild0 — some SimData may live there too.
    for (const e of simPkg.entries) {
        if (e.key.type !== SIMDATA_TYPE) continue;
        const entry = byInst.get(e.key.instance);
        if (!entry || !wanted.has(entry.name)) continue;
        const sdName = `${safeFilename(entry.name)}.simdata`;
        const target = path.join(simdataDir, sdName);
        try { await fs.access(target); continue; } catch {}
        const buf = e.value.getBuffer ? e.value.getBuffer() : e.value.buffer;
        if (!buf) continue;
        await fs.writeFile(target, buf);
        sdMatches++;
    }
    console.log(`      wrote ${sdMatches} SimData binaries`);

    // --- index.md for human navigation ------------------------------------
    const md = [
        "# Writer career reference extract",
        "",
        `Extracted from ${path.basename(SIM_PKG)} + ${path.basename(CLI_PKG)} on ${new Date().toISOString().slice(0,10)}.`,
        `${wanted.size} tuning XMLs, ${sdMatches} SimData binaries.`,
        "",
        "## By class",
        "",
    ];
    for (const [cls, items] of [...byClass.entries()].sort((a,b) => a[0].localeCompare(b[0]))) {
        md.push(`### ${cls} (${items.length})`);
        md.push("");
        for (const e of items.sort((a,b) => a.name.localeCompare(b.name))) {
            md.push(`- \`${e.name}\` (s=${e.inst})`);
        }
        md.push("");
    }
    await fs.writeFile(path.join(OUT_DIR, "INDEX.md"), md.join("\n"), "utf8");
    console.log(`[done] reference at ${path.relative(process.cwd(), OUT_DIR)}/`);
}

main().catch(err => { console.error(err); process.exit(1); });
