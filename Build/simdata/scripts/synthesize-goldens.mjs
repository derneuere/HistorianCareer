// scripts/synthesize-goldens.mjs
//
// Generate synthetic golden SimData files for round-trip testing.
//
// Strategy: for each supported class, build a small EA-style SimData using
// @s4tk/models directly (no tuning XML), serialize it, then write the bytes
// to `test/golden/<className>/synthetic.simdata`. These are not EA goldens —
// they're closed-loop fixtures that exercise the @s4tk/models read/write path
// and let us regression-test our own pipeline against a known-good binary.
//
// When real EA goldens become available (via `extract-golden.mjs`), they
// replace the synthetic ones — no test changes required.

import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SimDataResource } from "@s4tk/models";
import { DataType } from "@s4tk/models/enums.js";
import {
  SimDataSchema,
  SimDataSchemaColumn,
  SimDataInstance,
} from "@s4tk/models/lib/resources/simdata/fragments.js";
import {
  ObjectCell,
  NumberCell,
  TextCell,
  BigIntCell,
  ResourceKeyCell,
  VectorCell,
  BooleanCell,
} from "@s4tk/models/lib/resources/simdata/cells.js";
import { fnv32 } from "@s4tk/hashing/hashing.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const GOLDEN_DIR = path.resolve(__dirname, "../test/golden");

function hashSchema(name) {
  return (fnv32(name) | 0x80000000) >>> 0;
}

function makeSchema(name, columns) {
  const cols = [...columns]
    .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
    .map((c) => new SimDataSchemaColumn(c.name, c.type, 0));
  return new SimDataSchema(name, hashSchema(name), cols);
}

function writeOne(className, schema, instanceName, row) {
  const objCell = new ObjectCell(schema, row);
  const instance = SimDataInstance.fromObjectCell(instanceName, objCell);
  const r = new SimDataResource({
    version: 0x101,
    unused: 0,
    schemas: [schema],
    instances: [instance],
  });
  return r.getBuffer();
}

async function main() {
  await fs.mkdir(GOLDEN_DIR, { recursive: true });

  // Synthetic Aspiration
  const aspSchema = makeSchema("Aspiration", [
    { name: "display_name", type: DataType.LocalizationKey },
    { name: "display_description", type: DataType.LocalizationKey },
    { name: "objectives", type: DataType.Vector },
    { name: "reward", type: DataType.TableSetReference },
  ]);
  const aspBuf = writeOne("Aspiration", aspSchema, "synthetic_aspiration", {
    display_name: new NumberCell(DataType.LocalizationKey, 0xDEADBEEF),
    display_description: new NumberCell(DataType.LocalizationKey, 0xCAFEBABE),
    objectives: new VectorCell([
      new BigIntCell(DataType.TableSetReference, 0x1111111111111111n),
      new BigIntCell(DataType.TableSetReference, 0x2222222222222222n),
    ]),
    reward: new BigIntCell(DataType.TableSetReference, 0n),
  });
  await fs.mkdir(path.join(GOLDEN_DIR, "Aspiration"), { recursive: true });
  await fs.writeFile(
    path.join(GOLDEN_DIR, "Aspiration", "synthetic.simdata"),
    aspBuf,
  );

  // Synthetic Trait
  const traitSchema = makeSchema("Trait", [
    { name: "display_name", type: DataType.LocalizationKey },
    { name: "trait_description", type: DataType.LocalizationKey },
    { name: "trait_type", type: DataType.Int64 },
    { name: "icon", type: DataType.ResourceKey },
  ]);
  const traitBuf = writeOne("Trait", traitSchema, "synthetic_trait", {
    display_name: new NumberCell(DataType.LocalizationKey, 0x12345678),
    trait_description: new NumberCell(DataType.LocalizationKey, 0x9ABCDEF0),
    trait_type: new BigIntCell(DataType.Int64, 1n),
    icon: new ResourceKeyCell(0x00B2D882, 0, 0xDEADBEEFCAFEBABEn),
  });
  await fs.mkdir(path.join(GOLDEN_DIR, "Trait"), { recursive: true });
  await fs.writeFile(
    path.join(GOLDEN_DIR, "Trait", "synthetic.simdata"),
    traitBuf,
  );

  // Synthetic Buff
  const buffSchema = makeSchema("Buff", [
    { name: "buff_name", type: DataType.LocalizationKey },
    { name: "buff_description", type: DataType.LocalizationKey },
    { name: "mood_weight", type: DataType.Int32 },
    { name: "ui_sort_order", type: DataType.Int32 },
  ]);
  const buffBuf = writeOne("Buff", buffSchema, "synthetic_buff", {
    buff_name: new NumberCell(DataType.LocalizationKey, 0xAAAAAAAA),
    buff_description: new NumberCell(DataType.LocalizationKey, 0xBBBBBBBB),
    mood_weight: new NumberCell(DataType.Int32, 1),
    ui_sort_order: new NumberCell(DataType.Int32, 99),
  });
  await fs.mkdir(path.join(GOLDEN_DIR, "Buff"), { recursive: true });
  await fs.writeFile(path.join(GOLDEN_DIR, "Buff", "synthetic.simdata"), buffBuf);

  console.log(`Wrote synthetic goldens to ${GOLDEN_DIR}`);
  console.log("  Aspiration: aspBuf size", aspBuf.byteLength);
  console.log("  Trait:      traitBuf size", traitBuf.byteLength);
  console.log("  Buff:       buffBuf size", buffBuf.byteLength);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
