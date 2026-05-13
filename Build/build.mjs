#!/usr/bin/env node
// build.mjs — build HistorianCareer for The Sims 4 end-to-end.
//
// Produces:
//   Build/out/HistorianCareer_Tuning.package    XML tuning + STBL + SimData + DDS icons
//   Build/out/HistorianCareer.ts4script         Raw .py sources, zipped (no compileall)
//
// Default: build BOTH artifacts (with Layer B), install to the Sims 4 Mods
// folder, and nuke the Sims 4 thumb/cache files so the next launch reloads
// everything cleanly. The defaults match the common dev loop; flags below
// opt out of any step.
//
// Usage (from anywhere; this resolves paths relative to its own location):
//   node Build/build.mjs                      # full build + install + cache clear (default)
//   node Build/build.mjs --no-install         # build only, no copy
//   node Build/build.mjs --no-cache-clear     # build + install, leave caches alone
//   node Build/build.mjs --package-only       # skip .ts4script (and skip install of it)
//   node Build/build.mjs --script-only        # skip .package
//   node Build/build.mjs --no-layer-b         # Layer A only (faster, no SimData)
//   node Build/build.mjs --mods-folder PATH   # override the auto-detected Mods folder
//
// Why this exists: build.ps1 needed PowerShell, Python 3.7, and a manual cache
// nuke between runs. This script removes all three (cross-platform, no Python,
// auto-clears caches). See issue #19.

import { spawn } from "node:child_process";
import { promises as fs, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const SCRIPTS_DIR = path.join(PROJECT_ROOT, "Scripts");
const OUT_DIR = path.join(__dirname, "out");
const S4TK_BUILDER_DIR = path.join(__dirname, "s4tk-builder");
const SIMDATA_DIR = path.join(__dirname, "simdata");

const PKG_NAME = "HistorianCareer";
const TS4SCRIPT_OUT = path.join(OUT_DIR, `${PKG_NAME}.ts4script`);
const PACKAGE_OUT = path.join(OUT_DIR, `${PKG_NAME}_Tuning.package`);

// ----------------------------------------------------------------------------
// CLI
// ----------------------------------------------------------------------------

function parseArgs(argv) {
  const opts = {
    packageOnly: false,
    scriptOnly: false,
    install: true,
    cacheClear: true,
    layerB: true,
    modsFolder: null,
    help: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case "--package-only":    opts.packageOnly = true; break;
      case "--script-only":     opts.scriptOnly  = true; break;
      case "--no-install":      opts.install     = false; break;
      case "--no-cache-clear":  opts.cacheClear  = false; break;
      case "--no-layer-b":      opts.layerB      = false; break;
      case "--mods-folder":     opts.modsFolder  = argv[++i]; break;
      case "-h": case "--help": opts.help        = true; break;
      default:
        if (a.startsWith("--mods-folder=")) opts.modsFolder = a.slice("--mods-folder=".length);
        else { console.error(`Unknown argument: ${a}`); process.exit(2); }
    }
  }
  if (opts.packageOnly && opts.scriptOnly) {
    console.error("--package-only and --script-only are mutually exclusive.");
    process.exit(2);
  }
  return opts;
}

function printHelp() {
  console.log(`build.mjs — build HistorianCareer for The Sims 4.

Defaults to: full build (Layer A + B), install to Mods folder, clear Sims 4 caches.

Flags:
  --package-only       Skip .ts4script (build .package only).
  --script-only        Skip .package (build .ts4script only).
  --no-install         Don't copy outputs to the Mods folder.
  --no-cache-clear     Don't delete Sims 4 thumb/cache files.
  --no-layer-b         Build Layer A only (no Career/Aspiration SimData).
  --mods-folder PATH   Override the auto-detected Mods folder.
  -h, --help           Show this help.`);
}

// ----------------------------------------------------------------------------
// helpers
// ----------------------------------------------------------------------------

