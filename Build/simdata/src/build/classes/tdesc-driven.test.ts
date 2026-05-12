// Integration test: verify each v0.2 class produces the TDESC-correct
// SimData when fed a HistorianCareer tuning XML. Per-class assertions on the
// expected column set make regressions obvious if the TDESC fixtures change
// or the build pipeline drifts.

import { describe, expect, it } from "vitest";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fnv32, fnv64 } from "@s4tk/hashing/hashing.js";
import { parseTuning } from "../../tuning/parse.js";
import { createBuildContext } from "../build.js";
import { emitSimDataBuffer, parseSimDataBuffer } from "../../emit/emit.js";
import { buildSimDataForTuning, KNOWN_SCHEMA_HASHES } from "./index.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const HC_TUNING_DIR = path.resolve(__dirname, "../../../../../Tuning");

function makeCtx() {
  return createBuildContext({
    resolveStblKey: (token) => fnv32(token),
    resolveTuningRef: (name) => fnv64(name, true),
    knownSchemaHashes: KNOWN_SCHEMA_HASHES,
  });
}

async function buildOne(filename: string): Promise<ReturnType<typeof parseSimDataBuffer>> {
  const xml = await fs.readFile(path.join(HC_TUNING_DIR, filename), "utf8");
  const tree = parseTuning(xml);
  const ctx = makeCtx();
  const ir = buildSimDataForTuning(tree, ctx);
  const buf = emitSimDataBuffer(ir);
  return parseSimDataBuffer(buf);
}

describe("TDESC-driven schemas — expected column sets per class", () => {
  // v0.3: column sets are now anchored to real EA SimData goldens
  // (test/golden/) instead of the older s4tk-models fixture and TDESC raw
  // dump. The per-class schemas in src/build/classes/schemas.ts intersect the
  // TDESC's persisted-column set with what the real EA goldens contain.
  it("Objective: 3 EA-golden columns (display_text, satisfaction_points, tooltip)", async () => {
    const sd = await buildOne("objective_HC_ReadNonfictionBook.xml");
    const obj = sd.schemas.find((s) => s.name === "Objective");
    expect(obj).toBeDefined();
    const cols = obj!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "display_text",
      "satisfaction_points",
      "tooltip",
    ]);
  });

  it("Aspiration: 5 EA-golden columns (descriptive_text, disabled, display_name, is_child_aspiration, objectives)", async () => {
    const sd = await buildOne("aspiration_HistorianCalling_T1.xml");
    expect(sd.schemas[0]!.columns.map((c) => c.name).sort()).toEqual([
      "descriptive_text",
      "disabled",
      "display_name",
      "is_child_aspiration",
      "objectives",
    ]);
  });

  it("AspirationCareer: 2 EA-golden columns (disabled, objectives)", async () => {
    const sd = await buildOne("aspiration_career_Historian_L1.xml");
    expect(sd.schemas[0]!.columns.map((c) => c.name).sort()).toEqual([
      "disabled",
      "objectives",
    ]);
  });

  it("AspirationTrack: 9 EA-golden columns", async () => {
    const sd = await buildOne("aspiration_track_HistorianCalling.xml");
    const cols = sd.schemas[0]!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "aspirations",
      "category",
      "description_text",
      "display_text",
      "icon",
      "icon_high_res",
      "mood_asm_param",
      "primary_trait",
      "reward",
    ]);
  });

  it("Career: 2 EA-golden columns (career_category, start_track)", async () => {
    const sd = await buildOne("career_Adult_Historian.xml");
    const cols = sd.schemas[0]!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "career_category",
      "start_track",
    ]);
  });

  it("CareerLevel: 7 EA-golden columns", async () => {
    const sd = await buildOne("career_level_Adult_Historian_L1.xml");
    const cols = sd.schemas[0]!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "aspiration",
      "ideal_mood",
      "performance_stat",
      "simoleons_per_hour",
      "title",
      "title_description",
      "work_schedule",
    ]);
  });

  it("CareerTrack: 8 EA-golden columns (schema name 'TunableCareerTrack')", async () => {
    const sd = await buildOne("career_track_Adult_Historian.xml");
    // EA's SimData binary uses the TDESC's `class` attribute as the schema
    // name — "TunableCareerTrack", not the tuning XML's `c="CareerTrack"`.
    expect(sd.schemas[0]!.name).toBe("TunableCareerTrack");
    const cols = sd.schemas[0]!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "branches",
      "busy_time_situation_picker_tooltip",
      "career_description",
      "career_levels",
      "career_name",
      "icon",
      "icon_high_res",
      "image",
    ]);
  });

  it("Trait: 13 EA-canonical columns (current game version)", async () => {
    const sd = await buildOne("trait_HabilitationRenown.xml");
    // EA schema hash for current Trait (1.124.55)
    expect(sd.schemas[0]!.hash >>> 0).toBe(0x992bfa76);
    const cols = sd.schemas[0]!.columns.map((c) => c.name);
    expect(cols).toEqual([
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
    ]);
  });

  it("CareerChanceCard: 4 columns including the v0.2-added option fields", async () => {
    const sd = await buildOne("career_chance_card_Historian_Plagiarism.xml");
    const cols = sd.schemas
      .find((s) => s.name === "CareerChanceCard")!
      .columns.map((c) => c.name)
      .sort();
    expect(cols).toEqual([
      "description",
      "response_option_a",
      "response_option_b",
      "title",
    ]);
  });

  it("CareerChanceCard option subobject persists display_text and outcome_loot", async () => {
    const sd = await buildOne("career_chance_card_Historian_Plagiarism.xml");
    const inst = sd.instances[0]!;
    const opt = inst.row["response_option_a"] as unknown as { row: Record<string, { value?: unknown; children?: unknown[] }> };
    expect(opt.row).toBeDefined();
    expect(opt.row.display_text).toBeDefined();
    expect(opt.row.outcome_loot).toBeDefined();
    // display_text should be a non-zero STBL key
    expect((opt.row.display_text as { value: number }).value).toBeGreaterThan(0);
    // outcome_loot should be a vector with 2 children (two loot refs)
    expect((opt.row.outcome_loot as { children: unknown[] }).children).toHaveLength(2);
  });
});

describe("TDESC-driven schemas — STBL key resolution for HistorianCareer", () => {
  it("Aspiration's display_name is the FNV-32 of HC_ASP_T1_NAME", async () => {
    const sd = await buildOne("aspiration_HistorianCalling_T1.xml");
    const dn = sd.instances[0]!.row["display_name"] as { value: number };
    expect(dn.value).toBe(fnv32("HC_ASP_T1_NAME"));
  });

  it("Career's start_track is the FNV-64 of career_track_Adult_Historian", async () => {
    const sd = await buildOne("career_Adult_Historian.xml");
    const st = sd.instances[0]!.row["start_track"] as { value: bigint };
    expect(st.value).toBe(fnv64("career_track_Adult_Historian", true));
  });
});
