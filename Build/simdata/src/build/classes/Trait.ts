// Trait — hand-authored schema for the `Trait` tuning class.
//
// Source: `Trait.NOTES.md` in this directory documents what we learned and from
// where. The schema hash `0x992BFA76` is the EA-canonical hash (current game
// version 1.124.55, extracted from the real EA SimData golden at
// `test/golden/Trait/Trait_Hidden_JoinedFiftyMileHighClub_Teen.simdata`).
// The older s4tk-models fixture (`reference/s4tk-models/.../trait.simdata`)
// uses a 17-column schema with hash 0xDE2EAF66; that fixture is from an
// older game version with `bb_filter_styles`, `bb_filter_tags`, `species`,
// and `ui_category` columns which have since been dropped.
//
// We override the generic build with a custom function that handles the
// `trait_type` enum-to-Int64 mapping (PERSONALITY=0, GAMEPLAY=1, HIDDEN=4 per
// EA observation) and provides correct defaults for the 13 columns even when
// the tuning XML omits most of them.

import { deepFreeze } from "../../tdesc/types.js";
import type { TdescSchema } from "../../tdesc/types.js";
import type { TuningTree, TuningNode } from "../../tuning/types.js";
import type { BuildContext, SimDataIR } from "../types.js";
import { buildCell, hashSchemaName } from "../cells.js";
import { decodeEnumLiteral } from "../enums.js";
import { SimDataInstance, SimDataSchema, SimDataSchemaColumn } from "@s4tk/models/lib/resources/simdata/fragments.js";
import {
  ObjectCell,
  BigIntCell,
  NumberCell,
  TextCell,
  ResourceKeyCell,
  VectorCell,
  VariantCell,
} from "@s4tk/models/lib/resources/simdata/cells.js";
import { DataType } from "@s4tk/models/enums.js";

/**
 * EA-canonical Trait schema hash. Extracted from the EA SimData golden
 * (1.124.55). If you change column membership, this must change too.
 */
const TRAIT_SCHEMA_HASH = 0x992bfa76;

/** Schema in the order EA's binary uses (13 cols, current game version). */
const TRAIT_COLUMNS: readonly TdescColumnDef[] = Object.freeze([
  { name: "ages", type: "Vector" },
  { name: "cas_idle_asm_key", type: "ResourceKey" },
  { name: "cas_idle_asm_state", type: "String" },
  { name: "cas_selected_icon", type: "ResourceKey" },
  { name: "cas_trait_asm_param", type: "String" },
  { name: "conflicting_traits", type: "Vector" },
  { name: "display_name", type: "LocalizationKey" },
  { name: "genders", type: "Vector" },
  { name: "icon", type: "ResourceKey" },
  { name: "tags", type: "Vector" },
  { name: "trait_description", type: "LocalizationKey" },
  { name: "trait_origin_description", type: "LocalizationKey" },
  { name: "trait_type", type: "Int64" },
]);

interface TdescColumnDef {
  readonly name: string;
  readonly type:
    | "Vector"
    | "ResourceKey"
    | "String"
    | "LocalizationKey"
    | "Int64";
}

const COLUMN_TO_DATATYPE: Readonly<Record<TdescColumnDef["type"], DataType>> = Object.freeze({
  Vector: DataType.Vector,
  ResourceKey: DataType.ResourceKey,
  String: DataType.String,
  LocalizationKey: DataType.LocalizationKey,
  Int64: DataType.Int64,
});

const TRAIT_TYPE_MAP: Readonly<Record<string, bigint>> = Object.freeze({
  // Current EA enum (verified empirically from EA Trait golden:
  // HIDDEN → 4n).
  PERSONALITY: 0n,
  GAMEPLAY: 1n,
  ASPIRATION: 2n,
  ASPIRATION_REWARD: 3n,
  HIDDEN: 4n,
  BONUS: 5n,
  NPC: 6n,
  AWARD: 7n,
  SOCIAL: 8n,
});

