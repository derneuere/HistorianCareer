// pie-menu-category-id.test.mjs — minimal assertion-driven coverage for the
// 31-bit ID helper. Written as a plain ESM script (no test runner dependency)
// so it runs on the same Node version the build uses (16+).
//
// Run with: node pie-menu-category-id.test.mjs
//          → exits 0 on success, non-zero with a stack trace on failure.
//
// Covers:
//   1. smallInstanceIdFor produces a value in [1, 2^31 - 1].
//   2. smallInstanceIdFor is deterministic.
//   3. Distinct tuning names produce distinct IDs (statistical guard against
//      accidental collisions in the names we actually ship).
//   4. assertNoCollisions throws on a duplicate ID.
//   5. assertNoCollisions is silent on the happy path.
//   6. SMALL_ID_CLASSES currently lists exactly PieMenuCategory.
//   7. Empty / non-string input is rejected.

import assert from "node:assert/strict";

import {
    smallInstanceIdFor,
    assertNoCollisions,
    PIE_MENU_CATEGORY_ID_MASK,
    SMALL_ID_CLASSES,
} from "./pie-menu-category-id.mjs";

const tests = [];
function test(name, fn) {
    tests.push({ name, fn });
}

test("smallInstanceIdFor is in [1, 2^31 - 1]", () => {
    const id = smallInstanceIdFor("HC_PieMenuCategory_Historian");
    assert.ok(id >= 1n, `id should be >= 1, got ${id}`);
    assert.ok(id <= PIE_MENU_CATEGORY_ID_MASK, `id should be <= 0x7FFFFFFF, got 0x${id.toString(16)}`);
});

test("smallInstanceIdFor is deterministic", () => {
    const a = smallInstanceIdFor("HC_PieMenuCategory_Historian");
    const b = smallInstanceIdFor("HC_PieMenuCategory_Historian");
    assert.equal(a, b);
});

test("smallInstanceIdFor distinguishes between tuning names", () => {
    const names = [
        "HC_PieMenuCategory_Historian",
        "computer_Handiness",
        "computer_Programming",
        "computer_Web",
        "computer_VideoStation",
    ];
    const ids = new Set(names.map(n => smallInstanceIdFor(n).toString()));
    assert.equal(ids.size, names.length, "all names should hash to distinct IDs");
});

test("smallInstanceIdFor rejects empty / non-string input", () => {
    assert.throws(() => smallInstanceIdFor(""), /non-empty string/);
    assert.throws(() => smallInstanceIdFor(undefined), /non-empty string/);
    assert.throws(() => smallInstanceIdFor(123), /non-empty string/);
});

test("assertNoCollisions silent on distinct IDs", () => {
    const m = new Map();
    m.set("HC_PieMenuCategory_Historian", smallInstanceIdFor("HC_PieMenuCategory_Historian"));
    m.set("computer_Handiness", smallInstanceIdFor("computer_Handiness"));
    assertNoCollisions(m);
});

test("assertNoCollisions throws on duplicate IDs", () => {
    const m = new Map();
    m.set("alpha", 42n);
    m.set("beta", 42n);
    assert.throws(
        () => assertNoCollisions(m),
        /collision/,
    );
});

test("SMALL_ID_CLASSES covers PieMenuCategory and the career/aspiration family", () => {
    // PieMenuCategory — original case (issue #14): EA's <T n="category"> field
    // is a TunableReference constrained to <= 2^31.
    assert.ok(SMALL_ID_CLASSES.has("PieMenuCategory"));
    // Career family — surfaced when in-game testing showed Career/CareerTrack
    // display strings rendering as "@" / default-icon. lot51-core's
    // custom_filter_career_fix.py confirms 64-bit career IDs are silently
    // dropped by EA's sim-filter system. EA's own careers ship with 16-bit
    // instance IDs (e.g. Writer = 27933, GradeSchool track = 12900).
    for (const name of [
        "Career",
        "TunableCareerTrack",
        "CareerTrack",
        "CareerLevel",
        "Aspiration",
        "AspirationTrack",
        "AspirationCareer",
        "Objective",
        "Trait",
        "Statistic",
    ]) {
        assert.ok(SMALL_ID_CLASSES.has(name), `SMALL_ID_CLASSES missing ${name}`);
    }
});

let passed = 0;
let failed = 0;
for (const { name, fn } of tests) {
    try {
        fn();
        console.log(`  ok  ${name}`);
        passed++;
    } catch (err) {
        console.error(`  FAIL ${name}`);
        console.error(err.stack ?? err);
        failed++;
    }
}
console.log("");
console.log(`${passed}/${tests.length} passed`);
if (failed > 0) process.exit(1);
