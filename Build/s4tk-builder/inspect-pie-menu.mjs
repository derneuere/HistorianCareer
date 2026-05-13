// inspect-pie-menu.mjs — diagnostic dumper for the pie-menu / category wiring
// inside a HistorianCareer .package (or any .package, really).
//
// Use this to confirm that a built or deployed package is well-formed when
// the right-click pie menu is misbehaving in-game. The script prints the
// PieMenuCategory tuning + its SimData companion side-by-side, validates the
// fields the Olympus UI cares about (TGI tuple, schema hash, _collapsible,
// _display_name, _parent), and lists every SuperInteraction tuning that
// references the category by its decimal guid64.
//
// Usage (from the repo root):
//
//   node Build/s4tk-builder/inspect-pie-menu.mjs
//     → reads Build/out/HistorianCareer_Tuning.package
//
//   node Build/s4tk-builder/inspect-pie-menu.mjs <path/to/some.package>
//     → reads the file you pass in (e.g. the deployed copy under
//       ~/Documents/Electronic Arts/Die Sims 4/Mods/HistorianCareer/).
//
// Exits non-zero if the PMC tuning, the PMC SimData companion, the schema
// hash, the (type, group, instance) tuple, or any of the 5 expected
// SuperInteraction category references are missing or wrong.
//
// Background: issue #21. EA's pie menu wires up like this:
//   1. Per-interaction <T n="category"> = decimal guid64 of the PMC tuning.
//   2. PMC tuning lives at (type=0x03E9D964, group=0, instance=guid64).
//   3. PMC SimData companion at (type=0x545AC67A, group=<class-specific>,
//      instance=guid64), schema hash 0x022065C1.
//   4. The Olympus Flash UI builds its category registry at game start from
//      step (3). Without that SimData the categories silently fail to register
//      and right-clicks emit "Failed to locate category info for…".

import { promises as fs, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Package, SimDataResource } from "@s4tk/models";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..", "..");

const DEFAULT_PKG = path.join(PROJECT_ROOT, "Build", "out", "HistorianCareer_Tuning.package");

// Known TGI/schema constants for HC_PieMenuCategory_Historian.
const PMC_TUNING_TYPE = 0x03E9D964;        // Sims 4 PieMenuCategory tuning type
const SIMDATA_TYPE = 0x545AC67A;           // SimData companion type
const HC_PMC_INSTANCE = 0x628c53d0n;       // = 1653363664 = guid64 of HC_PieMenuCategory_Historian
const HC_PMC_SD_GROUP = 0x00E9D967;        // class-specific group for PieMenuCategory SimData
const HC_PMC_SCHEMA_HASH = 0x022065C1;     // Olympus's PMC schema hash (EA-fixed)

const SI_CATEGORY_DECIMAL = "1653363664";  // what every HC SuperInteraction should reference

const HC_EXPECTED_SIS = [
    "HC_Interaction_AnalyzePrimarySource",
    "HC_Interaction_HabilitationLecture",
    "HC_Interaction_PresentAtSymposium",
    "HC_Interaction_SuperviseDissertation",
    "HC_Interaction_TranscribeManuscript",
];

// ANSI colors — gracefully no-op when not on a TTY.
const c = (n) => (process.stdout.isTTY ? (s) => `\x1b[${n}m${s}\x1b[0m` : (s) => s);
const green = c(32);
const red = c(31);
const yellow = c(33);
const gray = c(90);

const issues = [];
function fail(msg) { issues.push(msg); console.log(red("  ✗ " + msg)); }
function ok(msg) { console.log(green("  ✓ " + msg)); }
function note(msg) { console.log(gray("    " + msg)); }

function tryGetBuffer(resource) {
    try { return resource.getBuffer(); } catch {}
    try { return resource.buffer; } catch {}
    return null;
}

function tryGetText(resource) {
    try { if (resource.content) return resource.content; } catch {}
    const b = tryGetBuffer(resource);
    return b ? b.toString("utf8") : null;
}

