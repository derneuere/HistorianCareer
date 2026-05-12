// resolve-names.test.mjs — unit tests for the build-time name resolver.
//
// Plain Node script: no test framework dependency. Each test calls assert.*
// from node:assert/strict; on failure the script exits non-zero. Targets the
// Node 16+ baseline declared by build.ps1.
//
// Run with:
//   node resolve-names.test.mjs
// or via the package.json "test" script.

import assert from "node:assert/strict";
import { fnv64 } from "@s4tk/hashing/hashing.js";
import {
  collectTuningNames,
  resolveNamesInXml,
} from "./resolve-names.mjs";

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  ok   ${name}`);
    passed++;
  } catch (err) {
    console.error(`  FAIL ${name}`);
    console.error(`       ${err.message}`);
    if (err.stack) console.error(err.stack.split("\n").slice(1, 4).join("\n"));
    failed++;
  }
}

// ----------------------------------------------------------------------------
// collectTuningNames
// ----------------------------------------------------------------------------

test("collectTuningNames: s='TBD_INSTANCE_ID' resolves to fnv64(name, true)", () => {
  const xmls = [
    [
      "HC_Loot_Add_HistorianLevel_Small.xml",
      `<?xml version="1.0" encoding="utf-8"?>
       <I c="LootActions" i="action" m="x" n="HC_Loot_Add_HistorianLevel_Small" s="TBD_INSTANCE_ID">
       </I>`,
    ],
  ];
  const map = collectTuningNames(xmls);
  const expected = fnv64("HC_Loot_Add_HistorianLevel_Small", true);
  assert.equal(map.get("HC_Loot_Add_HistorianLevel_Small"), expected);
});

test("collectTuningNames: numeric s= is used verbatim (source of truth)", () => {
  const xmls = [
    [
      "x.xml",
      `<I c="C" i="i" m="m" n="HC_Statistic_HistorianLevel" s="12345678901234567890">
       </I>`,
    ],
  ];
  const map = collectTuningNames(xmls);
  assert.equal(map.get("HC_Statistic_HistorianLevel"), 12345678901234567890n);
});

test("collectTuningNames: hex s= is parsed as BigInt", () => {
  const xmls = [
    [
      "x.xml",
      `<I c="C" i="i" m="m" n="HC_Foo" s="0xfb1119e76a8f15bf">
       </I>`,
    ],
  ];
  const map = collectTuningNames(xmls);
  assert.equal(map.get("HC_Foo"), 0xfb1119e76a8f15bfn);
});

test("collectTuningNames: missing s= falls back to fnv64", () => {
  const xmls = [
    [
      "x.xml",
      `<I c="C" i="i" m="m" n="HC_Bar">
       </I>`,
    ],
  ];
  const map = collectTuningNames(xmls);
  assert.equal(map.get("HC_Bar"), fnv64("HC_Bar", true));
});

test("collectTuningNames: dropping XML files without <I> tags is silent", () => {
  const xmls = [
    ["junk.xml", "<?xml version='1.0'?>\n<!-- only a comment -->"],
    [
      "good.xml",
      `<I c="C" i="i" m="m" n="HC_Statistic_HistorianLevel" s="TBD_INSTANCE_ID"></I>`,
    ],
  ];
  const map = collectTuningNames(xmls);
  assert.equal(map.size, 1);
  assert.ok(map.has("HC_Statistic_HistorianLevel"));
});

// ----------------------------------------------------------------------------
// resolveNamesInXml — replacement matrix
// ----------------------------------------------------------------------------

const sampleMap = new Map([
  ["HC_Statistic_HistorianLevel", 99999n],
  ["HC_Loot_Add_HistorianLevel_Small", 123456789012345n],
  ["HC_PieMenuCategory_Historian", 555n],
  ["aspiration_HistorianCalling_T1", 777n],
]);

test("resolveNamesInXml: bare <T>NAME</T> is replaced with decimal ID", () => {
  const xml = `<I c="C"><T>HC_Statistic_HistorianLevel</T></I>`;
  const { xml: out } = resolveNamesInXml(xml, sampleMap);
  assert.match(out, /<T>99999<\/T>/);
});

test("resolveNamesInXml: list members inside <L n='...'> are resolved", () => {
  const xml = `
    <L n="loot_list">
      <T>HC_Loot_Add_HistorianLevel_Small</T>
      <T>HC_Loot_Add_HistorianLevel_Small</T>
    </L>`;
  const { xml: out } = resolveNamesInXml(xml, sampleMap);
  const matches = out.match(/<T>123456789012345<\/T>/g) ?? [];
  assert.equal(matches.length, 2);
  // The original name must not still appear in an unwrapped <T>.
  assert.doesNotMatch(out, /<T>HC_Loot_Add_HistorianLevel_Small<\/T>/);
});

test("resolveNamesInXml: <T n='...'>NAME</T> named field ref is resolved", () => {
  const xml = `<T n="pie_menu_category">HC_PieMenuCategory_Historian</T>`;
  const { xml: out } = resolveNamesInXml(xml, sampleMap);
  assert.equal(out, `<T n="pie_menu_category">555</T>`);
});

test("resolveNamesInXml: <E n='...'>NAME</E> (enum-named ref) is resolved", () => {
  const xml = `<E n="some_ref">aspiration_HistorianCalling_T1</E>`;
  const { xml: out } = resolveNamesInXml(xml, sampleMap);
  assert.equal(out, `<E n="some_ref">777</E>`);
});

test("resolveNamesInXml: unknown HC_ name is left untouched AND warns", () => {
  const xml = `<T>HC_DoesNotExist</T>`;
  const { xml: out, warnings } = resolveNamesInXml(xml, sampleMap, {
    file: "test.xml",
  });
  assert.equal(out, xml);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /HC_DoesNotExist/);
  assert.match(warnings[0], /test\.xml/);
});

test("resolveNamesInXml: unknown non-HC name is left untouched WITHOUT warning", () => {
  // EA-shipped names like `book_ReadBook_NonFiction` or
  // `trait_University_Major_History_Completed` should never warn.
  const xml = `<T>book_ReadBook_NonFiction</T>
               <T>schedule_career_part_time_morning</T>`;
  const { xml: out, warnings } = resolveNamesInXml(xml, sampleMap);
  assert.equal(out, xml);
  assert.equal(warnings.length, 0);
});

test("resolveNamesInXml: numeric body is left untouched", () => {
  const xml = `<T n="initial_value">0</T>
               <T n="max_value">5</T>
               <T n="instance">99999</T>
               <T n="hex_lookalike">0xdeadbeef</T>`;
  const { xml: out, warnings } = resolveNamesInXml(xml, sampleMap);
  // The literal "99999" must NOT be reinterpreted as a name even though
  // sampleMap contains 99999n as a value — the resolver maps name → id, not
  // id → id.
  assert.equal(out, xml);
  assert.equal(warnings.length, 0);
});

test("resolveNamesInXml: enum text body (not a name) left untouched", () => {
  // `<E n="career_category">CAREER</E>` — CAREER is an enum value, not a name.
  const xml = `<E n="career_category">CAREER</E>
               <E n="trait_type">GAMEPLAY</E>
               <E n="career_category">KNOWLEDGE</E>`;
  const { xml: out, warnings } = resolveNamesInXml(xml, sampleMap);
  assert.equal(out, xml);
  assert.equal(warnings.length, 0);
});

test("resolveNamesInXml: STBL-key hex placeholder is not consumed", () => {
  // `0xfa1c…` and 0xTBD_STBL_KEY_XYZ-style placeholders look like names by
  // pattern (no whitespace, single token). Numeric/hex bodies must be skipped
  // BEFORE name lookup. The TBD_… form is alphanumeric — but we never want it
  // appearing here at all; this test guards the post-STBL-substitution shape.
  const xml = `<T n="display_name">0xfa1c2233</T>`;
  const { xml: out } = resolveNamesInXml(xml, sampleMap);
  assert.equal(out, xml);
});

test("resolveNamesInXml: preserves surrounding whitespace and other attrs", () => {
  const xml = `<I c="C">
  <L n="career_levels">
    <T>HC_Loot_Add_HistorianLevel_Small</T>
  </L>
