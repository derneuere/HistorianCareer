// Cell factories — convert (TdescType, TuningNode | undefined) → a `@s4tk/models` Cell.
//
// This is the heart of the build layer. It is pure: same inputs always produce
// the same Cell. Inputs that the schema declares as required but are missing
// in the tuning XML fall back to the default value (column.defaultValue or a
// type-appropriate zero).
//
// Boundary: this file is the ONLY place outside `emit/` that touches
// `@s4tk/models` cell classes.

import {
  BooleanCell,
  NumberCell,
  BigIntCell,
  TextCell,
  ResourceKeyCell,
  ObjectCell,
  VectorCell,
  VariantCell,
  Float2Cell,
  Float3Cell,
  Float4Cell,
  Cell,
} from "@s4tk/models/lib/resources/simdata/cells.js";
// DataType is a TypeScript enum with a `export default`. With NodeNext + CJS,
// the safest cross-runtime import is the named export from `@s4tk/models/enums`.
import { DataType } from "@s4tk/models/enums.js";
import {
  SimDataSchema,
  SimDataSchemaColumn,
} from "@s4tk/models/lib/resources/simdata/fragments.js";
import { fnv32 } from "@s4tk/hashing/hashing.js";
import type { TdescType, TdescColumn } from "../tdesc/types.js";
import type { TuningNode, TuningLNode, TuningUNode, TuningVNode } from "../tuning/types.js";
import type { BuildContext } from "./types.js";

// ---------------------------------------------------------------------------
// Hashing helpers
// ---------------------------------------------------------------------------

/**
 * Hash a column or schema name as EA's SimData binary format expects.
 * EA uses FNV-32 with the high bit forced to 1 (0x80000000). Crucially:
 * `>>> 0` reinterprets the bit pattern as an unsigned 32-bit number so
 * the serializer (which writes via `BinaryEncoder.uint32`) accepts it.
 */
export function hashColumnName(name: string): number {
  return (fnv32(name) | 0x80000000) >>> 0;
}

/**
 * Compute the schema hash. EA uses FNV-32 of the schema NAME with the high
 * bit set. This is what S4S puts in the `schema_hash` attribute of a
 * <Schema> element.
 */
export function hashSchemaName(name: string): number {
  return (fnv32(name) | 0x80000000) >>> 0;
}

/**
 * Compute a variant case hash. The `<V t="case">` tag is hashed with FNV-32
 * (no high-bit) to produce the `typeHash` on VariantCell. Note: this matches
 * S4S behavior; it's the same hash function as column names but WITHOUT the
 * high-bit OR.
 */
export function hashVariantTag(tag: string): number {
  return fnv32(tag);
}

// ---------------------------------------------------------------------------
// Schema construction
// ---------------------------------------------------------------------------

/**
 * Build a `SimDataSchema` from a list of `TdescColumn`s. Each column's type
 * is mapped to a `DataType`, then a `SimDataSchemaColumn` is created. Columns
 * are sorted by name (the EA/S4S convention for in-file column order).
 *
 * Schemas are interned in the build context by name so that recursive
 * structures (and multiple instances of the same Tuple) share the same
 * SimDataSchema object.
 */
export function buildSchema(
  name: string,
  columns: readonly TdescColumn[],
  ctx: BuildContext,
): SimDataSchema {
  const cached = ctx.schemaCache.get(name);
  if (cached) return cached;

  const schemaColumns: SimDataSchemaColumn[] = [];
  // Sort by name for byte-identical S4S behavior.
  const sortedColumns = [...columns]
    .filter((c) => c.persistedToSimData)
    .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));

  for (const col of sortedColumns) {
    const dataType = tdescTypeToDataType(col.type);
    schemaColumns.push(new SimDataSchemaColumn(col.name, dataType, 0));
  }

  const hash =
    ctx.knownSchemaHashes?.[name] !== undefined
      ? ctx.knownSchemaHashes[name]! >>> 0
      : hashSchemaName(name);
  const schema = new SimDataSchema(name, hash, schemaColumns);
  ctx.schemaCache.set(name, schema);
  return schema;
}