const C = {
  cyan:  s => `\x1b[36m${s}\x1b[0m`,
  gray:  s => `\x1b[90m${s}\x1b[0m`,
  green: s => `\x1b[32m${s}\x1b[0m`,
  yellow:s => `\x1b[33m${s}\x1b[0m`,
  red:   s => `\x1b[31m${s}\x1b[0m`,
};
const log = (msg, c = "cyan") => console.log(C[c](msg));

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: "inherit", shell: process.platform === "win32", ...opts });
    child.on("error", reject);
    child.on("exit", code => code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`)));
  });
}

async function exists(p) {
  try { await fs.access(p); return true; } catch { return false; }
}

/**
 * Returns true when any `.ts` file under `<simdataDir>/src` has an mtime newer
 * than the freshest file in `<simdataDir>/dist`. Cheap, no hashing — just stat
 * traversal. Used to decide whether tsc needs to re-run before each build.
 */
async function isSourceNewerThanDist(simdataDir) {
  const srcDir = path.join(simdataDir, "src");
  const distDir = path.join(simdataDir, "dist");
  if (!(await exists(srcDir)) || !(await exists(distDir))) return true;
  async function newestMtimeUnder(root, extFilter) {
    let newest = 0;
    async function walk(dir) {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      for (const e of entries) {
        const p = path.join(dir, e.name);
        if (e.isDirectory()) await walk(p);
        else if (!extFilter || extFilter(e.name)) {
          const stat = await fs.stat(p);
          if (stat.mtimeMs > newest) newest = stat.mtimeMs;
        }
      }
    }
    await walk(root);
    return newest;
  }
  const srcNewest  = await newestMtimeUnder(srcDir,  n => n.endsWith(".ts"));
  const distNewest = await newestMtimeUnder(distDir, n => n.endsWith(".js"));
  return srcNewest > distNewest;
}

/**
 * Auto-detect the Sims 4 user-data folder. The game localizes its folder name
 * by language (Die Sims 4 / Les Sims 4 / Los Sims 4 / …). Prefer the sibling
 * under ~/Documents/Electronic Arts/ that has an Options.ini (the marker that
 * the game has been launched and configured there). Returns the *root* user-
 * data folder, NOT the Mods subfolder — the cache-clear step needs the root.
 */
async function findSims4UserDataFolder() {
  const eaDocs = path.join(os.homedir(), "Documents", "Electronic Arts");
  if (!(await exists(eaDocs))) return null;
  const entries = await fs.readdir(eaDocs, { withFileTypes: true });
  const candidates = entries
    .filter(e => e.isDirectory() && /^(The|Die|Les|Los) Sims 4$/.test(e.name))
    .map(e => path.join(eaDocs, e.name));
  // Prefer the one with Options.ini; else first match; else null.
  for (const c of candidates) {
    if (await exists(path.join(c, "Options.ini"))) return c;
  }
  return candidates[0] ?? null;
}

// ----------------------------------------------------------------------------
// Step 1: build the .package (delegates to s4tk-builder)
// ----------------------------------------------------------------------------

async function buildPackage({ layerB }) {
  log(`==> Building ${path.relative(PROJECT_ROOT, PACKAGE_OUT)} (s4tk-builder)`);

  // Ensure simdata is npm-installed and tsc-compiled when Layer B is wanted.
  // Also recompile when any source file is newer than the dist (otherwise edits
  // to schemas.ts or classes/index.ts silently don't reach the build until you
  // manually rm -rf dist/). Common dev-loop trap: agent edits a .ts schema,
  // build runs the stale dist, package ships without the new class registered.
  if (await exists(SIMDATA_DIR)) {
    if (!(await exists(path.join(SIMDATA_DIR, "node_modules")))) {
      log("    installing simdata dependencies...", "gray");
      await run("npm", ["install", "--silent"], { cwd: SIMDATA_DIR });
    }
    const distIndex = path.join(SIMDATA_DIR, "dist", "index.js");
    const needsCompile = !(await exists(distIndex)) || (await isSourceNewerThanDist(SIMDATA_DIR));
    if (needsCompile) {
      log("    compiling simdata (tsc)...", "gray");
      await run("npx", ["tsc"], { cwd: SIMDATA_DIR });
    }
  }

  if (!(await exists(path.join(S4TK_BUILDER_DIR, "node_modules")))) {
    log("    installing s4tk-builder dependencies...", "gray");
    await run("npm", ["install", "--silent"], { cwd: S4TK_BUILDER_DIR });
  }

  const builderArgs = ["build-package.mjs"];
  if (layerB) builderArgs.push("--include-layer-b");
  await run("node", builderArgs, { cwd: S4TK_BUILDER_DIR });
}

// ----------------------------------------------------------------------------
// Step 2: build the .ts4script (zip of compiled .pyc files)
//
// Originally (commit 46fe592) we shipped raw .py and relied on Sims 4's
// runtime CPython 3.7 to compile on first import. That theoretically works
// (zipimport accepts both .py and .pyc per PEP 273) but in practice, on
// 1.124.55, our raw-.py packages silently fail to load: no entry in
// lastException.txt, no `historiancareer_debug.log` write, no marker from
// our `_hc_emit_loadtest_marker()` at the top of __init__.py — Sims 4's
// import system simply doesn't reach our package. EA's own ts4scripts all
// ship .pyc; matching their convention is what makes our package visible.
//
// We compile with Python 3.7 specifically (matches Sims 4's interpreter
// version — .pyc bytecode magic numbers are version-locked, and Sims 4's
// 3.7 will silently reject .pyc compiled with 3.10/3.11/3.12).
//
// If Python 3.7 isn't installed (no `py -3.7` and no `python3.7`), we fall
// back to shipping raw .py with a loud warning. The user can install 3.7
// from https://www.python.org/downloads/release/python-379/ — small,
// fast, and the only thing the build needs Python for.
// ----------------------------------------------------------------------------

// CRC32 table (precomputed lazily, IEEE polynomial 0xEDB88320).
let CRC32_TABLE = null;
function crc32(buf) {
  if (!CRC32_TABLE) {
    CRC32_TABLE = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      CRC32_TABLE[n] = c >>> 0;
    }
  }
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC32_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// Encode a JS Date as MS-DOS (time, date) for zip headers.
function dosDateTime(d) {
  const time = ((d.getHours() & 0x1f) << 11) | ((d.getMinutes() & 0x3f) << 5) | ((d.getSeconds() / 2) & 0x1f);
  const date = (((d.getFullYear() - 1980) & 0x7f) << 9) | (((d.getMonth() + 1) & 0x0f) << 5) | (d.getDate() & 0x1f);
  return { time, date };
}

/**
 * Recursively collect all .py files under root. Returns objects with the
 * absolute path and the POSIX-style entry name relative to `root`. Skips
 * .pyc, __pycache__/, and anything starting with "." or "_".
 */
async function collectScriptFiles(root) {
  const out = [];
  async function walk(dir) {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name === "__pycache__" || e.name.startsWith(".")) continue;
        await walk(full);
      } else if (e.isFile() && e.name.endsWith(".py")) {
        const rel = path.relative(root, full).split(path.sep).join("/");
        out.push({ full, name: rel });
      }
    }
  }
  await walk(root);
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Minimal zip writer. Produces a ZIP file with each input as a DEFLATE-
 * compressed entry. POSIX path separators in entry names (Sims 4's Python
 * zipimport needs forward slashes — backslashes silently break import).
 * No zip64, no encryption, no extra fields.
 */
async function writeZip(outPath, files) {
  const { time, date } = dosDateTime(new Date());
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;
  let entryCount = 0;

  for (const f of files) {
    const raw = await fs.readFile(f.full);
    const compressed = zlib.deflateRawSync(raw);
    const useDeflate = compressed.length < raw.length;
    const data = useDeflate ? compressed : raw;
    const method = useDeflate ? 8 : 0;
    const crc = crc32(raw);
    const nameBuf = Buffer.from(f.name, "utf8");

    // Local file header (PK\03\04).
    const lfh = Buffer.alloc(30);
    lfh.writeUInt32LE(0x04034b50, 0);
    lfh.writeUInt16LE(20, 4);             // version needed
    lfh.writeUInt16LE(0, 6);              // flags
    lfh.writeUInt16LE(method, 8);
    lfh.writeUInt16LE(time, 10);
    lfh.writeUInt16LE(date, 12);
    lfh.writeUInt32LE(crc, 14);
    lfh.writeUInt32LE(data.length, 18);   // compressed size
    lfh.writeUInt32LE(raw.length, 22);    // uncompressed size
    lfh.writeUInt16LE(nameBuf.length, 26);
    lfh.writeUInt16LE(0, 28);             // extra field length
    localChunks.push(lfh, nameBuf, data);

    // Central directory entry (PK\01\02).
    const cdh = Buffer.alloc(46);
    cdh.writeUInt32LE(0x02014b50, 0);
    cdh.writeUInt16LE(20, 4);             // version made by
    cdh.writeUInt16LE(20, 6);             // version needed
    cdh.writeUInt16LE(0, 8);              // flags
    cdh.writeUInt16LE(method, 10);
    cdh.writeUInt16LE(time, 12);
    cdh.writeUInt16LE(date, 14);
    cdh.writeUInt32LE(crc, 16);
    cdh.writeUInt32LE(data.length, 20);
    cdh.writeUInt32LE(raw.length, 24);
    cdh.writeUInt16LE(nameBuf.length, 28);
    cdh.writeUInt16LE(0, 30);             // extra
    cdh.writeUInt16LE(0, 32);             // comment
    cdh.writeUInt16LE(0, 34);             // disk number
    cdh.writeUInt16LE(0, 36);             // internal attrs
    cdh.writeUInt32LE(0, 38);             // external attrs
    cdh.writeUInt32LE(offset, 42);        // local header offset
    centralChunks.push(cdh, nameBuf);

    offset += 30 + nameBuf.length + data.length;
    entryCount++;
  }

  const centralSize = centralChunks.reduce((s, b) => s + b.length, 0);
  const centralOffset = offset;

  // End of central directory (PK\05\06).
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(0, 4);                       // disk number
  eocd.writeUInt16LE(0, 6);                       // disk of central dir start
  eocd.writeUInt16LE(entryCount, 8);              // records on this disk
  eocd.writeUInt16LE(entryCount, 10);             // total records
  eocd.writeUInt32LE(centralSize, 12);
  eocd.writeUInt32LE(centralOffset, 16);
  eocd.writeUInt16LE(0, 20);                      // comment length

  const out = Buffer.concat([...localChunks, ...centralChunks, eocd]);
  await fs.writeFile(outPath, out);
  return { entryCount, bytes: out.length };
}

/**
 * Catch the most common stale-cache-defeating bug: shipping a .ts4script that
 * fails to compile inside the game. Sims 4 silently swallows SyntaxError /
 * IndentationError / TabError during package import (it just logs to console,
 * which most players can't see). We've now lost two debug cycles to this; if
 * we can detect it at build time, do.
 *
 * We invoke Python 3 (any 3.7+) to `compile()` each .py file. If `python3` /
 * `py` / `python` isn't on PATH (rare on modern Win/Mac/Linux dev boxes) we
 * SKIP rather than fail — the build is still useful, the user just doesn't
 * get the static safety net.
 *
 * `compile(source, filename, "exec")` raises SyntaxError on any of the three
 * structural-error types. Returns a list of {file, error} on failure, [] on
 * success.
 */
async function pythonSyntaxCheck(files) {
  // Find a python interpreter on PATH. Prefer python3 (Mac/Linux convention)
  // → py -3 (Win launcher) → python (anywhere). We probe with `-V` and a
  // shell, since on Windows `py.exe` is on PATH but locating it via
  // child_process.spawn without a shell needs `.exe`.  Both probe and run
  // use the same shell setting to avoid path-resolution mismatches.
  const useShell = process.platform === "win32";
  const candidates = useShell
    ? ["py", "python3", "python"]
    : ["python3", "python"];
  let chosen = null;
  for (const c of candidates) {
    try {
      await new Promise((resolve, reject) => {
        const probeArgs = c === "py" ? ["-3", "-V"] : ["-V"];
        const child = spawn(c, probeArgs, { shell: useShell });
        child.on("error", reject);
        child.on("exit", code => code === 0 ? resolve() : reject(new Error(`exit ${code}`)));
      });
      chosen = c;
      break;
    } catch { /* try next */ }
  }
  if (!chosen) {
    log("    skipping Python syntax check (no python3 on PATH)", "gray");
    return [];
  }

  // Embed-checking via `-c` is annoying cross-platform: on Windows with
  // `shell: true`, the shell reparses the argument and our embedded newlines
  // break. Workaround: write the checker as a small .py file alongside
  // build.mjs and invoke it normally.
  const checkerPath = path.join(__dirname, "..py-syntax-check.py.tmp");
  const checker = [
    "import sys, ast",
    "errs = []",
    "for p in sys.argv[1:]:",
    "    try:",
    "        with open(p, 'rb') as f:",
    "            src = f.read()",
    "        ast.parse(src, filename=p)",
    "    except SyntaxError as e:",
    "        errs.append('{0}:{1}:{2}: {3}: {4}'.format(p, e.lineno, e.offset, type(e).__name__, e.msg))",
    "    except Exception as e:",
    "        errs.append('{0}: {1}: {2}'.format(p, type(e).__name__, e))",
    "if errs:",
    "    for e in errs: print(e)",
    "    sys.exit(1)",
    "",
  ].join("\n");
  await fs.writeFile(checkerPath, checker, "utf8");

  try {
    return await new Promise((resolve, reject) => {
      const args = chosen === "py" ? ["-3", checkerPath] : [checkerPath];
      for (const f of files) args.push(f.full);
      const stderrChunks = [];
      const stdoutChunks = [];
      const child = spawn(chosen, args, { shell: useShell });
      child.stdout.on("data", d => stdoutChunks.push(d));
      child.stderr.on("data", d => stderrChunks.push(d));
      child.on("error", reject);
      child.on("exit", code => {
        const stdout = Buffer.concat(stdoutChunks).toString();
        const stderr = Buffer.concat(stderrChunks).toString();
        if (code === 0) return resolve([]);
        const lines = stdout.split(/\r?\n/).filter(Boolean);
        resolve(lines.length ? lines : [stderr || `python exited ${code}`]);
      });
    });
  } finally {
    try { await fs.rm(checkerPath); } catch { /* ignore */ }
  }
}

/**
 * Locate a Python 3.7 interpreter. Returns the spawn command + args prefix, or
 * null if none found. On Windows, `py -3.7` is the launcher convention; on
 * Linux/macOS, `python3.7` is the standard path. We require 3.7 specifically
 * because Sims 4 ships 3.7 and .pyc bytecode magic is version-locked.
 */
async function findPython37() {
  const useShell = process.platform === "win32";
  const candidates = useShell
    ? [{ cmd: "py", args: ["-3.7"] }, { cmd: "python3.7", args: [] }]
    : [{ cmd: "python3.7", args: [] }, { cmd: "python3", args: [] }];
  for (const c of candidates) {
    try {
      const versionOutput = await new Promise((resolve, reject) => {
        const out = [];
        const child = spawn(c.cmd, [...c.args, "-V"], { shell: useShell });
        child.stdout.on("data", d => out.push(d));
        child.stderr.on("data", d => out.push(d));
        child.on("error", reject);
        child.on("exit", code => code === 0 ? resolve(Buffer.concat(out).toString()) : reject(new Error(`exit ${code}`)));
      });
      if (/Python 3\.7\./.test(versionOutput)) return c;
    } catch { /* try next */ }
  }
  return null;
}

/**
 * Compile a list of .py files to .pyc using Python 3.7's `py_compile`. Returns
 * a list of { full, name } where `full` is the .pyc on disk and `name` is the
 * POSIX-relative entry name (matching what the .py would have been, but with
 * .pyc extension). On compile error, throws with the per-file diagnostics.
 */
async function compileToPyc(py37, files, outDir) {
  await fs.mkdir(outDir, { recursive: true });
  // Build a {source: dest} map and feed it to a small helper script that
  // py_compile.compile()'s each one. Cleaner than spawning N processes.
  const pairs = files.map(f => ({
    src: f.full,
    dst: path.join(outDir, f.name.replace(/\.py$/, ".pyc")),
    name: f.name.replace(/\.py$/, ".pyc"),
  }));
  // Pre-mkdir the dst subdirs (collectScriptFiles preserves path structure).
  for (const p of pairs) await fs.mkdir(path.dirname(p.dst), { recursive: true });

  // Compile with optimize=2 (equivalent to running Python with `-OO`).
  //
  // Comments are dropped at the tokenizer stage on any optimize level — they
  // never make it into .pyc bytecode regardless. But DOCSTRINGS survive as
  // module/class/function constants on -O0/-O1, and Sims 4's tuning loader
  // has been observed to silently reject a sibling resource (a Statistic
  // XML) when that resource's source carried a multi-KB comment block with
  // unicode characters — taking the WHOLE resource down with no log entry
  // (issue #23). The Python side hasn't shown the same failure mode, but
  // shipping bytecode WITHOUT docstrings is cheap insurance: it
  //   - removes a large class of "free-form text in the artifact" surface
  //   - shrinks the .ts4script (smaller .pyc, faster load)
  //   - strips `assert` statements too — fine, none of ours are loadbearing.
  // optimize=2 = -OO. py_compile in Python 3.7 supports this arg.
  const helperPath = path.join(__dirname, ".pyc-compile-helper.py.tmp");
  const helper = [
    "import sys, py_compile",
    "errs = []",
    "for i in range(1, len(sys.argv), 2):",
    "    src = sys.argv[i]",
    "    dst = sys.argv[i+1]",
    "    try:",
    "        py_compile.compile(src, cfile=dst, doraise=True, optimize=2)",
    "    except py_compile.PyCompileError as e:",
    "        errs.append('{0}: {1}'.format(src, str(e).strip()))",
    "    except Exception as e:",
    "        errs.append('{0}: {1}: {2}'.format(src, type(e).__name__, e))",
    "if errs:",
    "    for e in errs: print(e)",
    "    sys.exit(1)",
    "",
  ].join("\n");
  await fs.writeFile(helperPath, helper, "utf8");

  try {
    await new Promise((resolve, reject) => {
      const args = [...py37.args, helperPath];
      for (const p of pairs) { args.push(p.src, p.dst); }
      const stdoutChunks = [], stderrChunks = [];
      const child = spawn(py37.cmd, args, { shell: process.platform === "win32" });
      child.stdout.on("data", d => stdoutChunks.push(d));
      child.stderr.on("data", d => stderrChunks.push(d));
      child.on("error", reject);
      child.on("exit", code => {
        if (code === 0) return resolve();
        const stdout = Buffer.concat(stdoutChunks).toString();
        const stderr = Buffer.concat(stderrChunks).toString();
        const lines = stdout.split(/\r?\n/).filter(Boolean);
        reject(new Error(`Python 3.7 compile failed:\n${(lines.length ? lines : [stderr]).join("\n")}`));
      });
    });
  } finally {
    try { await fs.rm(helperPath); } catch { /* ignore */ }
  }
  return pairs.map(p => ({ full: p.dst, name: p.name }));
}

async function buildTs4Script() {
  log(`==> Building ${path.relative(PROJECT_ROOT, TS4SCRIPT_OUT)} (.pyc bytecode, deflate-zipped)`);

  if (!(await exists(SCRIPTS_DIR))) {
    throw new Error(`Scripts/ directory not found at ${SCRIPTS_DIR}`);
  }
  const sourceFiles = await collectScriptFiles(SCRIPTS_DIR);
  if (sourceFiles.length === 0) {
    console.warn(C.yellow(`[warn] no .py files under ${SCRIPTS_DIR}; ts4script will be empty.`));
  }

  // Gate the zip on a Python syntax check (cheap, runs with any Python 3+).
  // We've shipped builds with hidden errors that Sims 4 silently swallowed;
  // catching them BEFORE the zip is created costs ~50ms.
  const syntaxErrs = await pythonSyntaxCheck(sourceFiles);
  if (syntaxErrs.length > 0) {
    console.error(C.red(`[FAIL] Python syntax errors detected; refusing to build .ts4script:`));
    for (const e of syntaxErrs) console.error(C.red(`    ${e}`));
    throw new Error(`${syntaxErrs.length} Python syntax error(s) in Scripts/`);
  }

  // Compile to .pyc using Python 3.7 (matches Sims 4's interpreter — .pyc
  // magic numbers are version-locked and 3.7 will silently reject anything
  // else). Falls back to raw .py with a loud warning if 3.7 isn't installed.
  const py37 = await findPython37();
  let zipFiles;
  if (py37) {
    log(`    compiling with Python 3.7 (${py37.cmd} ${py37.args.join(" ")})`, "gray");
    const pycOutDir = path.join(__dirname, ".pyc-build");
    // Wipe old .pyc dir so stale entries can't sneak into the zip.
    try { await fs.rm(pycOutDir, { recursive: true, force: true }); } catch { /* ignore */ }
    zipFiles = await compileToPyc(py37, sourceFiles, pycOutDir);
  } else {
    console.warn(C.yellow(`[warn] Python 3.7 not found on PATH (looked for 'py -3.7', 'python3.7').`));
    console.warn(C.yellow(`[warn] Falling back to raw .py — Sims 4 has been observed to silently`));
    console.warn(C.yellow(`[warn] skip loading .ts4scripts that contain raw .py instead of .pyc.`));
    console.warn(C.yellow(`[warn] Install 3.7 from https://www.python.org/downloads/release/python-379/`));
    zipFiles = sourceFiles;
  }

  // Atomic replace: write to a tmp path, then rename.
  const tmp = TS4SCRIPT_OUT + ".tmp";
  if (existsSync(tmp)) await fs.rm(tmp);
  if (existsSync(TS4SCRIPT_OUT)) await fs.rm(TS4SCRIPT_OUT);
  const { entryCount, bytes } = await writeZip(tmp, zipFiles);
  await fs.rename(tmp, TS4SCRIPT_OUT);

  for (const f of zipFiles) console.log(C.gray(`    + ${f.name}`));
  log(`    ${entryCount} entr${entryCount === 1 ? "y" : "ies"}, ${bytes} bytes`, "gray");
}

