// Trait — hand-authored schema for the `Trait` tuning class.
//
// Source: `Trait.NOTES.md` in this directory documents what we learned and from
// where. The schema hash `0xDE2EAF66` is the EA-canonical hash (extracted from
// the binary in `reference/s4tk-models/test/data/simdatas/binary/trait.simdata`).
//
// We override the generic build with a custom function that handles the
// `trait_type` enum-to-Int64 mapping (PERSONALITY=0, GAMEPLAY=1, HIDDEN=2 per
// EA observation) and provides correct defaults for the 17 columns even when
// the tuning XML omits most of them.

import { deepFreeze } from "../../tdesc/types.js";
import type { TdescSchema } from "../../tdesc/types.js";
import type { TuningTree, TuningNode } from "../../tuning/types.js";
import type { BuildContext, SimDataIR } from "../types.js";
import { buildCell, hashSchemaName } from "../cells.js";
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
 * EA-canonical Trait schema hash. Extracted from the EA binary.
 * If you change column membership, this must change too.
 */
const TRAIT_SCHEMA_HASH = 0xde2eaf66;

/** Schema in the order EA's binary uses. */
const TRAIT_COLUMNS: readonly TdescColumnDef[] = Object.freeze([
  { name: "ages", type: "Vector" },
  { name: "bb_filter_styles", type: "Vector" },
  { name: "bb_filter_tags", type: "Vector" },
  { name: "cas_idle_asm_key", type: "ResourceKey" },
  { name: "cas_idle_asm_state", type: "String" },
  { name: "cas_selected_icon", type: "ResourceKey" },
  { name: "cas_trait_asm_param", type: "String" },
  { name: "conflicting_traits", type: "Vector" },
  { name: "display_name", type: "LocalizationKey" },
  { name: "genders", type: "Vector" },
  { name: "icon", type: "ResourceKey" },
  { name: "species", type: "Vector" },
  { name: "tags", type: "Vector" },
  { name: "trait_description", type: "LocalizationKey" },
  { name: "trait_origin_description", type: "LocalizationKey" },
  { name: "trait_type", type: "Int64" },
  { name: "ui_category", type: "Variant" },
]);

interface TdescColumnDef {
  readonly name: string;
  readonly type:
    | "Vector"
    | "ResourceKey"
    | "String"
    | "LocalizationKey"
    | "Int64"
    | "Variant";
}

const COLUMN_TO_DATATYPE: Readonly<Record<TdescColumnDef["type"], DataType>> = Object.freeze({
  Vector: DataType.Vector,
  ResourceKey: DataType.ResourceKey,
  String: DataType.String,
  LocalizationKey: DataType.LocalizationKey,
  Int64: DataType.Int64,
  Variant: DataType.Variant,
});

