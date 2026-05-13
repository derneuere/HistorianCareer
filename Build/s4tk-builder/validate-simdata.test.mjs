// validate-simdata.test.mjs — unit tests for the SimData populated-fields validator.
//
// Plain Node script: no framework dependency. Run with:
//   node validate-simdata.test.mjs
// or via the package.json "test" script.

import assert from "node:assert/strict";
import {
  assertSimDataPopulated,
  REQUIRED_NONZERO_TRACK_COLUMNS,
  REQUIRED_NONZERO_ASPIRATION_COLUMNS,
  REQUIRED_NONZERO_ASPIRATION_ENTRY_COLUMNS,
  ASPIRATION_TRACK_GROUP,
  ASPIRATION_GROUP,
  ASPIRATION_TRACK_SCHEMA_HASH,
  ASPIRATION_SCHEMA_HASH,
  SIMDATA_TYPE,
} from "./validate-simdata.mjs";

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

// Synthesise a minimal Package-shaped object that has the .entries iterable
// the validator walks. Each entry must expose `.key` and `.value`. The cells
// we feed in mimic the shape of @s4tk/models cells closely enough for the
// validator's pure-functional checks: each cell has a .dataType and either a
// .value (primitives, TSR, STBL) or .type/.group/.instance (ResourceKey) or
// .children (Vector) or .row (Object).
//
// We don't actually import @s4tk/models here — the tests stay pure.

function makePkg(entries) {
  return { entries };
}

function makeTrackEntry({ name = "t", instance = 0x1000n, row }) {
  return {
    key: { type: SIMDATA_TYPE, group: ASPIRATION_TRACK_GROUP, instance },
    value: {
      instances: [
        {
          name,
          schema: { hash: ASPIRATION_TRACK_SCHEMA_HASH, name: "AspirationTrack" },
          row,
        },
      ],
    },
  };
}

function makeAspEntry({ name = "a", instance = 0x2000n, row }) {
  return {
    key: { type: SIMDATA_TYPE, group: ASPIRATION_GROUP, instance },
    value: {
      instances: [
        {
          name,
          schema: { hash: ASPIRATION_SCHEMA_HASH, name: "Aspiration" },
          row,
        },
      ],
    },
  };
}

// Cell constructors (minimal — only what the validator inspects).
const tsr = (v) => ({ value: typeof v === "bigint" ? v : BigInt(v) });
const stbl = (v) => ({ value: typeof v === "bigint" ? v : BigInt(v) });
const rk = (type, group, instance) => ({
  type: BigInt(type),
  group: BigInt(group),
  instance: BigInt(instance),
});
const vec = (...children) => ({ children });
const obj = (row) => ({ row });

// Reference: a healthy AspirationTrack row — matches the shape our
// HistorianCalling track ships today. All required columns non-null.
function healthyTrackRow() {
  return {
    aspirations: vec(
      obj({ key: { value: 1n }, value: tsr(0x6168b383n) }),
      obj({ key: { value: 2n }, value: tsr(0x6168b380n) }),
      obj({ key: { value: 3n }, value: tsr(0x6168b381n) }),
      obj({ key: { value: 4n }, value: tsr(0x6168b386n) }),
    ),
    category: tsr(0x6329n),
    description_text: stbl(0xc5cf3cc8n),
    display_text: stbl(0x41be9b6an),
    icon: rk(0xb2d882, 0, 0xd26124833b452384n),
    icon_high_res: rk(0, 0, 0),  // EA also ships these zero — that's fine.
    mood_asm_param: { value: "" },
    primary_trait: tsr(0x69cen),
    reward: tsr(0x6b61n),
  };
}

// Reference: a healthy Aspiration row — matches the shape our HistorianCalling
// tier ships today. All required columns non-null.
function healthyAspirationRow() {
  return {
    descriptive_text: stbl(0x64d30b81n),
    disabled: { value: false },
    display_name: stbl(0xe655bca3n),
    is_child_aspiration: { value: false },
    objectives: vec(tsr(0x4c48a506n)),
  };
}

// ----------------------------------------------------------------------------
// REQUIREMENT TABLE SANITY
// ----------------------------------------------------------------------------

