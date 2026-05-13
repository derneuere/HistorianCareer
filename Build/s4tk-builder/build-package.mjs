// build-package.mjs — produce HistorianCareer_Tuning.package from the Tuning/ XML files
// and strings.json, using @s4tk/models + @s4tk/hashing. No Sims 4 Studio required.
//
// What this script does, end to end:
//   1. Load strings.json. For each locale × key, hash the key with FNV-32 → STBL key.
//   2. Walk Tuning/*.xml. Skip any file starting with "_" (those are retired).
//   3. PASS 1 — read every XML and build a global `tuning_name → instance ID` map
//      (collectTuningNames in resolve-names.mjs). The map prefers s="<decimal>" when
//      a tuning has one hardcoded, else uses fnv64(name, true). This is the bedrock
//      for cross-resource references (issue #15).
//   4. PASS 2 — for each XML:
//        - parse the `n="<tuning_name>"` and `i="<i_attr>"` from the root <I> tag
//        - resolve the resource type via TuningResourceType.parseAttr(i_attr)
//        - look up the Instance ID in the Pass 1 map (collision-checked)
//        - replace the `s="TBD_INSTANCE_ID"` placeholder with the decimal ID
//        - replace every `0xTBD_STBL_KEY_<KEY>` placeholder with the formatted STBL key
//        - replace every named tuning reference (<T>NAME</T>, <E>NAME</E>,
//          <T n="...">NAME</T>) whose body matches a known tuning name with the
//          decimal instance ID (resolveNamesInXml). Names not in the map are left
//          as-is; HC_-prefixed unknowns emit a warning.
//        - add the XML to the Package
//   5. Build one STBL resource per locale, give each the locale's high-byte instance,
//      add to the Package.
//   6. Write the Package buffer to Build/out/HistorianCareer_Tuning.package.
//
// Layer B caveat: any tuning class that requires a SimData companion (Career, CareerTrack,
// CareerLevel, Aspiration, AspirationTrack, AspirationCareer, Trait, Objective, CareerChanceCard)
// will not be game-loadable from this build alone. Layer A resources (interactions, statistic,
// loot actions, pie menu) load without SimData and work end-to-end via this builder.

import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Package, XmlResource, StringTableResource, RawResource } from "@s4tk/models";
import { StringTableLocale, TuningResourceType, BinaryResourceType } from "@s4tk/models/enums.js";
import { fnv32, fnv64 } from "@s4tk/hashing/hashing.js";
import { formatAsHexString } from "@s4tk/hashing/formatting.js";

// simdata: our hand-rolled SimData generator that replaces the last S4S step.
// Built from ../simdata. Loaded from its compiled output under ./dist.
import {
    parseTuning,
    buildSimDataForTuning,
    createBuildContext,
    emitSimDataBuffer,
    supportedClasses,
    KNOWN_SCHEMA_HASHES,
} from "../simdata/dist/index.js";

// Build-time tuning name → decimal instance ID resolver (issue #15). Two
// pure passes, separated so the swap logic can be unit-tested without IO.
import { collectTuningNames, resolveNamesInXml } from "./resolve-names.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const TUNING_DIR = path.join(PROJECT_ROOT, "Tuning");
const ICONS_DIR = path.join(__dirname, "..", "icons");
const OUT_DIR = path.join(__dirname, "..", "out");
const OUT_PACKAGE = path.join(OUT_DIR, "HistorianCareer_Tuning.package");

// PNG image resource type for embedded image resources.
//
// IMPORTANT: there are TWO image-related type codes in Sims 4. They are NOT
// interchangeable:
//
//   0x00B2D882  "PNG image"        — the type ACTUAL stored image resources
//                                    live at. SimData ResourceKey columns
//                                    for icon/icon_high_res/image point at
//                                    this type.
//   0x2F7D0004  "TGI icon ref"     — a marker type used in Tuning XML as the
//                                    "type" segment of <T n="icon">…</T>
//                                    resource keys. The SimData generator
//                                    rewrites 0x2F7D0004 → 0x00B2D882 when
//                                    serializing ResourceKey cells.
//
// We embed icon PNGs at 0x00B2D882. The Tuning XML can still reference them
// with the 0x2F7D0004 marker — the simdata rewrite makes the lookup land on
// our 0x00B2D882 resource at the same instance.
//
// Verified by inspecting an EA-shipped CareerTrack SimData (Writer_Track1,
// instance 0x7508): icon column has type=0xB2D882.
const PNG_TYPE = 0x00B2D882;

