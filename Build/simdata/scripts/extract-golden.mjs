// scripts/extract-golden.mjs
//
// Use @s4tk/extraction (when installed) to pull tuning + SimData pairs from a
// local Sims 4 game install. Run this on a machine with the game; the
// resulting fixtures end up at test/golden/<className>/<resourceName>.{tuning.xml,simdata}.
//
// This script is a stub when @s4tk/extraction is not installed, but documents
// the workflow so future maintainers can fill it in.

import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const GOLDEN_DIR = path.resolve(__dirname, "../test/golden");

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--game-dir") out.gameDir = argv[++i];
    else if (a === "--class") (out.classes ??= []).push(argv[++i]);
    else if (a === "--help" || a === "-h") out.help = true;
  }
  return out;
}

const HELP = `Usage: node scripts/extract-golden.mjs --game-dir <path-to-game> [--class Career] [--class Trait] ...

Extracts paired (tuning XML, SimData binary) fixtures from a Sims 4 game install
and writes them under test/golden/<className>/.

Currently a stub. To enable, install @s4tk/extraction and implement the
extraction loop below.

Example (once implemented):
  node scripts/extract-golden.mjs --game-dir "C:/Program Files (x86)/Origin Games/The Sims 4" \\
                                  --class Career --class Trait
`;

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.gameDir) {
    process.stdout.write(HELP);
    process.exit(args.help ? 0 : 2);
  }

  // -----------------------------------------------------------------
  // Stub: when @s4tk/extraction is added as a devDependency, replace
  // the block below with the real extraction. The plan calls for:
  //
  // 1. Open the game's tuning packages (FullBuild0.package, etc.) with
  //    `@s4tk/models`' Package.from.
  // 2. For each Layer-B class in `args.classes` (default: the 8 from plan
  //    §3 plus Buff), find one example resource and pull its (tuning XML,
  //    SimData) pair.
  // 3. Write them to test/golden/<className>/<resourceName>.{tuning.xml,simdata}.
  // -----------------------------------------------------------------

  process.stderr.write(
    "extract-golden.mjs: not implemented yet.\n" +
      "See docs/extracting-goldens.md for the manual workflow until @s4tk/extraction is wired in.\n",
  );

  await fs.mkdir(GOLDEN_DIR, { recursive: true });
  process.exit(2);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
