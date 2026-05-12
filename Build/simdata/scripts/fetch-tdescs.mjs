// fetch-tdescs.mjs — download TDESC files from the Lot 51 TDESC API into
// test/fixtures/tdescs/, using a real Playwright-driven Chromium so we
// pass Cloudflare's TLS-fingerprint check.
//
// Why Playwright: tdesc.lot51.cc sits behind Cloudflare's bot-fight mode,
// which uses JA3/JA4 TLS fingerprinting. Plain HTTP clients (curl, fetch,
// axios, undici) all 403 regardless of headers or cookies. A real browser
// passes. Playwright drives a real Chromium with its real TLS stack.
//
// Two-step flow:
//   1. Hit the search/index endpoint to discover what TDESCs exist for the
//      requested version. The response is saved to _index.json for debug.
//   2. For each entry in MANIFEST.json, look it up in the index (by class
//      name), then fetch its .tdesc body and save to test/fixtures/tdescs/.
//
// Usage:
//   npm run fetch-tdescs                          # default: all entries
//   node scripts/fetch-tdescs.mjs --only=Career   # one class
//   node scripts/fetch-tdescs.mjs --refresh-index # re-fetch index even if cached
//   node scripts/fetch-tdescs.mjs --probe='Path'  # debug: fetch one arbitrary path

import { promises as fs } from "node:fs";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const FIXTURES = path.join(ROOT, "test", "fixtures", "tdescs");
const MANIFEST_PATH = path.join(FIXTURES, "MANIFEST.json");
const INDEX_CACHE = path.join(FIXTURES, "_index.json");

const SITE = "https://tdesc.lot51.cc";
const SEARCH_ENDPOINT = `${SITE}/api/simdex/search/tdesc`;
const DOC_ENDPOINT = `${SITE}/api/tdesc/doc`;

// Politeness: serialize requests with a small pause so we don't trip Cloudflare's
// rate limiter mid-batch.
const DELAY_MS = 1200;

// ---------- pure helpers (testable in isolation if we ever extract them) ----

function parseArgs(argv) {
    const out = {};
    for (const arg of argv) {
        const m = arg.match(/^--([^=]+)(?:=(.*))?$/);
        if (m) out[m[1]] = m[2] ?? true;
    }
    return out;
}

/**
 * Find the best path for a wanted class name inside the index response.
 * The index shape is not formally documented; this function does best-effort
 * matching that handles common shapes:
 *   - Array<{ path: string, name?, class?, … }>
 *   - { results: [...] }
 *   - { tdescs: [...] }
 *
 * Returns the matched path (a string suitable for the `path` query param of
 * the /api/tdesc/doc endpoint) or null.
 */
export function findPathInIndex(index, wantedName) {
    const candidates = normalizeIndex(index);
    if (!candidates.length) return null;

    const lowered = wantedName.toLowerCase();

    // Prefer entries where the *file name* matches exactly: `…/<ClassName>.tdesc`.
    const exact = candidates.find(entry => {
        const p = entry.path?.toLowerCase() ?? "";
        return p.endsWith(`/${lowered}.tdesc`) || p === `${lowered}.tdesc`;
    });
    if (exact) return exact.path;

    // Fall back to a class-attribute or display-name match.
    const byClass = candidates.find(entry =>
        (entry.class?.toLowerCase?.() === lowered) ||
        (entry.name?.toLowerCase?.() === lowered),
    );
    if (byClass?.path) return byClass.path;

    // Last resort: any path containing /ClassName.tdesc anywhere.
    const loose = candidates.find(entry => (entry.path?.toLowerCase?.() ?? "").includes(`${lowered}.tdesc`));
    return loose?.path ?? null;
}

function normalizeIndex(index) {
    if (!index) return [];
    if (Array.isArray(index)) return index;
    // Elasticsearch envelope: { hits: { hits: [{ _source: {...} }] } }
    if (index.hits && Array.isArray(index.hits.hits)) {
        return index.hits.hits.map(h => h._source ?? h);
    }
    if (Array.isArray(index.results)) return index.results;
    if (Array.isArray(index.tdescs)) return index.tdescs;
    if (Array.isArray(index.data)) return index.data;
    return [];
}

// ---------- I/O ------------------------------------------------------------

async function readJson(filepath) {
    try {
        return JSON.parse(await fs.readFile(filepath, "utf8"));
    } catch (err) {
        if (err.code === "ENOENT") return null;
        throw err;
    }
}

async function loadPlaywright() {
    try {
        return await import("playwright-core");
    } catch (err) {
        console.error("[fetch-tdescs] playwright-core is not installed.");
        console.error("                Run: npm install");
        console.error("                Then: npm run fetch-tdescs:install-browser");
        process.exit(2);
    }
}

