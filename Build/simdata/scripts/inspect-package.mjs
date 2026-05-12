// Inspect the SimData resources in the build output package.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { Package } from "@s4tk/models";
import { SimDataResource } from "@s4tk/models";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PACKAGE_PATH = join(__dirname, "..", "..", "..", "Build", "out", "HistorianCareer_Tuning.package");

const pkg = Package.from(readFileSync(PACKAGE_PATH));
console.log(`Package: ${pkg.size} entries`);

const targetClass = process.argv[2] || "Objective";

let count = 0;
for (const entry of pkg.entries) {
  // SimData resources have type 0x545AC67A.
  if (entry.key.type !== 0x545AC67A) continue;
  let sd;
  try {
    sd = entry.resource;
    if (!sd || !sd.schemas) {
      // Try as raw buffer
      sd = SimDataResource.from(entry.value);
    }
  } catch (e) {
    console.log(`  SKIP: ${entry.key.instance.toString(16)} failed to parse: ${e.message}`);
    continue;
  }
  if (!sd?.schemas) continue;
  for (const schema of sd.schemas) {
    if (schema.name !== targetClass && targetClass !== "*") continue;
    count++;
    console.log(`\n-- Resource ${entry.key.instance.toString(16).padStart(16, "0")} schema=${schema.name} (hash=0x${(schema.hash >>> 0).toString(16).padStart(8, "0").toUpperCase()}) --`);
    console.log(`  Columns:`);
    for (const col of schema.columns) {
      console.log(`    ${col.name.padEnd(35)} type=${col.type}`);
    }
    for (const inst of sd.instances) {
      console.log(`  Instance ${inst.name}:`);
      for (const [colName, cell] of Object.entries(inst.row)) {
        let valueStr;
        const v = cell?.value;
        if (v === undefined) {
          if (cell?.children) {
            valueStr = `(vector len=${cell.children.length})`;
          } else if (cell?.row) {
            valueStr = `(object)`;
          } else {
            valueStr = `(${cell?.constructor?.name || "unknown"})`;
          }
        } else if (typeof v === "bigint") {
          valueStr = `${v}n`;
        } else {
          valueStr = String(v);
        }
        console.log(`    ${colName.padEnd(35)} = ${valueStr}`);
      }
    }
    break;
  }
  if (count >= 3) break;
}
console.log(`\nFound ${count} ${targetClass} SimData resources.`);