/** Map a TDESC type kind onto the upstream DataType enum value. */
export function tdescTypeToDataType(t: TdescType): DataType {
  switch (t.kind) {
    case "bool":
      return DataType.Boolean;
    case "int8":
      return DataType.Int8;
    case "uint8":
      return DataType.UInt8;
    case "int16":
      return DataType.Int16;
    case "uint16":
      return DataType.UInt16;
    case "int32":
      return DataType.Int32;
    case "uint32":
      return DataType.UInt32;
    case "int64":
      return DataType.Int64;
    case "uint64":
      return DataType.UInt64;
    case "float":
      return DataType.Float;
    case "string":
      return DataType.String;
    case "hashed-string":
      return DataType.HashedString;
    case "string-key":
      return DataType.LocalizationKey;
    case "resource-key":
      return DataType.ResourceKey;
    case "table-set-reference":
      return DataType.TableSetReference;
    case "float2":
      return DataType.Float2;
    case "float3":
      return DataType.Float3;
    case "float4":
      return DataType.Float4;
    case "enum":
      // EA stores enum values as Int64 in SimData (see s4tk test data:
      // trait.xml's `<L name="species"><T type="Int64">1</T></L>`).
      return DataType.Int64;
    case "object":
      return DataType.Object;
    case "vector":
      return DataType.Vector;
    case "variant":
      return DataType.Variant;
  }
}

// ---------------------------------------------------------------------------
// Cell construction
// ---------------------------------------------------------------------------

/**
 * Build a Cell for the given column from the matching tuning node (which
 * may be `undefined` if the tuning XML omitted the slot — we fall back to
 * the default).
 */
export function buildCell(
  column: TdescColumn,
  node: TuningNode | undefined,
  ctx: BuildContext,
): Cell {
  return buildCellFromType(column.type, node, column.defaultValue, ctx);
}

/**
 * Lower-level: build a Cell from a TdescType (no defaultValue carried by
 * the type itself). The caller supplies a default if it has one.
 */
