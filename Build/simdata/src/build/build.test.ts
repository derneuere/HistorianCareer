// Pipeline smoke tests: hand a TdescSchema + TuningTree to buildSimData and
// verify the resulting SimData buffer round-trips through @s4tk/models.

import { describe, expect, it } from "vitest";
import { fnv64, fnv32 } from "@s4tk/hashing/hashing.js";
import { parseTuning } from "../tuning/parse.js";
import { parseTdesc } from "../tdesc/parse.js";
import { buildSimData, createBuildContext } from "./build.js";
import { emitSimDataBuffer, parseSimDataBuffer } from "../emit/emit.js";

describe("buildSimData (generic pipeline)", () => {
  it("builds a Trait SimData that round-trips through @s4tk/models", () => {
    const tdescXml = `<TDescDoc>
      <Class name="Trait" path="traits.traits.Trait">
        <Tunable name="display_name" type="TunableLocalizedString" />
        <Tunable name="trait_description" type="TunableLocalizedString" />
        <Tunable name="is_personality_trait" type="Tunable" class="bool" default="False" />
        <Tunable name="trait_type" type="TunableEnumEntry" class="TraitType">
          <EnumValue name="GAMEPLAY" />
          <EnumValue name="HIDDEN" />
        </Tunable>
      </Class>
    </TDescDoc>`;

    const tuningXml = `<I c="Trait" i="trait" m="traits.traits" n="trait_HabilitationRenown" s="TBD_INSTANCE_ID">
      <T n="display_name">0xDEADBEEF</T>
      <T n="trait_description">0xCAFEBABE</T>
      <T n="is_personality_trait">False</T>
      <T n="trait_type">GAMEPLAY</T>
    </I>`;

    const schema = parseTdesc(tdescXml);
    const tree = parseTuning(tuningXml);
    const ctx = createBuildContext({
      resolveStblKey: (token) => fnv32(token),
      resolveTuningRef: (name) => fnv64(name, true),
    });

    const ir = buildSimData(schema, tree, ctx);
    expect(ir.schemas).toHaveLength(1);
    expect(ir.instances).toHaveLength(1);
    expect(ir.instances[0]!.name).toBe("trait_HabilitationRenown");
    expect(ir.schemas[0]!.name).toBe("Trait");

    // Emit binary and parse back.
    const buffer = emitSimDataBuffer(ir);
    expect(buffer).toBeInstanceOf(Buffer);
    expect(buffer.byteLength).toBeGreaterThan(0);

    const round = parseSimDataBuffer(buffer);
    expect(round.schemas).toHaveLength(1);
    expect(round.schemas[0]!.name).toBe("Trait");
    expect(round.instances).toHaveLength(1);
    expect(round.instances[0]!.name).toBe("trait_HabilitationRenown");

    // Verify each scalar column survived the round trip.
    const row = round.instances[0]!.row;
    // Boolean: innerValue is the JS boolean primitive after S4S parse.
    expect(row.is_personality_trait!.toXmlNode().innerValue).toBe(0);
    // The display_name and trait_description are LocalizationKey (NumberCell).
    expect(row.display_name).toBeDefined();
    expect(row.trait_description).toBeDefined();
  });

  it("resolves 0xTBD_STBL_KEY_FOO via the resolver", () => {
    const tdescXml = `<TDescDoc><Class name="X">
      <Tunable name="display_name" type="TunableLocalizedString" />
    </Class></TDescDoc>`;
    const tuningXml = `<I c="X" i="x" m="x" n="x_test" s="TBD_INSTANCE_ID">
      <T n="display_name">0xTBD_STBL_KEY_FOO</T>
    </I>`;
    const schema = parseTdesc(tdescXml);
    const tree = parseTuning(tuningXml);

    const ctx = createBuildContext({
      resolveStblKey: (token) => (token === "FOO" ? 0xAABBCCDD : 0),
      resolveTuningRef: () => 0n,
    });
    const ir = buildSimData(schema, tree, ctx);
    const buf = emitSimDataBuffer(ir);
    const back = parseSimDataBuffer(buf);
    const dn = back.instances[0]!.row.display_name;
    // NumberCell exposes the value as a number via toXmlNode innerValue.
    // The S4S XML encodes LocalizationKey as "0xAABBCCDD".
    const xml = dn!.toXmlNode().toXml();
    expect(xml.toLowerCase()).toContain("0xaabbccdd");
  });

  it("handles vectors of references", () => {
    const tdescXml = `<TDescDoc><Class name="Y">
      <Tunable name="things" type="TunableList">
        <Tunable type="TunableReference" />
      </Tunable>
    </Class></TDescDoc>`;
    const tuningXml = `<I c="Y" i="y" m="y" n="y_test" s="TBD_INSTANCE_ID">
      <L n="things">
        <T>some_tuning_name</T>
        <T>12345</T>
      </L>
    </I>`;
    const schema = parseTdesc(tdescXml);
    const tree = parseTuning(tuningXml);
    const ctx = createBuildContext({
      resolveStblKey: () => 0,
      resolveTuningRef: (name) =>
        name === "some_tuning_name" ? 0xCAFEBABEDEADBEEFn : 0n,
    });
    const ir = buildSimData(schema, tree, ctx);
    const buf = emitSimDataBuffer(ir);
    const back = parseSimDataBuffer(buf);
    const things = back.instances[0]!.row.things;
    expect(things).toBeDefined();
    // Inspect the parsed cell directly — S4S formats TableSetReference as
    // decimal strings in XML, but we have the bigint values in memory.
    // Cast to a VectorCell-like shape and read the children.
    type ChildLike = { value?: unknown };
    const childrenAccessor = things as unknown as { children?: ChildLike[] };
    const childCells = childrenAccessor.children ?? [];
    expect(childCells).toHaveLength(2);
    expect(childCells[0]!.value).toBe(0xcafebabedeadbeefn);
    expect(childCells[1]!.value).toBe(12345n);
  });
});
