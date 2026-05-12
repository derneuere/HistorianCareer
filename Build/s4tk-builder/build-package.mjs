// build-package.mjs — produce HistorianCareer_Tuning.package from the Tuning/ XML files
// and strings.json, using @s4tk/models + @s4tk/hashing. No Sims 4 Studio required.
//
// What this script does, end to end:
//   1. Load strings.json. For each locale × key, hash the key with FNV-32 → STBL key.
//   2. Walk Tuning/*.xml. Skip any file starting with "_" (those are retired).
//   3. For each XML:
//        - parse the `n="<tuning_name>"` and `i="<i_attr>"` from the root <I> tag
//        - resolve the resource type via TuningResourceType.parseAttr(i_attr)
//        - compute the Instance ID = fnv64(tuning_name, highBit=true)
//        - replace the `s="TBD_INSTANCE_ID"` placeholder with that hash
//        - replace every `0xTBD_STBL_KEY_<KEY>` placeholder with the formatted STBL key
//        - add the XML to the Package
//   4. Build one STBL resource per locale, give each the locale's high-byte instance,
//      add to the Package.
//   5. Write the Package buffer to Build/out/HistorianCareer_Tuning.package.
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

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const TUNING_DIR = path.join(PROJECT_ROOT, "Tuning");
const OUT_DIR = path.join(__dirname, "..", "out");
const OUT_PACKAGE = path.join(OUT_DIR, "HistorianCareer_Tuning.package");

// CLI flag --include-layer-b includes the resources that require SimData companions.
// Layer A is the drop-in default; the package is loadable as-is.
const INCLUDE_LAYER_B = process.argv.includes("--include-layer-b");
// CLI flag --skip-simdata leaves Layer B tunings without their SimData companions
// (game will reject these — only useful for debugging the XML resources).
const SKIP_SIMDATA = process.argv.includes("--skip-simdata");

// SimData resource type ID (BinaryResourceType.SimData = 0x545AC67A).
const SIMDATA_TYPE = BinaryResourceType.SimData;

// Tuning classes that *require* a SimData companion. We emit them anyway but warn loudly,
// because without SimData the game will throw on load. Generate SimData for these in S4S.
const NEEDS_SIMDATA = new Set([
    "Career", "CareerTrack", "CareerLevel",
    "Aspiration", "AspirationTrack", "AspirationCareer",
    "Trait", "Objective", "CareerChanceCard",
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
    // 2-3. Walk Tuning/*.xml, build XmlResource entries.
    // -----------------------------------------------------------------------
    const allTuningFiles = (await fs.readdir(TUNING_DIR))
        .filter(f => f.endsWith(".xml") && !f.startsWith("_"));

    const entries = []; // { key: {type, group, instance}, value: Resource }
    const usedInstances = new Map(); // instance(bigint) -> tuningName  (collision check)

    let layerAcount = 0, layerBcount = 0, simdataWarnings = 0;

    for (const file of allTuningFiles) {
        const fullPath = path.join(TUNING_DIR, file);
        let xml = await fs.readFile(fullPath, "utf8");

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

        // Instance ID = FNV-64 of the tuning name, with the high bit set (S4S convention).
        const instance = fnv64(tuningName, true);

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
                        resolveTuningRef: (name) => fnv64(name, true),
                        knownSchemaHashes: KNOWN_SCHEMA_HASHES,
                    });
                    const ir = buildSimDataForTuning(tree, ctx);
                    const simBuffer = emitSimDataBuffer(ir);
                    entries.push({
                        key: { type: SIMDATA_TYPE, group: 0, instance },
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
    // 5. Serialize and write the .package.
    // -----------------------------------------------------------------------
    const pkg = new Package(entries);
    const buffer = pkg.getBuffer();
    await fs.writeFile(OUT_PACKAGE, buffer);

    console.log("");
    console.log(`[ok]   wrote ${entries.length} resources to ${path.relative(PROJECT_ROOT, OUT_PACKAGE)}`);
    console.log(`[ok]   Layer A resources: ${layerAcount} (no SimData required)`);
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
