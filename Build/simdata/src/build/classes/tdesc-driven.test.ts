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
  it("Objective: 5 EA columns (display_age_list, display_text, satisfaction_points, show_progress, tooltip)", async () => {
    const sd = await buildOne("objective_HC_ReadNonfictionBook.xml");
    // The Objective root schema, plus a nested schema for `display_age_list`
    // (an OptionalTunable wrapping a tuple), totals 2. We pick the Objective.
    const obj = sd.schemas.find((s) => s.name === "Objective");
    expect(obj).toBeDefined();
    const cols = obj!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "display_age_list",
      "display_text",
      "satisfaction_points",
      "show_progress",
      "tooltip",
    ]);
  });

  it("Aspiration: 4 EA columns (aspiration_valid_age_type, descriptive_text, display_name, objectives)", async () => {
    const sd = await buildOne("aspiration_HistorianCalling_T1.xml");
    expect(sd.schemas[0]!.columns.map((c) => c.name).sort()).toEqual([
      "aspiration_valid_age_type",
      "descriptive_text",
      "display_name",
      "objectives",
    ]);
  });

  it("AspirationCareer: 1 EA column (objectives only)", async () => {
    const sd = await buildOne("aspiration_career_Historian_L1.xml");
    expect(sd.schemas[0]!.columns.map((c) => c.name).sort()).toEqual(["objectives"]);
  });

  it("AspirationTrack: 11 EA columns (no provided_traits)", async () => {
    const sd = await buildOne("aspiration_track_HistorianCalling.xml");
    const cols = sd.schemas[0]!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "aspirations",
      "category",
      "description_text",
      "display_text",
      "icon",
      "icon_high_res",
      "is_hidden_unlockable",
      "mood_asm_param",
      "override_traits",
      "primary_trait",
      "reward",
    ]);
  });

  it("Career: 11 EA columns", async () => {
    const sd = await buildOne("career_Adult_Historian.xml");
    const cols = sd.schemas[0]!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "build_buy_info",
      "call_costar_interaction",
      "cancel_audition_interaction",
      "cancel_gig_interaction",
      "career_category",
      "career_panel_type",
      "find_audition_interaction",
      "hire_agent_interaction",
      "reputation_stat",
      "show_ideal_mood",
      "start_track",
    ]);
  });

  it("CareerLevel: 9 EA columns (excluding end_of_day_loot and super_affordances which lack export_modes)", async () => {
    const sd = await buildOne("career_level_Adult_Historian_L1.xml");
    const cols = sd.schemas[0]!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "agents_available",
      "aspiration",
      "ideal_mood",
      "pay_type",
      "performance_stat",
      "pto_per_day",
      "title",
      "title_description",
      "work_schedule",
    ]);
  });

  it("CareerTrack: 10 EA columns (renamed from class TunableCareerTrack)", async () => {
    const sd = await buildOne("career_track_Adult_Historian.xml");
    expect(sd.schemas[0]!.name).toBe("CareerTrack");
    const cols = sd.schemas[0]!.columns.map((c) => c.name).sort();
    expect(cols).toEqual([
      "branches",
      "busy_time_situation_picker_tooltip",
      "career_description",
      "career_levels",
      "career_name",
      "career_name_gender_neutral",
      "icon",
      "icon_high_res",
      "image",
      "show_now_hiring_string",
    ]);
  });

  it("Trait: 17 EA-canonical columns matching the s4tk binary fixture", async () => {
    const sd = await buildOne("trait_HabilitationRenown.xml");
    expect(sd.schemas[0]!.hash >>> 0).toBe(0xde2eaf66);
    const cols = sd.schemas[0]!.columns.map((c) => c.name);
    expect(cols).toEqual([
      "ages",
      "bb_filter_styles",
      "bb_filter_tags",
      "cas_idle_asm_key",
      "cas_idle_asm_state",
      "cas_selected_icon",
      "cas_trait_asm_param",
      "conflicting_traits",
      "display_name",
      "genders",
      "icon",
      "species",
      "tags",
      "trait_description",
      "trait_origin_description",
      "trait_type",
      "ui_category",
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
