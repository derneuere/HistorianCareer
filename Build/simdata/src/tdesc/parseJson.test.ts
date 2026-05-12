// parseTdescJson tests. We parse all 9 committed TDESC fixtures and verify
// that:
//   (a) parsing doesn't throw,
//   (b) the className matches the filename,
//   (c) at least one column is marked as persisted,
//   (d) the resulting object is frozen,
//   (e) parsing is deterministic (parse twice, expect deep-equal).
//
// The snapshot tests serve as the "wide net" regression check — Vitest writes
// the first run as a snapshot, then enforces equality. To regenerate after
// fetching new TDESCs: `npx vitest --update`.

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { parseTdescJson } from "./parseJson.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const TDESC_DIR = join(__dirname, "..", "..", "test", "fixtures", "tdescs");

const TDESC_FIXTURES: ReadonlyArray<{ readonly file: string; readonly className: string; readonly module: string }> = [
  { file: "Aspiration.tdesc.json",       className: "Aspiration",       module: "aspirations.aspiration_tuning" },
  { file: "AspirationCareer.tdesc.json", className: "AspirationCareer", module: "aspirations.aspiration_tuning" },
  { file: "AspirationTrack.tdesc.json",  className: "AspirationTrack",  module: "aspirations.aspiration_tuning" },
  { file: "Buff.tdesc.json",             className: "Buff",             module: "buffs.buff" },
  { file: "Career.tdesc.json",           className: "Career",           module: "careers.career_tuning" },
  { file: "CareerLevel.tdesc.json",      className: "CareerLevel",      module: "careers.career_tuning" },
  // Note: CareerTrack.tdesc.json's `class` attribute is "TunableCareerTrack"
  // (the EA class-naming convention), not "CareerTrack". We accept whatever
  // the TDESC declares; the build registry maps tuning XML's `c="CareerTrack"`
  // to whatever schema we configure for it.
  { file: "CareerTrack.tdesc.json",      className: "TunableCareerTrack", module: "careers.career_tuning" },
  { file: "Objective.tdesc.json",        className: "Objective",        module: "event_testing.objective_tuning" },
  { file: "Trait.tdesc.json",            className: "Trait",            module: "traits.traits" },
];