// ----------------------------------------------------------------------------
// Step 3: install to Mods folder
// ----------------------------------------------------------------------------

async function install({ modsFolder, packageOnly, scriptOnly }) {
  await fs.mkdir(modsFolder, { recursive: true });
  if (!scriptOnly && existsSync(PACKAGE_OUT)) {
    const dest = path.join(modsFolder, `${PKG_NAME}_Tuning.package`);
    await fs.copyFile(PACKAGE_OUT, dest);
    console.log(C.gray(`    + ${dest}`));
  }
  if (!packageOnly && existsSync(TS4SCRIPT_OUT)) {
    const dest = path.join(modsFolder, `${PKG_NAME}.ts4script`);
    await fs.copyFile(TS4SCRIPT_OUT, dest);
    console.log(C.gray(`    + ${dest}`));
  }
  log(`==> Installed to ${modsFolder}`, "green");
}

// ----------------------------------------------------------------------------
// Step 4: cache nuke
//
// Sims 4 caches thumbnails, sim avatars, and string assets in the user-data
// folder. The game does not re-read mod-derived content from these caches
// on every launch, so a mod change can be invisible until the caches are
// cleared. Without this step every iteration of "tweak XML / rebuild / launch
// game" risks the player seeing yesterday's build.
//
// We delete:
//   localthumbcache.package           primary thumbnail cache
//   localsimtexturecache.package      Sim texture cache (large; ~30MB+)
//   localsimtravelthumbcache.package  travel-screen Sim thumbnail cache
//   Onlinethumbnailcache.package      Gallery / online cache (legacy filename)
//   avatarcache.package               sim avatar cache
//   accountDataDB.package             account-side DB cache
//   clientDB.package                  client-side DB cache
//   houseDescription-client.package   house-description cache
//   cachestr/      (contents)         streamed asset cache
//   cache/         (contents)         general resource cache
//   onlinethumbnailcache/ (contents)  Gallery / online thumbnail cache (current)
//
// Without the DB-package caches, Sims 4 has been observed to silently filter
// mod-added aspirations / careers from binary-indexed CAS pickers even after
// the tuning + SimData are byte-correct (refs #17).
//
// We leave lastException*.txt / lastUIException*.txt alone — those are
// diagnostic logs from previous crashes; deleting them masks the very
// problems we'd want to debug.
// ----------------------------------------------------------------------------

