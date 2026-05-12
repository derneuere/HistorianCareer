import { describe, expect, it } from "vitest";
import { parseTuning, findChildByName } from "./parse.js";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const HC_TUNING_DIR = path.resolve(__dirname, "../../../../Tuning");

describe("parseTuning", () => {
  it("parses the Trait tuning", () => {
    const xml = `<?xml version="1.0" encoding="utf-8"?>
<I c="Trait" i="trait" m="traits.traits" n="trait_HabilitationRenown" s="TBD_INSTANCE_ID">
  <T n="display_name">0xDEADBEEF</T>
  <T n="trait_description">0xCAFEBABE</T>
  <T n="is_personality_trait">False</T>
  <T n="trait_type">GAMEPLAY</T>
  <L n="loot_on_trait_add">
    <T>loot.buff_Focused_Low</T>
  </L>
</I>`;
    const tree = parseTuning(xml);
    expect(tree.rootClass).toBe("Trait");
    expect(tree.rootKind).toBe("trait");
    expect(tree.instanceName).toBe("trait_HabilitationRenown");
    expect(tree.instanceId).toBe(0n);
    expect(tree.modulePath).toBe("traits.traits");
    expect(tree.children).toHaveLength(5);

    const displayName = findChildByName(tree, "display_name");
    expect(displayName?.kind).toBe("T");
    if (displayName?.kind === "T") {
      expect(displayName.value).toBe("0xDEADBEEF");
      expect(displayName.name).toBe("display_name");
    }

    const loot = findChildByName(tree, "loot_on_trait_add");
    expect(loot?.kind).toBe("L");
    if (loot?.kind === "L") {
      expect(loot.children).toHaveLength(1);
      const lootItem = loot.children[0]!;
      expect(lootItem.kind).toBe("T");
      if (lootItem.kind === "T") {
        expect(lootItem.value).toBe("loot.buff_Focused_Low");
        expect(lootItem.name).toBeUndefined();
      }
    }
  });

  it("parses a tuning with variants", () => {
    const xml = `<I c="Career" i="career" m="careers.career" n="x" s="TBD_INSTANCE_ID">
  <V n="career_availability_test" t="enabled">
    <U n="enabled">
      <L n="tests">
        <V t="trait">
          <U n="trait">
            <T n="subject">Actor</T>
          </U>
        </V>
      </L>
    </U>
  </V>
</I>`;
    const tree = parseTuning(xml);
    const test = findChildByName(tree, "career_availability_test");
    expect(test?.kind).toBe("V");
    if (test?.kind === "V") {
      expect(test.variantTag).toBe("enabled");
      expect(test.child?.kind).toBe("U");
    }
  });

  it("parses a real instance ID", () => {
    const xml = `<I c="Trait" i="trait" m="x" n="y" s="12345">
  <T n="foo">1</T>
</I>`;
    const tree = parseTuning(xml);
    expect(tree.instanceId).toBe(12345n);
  });

  it("throws on a non-<I> root", () => {
    expect(() => parseTuning(`<Foo/>`)).toThrow(/expected root/);
  });

  it("round-trips every HistorianCareer tuning XML without throwing", async () => {
    const files = (await fs.readdir(HC_TUNING_DIR)).filter(
      (f) => f.endsWith(".xml") && !f.startsWith("_"),
    );
    expect(files.length).toBeGreaterThan(10);
    let parsed = 0;
    for (const f of files) {
      const xml = await fs.readFile(path.join(HC_TUNING_DIR, f), "utf8");
      const tree = parseTuning(xml);
      expect(tree.rootClass).toBeTruthy();
      expect(tree.instanceName).toBeTruthy();
      parsed++;
    }
    expect(parsed).toBe(files.length);
  });
});
