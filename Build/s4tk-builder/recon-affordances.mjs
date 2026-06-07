// recon-affordances.mjs — one-off recon: extract EA interaction tunings from the
// live game's CombinedTuning to discover the right animation/mixer refs for the
// remaining HC bookshelf + social interactions. NOT part of the build.
//
// Usage: node recon-affordances.mjs
import { Package, CombinedTuningResource } from "@s4tk/models";
import fs from "node:fs";

const GAME = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\The Sims 4";
const PKGS = [
  `${GAME}\\Data\\Simulation\\SimulationFullBuild0.package`,
];

// Pull instance id + class + module + name from a root <I ...> or <M ...> attr line.
function rootAttrs(xml) {
  const m = xml.match(/<([IM])\s+([^>]*)>/);
  if (!m) return null;
  const tag = m[1];
  const attrs = {};
  for (const a of m[2].matchAll(/(\w+)="([^"]*)"/g)) attrs[a[1]] = a[2];
  return { tag, ...attrs };
}

const all = []; // { name, s, c, i, m, xml }
for (const pkgPath of PKGS) {
  if (!fs.existsSync(pkgPath)) { console.error("MISSING", pkgPath); continue; }
  console.error("Loading", pkgPath, "…");
  const buf = fs.readFileSync(pkgPath);
  const pkg = Package.from(buf, { keepDeletedRecords: false });
  console.error("  entries:", pkg.size);
  for (const entry of pkg.entries) {
    // CombinedTuning resources hold many tunings; plain Tuning resources hold one.
    const resType = entry.key.type;
    try {
      const buffer = entry.value.getBuffer ? entry.value.getBuffer() : entry.value.buffer;
      // Heuristic: try extractTuning for combined; if it throws, treat as plain xml.
      let xmls = null;
      try {
        xmls = CombinedTuningResource.extractTuning(buffer);
      } catch {
        xmls = null;
      }
      if (xmls && xmls.length) {
        for (const x of xmls) {
          const content = x.content;
          if (!content || content.indexOf("<I ") === -1) continue;
          const ra = rootAttrs(content);
          if (!ra) continue;
          all.push({ name: ra.n, s: ra.s, c: ra.c, i: ra.i, m: ra.m, xml: content });
        }
      }
    } catch (e) {
      // skip non-tuning resources
    }
  }
}
console.error("Total tunings collected:", all.length);

// Save a name index for grepping.
const idx = all
  .filter((t) => t.name)
  .map((t) => `${t.s}\t${t.c}\t${t.m}\t${t.name}`)
  .sort();
fs.writeFileSync("recon-index.tsv", idx.join("\n"), "utf-8");
console.error("Wrote recon-index.tsv (", idx.length, "named tunings )");

// Dump full XML for interactions of interest into recon-dump/.
fs.rmSync("recon-dump", { recursive: true, force: true });
fs.mkdirSync("recon-dump", { recursive: true });
// grep mode: `node recon-affordances.mjs grep:<regex>` prints name+id for every
// tuning whose XML matches the regex (used to find structural precedent).
const grepArg = process.argv.slice(2).find((a) => a.startsWith("grep:"));
if (grepArg) {
  const re = new RegExp(grepArg.slice(5), "s");
  let n = 0;
  for (const t of all) {
    if (t.name && re.test(t.xml)) {
      console.log(`${t.s}\t${t.c}\t${t.name}`);
      if (++n >= 60) break;
    }
  }
  console.error(`grep matched (showing up to 60):`, n);
  process.exit(0);
}

const rawArgs = process.argv.slice(2);
const wantIds = new Set(rawArgs.filter((a) => a.startsWith("id:")).map((a) => a.slice(3)));
const want = rawArgs.filter((a) => !a.startsWith("id:"));
let dumped = 0;
for (const t of all) {
  if (!t.name) continue;
  const lname = t.name.toLowerCase();
  const hit = wantIds.has(String(t.s)) ||
    want.some((w) => lname.includes(w.toLowerCase())) ||
    (want.length === 0 && wantIds.size === 0 && (lname.includes("book") || lname.includes("bookshelf")));
  if (hit) {
    fs.writeFileSync(`recon-dump/${t.s}_${t.name}.xml`, t.xml, "utf-8");
    dumped++;
  }
}
console.error("Dumped", dumped, "matching tunings to recon-dump/");