async function nukeCache({ userDataFolder }) {
  log(`==> Clearing Sims 4 caches in ${userDataFolder}`);
  const files = [
    "localthumbcache.package",
    "localsimtexturecache.package",
    "localsimtravelthumbcache.package",
    "Onlinethumbnailcache.package",
    "avatarcache.package",
    "accountDataDB.package",
    "clientDB.package",
    "houseDescription-client.package",
  ];
  const dirs = ["cachestr", "cache", "onlinethumbnailcache"];

  let cleared = 0;
  for (const f of files) {
    const p = path.join(userDataFolder, f);
    if (existsSync(p)) {
      await fs.rm(p, { force: true });
      console.log(C.gray(`    - ${f}`));
      cleared++;
    }
  }
  for (const d of dirs) {
    const dir = path.join(userDataFolder, d);
    if (!existsSync(dir)) continue;
    // Empty the contents but keep the directory (the game expects it to exist).
    const entries = await fs.readdir(dir);
    for (const e of entries) {
      await fs.rm(path.join(dir, e), { recursive: true, force: true });
    }
    console.log(C.gray(`    - ${d}/ (${entries.length} entr${entries.length === 1 ? "y" : "ies"})`));
    if (entries.length > 0) cleared++;
  }
  if (cleared === 0) {
    log("    nothing to clear (caches already empty)", "gray");
  }
}

