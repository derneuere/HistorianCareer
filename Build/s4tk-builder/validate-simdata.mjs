// validate-simdata.mjs — build-time guard that every emitted AspirationTrack
// and Aspiration SimData populates the columns EA always populates non-null.
//
// Background (issue #17, the AS3 INIT_DATA crash):
//
//   The CAS aspiration picker (and the in-game aspiration panel) lazy-loads
//   the global track catalog the first time the AS3 code calls
//   `AspirationTrackStaticData.GetTrackData(uid)`. That call triggers
//   `AspirationTrackStaticData.INIT_DATA()`, which fetches the track list via
//   the native `GetAspirationTrackStaticData` GameService, constructs one
//   `AspirationTrackStaticData` per row, then immediately reads:
//
//     _loc5_ = int(_loc4_.aspirations.length);   // <-- null-deref candidate
//
//   The AS3 field `aspirations:Array = [String]` is a placeholder. EA's
//   `OlympusObject.ParseObject` either replaces it with the actual incoming
//   Array (if `obj.aspirations` IS an Array), or — via the catch-all
//   `this[fieldName] = obj[fieldName]` branch — overwrites it with whatever
//   the engine emitted (potentially null/undefined). The placeholder survives
//   only when the field is entirely absent from the JSON the engine sent.
//
//   The engine, in turn, drives that JSON off our SimData. If the engine sees
//   our row but fails to resolve one of the columns (typically because a
//   ResourceKey cell or a Vector elem points at an instance ID it can't find
//   in the runtime tuning index), it emits `null` for that field on the JSON
//   side. The catch-all then nulls the AS3 placeholder. `null.length` throws
//   `TypeError #1009: Cannot access a property or method of a null object
//   reference.` STATIC_DATA_PER_CATEGORY stays uninitialised and EVERY future
//   `GetTrackData(uid)` call returns null — i.e. NO aspiration tracks render,
//   not even EA's. (See Docs/NOTE_cas_aspiration_picker_swf.md §5.)
//
//   By inspection (Build/_research_tmp/inspect-asp-simdata.mjs) our currently-
//   shipping SimData is byte-equivalent to EA's pattern: same schema, same
//   column order, all values that EA populates non-null are populated non-
//   null in ours too (verified against Track_Knowledge_A and Track_Knowledge_B,
//   the two EA tracks in the same `category=Asp_Cat_Knowledge` family). The
//   static-analysis hypothesis ("a null cell where EA always populates") is
//   not the cause for the CURRENT build. The bug may have been fixed by
//   commit 6b4e72f (TEEN_OR_OLDER) and we're now looking at a stale-cache
//   artefact, OR there's a runtime cause our static analysis can't see.
//
//   Either way, the defensive measure is the same: assert at build time that
//   every emitted AspirationTrack/Aspiration row populates the columns EA's
//   shipping rows always populate, with non-default values. If we ever
//   accidentally regress (e.g. an icon DDS gets deleted, an STBL key goes
//   missing, an aspiration tier reference fails to resolve to a non-zero
//   instance ID), this validator throws BEFORE the package goes to the game.
//
// This module is pure: no I/O, no global state. It takes a parsed @s4tk/models
// Package as input and inspects the entries it cares about. Throws on any
// violation. Tested in validate-simdata.test.mjs.
//
// Note: when the builder pushes SimData into the package, it uses
// `RawResource.from(simBuffer)` (the raw bytes are kept as-is; @s4tk doesn't
// re-parse them until you ask). For the validator to read columns, we
// re-parse via `SimDataResource.from(rawBuf)`. Pure tests stub a SimData-
// shaped object directly (skipping the re-parse step).

import { SimDataResource } from "@s4tk/models";

const SIMDATA_TYPE = 0x545AC67A;
const ASPIRATION_TRACK_GROUP = 0x0020FC6D;
const ASPIRATION_GROUP = 0x00B6465D;

