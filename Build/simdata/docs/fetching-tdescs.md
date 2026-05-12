# Fetching TDESC files

The Lot 51 TDESC API (`https://tdesc.lot51.cc/api/tdesc/doc?path=…`) sits behind Cloudflare's bot-fight mode, which uses **TLS-fingerprint** detection (JA3/JA4). Plain HTTP clients — `curl`, Node's `fetch`, `axios`, `undici` — all get 403'd no matter what headers or cookies you send. Browsers pass because their TLS handshake (BoringSSL, Chrome-specific cipher ordering) is on Cloudflare's allow-list.

The right fix is therefore a real browser. We use Playwright with its bundled Chromium.

## One-time setup

```powershell
cd HistorianCareer/Build/simdata

npm install                                      # ~3 MB, installs playwright-core
npm run fetch-tdescs:install-browser             # ~170 MB, downloads Chromium to a per-user cache
```

Chromium is cached under `%LOCALAPPDATA%\ms-playwright\`. It's reused across all Playwright projects on the machine, so this is genuinely one-time.

## Fetching

```powershell
# Fetch every entry in MANIFEST.json that isn't already on disk:
npm run fetch-tdescs

# Or invoke directly:
node scripts/fetch-tdescs.mjs

# Fetch just one class by name:
node scripts/fetch-tdescs.mjs --only=Career

# Force-refresh the cached index (use after an EA patch):
node scripts/fetch-tdescs.mjs --refresh-index

# Debug a specific path:
node scripts/fetch-tdescs.mjs --probe='Careers/Descriptions/Career.tdesc'
```

What the script does on each run:
1. Launches headless Chromium.
2. Visits `https://tdesc.lot51.cc/` to settle any Cloudflare challenge.
3. Hits `/api/simdex/search/tdesc?q=*&version=…` and caches the JSON to `test/fixtures/tdescs/_index.json` (gitignored).
4. For each entry in [`MANIFEST.json`](../test/fixtures/tdescs/MANIFEST.json), uses the index to locate the correct `path` query value, then `GET`s `/api/tdesc/doc?path=…&version=…` and saves the body as `<name>.tdesc`.

Per-entry status lines:
- `[ok]` — saved.
- `[=]`  — already on disk.
- `[X]`  — failed. Most common: Cloudflare challenge couldn't be cleared (rare with Playwright; try again, or pass `--refresh-index`).
- `[?]`  — got 200 but the body didn't look like XML; saved as `<name>.raw` so you can inspect what came back.

## Path overrides

If the index auto-match picks the wrong file for a class, set the `path` field explicitly in `MANIFEST.json`. The format is whatever goes into the `path=` query parameter at `/api/tdesc/doc?path=…`. You can find it by browsing `https://tdesc.lot51.cc/` to the file in question and looking at the URL.

## Versioning

EA patches periodically change TDESC contents. `MANIFEST.json` carries a `defaultVersion` field (currently `1.124.55`). Update it after game updates, then `--refresh-index` to pull fresh paths.

## Why not Playwright's full `playwright` package?

We use `playwright-core` instead of `playwright`. Difference: `playwright` auto-downloads all browsers on `npm install`; `playwright-core` is the library only, and you opt into browser downloads via `npm run fetch-tdescs:install-browser`. This keeps a default `npm install` light (3 MB instead of 200+ MB).

## Node version

Playwright 1.40+ requires Node 18+. We pin to **`playwright-core@1.39.0`** for Node 16 compatibility. If you upgrade to Node 18+, you can bump the pin in `package.json`.