// CLI flag --include-layer-b includes the resources that require SimData companions.
// Layer A is the drop-in default; the package is loadable as-is.
const INCLUDE_LAYER_B = process.argv.includes("--include-layer-b");
// CLI flag --skip-simdata leaves Layer B tunings without their SimData companions
// (game will reject these — only useful for debugging the XML resources).
const SKIP_SIMDATA = process.argv.includes("--skip-simdata");

// SimData resource type ID (BinaryResourceType.SimData = 0x545AC67A).
const SIMDATA_TYPE = BinaryResourceType.SimData;

/**
 * EA's SimData companion resources are stored at a CLASS-SPECIFIC group ID
 * derived deterministically from the tuning's resource type, NOT at group 0.
 *
 * The Olympus Flash UI looks up SimData by (type, group, instance) — a mod
 * shipping SimData at group=0 is invisible to the UI even though the package
 * loads cleanly. Symptoms include the silent pie-menu failure on right-click
 * ("Failed to locate category info"), the career display showing "@" / no
 * icon, and custom AspirationTracks not appearing in CAS.
 *
 * The encoding is: group = (tuningType & 0x00FFFFFF) XOR (tuningType >>> 24).
 * Empirically verified against EA goldens (extracted from
 * SimulationFullBuild0.package):
 *
 *   Class             Tuning type   EA SimData group   Formula result
 *   PieMenuCategory   0x03E9D964    0x00E9D967         (0xE9D964 ^ 0x03) = 0xE9D967 ✓
 *   Career            0x73996BEB    0x00996B98         (0x996BEB ^ 0x73) = 0x996B98 ✓
 *   CareerTrack       0x48C75CE3    0x00C75CAB         (0xC75CE3 ^ 0x48) = 0xC75CAB ✓
 *   CareerLevel       0x2C70ADF8    0x0070ADD4         (0x70ADF8 ^ 0x2C) = 0x70ADD4 ✓
 *   Aspiration        0x28B64675    0x00B6465D         (0xB64675 ^ 0x28) = 0xB6465D ✓
 *   AspirationTrack   0xC020FCAD    0x0020FC6D         (0x20FCAD ^ 0xC0) = 0x20FC6D ✓
 *   Trait             0xCB5FDDC7    0x005FDD0C         (0x5FDDC7 ^ 0xCB) = 0x5FDD0C ✓
 *   Buff              0x6017E896    0x0017E8F6         (0x17E896 ^ 0x60) = 0x17E8F6 ✓
 *   Objective         0x0069453E    0x0069453E         (0x69453E ^ 0x00) = 0x69453E ✓
 */
function simDataGroupFor(tuningType) {
    return ((tuningType & 0x00FFFFFF) ^ (tuningType >>> 24)) >>> 0;
}

// Tuning classes that *require* a SimData companion. Note "TunableCareerTrack"
// is EA's canonical class name (matches what `c="..."` says in the XML); the
// simdata library registers a CareerTrack alias under that name.
const NEEDS_SIMDATA = new Set([
    "Career", "CareerTrack", "TunableCareerTrack", "CareerLevel",
    "Aspiration", "AspirationTrack", "AspirationCareer",
    "Trait", "Objective", "CareerChanceCard",
    // PieMenuCategory: the Olympus UI builds its category registry from
    // SimData resources at boot, NOT from the tuning XML. Without this
    // companion the right-click pie menu silently fails with
    // "Failed to locate category info for interaction category with key: …".
    // See Docs/NOTE_pie_menu_category_registration.md.
    "PieMenuCategory",
]);

// Locale name in strings.json → s4tk StringTableLocale enum value.
const LOCALE_MAP = {
    en: StringTableLocale.English,
    de: StringTableLocale.German,
    fr: StringTableLocale.French,
    es: StringTableLocale.Spanish,
};