const ASPIRATION_TRACK_SCHEMA_HASH = 0x54fdb5fc;
const ASPIRATION_SCHEMA_HASH = 0x72abca6f;

// Columns EA's shipping AspirationTrack SimDatas always populate non-null
// (verified by enumerating all 27 EA tracks in ClientFullBuild0 +
// ClientDeltaBuild0 — see Build/_research_tmp/check-ea-tracks.mjs).
//
// `aspirations`: a Vector, always 1..N entries with a non-zero `value` TSR.
// `category`:    a TSR, always a non-zero EA AspirationCategory id.
// `display_text`: a LocalizationKey (uint32 STBL hash), always non-zero.
// `icon`:        a ResourceKey, always non-zero (every EA track ships an icon).
// `primary_trait`: a TSR — non-zero on adult tracks; zero on EA's 4 child
//                  tracks (Track_Mental/Social/Creativity/Motor). We allow
//                  zero ONLY if the schema explicitly opts out via a
//                  `KNOWN_ZERO_OK` allow-list (none of our tracks today).
// `reward`:      a TSR, always non-zero (every EA track has a reward).
const REQUIRED_NONZERO_TRACK_COLUMNS = {
  aspirations:    { kind: "vector-nonempty" },
  category:       { kind: "tsr" },
  display_text:   { kind: "stbl" },
  icon:           { kind: "resource-key" },
  primary_trait:  { kind: "tsr", note: "EA child tracks ship 0 here; adult tracks always non-zero" },
  reward:         { kind: "tsr" },
};

// Inner schema for AspirationTrack.aspirations entries: each must have a
// non-zero `value` (the aspiration uid TSR). The `key` is an enum (LEVEL_X);
// LEVEL_1 = 1 is non-zero, so even key=LEVEL_1 is OK here.
const REQUIRED_NONZERO_ASPIRATION_ENTRY_COLUMNS = {
  value:          { kind: "tsr", note: "aspiration tier reference must resolve" },
  // key (LEVEL_X) is always >= 1 by EA's enum definition — no check needed.
};

// Columns EA's shipping Aspiration SimDatas always populate non-null
// (verified by enumerating all 139 EA aspirations in
// ClientFullBuild0 + ClientDeltaBuild0).
//
// `display_name`: a LocalizationKey, always non-zero.
// `objectives`:   a Vector — EA has aspirations with 0 objectives (rare —
//                 e.g. tutorial slots) BUT for our HC tiers we want >=1
//                 since INIT_DATA's neighbour-class `AspirationTrackAgeType`
//                 indexes `aspirations[0]`. We enforce >=1.
//
// `descriptive_text` is allowed to be zero — many EA aspirations ship 0 here
// (e.g. aspiration_Knowledge_A1).
const REQUIRED_NONZERO_ASPIRATION_COLUMNS = {
  display_name:   { kind: "stbl" },
  objectives:     { kind: "vector-nonempty" },
};

// Inner schema for Aspiration.objectives entries: each is a TSR to an
// Objective tuning. The TSR must resolve to a non-zero instance.
const REQUIRED_NONZERO_OBJECTIVE_ENTRY = { kind: "tsr-direct", note: "objective reference must resolve" };

/**
 * Check whether a cell of the given semantic kind holds a non-default value.
 * Returns null on success or a short reason string on failure.
 */