// ----------------------------------------------------------------------------
// main
// ----------------------------------------------------------------------------

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) { printHelp(); return; }

  await fs.mkdir(OUT_DIR, { recursive: true });

  // 1. Build artifacts.
  if (!opts.scriptOnly)  await buildPackage({ layerB: opts.layerB });
  if (!opts.packageOnly) await buildTs4Script();

  // Resolve where to install / which game user-data folder to clear caches in.
  let userDataFolder = null;
  let modsFolder = opts.modsFolder;
  if (opts.install || opts.cacheClear) {
    if (modsFolder) {
      // User specified Mods folder; the user-data folder is its parent.
      userDataFolder = path.dirname(path.dirname(modsFolder));
    } else {
      userDataFolder = await findSims4UserDataFolder();
      if (userDataFolder) {
        modsFolder = path.join(userDataFolder, "Mods", PKG_NAME);
      } else if (opts.install || opts.cacheClear) {
        console.warn(C.yellow(
          "[warn] Could not auto-detect the Sims 4 user-data folder under " +
          path.join(os.homedir(), "Documents", "Electronic Arts") +
          ". Pass --mods-folder to specify it, or --no-install --no-cache-clear to skip.",
        ));
      }
    }
  }

  // 2. Install.
  if (opts.install) {
    if (!modsFolder) {
      console.warn(C.yellow("[warn] Skipping install (no Mods folder)."));
    } else {
      await install({ modsFolder, packageOnly: opts.packageOnly, scriptOnly: opts.scriptOnly });
    }
  }

  // 3. Cache nuke.
  if (opts.cacheClear) {
    if (!userDataFolder) {
      console.warn(C.yellow("[warn] Skipping cache clear (no Sims 4 user-data folder)."));
    } else {
      await nukeCache({ userDataFolder });
    }
  }

  log("==> Done.", "green");
}

main().catch(err => {
  console.error(C.red(`[error] ${err.stack ?? err.message ?? err}`));
  process.exit(1);
});