test("REQUIRED_NONZERO_TRACK_COLUMNS covers the 6 fields EA always populates", () => {
  // EA tracks (all 27 in ClientFullBuild0): every one has non-null aspirations,
  // category, display_text, icon, primary_trait (except 4 child tracks), reward.
  // We codify this in the requirement table; the validator enforces it on us.
  const expected = ["aspirations", "category", "display_text", "icon", "primary_trait", "reward"];
  for (const f of expected) {
    assert.ok(REQUIRED_NONZERO_TRACK_COLUMNS[f], `missing required column: ${f}`);
  }
});

test("REQUIRED_NONZERO_ASPIRATION_COLUMNS includes display_name and objectives", () => {
  assert.ok(REQUIRED_NONZERO_ASPIRATION_COLUMNS.display_name);
  assert.ok(REQUIRED_NONZERO_ASPIRATION_COLUMNS.objectives);
  // descriptive_text is NOT required: 127 of 139 EA aspirations ship 0 here.
  assert.equal(REQUIRED_NONZERO_ASPIRATION_COLUMNS.descriptive_text, undefined);
});

test("REQUIRED_NONZERO_ASPIRATION_ENTRY_COLUMNS requires only value, not key", () => {
  assert.ok(REQUIRED_NONZERO_ASPIRATION_ENTRY_COLUMNS.value);
  // key is an enum LEVEL_X (always >= 1) — no check needed.
  assert.equal(REQUIRED_NONZERO_ASPIRATION_ENTRY_COLUMNS.key, undefined);
});

// ----------------------------------------------------------------------------
// HAPPY PATH
// ----------------------------------------------------------------------------

test("happy path: healthy track + healthy aspiration pass", () => {
  const pkg = makePkg([
    makeTrackEntry({ row: healthyTrackRow() }),
    makeAspEntry({ row: healthyAspirationRow() }),
  ]);
  const { tracksChecked, aspirationsChecked } = assertSimDataPopulated(pkg);
  assert.equal(tracksChecked, 1);
  assert.equal(aspirationsChecked, 1);
});

test("happy path: package with no AspirationTrack/Aspiration is OK", () => {
  const pkg = makePkg([]);
  const { tracksChecked, aspirationsChecked } = assertSimDataPopulated(pkg);
  assert.equal(tracksChecked, 0);
  assert.equal(aspirationsChecked, 0);
});

// ----------------------------------------------------------------------------
// NULL TRACK FIELDS
// ----------------------------------------------------------------------------

test("rejects zero category TSR on AspirationTrack", () => {
  const row = healthyTrackRow();
  row.category = tsr(0n);
  const pkg = makePkg([makeTrackEntry({ name: "BadTrack", row })]);
  assert.throws(
    () => assertSimDataPopulated(pkg),
    (err) => {
      assert.match(err.message, /BadTrack/);
      assert.match(err.message, /category/);
      assert.match(err.message, /zero TSR/);
      return true;
    },
  );
});

test("rejects zero display_text STBL on AspirationTrack", () => {
  const row = healthyTrackRow();
  row.display_text = stbl(0n);
  const pkg = makePkg([makeTrackEntry({ name: "BadTrack", row })]);
  assert.throws(() => assertSimDataPopulated(pkg), /display_text.*zero STBL/);
});

test("rejects zero icon ResourceKey on AspirationTrack", () => {
  const row = healthyTrackRow();
  row.icon = rk(0, 0, 0);
  const pkg = makePkg([makeTrackEntry({ name: "BadTrack", row })]);
  assert.throws(() => assertSimDataPopulated(pkg), /icon.*zero ResourceKey/);
});

test("rejects empty aspirations Vector on AspirationTrack", () => {
  const row = healthyTrackRow();
  row.aspirations = vec();  // 0 entries
  const pkg = makePkg([makeTrackEntry({ name: "BadTrack", row })]);
  assert.throws(() => assertSimDataPopulated(pkg), /aspirations.*empty vector/);
});

test("rejects zero TSR in aspirations[i].value", () => {
  const row = healthyTrackRow();
  // Corrupt the third tier's value reference.
  row.aspirations.children[2] = obj({ key: { value: 3n }, value: tsr(0n) });
  const pkg = makePkg([makeTrackEntry({ name: "BadTrack", row })]);
  assert.throws(() => assertSimDataPopulated(pkg), /aspirations\[2\]\.value.*zero TSR/);
});

