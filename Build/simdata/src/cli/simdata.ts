#!/usr/bin/env node
// Tiny CLI: `simdata <tuning.xml> [-o out.simdata]`.
//
// Reads a single tuning XML, generates the corresponding SimData binary, writes
// it to <out>. For the STBL key resolver we accept a JSON file via `--strings`
// which maps token (e.g. "HC_TRAIT_NAME") → string, with FNV-32-hashed keys.

import { promises as fs } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fnv32, fnv64 } from "@s4tk/hashing/hashing.js";
import { parseTuning } from "../tuning/parse.js";
import { createBuildContext } from "../build/build.js";
import { emitSimDataBuffer } from "../emit/emit.js";
import { buildSimDataForTuning, KNOWN_SCHEMA_HASHES, supportedClasses } from "../build/classes/index.js";

interface Args {
  readonly input: string;
  readonly output?: string;
  readonly stringsJson?: string;
  readonly listClasses?: boolean;
  readonly help?: boolean;
}

function parseArgs(argv: readonly string[]): Args {
  const out: { input?: string; output?: string; stringsJson?: string; listClasses?: boolean; help?: boolean } = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    switch (a) {
      case "-h":
      case "--help":
        out.help = true;
        break;
      case "-o":
      case "--output":
        out.output = argv[++i];
        break;
      case "--strings":
        out.stringsJson = argv[++i];
        break;
      case "--list-classes":
        out.listClasses = true;
        break;
      default:
        if (a.startsWith("-")) throw new Error(`Unknown flag: ${a}`);
        if (out.input) throw new Error(`Unexpected positional: ${a}`);
        out.input = a;
    }
  }
  if (!out.help && !out.listClasses && !out.input) {
    throw new Error("Missing input file. Try --help.");
  }
  return out as Args;
}

const HELP = `Usage: simdata <tuning.xml> [-o out.simdata] [--strings strings.json]

Generates the SimData binary companion for a Sims 4 tuning XML.

Flags:
  -o, --output <path>      Output path (default: <input>.simdata next to the input).
      --strings <json>     JSON file mapping STBL key tokens to translation strings.
                           Used to resolve 0xTBD_STBL_KEY_FOO tokens by hashing the
                           token with FNV-32.
      --list-classes       Print the tuning classes simdata can handle, then exit.
  -h, --help               Show this help.
`;

async function main(): Promise<void> {
  let args: Args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`simdata: ${(err as Error).message}\n${HELP}`);
    process.exit(2);
  }

  if (args.help) {
    process.stdout.write(HELP);
    return;
  }

  if (args.listClasses) {
    for (const c of supportedClasses()) process.stdout.write(c + "\n");
    return;
  }

  const inputPath = path.resolve(args.input);
  const xml = await fs.readFile(inputPath, "utf8");
  const tree = parseTuning(xml);

  // STBL key resolution. If a strings.json is supplied, build a Map of
  // token → key from its keys; otherwise tokens are required to be absent
  // (resolver will throw if encountered).
  let strings: Record<string, unknown> | undefined;
  if (args.stringsJson) {
    strings = JSON.parse(await fs.readFile(path.resolve(args.stringsJson), "utf8"));
  }

  const ctx = createBuildContext({
    resolveStblKey: (token) => {
      if (!strings) throw new Error(`Token "${token}" requires --strings.`);
      // Strings JSON convention (mirrors the HistorianCareer builder):
      //   { en: { TOKEN: "English text", … }, de: { … }, … }
      const en = (strings as { en?: Record<string, string> }).en;
      if (!en || !(token in en)) throw new Error(`Unknown STBL token "${token}".`);
      return fnv32(token);
    },
    resolveTuningRef: (name) => fnv64(name, true),
    knownSchemaHashes: KNOWN_SCHEMA_HASHES,
  });

  const ir = buildSimDataForTuning(tree, ctx);
  const buffer = emitSimDataBuffer(ir);

  const outputPath = args.output
    ? path.resolve(args.output)
    : inputPath.replace(/\.xml$/i, ".simdata");
  await fs.writeFile(outputPath, buffer);
  process.stdout.write(
    `simdata: wrote ${buffer.byteLength} bytes (schema=${tree.rootClass}) to ${outputPath}\n`,
  );
}

main().catch((err) => {
  process.stderr.write(`simdata: ${(err as Error).stack ?? (err as Error).message}\n`);
  process.exit(1);
});