function violationReason(cell, kind) {
  if (cell == null) return "<missing>";
  switch (kind) {
    case "tsr": {
      const v = cell.value;
      if (v == null) return "<null TSR>";
      const bv = typeof v === "bigint" ? v : BigInt(v);
      if (bv === 0n) return "<zero TSR>";
      return null;
    }
    case "tsr-direct": {
      // The cell IS the TSR value (used for direct Vector<TSR> elements,
      // where the cell.value is the TSR uint64 directly).
      const v = cell.value;
      if (v == null) return "<null TSR>";
      const bv = typeof v === "bigint" ? v : BigInt(v);
      if (bv === 0n) return "<zero TSR>";
      return null;
    }
    case "stbl": {
      const v = cell.value;
      if (v == null) return "<null STBL>";
      const bv = typeof v === "bigint" ? v : BigInt(v);
      if (bv === 0n) return "<zero STBL>";
      return null;
    }
    case "resource-key": {
      const t = BigInt(cell.type ?? 0n);
      const g = BigInt(cell.group ?? 0n);
      const i = BigInt(cell.instance ?? 0n);
      if (t === 0n && g === 0n && i === 0n) return "<zero ResourceKey>";
      return null;
    }
    case "vector-nonempty": {
      const ch = cell.children ?? [];
      if (ch.length === 0) return "<empty vector>";
      return null;
    }
    default:
      return `<unknown check kind: ${kind}>`;
  }
}

/**
 * Inspect a parsed SimData instance against a per-column requirement table.
 * Returns an array of `{ column, reason }` for each violation (empty if clean).
 */
function checkInstance(inst, requiredColumns) {
  const violations = [];
  for (const [colName, spec] of Object.entries(requiredColumns)) {
    const cell = inst.row[colName];
    if (cell === undefined) {
      // Column missing from the row entirely. The schema decides which
      // columns appear; if a required column isn't even in the schema, the
      // build pipeline is misconfigured upstream.
      violations.push({ column: colName, reason: "<column missing from row>" });
      continue;
    }
    const reason = violationReason(cell, spec.kind);
    if (reason !== null) {
      violations.push({ column: colName, reason });
    }
  }
  return violations;
}

/**
 * Inspect an inner Vector's child Object cells (e.g. AspirationTrack.aspirations
 * elements) against a per-column requirement table.
 */
function checkVectorObjectChildren(vectorCell, requiredColumns) {
  const violations = [];
  const children = vectorCell.children ?? [];
  for (let i = 0; i < children.length; i++) {
    const child = children[i];
    const row = child.row ?? {};
    for (const [colName, spec] of Object.entries(requiredColumns)) {
      const cell = row[colName];
      if (cell === undefined) {
        violations.push({ index: i, column: colName, reason: "<column missing>" });
        continue;
      }
      const reason = violationReason(cell, spec.kind);
      if (reason !== null) {
        violations.push({ index: i, column: colName, reason });
      }
    }
  }
  return violations;
}

/**
 * Inspect an inner Vector of primitive cells (e.g. Aspiration.objectives —
 * which is a Vector<TSR>, NOT a Vector<Object{key,value}>).
 */
function checkVectorPrimitiveChildren(vectorCell, requirement) {
  const violations = [];
  const children = vectorCell.children ?? [];
  for (let i = 0; i < children.length; i++) {
    const cell = children[i];
    const reason = violationReason(cell, requirement.kind);
    if (reason !== null) {
      violations.push({ index: i, reason });
    }
  }
  return violations;
}

/**
 * Walk every SimData entry in the package and validate those at the AspirationTrack
 * or Aspiration TGI shape. Throws with an aggregated, human-readable error if any
 * validation fails. Returns a summary of what was checked on success.
 *
 * @param {Package} pkg  parsed @s4tk/models Package
 * @returns {{ tracksChecked: number, aspirationsChecked: number }}
 */
