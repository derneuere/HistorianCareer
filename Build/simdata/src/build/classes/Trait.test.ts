import { describe, expect, it } from "vitest";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fnv32, fnv64 } from "@s4tk/hashing/hashing.js";
import { buildTraitSimData, TRAIT_TDESC_SCHEMA } from "./Trait.js";
import { createBuildContext } from "../build.js";
import { emitSimDataBuffer, parseSimDataBuffer } from "../../emit/emit.js";
import { parseTuning } from "../../tuning/parse.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TRAIT_TUNING_PATH = path.resolve(
  __dirname,
  "../../../../../Tuning/trait_HabilitationRenown.xml",
);
// EA golden Trait simdata, extracted from the live 1.124.55 game build
// (this is what `parseTuning` should reproduce byte-equal).
const EA_TRAIT_GOLDEN = path.resolve(
  __dirname,
  "../../../test/golden/Trait/Trait_Hidden_JoinedFiftyMileHighClub_Teen.simdata",
);

describe("Trait class builder", () => {
  it("emits a SimData with the 13 EA-canonical columns (current game version)", async () => {
    const xml = await fs.readFile(TRAIT_TUNING_PATH, "utf8");
    const tree = parseTuning(xml);
    const ctx = createBuildContext({
      resolveStblKey: (token) => fnv32(token),
      resolveTuningRef: (name) => fnv64(name, true),
    });
    const ir = buildTraitSimData(tree, ctx);
    expect(ir.schemas).toHaveLength(1);
    const schema = ir.schemas[0]!;
    expect(schema.name).toBe("Trait");
    // Current game schema hash (1.124.55). The older 17-column s4tk fixture
    // had hash 0xde2eaf66.
    expect(schema.hash >>> 0).toBe(0x992bfa76);
    expect(schema.columns.map((c) => c.name)).toEqual(
      [
        "ages",
        "cas_idle_asm_key",
        "cas_idle_asm_state",
        "cas_selected_icon",
        "cas_trait_asm_param",
        "conflicting_traits",
        "display_name",
        "genders",
        "icon",
        "tags",
        "trait_description",
        "trait_origin_description",
        "trait_type",
      ],
    );

    const buf = emitSimDataBuffer(ir);
    expect(buf.byteLength).toBeGreaterThan(0);

    // Round-trip through @s4tk/models — the structural test.
    const round = parseSimDataBuffer(buf);
    expect(round.schemas[0]!.name).toBe("Trait");
    expect((round.schemas[0]!.hash >>> 0)).toBe(0x992bfa76);
    expect(round.instances).toHaveLength(1);
    expect(round.instances[0]!.name).toBe("trait_HabilitationRenown");

    // Spot-check key columns survived the round trip.
    const row = round.instances[0]!.row;
    expect((row.display_name as { value: number }).value).toBe(fnv32("HC_TRAIT_RENOWN_NAME"));
    expect((row.trait_description as { value: number }).value).toBe(
      fnv32("HC_TRAIT_RENOWN_DESC"),
    );
    expect((row.trait_type as { value: bigint }).value).toBe(1n); // GAMEPLAY
    expect((row.icon as { type: number; group: number; instance: bigint }).type).toBe(0);
  });

  it("matches the EA Trait golden's schema name and hash (acceptance: structural match)", async () => {
    // Read the EA golden — the binary the live game produces for the
    // Trait_Hidden_JoinedFiftyMileHighClub_Teen trait. Our schema name and
    // column set must match.
    const buf = await fs.readFile(EA_TRAIT_GOLDEN);
    const ea = parseSimDataBuffer(buf);
    expect(ea.schemas).toHaveLength(1);
    const eaSchema = ea.schemas[0]!;
    expect(eaSchema.name).toBe("Trait");
    expect(eaSchema.hash >>> 0).toBe(0x992bfa76);

    // Confirm our TDESC-driven schema has the same column names.
    const ours = new Set(TRAIT_TDESC_SCHEMA.rootColumns.map((c) => c.name));
    for (const eaCol of eaSchema.columns) {
      expect(ours.has(eaCol.name)).toBe(true);
    }
    expect(eaSchema.columns.length).toBe(ours.size);
  });
});