/** Build the Trait SimDataIR from a parsed tuning tree. */
export function buildTraitSimData(tree: TuningTree, ctx: BuildContext): SimDataIR {
  if (tree.rootClass !== "Trait") {
    throw new Error(`buildTraitSimData: expected <I c="Trait">, got "${tree.rootClass}".`);
  }

  // Build the SimDataSchema first (sorted alphabetically as S4S writes them).
  const schemaCols: SimDataSchemaColumn[] = TRAIT_COLUMNS
    .map((c) => new SimDataSchemaColumn(c.name, COLUMN_TO_DATATYPE[c.type], 0))
    .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  const schema = new SimDataSchema("Trait", TRAIT_SCHEMA_HASH, schemaCols);
  ctx.schemaCache.set("Trait", schema);

  // Pull tuning slots by name.
  const slots = childrenBySlot(tree.children);

  // Cells in arbitrary order; ObjectCell rows are keyed by column name.
  const row: Record<string, ObjectCell | NumberCell | BigIntCell | TextCell | ResourceKeyCell | VectorCell> = {};

  // -- Strings & STBL keys
  row["display_name"] = locKeyCell(slots.get("display_name"), ctx);
  row["trait_description"] = locKeyCell(slots.get("trait_description"), ctx);
  row["trait_origin_description"] = locKeyCell(slots.get("trait_origin_description"), ctx);
  // cas_idle_asm_state: EA writes "" when the tuning omits it.
  row["cas_idle_asm_state"] = stringCell(slots.get("cas_idle_asm_state"));
  // cas_trait_asm_param: EA's default is "None" — the literal string, not empty.
  // When the tuning omits the slot, EA writes the literal "None" from the TDESC.
  row["cas_trait_asm_param"] = stringCell(slots.get("cas_trait_asm_param"), "None");

  // -- ResourceKeys (default 0/0/0n)
  row["icon"] = resourceKeyCell(slots.get("icon"));
  row["cas_idle_asm_key"] = resourceKeyCell(slots.get("cas_idle_asm_key"));
  row["cas_selected_icon"] = resourceKeyCell(slots.get("cas_selected_icon"));

  // -- trait_type Int64. Mapped from the enum tuning value.
  const traitTypeText = textOf(slots.get("trait_type"));
  const traitType = TRAIT_TYPE_MAP[traitTypeText] ?? 0n;
  row["trait_type"] = new BigIntCell(DataType.Int64, traitType);

  // -- Vectors of Int64 (with enum-literal decoding so e.g. <E>TEEN</E> → 8n)
  row["ages"] = int64VectorFromList(slots.get("ages"));
  row["tags"] = int64VectorFromList(slots.get("tags"));
  row["genders"] = int64VectorFromList(slots.get("genders"));

  // -- Vector of trait references
  row["conflicting_traits"] = tableSetRefVector(slots.get("conflicting_traits"), ctx);

  const instance = SimDataInstance.fromObjectCell(
    tree.instanceName,
    new ObjectCell(schema, row),
  );

  return Object.freeze({
    version: 0x100,
    unused: 0,
    schemas: [schema],
    instances: [instance],
  });
}

// ---------------------------------------------------------------------------
// TDESC-style schema export — built by parsing the real EA Trait.tdesc.json
// fixture, then filtering to the 13-column EA-canonical allow-list that
// matches the current game version (schema_hash=0x992BFA76).
//
// The custom `buildTraitSimData` above is what actually emits the SimData; this
// export is for the registry/debugging path.
// ---------------------------------------------------------------------------

import { loadTdescFixture, selectColumns, withAdditionalColumns } from "./loadSchema.js";
import type { TdescColumn as _TdescColumn } from "../../tdesc/types.js";

// The 2 columns the TDESC lacks `export_modes` on (TunableSet/TunableTags
// without explicit export_modes) but are still persisted by EA per the binary
// fixture. We add them here with the inferred types.
//
// Note: `species` and `bb_filter_tags` were on the older s4tk fixture; the
// current EA Trait golden does NOT include them, so we don't add them.
const TRAIT_EXTRA_COLUMNS: readonly _TdescColumn[] = Object.freeze([
  { name: "ages", type: { kind: "vector", elem: { kind: "int64" } }, persistedToSimData: true },
  { name: "genders", type: { kind: "vector", elem: { kind: "int64" } }, persistedToSimData: true },
]);

