// Tests for the enum value mappings used by the cell builder.
//
// The cell builder must convert string enum literals like "LEVEL_1" or
// "TEEN" into bigint values matching what EA's SimData binary expects.

import { describe, expect, it } from "vitest";
import {
  AGE,
  ASPIRATION_TRACK_LEVELS,
  CAREER_CATEGORY,
  TRAIT_TYPE,
  decodeEnumLiteral,
  lookupEnumValue,
  ENUM_REGISTRY,
} from "./enums.js";

describe("enum value tables", () => {
  it("Age enum: TEEN=8, ADULT=32, ELDER=64 (bit flags)", () => {
    expect(AGE.TEEN).toBe(8n);
    expect(AGE.ADULT).toBe(32n);
    expect(AGE.ELDER).toBe(64n);
    expect(AGE.BABY).toBe(1n);
    expect(AGE.UNUSED_FLAG).toBe(2n);
    expect(AGE.CHILD).toBe(4n);
    expect(AGE.YOUNGADULT).toBe(16n);
  });

  it("TraitType: PERSONALITY=0, GAMEPLAY=1, HIDDEN=4", () => {
    expect(TRAIT_TYPE.PERSONALITY).toBe(0n);
    expect(TRAIT_TYPE.GAMEPLAY).toBe(1n);
    expect(TRAIT_TYPE.HIDDEN).toBe(4n);
  });

  it("AspirationTrackLevels: LEVEL_1=1, LEVEL_2=2, …", () => {
    expect(ASPIRATION_TRACK_LEVELS.LEVEL_1).toBe(1n);
    expect(ASPIRATION_TRACK_LEVELS.LEVEL_2).toBe(2n);
    expect(ASPIRATION_TRACK_LEVELS.LEVEL_3).toBe(3n);
  });

  it("CareerCategory: TeenPartTime=3", () => {
    expect(CAREER_CATEGORY.TeenPartTime).toBe(3n);
  });
});

describe("lookupEnumValue", () => {
  it("returns the value for a known enum/literal pair", () => {
    expect(lookupEnumValue("Age", "TEEN")).toBe(8n);
    expect(lookupEnumValue("AspirationTrackLevels", "LEVEL_3")).toBe(3n);
  });

  it("returns undefined for unknown enum names", () => {
    expect(lookupEnumValue("NonexistentEnum", "X")).toBeUndefined();
  });

  it("returns undefined for unknown literals", () => {
    expect(lookupEnumValue("Age", "UNKNOWN_AGE")).toBeUndefined();
  });
});

describe("decodeEnumLiteral", () => {
  it("decodes named-enum literals", () => {
    expect(decodeEnumLiteral("Age", "TEEN")).toBe(8n);
    expect(decodeEnumLiteral("TraitType", "HIDDEN")).toBe(4n);
  });

  it("decodes numeric literals directly", () => {
    expect(decodeEnumLiteral(undefined, "5")).toBe(5n);
    expect(decodeEnumLiteral("Age", "5")).toBe(5n); // numeric wins
    expect(decodeEnumLiteral(undefined, "0x10")).toBe(16n);
  });

  it("returns 0n for empty / None literals", () => {
    expect(decodeEnumLiteral("Age", "")).toBe(0n);
    expect(decodeEnumLiteral("Age", "None")).toBe(0n);
  });

  it("falls back to a global probe when enumName is missing or unknown", () => {
    // No enumName supplied — should still find TEEN in the global probe.
    expect(decodeEnumLiteral(undefined, "TEEN")).toBe(8n);
    // Unknown enumName but known literal in another enum.
    expect(decodeEnumLiteral("NonexistentEnum", "LEVEL_1")).toBe(1n);
  });

  it("returns 0n for unknown literals without crashing", () => {
    expect(decodeEnumLiteral("Age", "DEFINITELY_NOT_AN_AGE")).toBe(0n);
    expect(decodeEnumLiteral(undefined, "DEFINITELY_NOT_AN_ENUM_VALUE")).toBe(0n);
  });
});

describe("ENUM_REGISTRY", () => {
  it("has Sims4_AgesEnum as an alias for Age", () => {
    expect(ENUM_REGISTRY.Sims4_AgesEnum).toBe(ENUM_REGISTRY.Age);
  });

  it("contains the expected enum families", () => {
    expect(ENUM_REGISTRY).toHaveProperty("Age");
    expect(ENUM_REGISTRY).toHaveProperty("TraitType");
    expect(ENUM_REGISTRY).toHaveProperty("AspirationTrackLevels");
    expect(ENUM_REGISTRY).toHaveProperty("CareerCategory");
    expect(ENUM_REGISTRY).toHaveProperty("AspirationValidAgeType");
    expect(ENUM_REGISTRY).toHaveProperty("ObjectiveCategoryType");
  });
});