describe("parseTdescJson — parses all 9 EA TDESC fixtures", () => {
  for (const { file, className, module } of TDESC_FIXTURES) {
    it(`parses ${file}`, () => {
      const json = readFileSync(join(TDESC_DIR, file), "utf8");
      const schema = parseTdescJson(json);
      expect(schema.className).toBe(className);
      expect(schema.classPath).toBe(`${module}.${className}`);
      expect(schema.rootColumns.length).toBeGreaterThan(0);
      // At least one column should be persisted.
      const persisted = schema.rootColumns.filter((c) => c.persistedToSimData);
      expect(persisted.length).toBeGreaterThan(0);
      // The result must be deeply frozen.
      expect(Object.isFrozen(schema)).toBe(true);
      expect(Object.isFrozen(schema.rootColumns)).toBe(true);
      if (schema.rootColumns.length > 0) {
        expect(Object.isFrozen(schema.rootColumns[0])).toBe(true);
      }
    });
  }

  it("parsing is deterministic", () => {
    const json = readFileSync(join(TDESC_DIR, "Aspiration.tdesc.json"), "utf8");
    const a = parseTdescJson(json);
    const b = parseTdescJson(json);
    // Same shape; we can't compare by reference (each parse builds a new
    // object), but JSON-stringify equivalence is a fine deterministic check.
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it("Buff TDESC persists columns matching the full export_modes rule", () => {
    const json = readFileSync(join(TDESC_DIR, "Buff.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const persistedNames = new Set(
      schema.rootColumns.filter((c) => c.persistedToSimData).map((c) => c.name),
    );
    // The v0.3 persistence rule requires the full export_modes triple
    // (client_binary, server_binary, server_xml). These columns have it:
    const expectedFullTriple = [
      "audio_sting_on_add",
      "audio_sting_on_remove",
      "buff_description",
      "buff_name",
      "icon",
      "mood_type",
      "mood_weight",
      "plumbob_vfx",
      "ui_sort_order",
    ];
    for (const name of expectedFullTriple) {
      expect(persistedNames.has(name)).toBe(true);
    }
    // These have ONLY `client_binary` — excluded by the v0.3 rule:
    expect(persistedNames.has("timeout_string")).toBe(false);
    expect(persistedNames.has("timeout_string_no_next_buff")).toBe(false);
    // `cas_vfx` is "client_binary,server_binary,server_xml" → included; we
    // don't assert here because it's a new addition that may shift across
    // game versions.
  });

  it("Trait TDESC persists columns matching the full export_modes rule", () => {
    const json = readFileSync(join(TDESC_DIR, "Trait.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const persistedNames = new Set(
      schema.rootColumns.filter((c) => c.persistedToSimData).map((c) => c.name),
    );
    // The v0.3 rule (full export_modes triple) captures these columns. The
    // EA golden also has `ages` and `genders` which are TunableSet without
    // explicit export_modes — those are added back via per-class allow-list.
    const expectedInTdesc = [
      "cas_idle_asm_key", "cas_idle_asm_state",
      "cas_trait_asm_param", "conflicting_traits",
      "display_name", "icon", "tags", "trait_description",
      "trait_origin_description", "trait_type",
    ];
    for (const name of expectedInTdesc) {
      expect(persistedNames.has(name)).toBe(true);
    }
  });

  it("AspirationTrack has the right persisted set including aspirations + category", () => {
    const json = readFileSync(join(TDESC_DIR, "AspirationTrack.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const persistedNames = new Set(
      schema.rootColumns.filter((c) => c.persistedToSimData).map((c) => c.name),
    );
    expect(persistedNames.has("aspirations")).toBe(true);
    expect(persistedNames.has("category")).toBe(true);
    expect(persistedNames.has("display_text")).toBe(true);
    expect(persistedNames.has("description_text")).toBe(true);
    expect(persistedNames.has("reward")).toBe(true);
  });

  it("Career has the start_track, career_category, career_panel_type columns", () => {
    const json = readFileSync(join(TDESC_DIR, "Career.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const persistedNames = new Set(
      schema.rootColumns.filter((c) => c.persistedToSimData).map((c) => c.name),
    );
    expect(persistedNames.has("start_track")).toBe(true);
    expect(persistedNames.has("career_category")).toBe(true);
    expect(persistedNames.has("career_panel_type")).toBe(true);
  });

  it("CareerLevel has pay_type, work_schedule, title", () => {
    const json = readFileSync(join(TDESC_DIR, "CareerLevel.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const persistedNames = new Set(
      schema.rootColumns.filter((c) => c.persistedToSimData).map((c) => c.name),
    );
    expect(persistedNames.has("title")).toBe(true);
    expect(persistedNames.has("title_description")).toBe(true);
    expect(persistedNames.has("pay_type")).toBe(true);
    expect(persistedNames.has("work_schedule")).toBe(true);
    expect(persistedNames.has("aspiration")).toBe(true);
  });

  it("AspirationCareer only persists `objectives` from the TDESC", () => {
    const json = readFileSync(join(TDESC_DIR, "AspirationCareer.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const persistedNames = schema.rootColumns
      .filter((c) => c.persistedToSimData)
      .map((c) => c.name)
      .sort();
    expect(persistedNames).toEqual(["objectives"]);
  });
});

describe("parseTdescJson — v0.3 persistence rule (full export_modes triple)", () => {
  // Synthesize a minimal TDESC inline so the test doesn't depend on the
  // fixture having any particular column. We parse the JSON directly.
  function persistedFor(exportModes: string | undefined): boolean {
    const doc = {
      TuningRoot: [
        {
          ":@": { class: "X", module: "x.y" },
          Instance: [
            {
              ":@": {
                name: "test_col",
                class: "Tunable",
                type: "int",
                ...(exportModes !== undefined ? { export_modes: exportModes } : {}),
              },
              Tunable: [],
            },
          ],
        },
      ],
    };
    const schema = parseTdescJson(JSON.stringify(doc));
    return schema.rootColumns[0]!.persistedToSimData;
  }

  it("persists when export_modes is the full triple (any order)", () => {
    expect(persistedFor("client_binary,server_binary,server_xml")).toBe(true);
    expect(persistedFor("server_xml,server_binary,client_binary")).toBe(true);
  });

  it("excludes when only `client_binary` is set", () => {
    expect(persistedFor("client_binary")).toBe(false);
  });

  it("excludes when export_modes is missing entirely", () => {
    expect(persistedFor(undefined)).toBe(false);
  });

  it("excludes any single/pair subset", () => {
    expect(persistedFor("client_binary,server_binary")).toBe(false);
    expect(persistedFor("server_binary,server_xml")).toBe(false);
    expect(persistedFor("server_xml")).toBe(false);
  });
});

describe("parseTdescJson — type inference correctness", () => {
  it("TunableLocalizedString → string-key", () => {
    const json = readFileSync(join(TDESC_DIR, "Aspiration.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const displayName = schema.rootColumns.find((c) => c.name === "display_name");
    expect(displayName?.type.kind).toBe("string-key");
  });

  it("TunableReference → table-set-reference", () => {
    const json = readFileSync(join(TDESC_DIR, "Career.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const startTrack = schema.rootColumns.find((c) => c.name === "start_track");
    expect(startTrack?.type.kind).toBe("table-set-reference");
  });

  it("TunableList → vector with inner element type", () => {
    const json = readFileSync(join(TDESC_DIR, "Aspiration.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const objectives = schema.rootColumns.find((c) => c.name === "objectives");
    expect(objectives?.type.kind).toBe("vector");
    if (objectives?.type.kind === "vector") {
      // objectives is a list of TunableReference → table-set-reference
      expect(objectives.type.elem.kind).toBe("table-set-reference");
    }
  });

  it("TunableResourceKey → resource-key", () => {
    const json = readFileSync(join(TDESC_DIR, "AspirationTrack.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const icon = schema.rootColumns.find((c) => c.name === "icon");
    expect(icon?.type.kind).toBe("resource-key");
  });

  it("TunableEnumEntry → enum", () => {
    const json = readFileSync(join(TDESC_DIR, "Career.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const careerCategory = schema.rootColumns.find((c) => c.name === "career_category");
    expect(careerCategory?.type.kind).toBe("enum");
    if (careerCategory?.type.kind === "enum") {
      expect(careerCategory.type.enumName).toBe("CareerCategory");
    }
  });

  it("Tunable bool → bool", () => {
    const json = readFileSync(join(TDESC_DIR, "Career.tdesc.json"), "utf8");
    const schema = parseTdescJson(json);
    const showIdealMood = schema.rootColumns.find((c) => c.name === "show_ideal_mood");
    expect(showIdealMood?.type.kind).toBe("bool");
  });
});