/**
 * Find an installed Chrome (or Chrome-family) browser to drive via Playwright.
 * Order: $CHROME_EXE env, Chrome, Chrome Beta, Edge. Returns null if none found,
 * in which case the caller falls back to Playwright's bundled Chromium.
 */
function resolveBrowserExecutable() {
    if (process.env.CHROME_EXE && existsSync(process.env.CHROME_EXE)) return process.env.CHROME_EXE;
    const candidates = [
        process.env.ProgramFiles && path.join(process.env.ProgramFiles, "Google", "Chrome", "Application", "chrome.exe"),
        process.env["ProgramFiles(x86)"] && path.join(process.env["ProgramFiles(x86)"], "Google", "Chrome", "Application", "chrome.exe"),
        process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Google", "Chrome", "Application", "chrome.exe"),
        process.env.ProgramFiles && path.join(process.env.ProgramFiles, "Microsoft", "Edge", "Application", "msedge.exe"),
        process.env["ProgramFiles(x86)"] && path.join(process.env["ProgramFiles(x86)"], "Microsoft", "Edge", "Application", "msedge.exe"),
    ].filter(Boolean);
    for (const p of candidates) if (existsSync(p)) return p;
    return null;
}

// ---------- main ----------------------------------------------------------

async function main() {
    const args = parseArgs(process.argv.slice(2));

    await fs.mkdir(FIXTURES, { recursive: true });

    const manifest = await readJson(MANIFEST_PATH);
    if (!manifest || !Array.isArray(manifest.entries)) {
        throw new Error(`Missing or malformed manifest: ${MANIFEST_PATH}`);
    }
    const version = args.version ?? manifest.defaultVersion;
    if (!version) throw new Error("No version specified (pass --version=… or set defaultVersion in MANIFEST.json)");

    const { chromium } = await loadPlaywright();

    // Prefer the user's installed Chrome/Edge over Playwright's bundled Chromium.
    // Playwright's Chromium needs the VC++ runtime which is often missing on stock
    // Windows; the user's installed browser has its own bundled runtime. Set
    // `PLAYWRIGHT_BROWSERS_PATH=0` or env CHROME_EXE to override discovery.
    const browserPath = resolveBrowserExecutable();
    if (browserPath) {
        console.log(`[playwright] launching ${browserPath}`);
    } else {
        console.log(`[playwright] launching bundled Chromium (no installed Chrome/Edge found)`);
    }
    const browser = await chromium.launch({
        headless: true,
        ...(browserPath ? { executablePath: browserPath, channel: undefined } : {}),
    });
    try {
        const context = await browser.newContext({
            userAgent:
                // Use a current Chrome UA. Playwright's bundled Chromium is recent; the UA
                // should match the version of the bundled browser, but Cloudflare cares
                // about TLS far more than UA, and any plausible Chrome string is fine.
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            extraHTTPHeaders: {
                "Accept-Language": "en-US,en;q=0.9",
            },
            viewport: { width: 1280, height: 800 },
        });

        // Warm up: visit the homepage so Cloudflare establishes any session state
        // it wants to. Subsequent context.request calls inherit cookies/TLS.
        const page = await context.newPage();
        console.log(`[playwright] warming up: GET ${SITE}/`);
        await page.goto(`${SITE}/`, { waitUntil: "domcontentloaded", timeout: 30_000 });
        // Cloudflare's challenge runs JS that auto-resolves; give it a beat.
        await page.waitForTimeout(2_500);
        const title = await page.title();
        if (title.toLowerCase().includes("just a moment")) {
            console.log("[playwright] saw Cloudflare challenge, waiting it out…");
            await page.waitForTimeout(6_000);
        }
        console.log(`[playwright] page settled: "${title.slice(0, 60)}"`);

        /**
         * Run a fetch *inside the page* so it uses the same network stack
         * that Cloudflare already cleared. `context.request` uses a separate
         * HTTP client whose TLS stack still trips the JA4 detector.
         */
        async function fetchInPage(url) {
            return await page.evaluate(async (u) => {
                const r = await fetch(u, {
                    headers: { "accept": "application/json, text/plain, */*" },
                    credentials: "include",
                });
                return { status: r.status, body: await r.text() };
            }, url);
        }

        // --------- probe mode ----------
        if (args.probe) {
            const url = `${DOC_ENDPOINT}?${new URLSearchParams({ path: args.probe, version })}`;
            const res = await fetchInPage(url);
            console.log(`[probe] ${url}`);
            console.log(`        HTTP ${res.status}  bytes=${res.body.length}`);
            console.log(`        first 200 chars: ${JSON.stringify(res.body.slice(0, 200))}`);
            return;
        }

        // --------- 1. Get index (cache to disk) ----------
        let index = args["refresh-index"] ? null : await readJson(INDEX_CACHE);
        if (!index) {
            const searchUrl = `${SEARCH_ENDPOINT}?${new URLSearchParams({ q: "*", version })}`;
            console.log(`[playwright] GET ${searchUrl} (via page fetch)`);
            const res = await fetchInPage(searchUrl);
            if (res.status !== 200) {
                console.error(`[playwright] index fetch returned HTTP ${res.status}; first 200 chars:`);
                console.error(res.body.slice(0, 200));
                throw new Error("index fetch failed");
            }
            try {
                index = JSON.parse(res.body);
            } catch (err) {
                console.error("[playwright] index response was not valid JSON; first 400 chars:");
                console.error(res.body.slice(0, 400));
                throw err;
            }
            await fs.writeFile(INDEX_CACHE, JSON.stringify(index, null, 2), "utf8");
            console.log(`[playwright] cached index → ${path.relative(ROOT, INDEX_CACHE)} (${res.body.length}B)`);
        } else {
            console.log(`[playwright] using cached index from ${path.relative(ROOT, INDEX_CACHE)}`);
        }

        const indexEntries = normalizeIndex(index);
        console.log(`[playwright] index has ${indexEntries.length} entries`);

        // --------- 2. Per-class lookup + fetch ----------
        const entries = manifest.entries.filter(e => !args.only || e.name === args.only);
        let ok = 0, skip = 0, fail = 0;

        for (const entry of entries) {
            // Lot 51's API serves TDESCs as JSON (with a ":@" convention for attributes).
            // Save as .tdesc.json so downstream code can dispatch on extension.
            const outPath = path.join(FIXTURES, `${entry.name}.tdesc.json`);

            try {
                await fs.access(outPath);
                console.log(`[=]  ${entry.name.padEnd(22)} already on disk`);
                skip++;
                continue;
            } catch { /* fetch it */ }

            // Path resolution: manifest > index lookup.
            const resolvedPath = entry.path || findPathInIndex(index, entry.name);
            if (!resolvedPath) {
                console.log(`[X]  ${entry.name.padEnd(22)} no path in MANIFEST and no match in index`);
                fail++;
                continue;
            }

            const url = `${DOC_ENDPOINT}?${new URLSearchParams({ path: resolvedPath, version: entry.version ?? version })}`;
            const res = await fetchInPage(url);
            const body = res.body;

            if (res.status !== 200) {
                console.log(`[X]  ${entry.name.padEnd(22)} HTTP ${res.status}  path=${resolvedPath}`);
                fail++;
                continue;
            }
            const head = body.trim().slice(0, 200);
            const looksLikeChallenge = head.includes("Just a moment") || head.includes("__cf_chl_opt");
            if (looksLikeChallenge) {
                console.log(`[X]  ${entry.name.padEnd(22)} cloudflare challenge — bailing.`);
                fail++;
                break;
            }
            // Lot 51 serves TDESCs as JSON; legacy XML-style would also be acceptable.
            const looksLikeJson = head.startsWith("{") || head.startsWith("[");
            const looksLikeXml = head.startsWith("<?xml") || head.startsWith("<TDesc") || head.startsWith("<Class");
            if (!looksLikeJson && !looksLikeXml) {
                const rawPath = outPath.replace(/\.tdesc\.json$/, ".raw");
                await fs.writeFile(rawPath, body, "utf8");
                console.log(`[?]  ${entry.name.padEnd(22)} unrecognized payload (${body.length}B), saved ${path.relative(ROOT, rawPath)} for inspection`);
                fail++;
                continue;
            }
            // Validate JSON parses, and verify it's a TuningRoot-shaped TDESC.
            if (looksLikeJson) {
                try {
                    const parsed = JSON.parse(body);
                    if (!parsed.TuningRoot) {
                        console.log(`[?]  ${entry.name.padEnd(22)} JSON has no TuningRoot key — schema may differ`);
                    }
                } catch (err) {
                    console.log(`[X]  ${entry.name.padEnd(22)} body is not valid JSON: ${err.message}`);
                    fail++;
                    continue;
                }
            }

            await fs.writeFile(outPath, body, "utf8");
            console.log(`[ok] ${entry.name.padEnd(22)} ${body.length}B  path=${resolvedPath}`);
            ok++;

            await page.waitForTimeout(DELAY_MS);
        }

        console.log("");
        console.log(`[summary] ok=${ok}  skip=${skip}  fail=${fail}  (of ${entries.length})`);
        if (fail > 0) process.exitCode = 1;
    } finally {
        await browser.close();
    }
}

main().catch(err => {
    console.error(err);
    process.exit(1);
});