export function assertSimDataPopulated(pkg) {
  let tracksChecked = 0;
  let aspirationsChecked = 0;

  /** @type {string[]} */
  const lines = [];

  for (const entry of pkg.entries) {
    const k = entry.key;
    if (k.type !== SIMDATA_TYPE) continue;

    let sd;
    try {
      const v = entry.value;
      // The builder wraps SimData in a `RawResource` (raw bytes — @s4tk
      // doesn't re-parse them by default). For validation we need the
      // parsed cell tree, so re-parse from the raw buffer. If the entry
      // is already a SimDataResource (e.g. when tests stub it directly),
      // we can use it as-is.
      if (v && Array.isArray(v.instances)) {
        sd = v;
      } else if (v && typeof v.getBuffer === "function") {
        sd = SimDataResource.from(v.getBuffer());
      } else {
        // Unknown shape — skip without throwing (other resource types may
        // legitimately have value shapes the validator doesn't recognize).
        continue;
      }
    } catch (err) {
      lines.push(
        `  SimData at group=0x${k.group.toString(16)} instance=0x${BigInt(k.instance).toString(16)} ` +
          `failed to parse: ${err.message}`,
      );
      continue;
    }

    for (const inst of sd.instances ?? []) {
      const schemaHash = inst.schema.hash;

      // AspirationTrack rows
      if (k.group === ASPIRATION_TRACK_GROUP && schemaHash === ASPIRATION_TRACK_SCHEMA_HASH) {
        tracksChecked++;
        const violations = checkInstance(inst, REQUIRED_NONZERO_TRACK_COLUMNS);
        // Also walk aspirations inner vector
        const aspsCell = inst.row.aspirations;
        if (aspsCell && aspsCell.children) {
          const innerViolations = checkVectorObjectChildren(aspsCell, REQUIRED_NONZERO_ASPIRATION_ENTRY_COLUMNS);
          for (const v of innerViolations) {
            violations.push({
              column: `aspirations[${v.index}].${v.column}`,
              reason: v.reason,
            });
          }
        }
        if (violations.length > 0) {
          for (const v of violations) {
            lines.push(
              `  AspirationTrack "${inst.name}" (instance=0x${BigInt(k.instance).toString(16)}): ` +
                `${v.column} = ${v.reason}`,
            );
          }
        }
        continue;
      }

      // Aspiration rows
      if (k.group === ASPIRATION_GROUP && schemaHash === ASPIRATION_SCHEMA_HASH) {
        aspirationsChecked++;
        const violations = checkInstance(inst, REQUIRED_NONZERO_ASPIRATION_COLUMNS);
        // Objectives vector children — each is a TSR cell directly (no inner schema)
        const objCell = inst.row.objectives;
        if (objCell && objCell.children && objCell.children.length > 0) {
          const innerViolations = checkVectorPrimitiveChildren(objCell, REQUIRED_NONZERO_OBJECTIVE_ENTRY);
          for (const v of innerViolations) {
            violations.push({
              column: `objectives[${v.index}]`,
              reason: v.reason,
            });
          }
        }
        if (violations.length > 0) {
          for (const v of violations) {
            lines.push(
              `  Aspiration "${inst.name}" (instance=0x${BigInt(k.instance).toString(16)}): ` +
                `${v.column} = ${v.reason}`,
            );
          }
        }
        continue;
      }
    }
  }

  if (lines.length > 0) {
    throw new Error(
      `assertSimDataPopulated: ${lines.length} field(s) below EA's non-null bar. ` +
        `These nulls can crash the Olympus AS3 client at game launch via ` +
        `AspirationTrackStaticData.INIT_DATA's _loc4_.aspirations.length null-deref ` +
        `(see issue #17 and Docs/NOTE_cas_aspiration_picker_swf.md §5):\n${lines.join("\n")}`,
    );
  }

  return { tracksChecked, aspirationsChecked };
}

// Re-export the requirement tables so tests can inspect them.
export {
  REQUIRED_NONZERO_TRACK_COLUMNS,
  REQUIRED_NONZERO_ASPIRATION_ENTRY_COLUMNS,
  REQUIRED_NONZERO_ASPIRATION_COLUMNS,
  REQUIRED_NONZERO_OBJECTIVE_ENTRY,
  ASPIRATION_TRACK_GROUP,
  ASPIRATION_GROUP,
  ASPIRATION_TRACK_SCHEMA_HASH,
  ASPIRATION_SCHEMA_HASH,
  SIMDATA_TYPE,
};