test("rejects zero reward TSR on AspirationTrack", () => {
  const row = healthyTrackRow();
  row.reward = tsr(0n);
  const pkg = makePkg([makeTrackEntry({ name: "BadTrack", row })]);
  assert.throws(() => assertSimDataPopulated(pkg), /reward.*zero TSR/);
});

test("rejects zero primary_trait TSR on AspirationTrack", () => {
  // All EA adult tracks have a non-zero primary_trait. (4 child tracks ship 0
  // here, but we deliberately don't ship a child track, so 0 is a regression.)
  const row = healthyTrackRow();
  row.primary_trait = tsr(0n);
  const pkg = makePkg([makeTrackEntry({ name: "BadTrack", row })]);
  assert.throws(() => assertSimDataPopulated(pkg), /primary_trait.*zero TSR/);
});

// ----------------------------------------------------------------------------
// NULL ASPIRATION FIELDS
// ----------------------------------------------------------------------------

test("rejects zero display_name STBL on Aspiration", () => {
  const row = healthyAspirationRow();
  row.display_name = stbl(0n);
  const pkg = makePkg([makeAspEntry({ name: "BadAsp", row })]);
  assert.throws(() => assertSimDataPopulated(pkg), /BadAsp.*display_name.*zero STBL/);
});

test("rejects empty objectives Vector on Aspiration", () => {
  const row = healthyAspirationRow();
  row.objectives = vec();
  const pkg = makePkg([makeAspEntry({ name: "BadAsp", row })]);
  assert.throws(() => assertSimDataPopulated(pkg), /BadAsp.*objectives.*empty vector/);
});

test("rejects zero TSR in objectives[i]", () => {
  const row = healthyAspirationRow();
  row.objectives = vec(tsr(0n));
  const pkg = makePkg([makeAspEntry({ name: "BadAsp", row })]);
  assert.throws(() => assertSimDataPopulated(pkg), /BadAsp.*objectives\[0\].*zero TSR/);
});

test("allows zero descriptive_text on Aspiration (matches EA's 127/139 pattern)", () => {
  const row = healthyAspirationRow();
  row.descriptive_text = stbl(0n);
  // Should NOT throw — descriptive_text is not in the required-nonzero set.
  const pkg = makePkg([makeAspEntry({ row })]);
  assertSimDataPopulated(pkg);
});

// ----------------------------------------------------------------------------
// ERROR MESSAGE QUALITY
// ----------------------------------------------------------------------------

test("error message references issue #17 and the AS3 crash mechanism", () => {
  const row = healthyTrackRow();
  row.category = tsr(0n);
  const pkg = makePkg([makeTrackEntry({ row })]);
  assert.throws(() => assertSimDataPopulated(pkg), (err) => {
    assert.match(err.message, /issue #17/);
    assert.match(err.message, /INIT_DATA/);
    assert.match(err.message, /aspirations\.length/);
    return true;
  });
});

test("aggregates violations across multiple instances", () => {
  const row1 = healthyTrackRow();
  row1.category = tsr(0n);
  const row2 = healthyAspirationRow();
  row2.display_name = stbl(0n);
  const pkg = makePkg([
    makeTrackEntry({ name: "T1", row: row1 }),
    makeAspEntry({ name: "A1", row: row2 }),
  ]);
  assert.throws(() => assertSimDataPopulated(pkg), (err) => {
    assert.match(err.message, /2 field/);
    assert.match(err.message, /T1.*category/s);
    assert.match(err.message, /A1.*display_name/s);
    return true;
  });
});

// ----------------------------------------------------------------------------
// NEGATIVE: NON-MATCHING SHAPES
// ----------------------------------------------------------------------------

test("skips SimData entries that aren't at the AspirationTrack/Aspiration TGI", () => {
  // Group/schema-hash combos that don't match are silently ignored.
  const pkg = makePkg([
    {
      key: { type: SIMDATA_TYPE, group: 0x12345, instance: 0x100n },
      value: {
        instances: [{
          name: "RandomSimData",
          schema: { hash: 0xdeadbeef, name: "Other" },
          row: {},  // empty — would trip the check if we were checking it
        }],
      },
    },
  ]);
  // No violations expected.
  const { tracksChecked, aspirationsChecked } = assertSimDataPopulated(pkg);
  assert.equal(tracksChecked, 0);
  assert.equal(aspirationsChecked, 0);
});

// ----------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