export const TRAIT_TDESC_SCHEMA: TdescSchema = (() => {
  // First merge the TDESC-parsed schema with the two "extra" columns, then
  // filter to the 13 EA-canonical columns. `selectColumns` validates that all
  // 13 are present.
  const merged = withAdditionalColumns(loadTdescFixture("Trait.tdesc.json"), TRAIT_EXTRA_COLUMNS);
  return selectColumns(merged, TRAIT_COLUMNS.map((c) => c.name));
})();


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function childrenBySlot(children: readonly TuningNode[]): Map<string, TuningNode> {
  const out = new Map<string, TuningNode>();
  for (const c of children) {
    if ("name" in c && c.name) out.set(c.name, c);
  }
  return out;
}

function textOf(node: TuningNode | undefined): string {
  if (!node) return "";
  if (node.kind === "T" || node.kind === "E") return node.value;
  return "";
}

function locKeyCell(node: TuningNode | undefined, ctx: BuildContext): NumberCell {
  const raw = textOf(node);
  if (!raw) return new NumberCell(DataType.LocalizationKey, 0);
  const m = raw.match(/^0xTBD_STBL_KEY_(.+)$/);
  if (m) return new NumberCell(DataType.LocalizationKey, ctx.resolveStblKey(m[1]!));
  if (raw.startsWith("0x") || raw.startsWith("0X")) {
    return new NumberCell(DataType.LocalizationKey, parseInt(raw.slice(2), 16) >>> 0);
  }
  return new NumberCell(DataType.LocalizationKey, parseInt(raw, 10) >>> 0);
}

function stringCell(node: TuningNode | undefined, defaultValue: string = ""): TextCell {
  const v = textOf(node);
  return new TextCell(DataType.String, v !== "" ? v : defaultValue);
}

/**
 * EA rewrites the icon resource type 0x2F7D0004 → 0x00B2D882 when writing
 * SimData. See cells.ts for the rewrite table.
 */
const TRAIT_RESOURCE_TYPE_REWRITES: Readonly<Record<number, number>> = Object.freeze({
  0x2f7d0004: 0x00b2d882,
});

function resourceKeyCell(node: TuningNode | undefined): ResourceKeyCell {
  const raw = textOf(node).trim();
  if (!raw) return new ResourceKeyCell(0, 0, 0n);
  // Accept "TYPE-GROUP-INSTANCE16" or "TYPE:GROUP:INSTANCE16".
  const sep = raw.includes("-") ? "-" : raw.includes(":") ? ":" : null;
  if (sep) {
    const [t = "0", g = "0", i = "0"] = raw.split(sep);
    let type = parseInt(t, 16) >>> 0;
    const rewritten = TRAIT_RESOURCE_TYPE_REWRITES[type];
    if (rewritten !== undefined) type = rewritten;
    return new ResourceKeyCell(
      type,
      parseInt(g, 16) >>> 0,
      BigInt("0x" + i),
    );
  }
  return new ResourceKeyCell(0, 0, 0n);
}

function int64VectorFromList(node: TuningNode | undefined): VectorCell {
  if (!node || node.kind !== "L") return new VectorCell([]);
  const children: BigIntCell[] = [];
  for (const item of node.children) {
    const v = textOf(item);
    if (!v) continue;
    let val: bigint;
    if (v.startsWith("0x") || v.startsWith("0X")) {
      val = BigInt("0x" + v.slice(2));
    } else if (/^-?\d+$/.test(v)) {
      val = BigInt(v);
    } else {
      // Enum literal like <E>TEEN</E> — look up in the enum registry.
      val = decodeEnumLiteral(undefined, v);
    }
    children.push(new BigIntCell(DataType.Int64, val));
  }
  return new VectorCell(children);
}

function tableSetRefVector(node: TuningNode | undefined, ctx: BuildContext): VectorCell {
  if (!node || node.kind !== "L") return new VectorCell([]);
  const children: BigIntCell[] = [];
  for (const item of node.children) {
    const v = textOf(item).trim();
    if (!v) continue;
    let id: bigint;
    if (v.startsWith("0x") || v.startsWith("0X")) id = BigInt("0x" + v.slice(2));
    else if (/^\d+$/.test(v)) id = BigInt(v);
    else id = ctx.resolveTuningRef(v);
    children.push(new BigIntCell(DataType.TableSetReference, id));
  }
  return new VectorCell(children);
}

// Silence unused-import lint: buildCell, hashSchemaName may be needed if we
// extend the schema later. VariantCell is no longer used now that ui_category
// has been removed from the current-game schema.
void buildCell;
void hashSchemaName;
void VariantCell;