export function buildCellFromType(
  type: TdescType,
  node: TuningNode | undefined,
  defaultValue: unknown,
  ctx: BuildContext,
): Cell {
  switch (type.kind) {
    case "bool":
      return new BooleanCell(coerceBool(textValue(node), defaultValue));
    case "int8":
      return new NumberCell(DataType.Int8, coerceNumber(type, textValue(node), defaultValue));
    case "uint8":
      return new NumberCell(DataType.UInt8, coerceNumber(type, textValue(node), defaultValue));
    case "int16":
      return new NumberCell(DataType.Int16, coerceNumber(type, textValue(node), defaultValue));
    case "uint16":
      return new NumberCell(DataType.UInt16, coerceNumber(type, textValue(node), defaultValue));
    case "int32":
      return new NumberCell(DataType.Int32, coerceNumber(type, textValue(node), defaultValue));
    case "uint32":
      return new NumberCell(DataType.UInt32, coerceNumber(type, textValue(node), defaultValue));
    case "float":
      return new NumberCell(DataType.Float, coerceNumber(type, textValue(node), defaultValue));
    case "int64":
      return new BigIntCell(DataType.Int64, coerceBigInt(textValue(node), defaultValue));
    case "uint64":
      return new BigIntCell(DataType.UInt64, coerceBigInt(textValue(node), defaultValue));
    case "table-set-reference": {
      // The tuning value is either a tuning name (string, e.g. "career_track_Adult_Historian"),
      // an instance ID literal (decimal or 0x…), or empty (→ 0).
      const v = textValue(node);
      const id =
        v.length > 0
          ? resolveTuningRef(v, ctx)
          : coerceBigInt("", defaultValue);
      return new BigIntCell(DataType.TableSetReference, id);
    }
    case "string":
      return new TextCell(DataType.String, coerceString(textValue(node), defaultValue));
    case "hashed-string":
      return new TextCell(DataType.HashedString, coerceString(textValue(node), defaultValue));
    case "string-key": {
      // STBL key — uint32. Tuning value is one of:
      //   - "0xDEADBEEF"     -> parsed as hex
      //   - "0xTBD_STBL_KEY_FOO" -> resolved via ctx.resolveStblKey
      //   - "12345"          -> parsed as decimal
      //   - ""               -> default (0)
      const v = textValue(node);
      const key = v.length > 0 ? resolveStblKey(v, ctx) : coerceNumber({ kind: "uint32" }, "", defaultValue);
      return new NumberCell(DataType.LocalizationKey, key);
    }
    case "resource-key": {
      const v = textValue(node);
      const { type: t, group, instance } = parseResourceKey(v, defaultValue, ctx);
      return new ResourceKeyCell(t, group, instance);
    }
    case "float2": {
      const [x, y] = parseFloatList(textValue(node), 2);
      return new Float2Cell(x ?? 0, y ?? 0);
    }
    case "float3": {
      const [x, y, z] = parseFloatList(textValue(node), 3);
      return new Float3Cell(x ?? 0, y ?? 0, z ?? 0);
    }
    case "float4": {
      const [x, y, z, w] = parseFloatList(textValue(node), 4);
      return new Float4Cell(x ?? 0, y ?? 0, z ?? 0, w ?? 0);
    }
    case "enum": {
      // EA stores enums as Int64. We need a value lookup table; for v0.1 we
      // accept the textual enum name and map it to its index in `type.values`.
      // The real EA encoding uses the integer value declared in the Python
      // enum, which we don't have access to without the source — so we use
      // the index as a best-effort. Per-class schemas can override with a
      // custom builder when needed.
      const v = textValue(node);
      const idx = type.values.indexOf(v);
      const value = BigInt(idx >= 0 ? idx : 0);
      return new BigIntCell(DataType.Int64, value);
    }
    case "object": {
      const schema = ctx.schemaCache.get(type.schemaName)
        ?? (() => {
          // Materialize the schema on first use, but only with persisted columns.
          return registerObjectSchema(type.schemaName, type.columns, ctx);
        })();
      const row: Record<string, Cell> = {};
      const childNodes = collectNamedChildren(node);
      for (const col of type.columns) {
        if (!col.persistedToSimData) continue;
        const childNode = childNodes.get(col.name);
        row[col.name] = buildCell(col, childNode, ctx);
      }
      return new ObjectCell(schema, row);
    }
    case "vector": {
      // The list children are unnamed.
      const list = collectListChildren(node);
      const children: Cell[] = [];
      for (const item of list) {
        children.push(buildCellFromType(type.elem, item, undefined, ctx));
      }
      return new VectorCell(children);
    }
    case "variant": {
      // Variant tunings look like <V n="x" t="case"><…/></V>. The build
      // dispatches on `variantTag` and produces a single child cell.
      if (!node || node.kind !== "V") {
        // Empty variant — emit a 0 typeHash with a placeholder child.
        return new VariantCell(0, new BooleanCell(false));
      }
      const tag = node.variantTag;
      const matchedCase = type.cases.find((c) => c.name === tag);
      const childCell = matchedCase
        ? buildCellFromType(matchedCase.type, node.child, undefined, ctx)
        : new BooleanCell(false);
      return new VariantCell(hashVariantTag(tag), childCell);
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers — text extraction and coercion
// ---------------------------------------------------------------------------

function textValue(node: TuningNode | undefined): string {
  if (!node) return "";
  if (node.kind === "T" || node.kind === "E") return node.value;
  return "";
}

function coerceBool(raw: string, def: unknown): boolean {
  if (raw === "") return typeof def === "boolean" ? def : false;
  return raw === "True" || raw === "true" || raw === "1";
}

function coerceNumber(type: TdescType, raw: string, def: unknown): number {
  if (raw === "") {
    if (typeof def === "number") return def;
    return 0;
  }
  const trimmed = raw.trim();
  if (trimmed.startsWith("0x") || trimmed.startsWith("0X")) {
    return parseInt(trimmed.slice(2), 16);
  }
  if (type.kind === "float") return parseFloat(trimmed);
  return parseInt(trimmed, 10);
}

function coerceBigInt(raw: string, def: unknown): bigint {
  if (raw === "") {
    if (typeof def === "bigint") return def;
    if (typeof def === "number") return BigInt(def);
    return 0n;
  }
  const trimmed = raw.trim();
  if (trimmed.startsWith("0x") || trimmed.startsWith("0X")) {
    return BigInt("0x" + trimmed.slice(2));
  }
  return BigInt(trimmed);
}

function coerceString(raw: string, def: unknown): string {
  if (raw === "") return typeof def === "string" ? def : "";
  return raw;
}

/**
 * Parse a STBL key value as found in tuning XML. Supported forms:
 *   "0xDEADBEEF"          → 0xDEADBEEF
 *   "0xTBD_STBL_KEY_FOO"  → ctx.resolveStblKey("FOO")  (drops the prefix)
 *   "12345"               → 12345
 */
function resolveStblKey(raw: string, ctx: BuildContext): number {
  const m = raw.match(/^0xTBD_STBL_KEY_(.+)$/);
  if (m) return ctx.resolveStblKey(m[1]!);
  if (raw.startsWith("0x") || raw.startsWith("0X")) {
    return parseInt(raw.slice(2), 16) >>> 0;
  }
  return parseInt(raw, 10) >>> 0;
}

/**
 * Parse a tuning reference (the raw text of a tuning `<T>` whose value is a
 * tuning name like "loot.buff_Focused_Low", "career_track_Adult_Historian",
 * "12345", or "0x…"). Returns the 64-bit instance ID.
 */
function resolveTuningRef(raw: string, ctx: BuildContext): bigint {
  const trimmed = raw.trim();
  if (!trimmed) return 0n;
  if (trimmed.startsWith("0x") || trimmed.startsWith("0X")) {
    return BigInt("0x" + trimmed.slice(2));
  }
  // Pure integer literal — return as-is.
  if (/^\d+$/.test(trimmed)) return BigInt(trimmed);
  return ctx.resolveTuningRef(trimmed);
}

/**
 * Parse a resource key. EA's tuning XML stores them as strings; the SimData
 * XML stores them as "TYPE-GROUP-INSTANCE16" (hyphen-separated hex). Tuning
 * keys can be:
 *   - "TYPE:GROUP:INSTANCE"  (the s4tk-builder convention, hex parts)
 *   - "00B2D882-00000000-DEADBEEFCAFEBABE"  (S4S XML SimData convention)
 *   - "loot.foo"             (a tuning name — type/group inferred from class)
 *   - ""                     (use default; zero key)
 */
function parseResourceKey(
  raw: string,
  def: unknown,
  ctx: BuildContext,
): { type: number; group: number; instance: bigint } {
  if (!raw) {
    if (typeof def === "string" && def.length > 0) raw = def;
    else return { type: 0, group: 0, instance: 0n };
  }

  if (ctx.resolveResourceKey) {
    try {
      return ctx.resolveResourceKey(raw);
    } catch {
      /* fall through to default parsing */
    }
  }

  const cleaned = raw.trim();
  if (cleaned.includes("-")) {
    const [t, g, i] = cleaned.split("-");
    return {
      type: parseInt(t ?? "0", 16) >>> 0,
      group: parseInt(g ?? "0", 16) >>> 0,
      instance: BigInt("0x" + (i ?? "0")),
    };
  }
  if (cleaned.includes(":")) {
    const [t, g, i] = cleaned.split(":");
    return {
      type: parseInt(t ?? "0", 16) >>> 0,
      group: parseInt(g ?? "0", 16) >>> 0,
      instance: BigInt("0x" + (i ?? "0")),
    };
  }
  // Unknown / plain name — return a zero key. The caller (per-class builder)
  // may have a better strategy (e.g., resolve via the tuning name).
  return { type: 0, group: 0, instance: 0n };
}

function parseFloatList(raw: string, n: number): number[] {
  if (!raw) return new Array(n).fill(0);
  return raw.split(",").map((s) => parseFloat(s.trim()));
}

/**
 * Group children of a U/V node by their `n=` slot name.
 */
function collectNamedChildren(node: TuningNode | undefined): Map<string, TuningNode> {
  const out = new Map<string, TuningNode>();
  if (!node) return out;
  let children: readonly TuningNode[] = [];
  if (node.kind === "U") children = (node as TuningUNode).children;
  else if (node.kind === "V" && (node as TuningVNode).child)
    children = [(node as TuningVNode).child!];
  for (const c of children) {
    if ("name" in c && c.name) out.set(c.name, c);
  }
  return out;
}

/** Get the unnamed children of an L node. */
function collectListChildren(node: TuningNode | undefined): TuningNode[] {
  if (!node) return [];
  if (node.kind !== "L") return [];
  return [...(node as TuningLNode).children];
}

/**
 * Build an ObjectCell's schema from inline TdescColumn declarations, interning
 * it in the context cache. Used by nested object construction.
 */
function registerObjectSchema(
  schemaName: string,
  columns: readonly TdescColumn[],
  ctx: BuildContext,
): SimDataSchema {
  return buildSchema(schemaName, columns, ctx);
}