async function main() {
    await fs.mkdir(OUT_DIR, { recursive: true });

    // -----------------------------------------------------------------------
    // 1. Load strings.json and compute STBL keys.
    // -----------------------------------------------------------------------
    const stringsPath = path.join(__dirname, "strings.json");
    const strings = JSON.parse(await fs.readFile(stringsPath, "utf8"));
    const localeNames = Object.keys(strings).filter(k => k in LOCALE_MAP);
    if (!localeNames.includes("en")) {
        throw new Error("strings.json must contain an 'en' locale.");
    }

    // Every key found in any locale; English is the canonical key list.
    const keyNames = Object.keys(strings.en);
    /** keyName -> 32-bit STBL key (number) */
    const stblKeyByName = new Map();
    for (const k of keyNames) {
        stblKeyByName.set(k, fnv32(k));
    }

    console.log(`[builder] ${keyNames.length} STBL keys across ${localeNames.length} locale(s): ${localeNames.join(", ")}`);

    // -----------------------------------------------------------------------
    // 1b. Embed custom PNG icons from Build/icons/.
    //
    // For each .png in that folder, the build registers a resource of type
    // 0x2F7D0004 (Sims 4's PNG image type) with instance = fnv64(basename, true).
    // It also adds an entry to nameToInstance so tuning XML files can reference
    // the icon by its bare filename, e.g.
    //     <T n="icon" p="...">Career_Historian_Main.png</T>
    // The Pass 2 name resolver swaps this for the resource key the game looks up.
    // The XML emit format Sims 4 expects for an icon ref is:
    //     <T n="icon" p="path/for/preview.png">2f7d0004:00000000:{16 hex}</T>
    // So we also rewrite the inner text to that full TGI form after resolving.
    // -----------------------------------------------------------------------
    /** @type {Map<string, bigint>} iconFilename → 64-bit resource instance */
    const iconNameToInstance = new Map();
    const iconEntries = []; // Buffered until we add to the package below.
    if (await fs.access(ICONS_DIR).then(() => true).catch(() => false)) {
        const iconFiles = (await fs.readdir(ICONS_DIR))
            .filter(f => f.toLowerCase().endsWith(".png"));
        for (const file of iconFiles) {
            const buf = await fs.readFile(path.join(ICONS_DIR, file));
            const instance = fnv64(file, true);
            iconNameToInstance.set(file, instance);
            iconEntries.push({
                key: { type: PNG_TYPE, group: 0, instance },
                value: RawResource.from(buf),
            });
            console.log(`  + icon ${file.padEnd(46)} type=PNG                  instance=0x${instance.toString(16)} (${buf.byteLength}B)`);
        }
        console.log(`[builder] embedded ${iconFiles.length} icon PNG(s) from Build/icons/`);
    }

    // -----------------------------------------------------------------------
    // 2-3. Walk Tuning/*.xml, build XmlResource entries.
    //
    // Done in two passes (issue #15):
    //   Pass 1 — read every XML and collect a global `tuning_name → instance ID`
    //            map (preferring s="<number>" if present, else fnv64(name,true)).
    //   Pass 2 — for each XML, substitute STBL placeholders AND replace named
    //            tuning references (<T>NAME</T> / <E>NAME</E> / <T n="…">NAME</T>)
    //            with their decimal instance IDs.
    // -----------------------------------------------------------------------
    const allTuningFiles = (await fs.readdir(TUNING_DIR))
        .filter(f => f.endsWith(".xml") && !f.startsWith("_"));

    // Pass 1: read all XMLs and build the global name → instance map.
    /** @type {Map<string, string>} */
    const rawXmlByFile = new Map();
    for (const file of allTuningFiles) {
        const fullPath = path.join(TUNING_DIR, file);
        rawXmlByFile.set(file, await fs.readFile(fullPath, "utf8"));
    }
    const nameToInstance = collectTuningNames(rawXmlByFile);
    console.log(`[builder] resolved ${nameToInstance.size} tuning name(s) → instance IDs`);

    const entries = []; // { key: {type, group, instance}, value: Resource }
    const usedInstances = new Map(); // instance(bigint) -> tuningName  (collision check)

    let layerAcount = 0, layerBcount = 0, simdataWarnings = 0;
    let nameResolverWarnings = 0;

    // Pass 2: per-file substitution + add to package.
    for (const file of allTuningFiles) {
        let xml = rawXmlByFile.get(file);

        // Parse `<I c="..." i="..." n="..." s="...">` from the root tag.
        const rootMatch = xml.match(/<I\s+([^>]+)>/);
        if (!rootMatch) {
            console.warn(`[skip] ${file}: no <I ...> root element`);
            continue;
        }
        const attrs = parseAttrs(rootMatch[1]);
        const tuningName = attrs.n;
        const iAttr = attrs.i;
        const cAttr = attrs.c;
        if (!tuningName || !iAttr) {
            console.warn(`[skip] ${file}: missing n="" or i="" on root <I>`);
            continue;
        }

        // Resolve resource type from the `i` attribute (e.g., "interaction", "career",
        // "aspiration", "objective", "action"...). Unknown attrs fall back to Tuning.
        const resourceType = TuningResourceType.parseAttr(iAttr);

        // Instance ID — take from the shared name→ID map populated in Pass 1.
        // This stays consistent with how cross-references are resolved below,
        // and the map already preferred a literal s="<decimal>" over fnv64
        // when one was present on this tuning's root.
        const instance = nameToInstance.get(tuningName) ?? fnv64(tuningName, true);

        // Collision check — should never happen unless two XMLs share `n=`.
        if (usedInstances.has(instance)) {
            throw new Error(
                `Instance ID collision: ${file} and ${usedInstances.get(instance)} both hash to ${instance.toString(16)}`,
            );
        }
        usedInstances.set(instance, tuningName);

        // Replace placeholders in the XML body.
        // 1) s="TBD_INSTANCE_ID" -> s="<decimal>"
        xml = xml.replace(/s="TBD_INSTANCE_ID"/, `s="${instance.toString()}"`);

        // 2) 0xTBD_STBL_KEY_<KEY>  -> 0x<8 hex digits>!  (8-hex prefix style; '!' suffix is
        //    EA's hint to the localization system that the value is a STBL key. The trailing
        //    '!' is harmless if unused.)
        xml = xml.replace(/0xTBD_STBL_KEY_([A-Z0-9_]+)/g, (_full, keyName) => {
            const key = stblKeyByName.get(keyName);
            if (key === undefined) {
                throw new Error(`${file}: references unknown STBL key '${keyName}' — add it to strings.json (en).`);
            }
            // 8-digit hex, no 0x prefix from formatAsHexString; we re-add the prefix to match
            // EA's literal style in tuning files.
            return "0x" + formatAsHexString(key, 8, false);
        });

        // 3) Named tuning references → decimal instance IDs (issue #15).
        //    Runs AFTER STBL substitution so the post-substitution form (e.g.
        //    `<T n="display_name">0xfa1c2233</T>`) is correctly treated as a
        //    numeric body and skipped. Runs ONCE per file with the global map
        //    built in Pass 1.
        {
            const { xml: rewritten, warnings } = resolveNamesInXml(xml, nameToInstance, { file });
            xml = rewritten;
            for (const w of warnings) {
                console.warn(`[warn] ${w}`);
                nameResolverWarnings++;
            }
        }

        // 4) Custom icon refs → resource keys.
        //    Source XML can reference a custom icon by bare filename:
        //        <T n="icon" p="...">Career_Historian_Main.png</T>
        //    Rewrite that to the full TGI Sims 4 expects:
        //        <T n="icon" p="...">2f7d0004:00000000:{16 hex of fnv64(filename)}</T>
        //    Matches both `<T n="icon">` and `<T n="icon_high_res">` / `<T n="image">`.
        if (iconNameToInstance.size > 0) {
            xml = xml.replace(
                /(<T(?:\s+n="(?:icon|icon_high_res|image)")?(?:\s+p="[^"]*")?>)([A-Za-z0-9_\-]+\.png)(<\/T>)/g,
                (match, open, body, close) => {
                    const inst = iconNameToInstance.get(body);
                    if (inst === undefined) return match; // unknown PNG name; leave as-is
                    const tgi = `2f7d0004:00000000:${inst.toString(16).padStart(16, "0")}`;
                    return `${open}${tgi}${close}`;
                },
            );
        }

        // Warn if any placeholder slipped through.
        const leftovers = xml.match(/TBD_(INSTANCE_ID|STBL_KEY_[A-Z0-9_]+)/g);
        if (leftovers) {
            console.warn(`[warn] ${file}: unresolved placeholders → ${leftovers.join(", ")}`);
        }

        const isLayerB = NEEDS_SIMDATA.has(cAttr);
        if (isLayerB && !INCLUDE_LAYER_B) {
            // Skip; Layer A drop-in default.
            console.log(`  - skip ${file.padEnd(46)} (Layer B; rebuild with --include-layer-b once you've generated SimData in S4S)`);
            layerBcount++;
            continue;
        }
        if (isLayerB) {
            layerBcount++;
        } else {
            layerAcount++;
        }

        const xmlResource = new XmlResource(xml);

        entries.push({
            key: { type: resourceType, group: 0, instance },
            value: xmlResource,
        });

        const typeName = TuningResourceType[resourceType] ?? "Tuning";
        console.log(`  + ${file.padEnd(50)} type=${typeName.padEnd(20)} instance=0x${instance.toString(16)}`);

        // -----------------------------------------------------------------------
        // 3b. SimData companion (Layer B only).
        //
        // For every tuning whose class needs a SimData companion, generate one
        // using our `simdata` library. The SimData entry must share the same
        // instance ID as the tuning resource — the game uses (TGI minus type)
        // to pair them.
        // -----------------------------------------------------------------------
        if (isLayerB && !SKIP_SIMDATA) {
            const supported = new Set(supportedClasses());
            if (!supported.has(cAttr)) {
                console.warn(`[warn] ${file}: class "${cAttr}" is not yet supported by simdata; SimData not generated.`);
                simdataWarnings++;
            } else {
                try {
                    const tree = parseTuning(xml);
                    const ctx = createBuildContext({
                        resolveStblKey: (token) => {
                            const k = stblKeyByName.get(token);
                            if (k === undefined) {
                                throw new Error(`unknown STBL key "${token}" — add to strings.json`);
                            }
                            return k;
                        },
                        // Match the s4tk-builder's tuning name → instance ID convention.
                        // Prefer the global map (which honors s="<decimal>" overrides
                        // when present); fall back to fnv64 for refs to EA-shipped
                        // tunings that aren't in our XMLs.
                        resolveTuningRef: (name) => nameToInstance.get(name) ?? fnv64(name, true),
                        knownSchemaHashes: KNOWN_SCHEMA_HASHES,
                    });
                    const ir = buildSimDataForTuning(tree, ctx);
                    const simBuffer = emitSimDataBuffer(ir);
                    entries.push({
                        key: { type: SIMDATA_TYPE, group: simDataGroupFor(resourceType), instance },
                        value: RawResource.from(simBuffer),
                    });
                    console.log(`    └─ + SimData (${simBuffer.byteLength}B, schema=${cAttr})`);
                } catch (err) {
                    console.warn(`[warn] ${file}: SimData generation failed: ${err.message}`);
                    simdataWarnings++;
                }
            }
        } else if (isLayerB) {
            simdataWarnings++;
        }
    }

    // -----------------------------------------------------------------------
    // 4. Build one StringTableResource per locale.
    // -----------------------------------------------------------------------
    for (const localeName of localeNames) {
        const localeId = LOCALE_MAP[localeName];
        const stbl = new StringTableResource();
        const table = strings[localeName];
        for (const keyName of keyNames) {
            const value = table[keyName] ?? strings.en[keyName] ?? "";
            const stblKey = stblKeyByName.get(keyName);
            stbl.add(stblKey, value);
        }

        // The STBL instance ID encodes the locale in the high byte and a fixed body.
        // Convention: low 56 bits = FNV-56 of the package name (any unique string works).
        const stblBaseInstance = BigInt.asUintN(56, fnv64("HistorianCareer.stbl", true));
        const stblInstance = StringTableLocale.setHighByte(localeId, stblBaseInstance);

        entries.push({
            key: { type: BinaryResourceType.StringTable, group: 0, instance: stblInstance },
            value: stbl,
        });
        console.log(`  + STBL.${localeName.padEnd(8)}                                  type=StringTable          instance=0x${stblInstance.toString(16)} (${keyNames.length} entries)`);
    }

    // -----------------------------------------------------------------------
    // 4b. Add the icon PNG resources buffered during step 1b.
    // -----------------------------------------------------------------------
    for (const iconEntry of iconEntries) {
        entries.push(iconEntry);
    }

    // -----------------------------------------------------------------------
    // 5. Serialize and write the .package.
    // -----------------------------------------------------------------------
    const pkg = new Package(entries);
    const buffer = pkg.getBuffer();
    await fs.writeFile(OUT_PACKAGE, buffer);

    console.log("");
    console.log(`[ok]   wrote ${entries.length} resources to ${path.relative(PROJECT_ROOT, OUT_PACKAGE)}`);
    console.log(`[ok]   Layer A resources: ${layerAcount} (no SimData required)`);
    if (nameResolverWarnings > 0) {
        console.log(`[warn] name resolver: ${nameResolverWarnings} HC_-looking refs were not in the tuning map — see warnings above.`);
    }
    if (!INCLUDE_LAYER_B && layerBcount > 0) {
        console.log(`[info] Skipped ${layerBcount} Layer B resources (default drop-in build). Run with --include-layer-b for full Career/Aspiration support.`);
    } else if (INCLUDE_LAYER_B && layerBcount > 0) {
        const simdataEmitted = layerBcount - simdataWarnings;
        console.log(`[ok]   Layer B resources: ${layerBcount} emitted; ${simdataEmitted} with auto-generated SimData via the simdata library.`);
        if (simdataWarnings > 0) {
            console.log(`[warn] ${simdataWarnings} Layer B resources are missing SimData companions; these will fail to load in-game.`);
            console.log(`[warn] Open the .package in S4S and right-click each → Generate SimData, OR extend simdata to support those classes.`);
        }
    }
}

// --- helpers -----------------------------------------------------------------

function parseAttrs(attrString) {
    const out = {};
    const re = /(\w+)="([^"]*)"/g;
    let m;
    while ((m = re.exec(attrString)) !== null) {
        out[m[1]] = m[2];
    }
    return out;
}

main().catch(err => {
    console.error(err);
    process.exit(1);
});
