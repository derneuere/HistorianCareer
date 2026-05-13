// validate-enums.test.mjs — unit tests for the build-time enum value validator.
//
// Plain Node script: no test framework dependency. Each test calls assert.*
// from node:assert/strict; on failure the script exits non-zero.
//
// Run with:
//   node validate-enums.test.mjs
// or via the package.json "test" script.

import assert from "node:assert/strict";
import {
  FIELD_ENUMS,
  findInvalidEnumValues,
  assertKnownEnumValues,
} from "./validate-enums.mjs";

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
// FIELD_ENUMS table sanity
// ----------------------------------------------------------------------------

test("FIELD_ENUMS: aspiration_valid_age_type allows real EA members only", () => {
  const allowed = FIELD_ENUMS.aspiration_valid_age_type;
  assert.ok(allowed instanceof Set, "expected a Set");
  assert.ok(allowed.has("TEEN_OR_OLDER"));
  assert.ok(allowed.has("TEEN_ONLY"));
  assert.ok(allowed.has("CHILD_ONLY"));
  assert.ok(allowed.has("TODDLER_ONLY"));
  // INVALID is the silent-fallback target — never an intended value.
  assert.equal(allowed.has("INVALID"), false);
  // YAE_ONLY is the bug that motivated this validator — must remain rejected.
  assert.equal(allowed.has("YAE_ONLY"), false);
  // Not a real enum member either.
  assert.equal(allowed.has("TEEN_AND_YAE"), false);
});

// ----------------------------------------------------------------------------
// findInvalidEnumValues
// ----------------------------------------------------------------------------

test("findInvalidEnumValues: accepts TEEN_OR_OLDER", () => {
  const xml = `<I c="Aspiration" n="x" s="1">
    <E n="aspiration_valid_age_type">TEEN_OR_OLDER</E>
  </I>`;
  assert.deepEqual(findInvalidEnumValues(xml), []);
});

test("findInvalidEnumValues: rejects YAE_ONLY (the issue #17 root cause)", () => {
  const xml = `<I c="Aspiration" n="x" s="1">
    <E n="aspiration_valid_age_type">YAE_ONLY</E>
  </I>`;
  assert.deepEqual(findInvalidEnumValues(xml), [
    { field: "aspiration_valid_age_type", value: "YAE_ONLY" },
  ]);
});

test("findInvalidEnumValues: rejects INVALID (silent-fallback target)", () => {
  const xml = `<E n="aspiration_valid_age_type">INVALID</E>`;
  assert.deepEqual(findInvalidEnumValues(xml), [
    { field: "aspiration_valid_age_type", value: "INVALID" },
  ]);
});

test("findInvalidEnumValues: numeric body is allowed (parser uses int path)", () => {
  // EA's parser tries name lookup first; on failure it tries int(value). A
  // bare numeric like "120" is unambiguous; not a silent-fallback risk.
  const xml = `<E n="aspiration_valid_age_type">120</E>`;
  assert.deepEqual(findInvalidEnumValues(xml), []);
});

test("findInvalidEnumValues: empty body is ignored", () => {
  const xml = `<E n="aspiration_valid_age_type"></E>`;
  assert.deepEqual(findInvalidEnumValues(xml), []);
});

test("findInvalidEnumValues: untracked fields are ignored", () => {
  // We only validate fields that appear in FIELD_ENUMS; everything else
  // passes through. AspirationTrackLevels is intentionally NOT in the
  // table — those are SimData-side, not silent-fallback targets.
  const xml = `<E n="some_random_field">WHATEVER_VALUE</E>`;
  assert.deepEqual(findInvalidEnumValues(xml), []);
});

test("findInvalidEnumValues: <E> without an n= attr is ignored", () => {
  // Positional enum refs without `n=` are caught by the name-resolver pass,
  // not by this validator. We deliberately don't try to figure out the
  // intended field from positional context.
  const xml = `<L n="ages"><E>YAE_ONLY</E></L>`;
  assert.deepEqual(findInvalidEnumValues(xml), []);
});

test("findInvalidEnumValues: surfaces every violation in a file", () => {
  const xml = `<I>
    <E n="aspiration_valid_age_type">YAE_ONLY</E>
    <E n="aspiration_valid_age_type">TEEN_AND_YAE</E>
    <E n="aspiration_valid_age_type">TEEN_OR_OLDER</E>
  </I>`;
  assert.deepEqual(findInvalidEnumValues(xml), [
    { field: "aspiration_valid_age_type", value: "YAE_ONLY" },
    { field: "aspiration_valid_age_type", value: "TEEN_AND_YAE" },
  ]);
});

test("findInvalidEnumValues: tolerates extra attributes and whitespace", () => {
  const xml = `<E   n="aspiration_valid_age_type"   p="foo"  >
                  TEEN_OR_OLDER
              </E>`;
  assert.deepEqual(findInvalidEnumValues(xml), []);
});

// ----------------------------------------------------------------------------
// assertKnownEnumValues
// ----------------------------------------------------------------------------

test("assertKnownEnumValues: passes when every file is clean", () => {
  const files = [
    [
      "aspiration_t1.xml",
      `<I><E n="aspiration_valid_age_type">TEEN_OR_OLDER</E></I>`,
    ],
    [
      "career_x.xml",
      `<I><T n="display_name">0xabc</T></I>`,
    ],
  ];
  // Should not throw.
  assertKnownEnumValues(files);
});

test("assertKnownEnumValues: throws on a single violation", () => {
  const files = [
    [
      "aspiration_t1.xml",
      `<I><E n="aspiration_valid_age_type">YAE_ONLY</E></I>`,
    ],
  ];
  assert.throws(
    () => assertKnownEnumValues(files),
    (err) => {
      assert.match(err.message, /aspiration_t1\.xml/);
      assert.match(err.message, /YAE_ONLY/);
      assert.match(err.message, /TEEN_OR_OLDER/); // suggested members listed
      assert.match(err.message, /issue #17/);
      return true;
    },
  );
});

test("assertKnownEnumValues: aggregates violations across files", () => {
  const files = [
    [
      "aspiration_t1.xml",
      `<I><E n="aspiration_valid_age_type">YAE_ONLY</E></I>`,
    ],
    [
      "aspiration_t2.xml",
      `<I><E n="aspiration_valid_age_type">INVALID</E></I>`,
    ],
    [
      "ok.xml",
      `<I><E n="aspiration_valid_age_type">TEEN_OR_OLDER</E></I>`,
    ],
  ];
  assert.throws(() => assertKnownEnumValues(files), /2 disallowed enum value/);
});

test("assertKnownEnumValues: accepts our real shipping XML shape", () => {
  // Sanity-check against the exact aspiration_HistorianCalling_T1.xml shape
  // that ships today; the validator must not regress on the fixed mod.
  const xml = `<?xml version="1.0" encoding="utf-8"?>
<I c="Aspiration" i="aspiration" m="aspirations.aspiration_tuning" n="aspiration_HistorianCalling_T1" s="TBD_INSTANCE_ID">
  <T n="display_name">0xTBD_STBL_KEY_HC_ASP_T1_NAME</T>
  <T n="descriptive_text">0xTBD_STBL_KEY_HC_ASP_T1_DESC</T>
  <E n="aspiration_valid_age_type">TEEN_OR_OLDER</E>
  <L n="objectives">
    <T>objective_HC_RunTranscribeManuscript_x2</T>
  </L>
</I>`;
  assertKnownEnumValues([["aspiration_HistorianCalling_T1.xml", xml]]);
});

// ----------------------------------------------------------------------------
// Summary
// ----------------------------------------------------------------------------

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
