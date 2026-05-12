// parseTdesc(xml) — pure transform from a TDESC XML string to a frozen TdescSchema.
//
// TDESC format reference: ../../docs/tdesc-format.md. Briefly:
//
//   <TDescDoc>
//     <Class name="Foo" path="some.module.Foo">
//       <Tunable name="...">
//         <TunableExport simdata="True" />
//         <TunableDescription text="..." />
//         <!-- type-specific children, e.g. enum entries or tuple subtunables -->
//       </Tunable>
//       ...
//     </Class>
//   </TDescDoc>
//
// We deliberately accept a generous subset: anything we don't recognize becomes
// an `Undefined`-typed scalar so the parser never throws on a real EA TDESC we
// haven't covered. The build layer is the one that hard-errors on unsupported
// types; the parser is permissive.

import { XmlDocumentNode } from "@s4tk/xml-dom";
import type { XmlNode } from "@s4tk/xml-dom";
import {
  deepFreeze,
  type TdescColumn,
  type TdescSchema,
  type TdescScalarKind,
  type TdescType,
  type TdescVariantCase,
} from "./types.js";

/**
 * Parses a TDESC XML document and returns the resulting schema. The returned
 * object is recursively `Object.freeze`d.
 *
 * @throws If the document has no `<TDescDoc>`/`<Class>` root pair.
 */