</I>`;
  const { xml: out } = resolveNamesInXml(xml, sampleMap);
  assert.match(out, /<L n="career_levels">/);
  assert.match(out, /\n    <T>123456789012345<\/T>\n/);
});

// ----------------------------------------------------------------------------
// Integration: collect + resolve together (mirrors what the builder does)
// ----------------------------------------------------------------------------

test("integration: collect then resolve across multiple files", () => {
  const xmls = [
    [
      "HC_Loot_Add_HistorianLevel_Small.xml",
      `<I c="LootActions" i="action" m="x" n="HC_Loot_Add_HistorianLevel_Small" s="TBD_INSTANCE_ID">
        <T n="statistic">HC_Statistic_HistorianLevel</T>
       </I>`,
    ],
    [
      "HC_Statistic_HistorianLevel.xml",
      `<I c="Statistic" i="statistic" m="y" n="HC_Statistic_HistorianLevel" s="TBD_INSTANCE_ID">
        <T n="initial_value">0</T>
       </I>`,
    ],
    [
      "HC_Interaction_TranscribeManuscript.xml",
      `<I c="SuperInteraction" i="interaction" m="z" n="HC_Interaction_TranscribeManuscript" s="TBD_INSTANCE_ID">
        <L n="loot_list">
          <T>HC_Loot_Add_HistorianLevel_Small</T>
        </L>
       </I>`,
    ],
  ];
  const map = collectTuningNames(xmls);
  assert.equal(map.size, 3);

  const statId = fnv64("HC_Statistic_HistorianLevel", true).toString();
  const lootId = fnv64("HC_Loot_Add_HistorianLevel_Small", true).toString();

  const lootXml = xmls[0][1];
  const { xml: lootResolved } = resolveNamesInXml(lootXml, map);
  assert.match(lootResolved, new RegExp(`<T n="statistic">${statId}</T>`));

  const intXml = xmls[2][1];
  const { xml: intResolved } = resolveNamesInXml(intXml, map);
  assert.match(intResolved, new RegExp(`<T>${lootId}</T>`));
});

// ----------------------------------------------------------------------------

console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
