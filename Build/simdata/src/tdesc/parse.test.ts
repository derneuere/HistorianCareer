import { describe, expect, it } from "vitest";
import { parseTdesc } from "./parse.js";

describe("parseTdesc", () => {
  it("parses a minimal Trait-like TDESC", () => {
    const xml = `
<?xml version="1.0" encoding="utf-8"?>
<TDescDoc>
  <Class name="Trait" path="traits.traits.Trait">
    <Tunable name="display_name" type="TunableLocalizedString" />
    <Tunable name="trait_description" type="TunableLocalizedString" />
    <Tunable name="icon" type="TunableResourceKey" />
    <Tunable name="is_personality_trait" type="Tunable" class="bool" default="False" />
    <Tunable name="trait_type" type="TunableEnumEntry" class="TraitType">
      <EnumValue name="GAMEPLAY" />
      <EnumValue name="HIDDEN" />
    </Tunable>
    <Tunable name="conflicting_traits" type="TunableList">
      <Tunable type="TunableReference" />
    </Tunable>
  </Class>
</TDescDoc>`;

    const schema = parseTdesc(xml);
    expect(schema.className).toBe("Trait");
    expect(schema.classPath).toBe("traits.traits.Trait");
    expect(schema.rootColumns).toHaveLength(6);

    const names = schema.rootColumns.map((c) => c.name);
    expect(names).toEqual([
      "display_name",
      "trait_description",
      "icon",
      "is_personality_trait",
      "trait_type",
      "conflicting_traits",
    ]);

    const displayName = schema.rootColumns[0]!;
    expect(displayName.type).toEqual({ kind: "string-key" });
    expect(displayName.persistedToSimData).toBe(true);

    const icon = schema.rootColumns[2]!;
    expect(icon.type).toEqual({ kind: "resource-key" });

    const isPers = schema.rootColumns[3]!;
    expect(isPers.type).toEqual({ kind: "bool" });
    expect(isPers.defaultValue).toBe(false);

    const traitType = schema.rootColumns[4]!;
    expect(traitType.type).toEqual({
      kind: "enum",
      enumName: "TraitType",
      values: ["GAMEPLAY", "HIDDEN"],
    });

    const conflicting = schema.rootColumns[5]!;
    expect(conflicting.type).toEqual({
      kind: "vector",
      elem: { kind: "table-set-reference" },
    });
  });

  it("honors an explicit <TunableExport simdata=\"False\"/>", () => {
    const xml = `<TDescDoc><Class name="X">
      <Tunable name="hidden" type="Tunable" class="bool" default="False">
        <TunableExport simdata="False" />
      </Tunable>
      <Tunable name="visible" type="Tunable" class="bool" default="True">
        <TunableExport simdata="True" />
      </Tunable>
    </Class></TDescDoc>`;
    const schema = parseTdesc(xml);
    expect(schema.rootColumns[0]?.persistedToSimData).toBe(false);
    expect(schema.rootColumns[1]?.persistedToSimData).toBe(true);
  });

  it("parses tuples and variants recursively", () => {
    const xml = `<TDescDoc><Class name="X">
      <Tunable name="schedule" type="TunableTuple" class="WorkSchedule">
        <Tunable name="start_hour" type="Tunable" class="int" default="9" />
        <Tunable name="end_hour" type="Tunable" class="int" default="17" />
      </Tunable>
      <Tunable name="reward" type="TunableVariant" class="RewardVariant">
        <Tunable name="trait" type="TunableReference" />
        <Tunable name="money" type="Tunable" class="int" />
      </Tunable>
    </Class></TDescDoc>`;
    const schema = parseTdesc(xml);
    const schedule = schema.rootColumns[0]!.type;
    if (schedule.kind !== "object") throw new Error("expected object");
    expect(schedule.schemaName).toBe("WorkSchedule");
    expect(schedule.columns).toHaveLength(2);
    expect(schedule.columns[0]!.type).toEqual({ kind: "int32" });

    const reward = schema.rootColumns[1]!.type;
    if (reward.kind !== "variant") throw new Error("expected variant");
    expect(reward.cases).toHaveLength(2);
    expect(reward.cases[0]).toEqual({
      name: "trait",
      type: { kind: "table-set-reference" },
    });
  });

  it("freezes the result", () => {
    const xml = `<TDescDoc><Class name="X"><Tunable name="a" type="Tunable" class="bool"/></Class></TDescDoc>`;
    const schema = parseTdesc(xml);
    expect(Object.isFrozen(schema)).toBe(true);
    expect(Object.isFrozen(schema.rootColumns)).toBe(true);
    expect(() => {
      // @ts-expect-error mutation should be impossible
      schema.rootColumns.push({} as never);
    }).toThrow();
  });

  it("throws on a non-TDescDoc root", () => {
    expect(() => parseTdesc(`<NotATDesc/>`)).toThrow(/expected root/);
  });
});