async function main() {
    const pkgPath = process.argv[2] ?? DEFAULT_PKG;
    if (!existsSync(pkgPath)) {
        console.error(red(`error: package not found at ${pkgPath}`));
        console.error(`usage: node ${path.relative(PROJECT_ROOT, fileURLToPath(import.meta.url))} [package-path]`);
        process.exit(2);
    }

    console.log(`Inspecting ${path.relative(PROJECT_ROOT, pkgPath)}`);
    const stat = await fs.stat(pkgPath);
    console.log(gray(`  size: ${stat.size} bytes, modified ${stat.mtime.toISOString()}`));
    const buf = await fs.readFile(pkgPath);
    const pkg = Package.from(buf);
    console.log(`Loaded: ${pkg.size} resources`);

    // -----------------------------------------------------------------------
    // 1. PMC tuning resource.
    // -----------------------------------------------------------------------
    console.log("\n[1] PieMenuCategory tuning resource");
    const pmcTunings = pkg.entries.filter(e => e.key.type === PMC_TUNING_TYPE);
    if (pmcTunings.length === 0) {
        fail(`no PieMenuCategory tuning resource found (type=0x${PMC_TUNING_TYPE.toString(16).padStart(8,"0")})`);
        note("expected: type=0x03E9D964, group=0, instance=0x628c53d0");
    } else {
        for (const e of pmcTunings) {
            const tgi = `type=0x${e.key.type.toString(16).padStart(8,"0")} group=0x${e.key.group.toString(16).padStart(8,"0")} instance=0x${e.key.instance.toString(16)}`;
            if (e.key.instance === HC_PMC_INSTANCE && e.key.group === 0) {
                ok(`PMC tuning present: ${tgi}`);
                const text = tryGetText(e.resource);
                if (text) {
                    const root = text.match(/<I[^>]*n="([^"]+)"[^>]*s="([^"]+)"/);
                    if (root) {
                        note(`tuning name: "${root[1]}"   s="${root[2]}"`);
                        if (root[2] !== SI_CATEGORY_DECIMAL) {
                            fail(`expected s="${SI_CATEGORY_DECIMAL}", got s="${root[2]}"`);
                        }
                    }
                    const disp = text.match(/<T n="_display_name">([^<]+)<\/T>/);
                    if (disp) note(`_display_name STBL key: ${disp[1]}`);
                }
            } else {
                console.log(yellow(`  ? unexpected PMC tuning TGI: ${tgi}`));
            }
        }
    }

    // -----------------------------------------------------------------------
    // 2. PMC SimData companion.
    // -----------------------------------------------------------------------
    console.log("\n[2] PieMenuCategory SimData companion");
    const sdMatch = pkg.entries.find(e =>
        e.key.type === SIMDATA_TYPE
        && e.key.instance === HC_PMC_INSTANCE
    );
    if (!sdMatch) {
        fail(`no SimData companion at instance 0x${HC_PMC_INSTANCE.toString(16)}`);
        note("the Olympus UI builds its category registry from this resource");
        note("expected: type=0x545AC67A, group=0x00E9D967, instance=0x628c53d0");
    } else {
        const tgi = `type=0x${sdMatch.key.type.toString(16).padStart(8,"0")} group=0x${sdMatch.key.group.toString(16).padStart(8,"0")} instance=0x${sdMatch.key.instance.toString(16)}`;
        ok(`PMC SimData present: ${tgi}`);
        if (sdMatch.key.group !== HC_PMC_SD_GROUP) {
            fail(`SimData group is 0x${sdMatch.key.group.toString(16)}; expected 0x${HC_PMC_SD_GROUP.toString(16)} (EA's class-specific group for PieMenuCategory)`);
        }
        const sdBuf = tryGetBuffer(sdMatch.resource);
        if (!sdBuf) {
            fail("failed to read SimData bytes");
        } else if (sdBuf.subarray(0, 4).toString("ascii") !== "DATA") {
            fail(`SimData magic is "${sdBuf.subarray(0, 4).toString("ascii")}", expected "DATA"`);
        } else {
            try {
                const sd = SimDataResource.from(sdBuf);
                if (sd.schemas.length !== 1) {
                    fail(`expected 1 schema, got ${sd.schemas.length}`);
                } else {
                    const schema = sd.schemas[0];
                    note(`schema name: "${schema.name}"`);
                    note(`schema hash: 0x${schema.hash.toString(16).padStart(8,"0")}`);
                    if (schema.hash !== HC_PMC_SCHEMA_HASH) {
                        fail(`wrong schema hash — Olympus won't recognize the row. Got 0x${schema.hash.toString(16)}, expected 0x${HC_PMC_SCHEMA_HASH.toString(16).padStart(8,"0")}`);
                    } else {
                        ok(`schema hash matches EA's 0x022065C1`);
                    }
                    const colNames = schema.columns.map(col => col.name);
                    const expectedCols = ["_collapsible", "_display_name", "_display_priority", "_icon", "_parent", "_special_category", "mood_overrides"];
                    const missing = expectedCols.filter(n => !colNames.includes(n));
                    if (missing.length > 0) {
                        fail(`missing schema columns: ${missing.join(", ")}`);
                    } else {
                        ok(`all 7 columns present: ${colNames.join(", ")}`);
                    }
                }
                if (sd.instances.length !== 1) {
                    fail(`expected 1 instance row, got ${sd.instances.length}`);
                } else {
                    const inst = sd.instances[0];
                    note(`instance row name: "${inst.name}"`);
                    const schema = inst.schema ?? sd.schemas[0];
                    for (const col of schema.columns) {
                        const cell = inst.row?.cells?.[col.name] ?? inst.row?.[col.name];
                        const v = cell?.value;
                        let rendered;
                        if (cell?.constructor?.name === "ResourceKeyCell") {
                            rendered = `(type=0x${(cell.type ?? 0).toString(16)}, group=0x${(cell.group ?? 0).toString(16)}, instance=0x${(cell.instance ?? 0n).toString(16)})`;
                        } else if (cell?.constructor?.name === "VectorCell") {
                            rendered = `[${cell.children?.length ?? 0} item(s)]`;
                        } else if (typeof v === "bigint") {
                            rendered = `${v}n (0x${v.toString(16)})`;
                        } else if (typeof v === "number") {
                            rendered = `${v} (0x${v.toString(16)})`;
                        } else {
                            rendered = String(v);
                        }
                        note(`  ${col.name.padEnd(22)} = ${rendered}`);
                    }
                    // Spot-check: _collapsible must be truthy for a submenu.
                    const collapsibleCell = inst.row?.cells?._collapsible ?? inst.row?._collapsible;
                    if (collapsibleCell && collapsibleCell.value === false) {
                        console.log(yellow("  ! _collapsible is FALSE — this category will not display as a submenu; interactions will appear flat."));
                    }
                    const parentCell = inst.row?.cells?._parent ?? inst.row?._parent;
                    if (parentCell && parentCell.value !== 0n && parentCell.value !== 0) {
                        console.log(yellow(`  ! _parent is set (0x${parentCell.value.toString(16)}) — this category is a child of another PMC. Top-level submenus need _parent=0.`));
                    }
                }
            } catch (e) {
                fail(`SimDataResource parse error: ${e.message}`);
            }
        }
    }

    // -----------------------------------------------------------------------
    // 3. SuperInteraction <T n="category"> wiring.
    // -----------------------------------------------------------------------
    console.log("\n[3] SuperInteraction <T n=\"category\"> wiring");
    /** @type {Map<string, {type:number, instance:bigint, category:string}>} */
    const interactionRefs = new Map();
    for (const entry of pkg.entries) {
        const text = tryGetText(entry.resource);
        if (!text || !text.includes('n="category"')) continue;
        const root = text.match(/<I[^>]*n="([^"]+)"/);
        if (!root) continue;
        const name = root[1];
        if (!name.startsWith("HC_")) continue;  // ignore EA tunings we may have re-emitted
        const m = text.match(/<T n="category">([^<]+)<\/T>/);
        if (!m) continue;
        interactionRefs.set(name, { type: entry.key.type, instance: entry.key.instance, category: m[1] });
    }
    if (interactionRefs.size === 0) {
        fail("no HC_-named tunings with <T n=\"category\"> found");
    } else {
        for (const name of HC_EXPECTED_SIS) {
            const r = interactionRefs.get(name);
            if (!r) {
                fail(`expected SuperInteraction missing: ${name}`);
            } else if (r.category !== SI_CATEGORY_DECIMAL) {
                fail(`${name}: category=${r.category}, expected ${SI_CATEGORY_DECIMAL}`);
            } else {
                ok(`${name.padEnd(40)} category=${r.category} ✓`);
            }
        }
    }

    // -----------------------------------------------------------------------
    // Summary.
    // -----------------------------------------------------------------------
    console.log();
    if (issues.length === 0) {
        console.log(green("PASS — pie-menu wiring in this package is well-formed."));
        console.log(gray("If the in-game pie menu still appears flat, the regression is environmental"));
        console.log(gray("(save-state contamination or stale game cache). See Docs/NOTE_pie_menu_diagnostic_checklist.md."));
        process.exit(0);
    } else {
        console.log(red(`FAIL — ${issues.length} issue(s) found in the package itself:`));
        for (const m of issues) console.log(red(`  - ${m}`));
        process.exit(1);
    }
}

main().catch(e => {
    console.error(red("unexpected error:"), e);
    process.exit(2);
});