const TRAIT_TYPE_MAP: Readonly<Record<string, bigint>> = Object.freeze({
  PERSONALITY: 0n,
  GAMEPLAY: 1n,
  HIDDEN: 2n,
  // EA also defines NPC=3, CAREER=4, BONUS=5 etc; if/when needed add here.
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
  const row: Record<string, ObjectCell | NumberCell | BigIntCell | TextCell | ResourceKeyCell | VectorCell | VariantCell> = {};

  // -- Strings & STBL keys
  row["display_name"] = locKeyCell(slots.get("display_name"), ctx);
  row["trait_description"] = locKeyCell(slots.get("trait_description"), ctx);
  row["trait_origin_description"] = locKeyCell(slots.get("trait_origin_description"), ctx);
  row["cas_idle_asm_state"] = stringCell(slots.get("cas_idle_asm_state"));
  row["cas_trait_asm_param"] = stringCell(slots.get("cas_trait_asm_param"));

  // -- ResourceKeys (default 0/0/0n)
  row["icon"] = resourceKeyCell(slots.get("icon"));
  row["cas_idle_asm_key"] = resourceKeyCell(slots.get("cas_idle_asm_key"));
  row["cas_selected_icon"] = resourceKeyCell(slots.get("cas_selected_icon"));

  // -- trait_type Int64. Mapped from the enum tuning value.
  const traitTypeText = textOf(slots.get("trait_type"));
  const traitType = TRAIT_TYPE_MAP[traitTypeText] ?? 0n;
  row["trait_type"] = new BigIntCell(DataType.Int64, traitType);

  // -- Vectors of Int64
  row["ages"] = int64VectorFromList(slots.get("ages"));
  row["species"] = int64VectorFromList(slots.get("species"));
  row["tags"] = int64VectorFromList(slots.get("tags"));
  row["genders"] = int64VectorFromList(slots.get("genders"));

  // -- Empty vectors (filter style/tag — typically empty in tuning)
  row["bb_filter_styles"] = new VectorCell([]);
  row["bb_filter_tags"] = new VectorCell([]);

  // -- Vector of trait references
  row["conflicting_traits"] = tableSetRefVector(slots.get("conflicting_traits"), ctx);

  // -- ui_category: Variant with int64 child. EA tags the variant with
  //    a per-class hash (0x603EAA6C for the default category). When the
  //    tuning XML doesn't specify it, we emit a no-op variant.
  row["ui_category"] = buildUiCategoryVariant(slots.get("ui_category"));

  const instance = SimDataInstance.fromObjectCell(
    tree.instanceName,
    new ObjectCell(schema, row),
  );

  return Object.freeze({
    version: 0x101,
    unused: 0,
    schemas: [schema],
    instances: [instance],
  });
}

// ---------------------------------------------------------------------------
// TDESC-style schema export — built by parsing the real EA Trait.tdesc.json
// fixture, then filtering to the 17-column EA-canonical allow-list that
// matches the s4tk-models EA binary fixture (schema_hash=0xDE2EAF66).
//
// The custom `buildTraitSimData` above is what actually emits the SimData; this
// export is for the registry/debugging path.
// ---------------------------------------------------------------------------

import { loadTdescFixture, selectColumns, withAdditionalColumns } from "./loadSchema.js";
import type { TdescColumn as _TdescColumn } from "../../tdesc/types.js";

// The 4 columns the TDESC lacks `export_modes` on (TunableSet/TunableTags
// without explicit export_modes) but are still persisted by EA per the binary
// fixture. We add them here with the inferred types.
const TRAIT_EXTRA_COLUMNS: readonly _TdescColumn[] = Object.freeze([
  { name: "ages", type: { kind: "vector", elem: { kind: "int64" } }, persistedToSimData: true },
  { name: "bb_filter_tags", type: { kind: "vector", elem: { kind: "int64" } }, persistedToSimData: true },
  { name: "genders", type: { kind: "vector", elem: { kind: "int64" } }, persistedToSimData: true },
  { name: "species", type: { kind: "vector", elem: { kind: "int64" } }, persistedToSimData: true },
]);

export const TRAIT_TDESC_SCHEMA: TdescSchema = (() => {
  // First merge the TDESC-parsed schema with the four "extra" columns, then
  // filter to the 17 EA-canonical columns. `selectColumns` validates that all
  // 17 are present.
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

function stringCell(node: TuningNode | undefined): TextCell {
  return new TextCell(DataType.String, textOf(node));
}

function resourceKeyCell(node: TuningNode | undefined): ResourceKeyCell {
  const raw = textOf(node).trim();
  if (!raw) return new ResourceKeyCell(0, 0, 0n);
  // Accept "TYPE-GROUP-INSTANCE16" or "TYPE:GROUP:INSTANCE16".
  const sep = raw.includes("-") ? "-" : raw.includes(":") ? ":" : null;
  if (sep) {
    const [t = "0", g = "0", i = "0"] = raw.split(sep);
    return new ResourceKeyCell(
      parseInt(t, 16) >>> 0,
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
    const val =
      v.startsWith("0x") || v.startsWith("0X")
        ? BigInt("0x" + v.slice(2))
        : BigInt(parseInt(v, 10));
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

/** The EA variant tag for the default ui_category. */
const UI_CATEGORY_DEFAULT_TAG = 0x603eaa6c;

function buildUiCategoryVariant(node: TuningNode | undefined): VariantCell {
  // Default: variant with tag 0x603EAA6C wrapping an Int64(0).
  if (!node) {
    return new VariantCell(UI_CATEGORY_DEFAULT_TAG, new BigIntCell(DataType.Int64, 0n));
  }
  // Variant tunings look like <V n="ui_category" t="…"><T type="Int64">N</T></V>.
  // For trait we accept the variant tag from the tuning if present; otherwise
  // default.
  if (node.kind !== "V") {
    return new VariantCell(UI_CATEGORY_DEFAULT_TAG, new BigIntCell(DataType.Int64, 0n));
  }
  const inner = node.child;
  const v = inner ? textOf(inner) : "0";
  const value = v.startsWith("0x") ? BigInt("0x" + v.slice(2)) : BigInt(parseInt(v, 10));
  // Variant tag: use the EA-default if the tuning hasn't specified an override.
  const tag = node.variantTag
    ? hashSchemaName(node.variantTag) >>> 0
    : UI_CATEGORY_DEFAULT_TAG;
  return new VariantCell(tag, new BigIntCell(DataType.Int64, value));
}

// Silence unused-import lint: buildCell may be needed if we extend the schema later.
void buildCell;