export function parseTdesc(xml: string): TdescSchema {
  const doc = XmlDocumentNode.from(xml, { ignoreComments: true });
  const root = doc.child;
  if (!root) throw new Error("TDESC parse: empty document.");

  const rootTag = root.tag;
  // EA's tag is "TDescDoc"; S4S sometimes emits "TdescDoc" or simply "Class".
  if (rootTag !== "TDescDoc" && rootTag !== "TdescDoc" && rootTag !== "Class") {
    throw new Error(`TDESC parse: expected root <TDescDoc>, got <${rootTag}>.`);
  }

  const classNode =
    rootTag === "Class" ? root : root.children.find((c) => c.tag === "Class");
  if (!classNode) throw new Error("TDESC parse: no <Class> element.");

  const className = classNode.attributes["name"] ?? "";
  const classPath = classNode.attributes["path"] ?? "";
  if (!className) throw new Error("TDESC parse: <Class> is missing name attribute.");

  const rootColumns: TdescColumn[] = [];
  for (const child of classNode.children) {
    if (child.tag === "Tunable") {
      rootColumns.push(parseTunable(child));
    }
    // ignore <Class>-level <TunableDescription>, comments, etc.
  }

  const schema: TdescSchema = {
    className,
    classPath,
    rootColumns,
  };

  return deepFreeze(schema);
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Parse one <Tunable name="..." type="..." ...> element into a TdescColumn. */
function parseTunable(node: XmlNode): TdescColumn {
  const name = node.attributes["name"] ?? "";
  if (!name) throw new Error("TDESC parse: <Tunable> missing name attribute.");

  const type = parseTunableType(node);

  const defaultValue = parseDefault(node, type);
  const persistedToSimData = readSimDataExportFlag(node);

  return {
    name,
    type,
    defaultValue,
    persistedToSimData,
  };
}

/**
 * Detects whether a <Tunable> is marked for SimData export.
 *
 * The convention is documented in `docs/tdesc-format.md`. Briefly:
 *   - Explicit: a child `<TunableExport simdata="True" />` says YES.
 *   - Explicit: a child `<TunableExport simdata="False" />` says NO.
 *   - Implicit (no <TunableExport>): YES by default for top-level tunables.
 *     This matches the observed behavior of EA's SimData exporter for the
 *     classes in scope. The build layer will defer to the per-class hand-
 *     authored schema where this heuristic is wrong.
 */
function readSimDataExportFlag(node: XmlNode): boolean {
  if (!node.hasChildren) return true;
  for (const child of node.children) {
    if (child.tag !== "TunableExport") continue;
    const raw = child.attributes["simdata"];
    if (raw === undefined) continue;
    return raw === "True" || raw === "true" || raw === "1";
  }
  return true;
}

/** Read the optional default= attribute on a <Tunable> and coerce it. */
function parseDefault(node: XmlNode, type: TdescType): unknown {
  const raw = node.attributes["default"];
  if (raw === undefined) return undefined;

  switch (type.kind) {
    case "bool":
      return raw === "True" || raw === "true" || raw === "1";
    case "int8":
    case "uint8":
    case "int16":
    case "uint16":
    case "int32":
    case "uint32":
    case "string-key":
      return parseIntegerLiteral(raw);
    case "int64":
    case "uint64":
    case "table-set-reference":
      return parseBigIntLiteral(raw);
    case "float":
      return parseFloat(raw);
    case "string":
    case "hashed-string":
      return raw;
    case "enum":
      return raw;
    case "resource-key":
      return raw;
    case "object":
    case "variant":
    case "vector":
    case "float2":
    case "float3":
    case "float4":
      return undefined;
  }
}

function parseIntegerLiteral(s: string): number {
  const t = s.trim();
  if (t.startsWith("0x") || t.startsWith("0X")) return parseInt(t.slice(2), 16);
  return parseInt(t, 10);
}

function parseBigIntLiteral(s: string): bigint {
  const t = s.trim();
  if (t.startsWith("0x") || t.startsWith("0X")) return BigInt("0x" + t.slice(2));
  return BigInt(t);
}

/** Top-level dispatcher: read `type=` and `class=` and recurse. */
function parseTunableType(node: XmlNode): TdescType {
  const tdescType = node.attributes["type"] ?? "Tunable";
  switch (tdescType) {
    case "Tunable":
      return parseTunableScalar(node);
    case "TunableLocalizedString":
      return { kind: "string-key" };
    case "TunableResourceKey":
      return { kind: "resource-key" };
    case "TunableReference":
      return { kind: "table-set-reference" };
    case "TunableEnumEntry":
    case "TunableEnum":
      return parseEnum(node);
    case "TunableList":
      return parseList(node);
    case "TunableTuple":
      return parseTuple(node);
    case "TunableVariant":
      return parseVariant(node);
    case "OptionalTunable":
      return parseOptional(node);
    default:
      // Permissive fallback. The build layer will refuse to emit this if it
      // appears on a column we attempt to export.
      return { kind: "string" };
  }
}

/** Map a TDESC "class" attribute (for scalar Tunables) to our kind. */
function parseTunableScalar(node: XmlNode): TdescType {
  const cls = node.attributes["class"] ?? "str";
  const kind = scalarKindFromClass(cls);
  return { kind };
}

const SCALAR_CLASS_TO_KIND: Readonly<Record<string, TdescScalarKind>> = Object.freeze({
  bool: "bool",
  Boolean: "bool",
  int: "int32",
  int32: "int32",
  Int32: "int32",
  uint: "uint32",
  uint32: "uint32",
  UInt32: "uint32",
  int8: "int8",
  Int8: "int8",
  uint8: "uint8",
  UInt8: "uint8",
  int16: "int16",
  Int16: "int16",
  uint16: "uint16",
  UInt16: "uint16",
  int64: "int64",
  Int64: "int64",
  uint64: "uint64",
  UInt64: "uint64",
  float: "float",
  Single: "float",
  Float: "float",
  str: "string",
  string: "string",
  String: "string",
  HashedString: "hashed-string",
});

function scalarKindFromClass(cls: string): TdescScalarKind {
  return SCALAR_CLASS_TO_KIND[cls] ?? "string";
}

function parseEnum(node: XmlNode): TdescType {
  const enumName = node.attributes["class"] ?? node.attributes["enum_name"] ?? "";
  const values: string[] = [];
  if (node.hasChildren) {
    for (const child of node.children) {
      // EA's TDESC uses <EnumValue name="..."/> children; S4S sometimes uses
      // <EnumItem>. Accept both.
      if (child.tag === "EnumValue" || child.tag === "EnumItem") {
        const v = child.attributes["name"];
        if (v) values.push(v);
      }
    }
  }
  return { kind: "enum", enumName, values };
}

function parseList(node: XmlNode): TdescType {
  // TunableList has exactly one inner <Tunable> describing its value template.
  let inner: TdescType = { kind: "string" };
  if (node.hasChildren) {
    for (const child of node.children) {
      if (child.tag === "Tunable" || child.tag === "TunableList") {
        // Use the inner element's type, ignoring its name.
        inner = parseTunableType(child);
        break;
      }
    }
  }
  return { kind: "vector", elem: inner };
}

function parseTuple(node: XmlNode): TdescType {
  const schemaName = node.attributes["class"] ?? node.attributes["name"] ?? "Tuple";
  const columns: TdescColumn[] = [];
  if (node.hasChildren) {
    for (const child of node.children) {
      if (child.tag === "Tunable") columns.push(parseTunable(child));
    }
  }
  return { kind: "object", schemaName, columns };
}

function parseVariant(node: XmlNode): TdescType {
  const variantName = node.attributes["class"] ?? node.attributes["name"] ?? "Variant";
  const cases: TdescVariantCase[] = [];
  if (node.hasChildren) {
    for (const child of node.children) {
      if (child.tag === "Tunable") {
        const name = child.attributes["name"] ?? "";
        if (!name) continue;
        cases.push({ name, type: parseTunableType(child) });
      }
    }
  }
  return { kind: "variant", variantName, cases };
}

function parseOptional(node: XmlNode): TdescType {
  // OptionalTunable has one inner Tunable describing the value when present.
  // We pass through to the inner type; nullability is implicit via the
  // tuning XML omitting the value.
  if (node.hasChildren) {
    for (const child of node.children) {
      if (child.tag === "Tunable") return parseTunableType(child);
    }
  }
  return { kind: "string" };
}
