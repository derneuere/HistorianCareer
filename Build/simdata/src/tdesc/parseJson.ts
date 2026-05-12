// parseTdescJson(jsonText) — pure transform from a TDESC JSON string to a
// frozen TdescSchema.
//
// TDESC JSON shape (`fast-xml-parser` convention; see docs/tdesc-format.md):
//
//   {
//     "TuningRoot": [{
//       ":@": { "class": "Foo", "module": "some.module", "muid": "..." , ... },
//       "Instance": [
//         {
//           ":@": { "name": "...", "class": "Tunable" | "TunableList" | ..., "type": "..." | "...", "export_modes": "client_binary,..." , ... },
//           "TunableEnum"|"TunableList"|"TunableTuple"|"TunableVariant"|... : [ children ]
//         },
//         ...
//       ]
//     }]
//   }
//
// Persistence rule (v0.3): a top-level tunable is persisted iff its
// `:@.export_modes` attribute is the *complete* triple
// `client_binary,server_binary,server_xml`. EA's exporter (per empirical
// comparison against 9 real EA SimData goldens) uses the presence of all three
// export modes — not just `client_binary` — to gate inclusion in SimData. The
// 14 tunables in our current TDESCs that have ONLY `client_binary`
// (build_buy_info, call_costar_interaction, …) are NOT persisted in EA's
// binaries; they're only `client_binary` because EA marked them for some
// future broadening that never landed in SimData. We use exact-match instead
// of substring to exclude them. See docs/tdesc-format.md for the empirical
// derivation.
//
// Per-class allow-lists (in `src/build/classes/schemas.ts`) provide an
// additional filter to handle (a) columns EA persists in older goldens that
// are missing from the current TDESC (e.g. Aspiration.disabled —
// AspirationBasic parent class field), and (b) columns the current TDESC
// added that aren't in our goldens (e.g. plumbob_vfx, cas_vfx on Buff).

import {
  deepFreeze,
  type TdescColumn,
  type TdescSchema,
  type TdescScalarKind,
  type TdescType,
  type TdescVariantCase,
} from "./types.js";

/**
 * Parses a TDESC JSON document and returns the resulting schema. The returned
 * object is recursively `Object.freeze`d.
 *
 * @throws If the document doesn't have the expected `TuningRoot[0]` shape.
 */
export function parseTdescJson(jsonText: string): TdescSchema {
  const doc = JSON.parse(jsonText);
  return parseTdescJsonObject(doc);
}

/**
 * Variant that accepts an already-parsed JSON object. Useful for tests that
 * want to mutate the input before parsing.
 */
export function parseTdescJsonObject(doc: unknown): TdescSchema {
  const root = readTuningRoot(doc);
  const rootAttrs = readAttrs(root);
  const className = readString(rootAttrs, "class");
  const modulePath = readString(rootAttrs, "module");
  if (!className) {
    throw new Error("TDESC parse: TuningRoot[0] is missing the 'class' attribute.");
  }
  const classPath = modulePath ? `${modulePath}.${className}` : className;

  const instances = readArray(root, "Instance");
  const rootColumns: TdescColumn[] = [];
  for (const inst of instances) {
    const col = parseTopLevelInstance(inst);
    if (col) rootColumns.push(col);
  }

  const schema: TdescSchema = {
    className,
    classPath,
    rootColumns,
  };
  return deepFreeze(schema);
}

// ---------------------------------------------------------------------------
// Top-level walk
// ---------------------------------------------------------------------------

/** Parse one top-level <Instance> entry into a TdescColumn. */
function parseTopLevelInstance(inst: unknown): TdescColumn | null {
  if (!isObject(inst)) return null;
  const attrs = readAttrs(inst);
  const name = readString(attrs, "name");
  if (!name) return null;
  // Skip "Deleted" placeholders — EA marks removed tunables with `Deleted: True`
  // (see AspirationCareer.do_not_register_events_on_load).
  if (readBoolean(attrs, "Deleted")) return null;

  const type = parseTunableType(inst, attrs);
  const defaultValue = parseDefault(attrs, type);
  const persistedToSimData = isPersisted(attrs);

  return {
    name,
    type,
    defaultValue,
    persistedToSimData,
  };
}

/**
 * Persistence rule. A top-level tunable is persisted iff its `export_modes`
 * attribute is the COMPLETE triple `client_binary,server_binary,server_xml`.
 * (See docs/tdesc-format.md for the empirical justification — short version:
 * EA's TDESCs mark some new columns as `client_binary` only, and those are
 * not actually persisted to the SimData binary.)
 */
const FULL_EXPORT_MODES = "client_binary,server_binary,server_xml";

function isPersisted(attrs: ReadonlyAttrs): boolean {
  const modes = readString(attrs, "export_modes");
  if (!modes) return false;
  // Parse as a comma-separated set so order doesn't matter.
  const parts = new Set(modes.split(",").map((s) => s.trim()));
  return (
    parts.has("client_binary") &&
    parts.has("server_binary") &&
    parts.has("server_xml")
  );
}

// Re-export the constant for tests and tooling that want to spot-check.
export { FULL_EXPORT_MODES };

// ---------------------------------------------------------------------------
// Type construction
// ---------------------------------------------------------------------------

/**
 * Map a JSON-encoded tunable (the parent node carrying `:@` attributes and a
 * type-keyed body) to a TdescType.
 */
function parseTunableType(node: unknown, attrs: ReadonlyAttrs): TdescType {
  const cls = readString(attrs, "class") ?? "Tunable";

  switch (cls) {
    case "Tunable":
      return parseScalarTunable(attrs);

    case "TunableLocalizedString":
      return { kind: "string-key" };

    case "TunableResourceKey":
    case "TunableIcon":
    case "TunableInteractionAsmResourceKey":
      return { kind: "resource-key" };

    case "TunableReference":
      return { kind: "table-set-reference" };

    case "TunableEnumEntry":
    case "TunableEnum":
      return parseEnum(node, attrs);

    case "TunableList":
    case "TunableSet":
      return parseList(node, attrs);

    case "TunableTags":
      // TunableTags is conceptually a set of int64 tag IDs.
      return { kind: "vector", elem: { kind: "int64" } };

    case "TunableTuple":
      return parseTuple(node, attrs);

    case "TunableVariant":
      return parseVariant(node, attrs);

    case "OptionalTunable":
      return parseOptional(node);

    case "TunableRange":
      // A scalar with min/max constraints; type comes from `:@.type`.
      return parseScalarTunable(attrs);

    case "TunableMapping": {
      // A dict mapping key→value. EA's SimData layer treats these as a vector
      // of tuples; we approximate with vector<object>. Empirically, EA names
      // the mapping element schema using the slot name (e.g. "aspirations" —
      // the same name as the parent column), NOT the TDESC's
      // `mapping_class` attribute. We default to the slot name.
      const keyType = parseMappingChild(node, attrs, "mapping_key");
      const valueType = parseMappingChild(node, attrs, "mapping_value");
      const schemaName =
        readString(attrs, "name") ??
        readString(attrs, "mapping_class") ??
        "Mapping";
      return {
        kind: "vector",
        elem: {
          kind: "object",
          schemaName,
          columns: [
            { name: "key", type: keyType, persistedToSimData: true },
            { name: "value", type: valueType, persistedToSimData: true },
          ],
        },
      };
    }

    case "TunableTestSet":
    case "TunableTestSetWithTooltip":
    case "TdescFragTag":
      // Test sets / fragments are tuning-only validation primitives; they have
      // no SimData representation. Surface as `string` so the persistence flag
      // (which is what gates emission) is the sole guard.
      return { kind: "string" };

    default:
      // Permissive fallback for EA's many TunableXxx wrapper classes. We treat
      // them as their inner structure when possible (one-child wrappers behave
      // like OptionalTunable), otherwise as opaque strings.
      return parseUnknownWrapper(node);
  }
}

/** Parse `Tunable` and `TunableRange` scalars by reading `:@.type`. */
function parseScalarTunable(attrs: ReadonlyAttrs): TdescType {
  const t = readString(attrs, "type") ?? "str";
  const kind = SCALAR_TYPE_TO_KIND[t];
  if (kind) return { kind };
  return { kind: "string" };
}

const SCALAR_TYPE_TO_KIND: Readonly<Record<string, TdescScalarKind>> = Object.freeze({
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
});

function parseEnum(_node: unknown, attrs: ReadonlyAttrs): TdescType {
  // Enum class name is in `:@.type` (e.g. "TraitType"); `:@.class` is
  // "TunableEnumEntry". The actual entries live in EA's Python source and
  // aren't enumerated in the TDESC (we'd need the corresponding
  // <static_entries> reference). For TDESC-driven builds, we map enum text
  // by position in the per-class enum-values list (see cells.ts).
  const enumName = readString(attrs, "type") ?? readString(attrs, "class") ?? "";
  return { kind: "enum", enumName, values: [] };
}

/** Parse TunableList / TunableSet: one inner element template. */
function parseList(node: unknown, attrs: ReadonlyAttrs): TdescType {
  // `fast-xml-parser` puts the body under a key matching the class name.
  // For TunableList: node.TunableList = [child0, child1, ...]
  // The first child is typically a <Tunable> (or another wrapper) describing
  // the element type.
  const cls = readString(attrs, "class") ?? "TunableList";
  const body = getBody(node, cls);
  if (body.length === 0) {
    // Empty list-of-strings as a permissive default.
    return { kind: "vector", elem: { kind: "string" } };
  }
  const innerNode = body[0];
  if (!innerNode || !isObject(innerNode)) {
    return { kind: "vector", elem: { kind: "string" } };
  }
  const innerAttrs = readAttrs(innerNode);
  const innerType = parseTunableType(innerNode, innerAttrs);
  return { kind: "vector", elem: innerType };
}

/** Parse TunableTuple: many sub-tunables. */
function parseTuple(node: unknown, attrs: ReadonlyAttrs): TdescType {
  const cls = readString(attrs, "class") ?? "TunableTuple";
  // Schema-name selection: prefer the EA-named class (e.g.
  // "TunableSubsetCompletionType") if it differs from the generic
  // "TunableTuple"; fall back to the slot `name` (e.g. "start_time"); fall
  // back to a generated name made from the field set.
  //
  // The naming matters because the build layer interns SimDataSchemas by
  // name — two distinct tuple types with the same name (e.g. two nested
  // anonymous TunableTuples) would clobber each other and cause row/column
  // mismatches at serialization time (see issue #10 CareerLevel crash).
  const columns: TdescColumn[] = [];
  for (const child of iterChildren(node, cls)) {
    if (!isObject(child)) continue;
    const childAttrs = readAttrs(child);
    const childName = readString(childAttrs, "name");
    if (!childName) continue;
    if (readBoolean(childAttrs, "Deleted")) continue;
    const childType = parseTunableType(child, childAttrs);
    columns.push({
      name: childName,
      type: childType,
      defaultValue: parseDefault(childAttrs, childType),
      // Inside a tuple, every named field is part of the tuple's structure.
      // The persistence flag is meaningful only at the top level (where it
      // gates SimData emission); inside a tuple we say "yes, this is part
      // of the tuple's schema".
      persistedToSimData: true,
    });
  }
  const schemaName = pickTupleSchemaName(attrs, cls, columns);
  return { kind: "object", schemaName, columns };
}

/**
 * Pick a unique-enough schema name for a TunableTuple. If `class` is the
 * generic "TunableTuple", we fall back to `name` and then to a name derived
 * from the column set so distinct anonymous tuples don't collide in the
 * SimData schema cache.
 */
function pickTupleSchemaName(
  attrs: ReadonlyAttrs,
  cls: string,
  columns: readonly TdescColumn[],
): string {
  // EA's named tuple classes (e.g. "TunableSubsetCompletionType",
  // "TunableScreenSlamKeyBased") get their class name. We only resort to slot
  // name + column-derived suffix for the generic "TunableTuple".
  if (cls && cls !== "TunableTuple") return cls;
  const slotName = readString(attrs, "name");
  if (slotName) return slotName;
  // Anonymous tuple — synthesize a name from the column set. This is stable
  // for the same set of columns (so duplicate tuples share a schema) but
  // distinguishes structurally-different tuples.
  if (columns.length === 0) return "AnonTuple";
  return "AnonTuple_" + columns.map((c) => c.name).join("_");
}

/** Parse TunableVariant: discriminated union of cases. */
function parseVariant(node: unknown, attrs: ReadonlyAttrs): TdescType {
  const variantName =
    readString(attrs, "class") ?? readString(attrs, "name") ?? "Variant";
  const cls = readString(attrs, "class") ?? "TunableVariant";
  const cases: TdescVariantCase[] = [];
  for (const child of iterChildren(node, cls)) {
    if (!isObject(child)) continue;
    const childAttrs = readAttrs(child);
    const caseName = readString(childAttrs, "name");
    if (!caseName) continue;
    // The "disabled" case is a TunableExistance sentinel — surface it as a
    // boolean placeholder so the variant has a slot for it.
    const childCls = readString(childAttrs, "class") ?? "Tunable";
    let caseType: TdescType;
    if (childCls === "TunableExistance") {
      caseType = { kind: "bool" };
    } else {
      caseType = parseTunableType(child, childAttrs);
    }
    cases.push({ name: caseName, type: caseType });
  }
  return { kind: "variant", variantName, cases };
}

/**
 * Parse OptionalTunable: pass through to the inner type. EA's tuning XML
 * encodes the "absent" state via a missing `<U>` or a `disabled` variant,
 * which the build layer handles by emitting defaults.
 */
function parseOptional(node: unknown): TdescType {
  // OptionalTunable's body has exactly one child wrapping the enabled value.
  // It's commonly under a `TunableVariant` (with `disabled` + `enabled` cases)
  // or directly a single Tunable.
  const wrapper = isObject(node) ? (node as Record<string, unknown>) : null;
  if (!wrapper) return { kind: "string" };
  for (const [key, val] of Object.entries(wrapper)) {
    if (key === ":@") continue;
    if (!Array.isArray(val)) continue;
    // Walk the array — usually one or two entries. Skip "disabled" sentinels.
    for (const child of val) {
      if (!isObject(child)) continue;
      const childAttrs = readAttrs(child);
      const childName = readString(childAttrs, "name");
      const childCls = readString(childAttrs, "class") ?? "";
      if (childCls === "TunableExistance") continue;
      if (childName === "disabled") continue;
      // For OptionalTunable wrapping a variant, parseTunableType yields a
      // variant type. For OptionalTunable wrapping a single Tunable, it
      // yields that Tunable's type. Either way, that's the "enabled" shape.
      return parseTunableType(child, childAttrs);
    }
  }
  return { kind: "string" };
}

/**
 * Read a TunableMapping's key or value column. Looks for the named child
 * under the node body and parses it as a tunable type.
 *
 * TunableMapping's body is `TunableList → [ TunableTuple → [key, value] ]`
 * (the mapping is conceptually a list of (key,value) tuples). We recurse
 * through that nested structure to find the named child.
 */
function parseMappingChild(node: unknown, attrs: ReadonlyAttrs, attrName: "mapping_key" | "mapping_value"): TdescType {
  // `:@.mapping_key` and `:@.mapping_value` name the inner field; the field
  // itself appears as a `<Tunable name="…">` in the body. We don't always
  // have these in the TDESC, so default to int64 (most common for tag keys).
  const childName = readString(attrs, attrName);
  if (!childName) return { kind: "int64" };
  const found = findNamedTunable(node, childName);
  return found ?? { kind: "int64" };
}

/**
 * Recursively search the body of a TDESC node for a child whose `:@.name`
 * matches the requested name. Returns the parsed type, or undefined if not
 * found. Used by parseMappingChild to dig through the TunableList → TunableTuple
 * nesting that TunableMapping bodies use.
 */
function findNamedTunable(node: unknown, name: string): TdescType | undefined {
  if (!isObject(node)) return undefined;
  for (const [key, val] of Object.entries(node)) {
    if (key === ":@") continue;
    if (!Array.isArray(val)) continue;
    for (const child of val) {
      if (!isObject(child)) continue;
      const childAttrs = readAttrs(child);
      if (readString(childAttrs, "name") === name) {
        return parseTunableType(child, childAttrs);
      }
      // Recurse into the body of this child.
      const inner = findNamedTunable(child, name);
      if (inner) return inner;
    }
  }
  return undefined;
}

/**
 * Permissive fallback for unrecognized wrapper classes. EA names many
 * single-purpose wrappers (`TunableScreenSlam`, `TunablePlayAudio`, …). We
 * treat them as opaque objects whose columns are whatever Tunables appear in
 * the body.
 */
function parseUnknownWrapper(node: unknown): TdescType {
  if (!isObject(node)) return { kind: "string" };
  const attrs = readAttrs(node);
  const cls = readString(attrs, "class") ?? "Wrapper";
  // Find the first array property (other than :@) and recurse into its
  // children, treating them as tuple-like fields.
  for (const [key, val] of Object.entries(node)) {
    if (key === ":@") continue;
    if (!Array.isArray(val)) continue;
    const columns: TdescColumn[] = [];
    for (const child of val) {
      if (!isObject(child)) continue;
      const childAttrs = readAttrs(child);
      const childName = readString(childAttrs, "name");
      if (!childName) continue;
      if (readBoolean(childAttrs, "Deleted")) continue;
      const childType = parseTunableType(child, childAttrs);
      columns.push({
        name: childName,
        type: childType,
        defaultValue: parseDefault(childAttrs, childType),
        persistedToSimData: true,
      });
    }
    if (columns.length > 0) {
      // Use the wrapper's class name for the schema (e.g.
      // "TunableWeeklySchedule") so distinct wrappers don't collide in the
      // schema cache. Fall back to the body-key tag if no class is provided.
      const schemaName = cls !== "Wrapper" ? cls : `Wrapper_${key}`;
      return { kind: "object", schemaName, columns };
    }
    return { kind: "string" };
  }
  return { kind: "string" };
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

function parseDefault(attrs: ReadonlyAttrs, type: TdescType): unknown {
  const raw = readString(attrs, "default");
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
      return Number.parseFloat(raw);
    case "string":
    case "hashed-string":
      // EA's TDESCs commonly mark `default="None"` for string Tunables, but
      // the actual EA SimData binary writes empty bytes when the tuning omits
      // the slot (verified against AspirationTrack.mood_asm_param,
      // Buff.timeout_string, …). So treat "None" as no default.
      if (raw === "None") return undefined;
      return raw;
    case "enum":
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
  if (t.startsWith("0x") || t.startsWith("0X")) return Number.parseInt(t.slice(2), 16);
  if (t === "None") return 0;
  const n = Number.parseInt(t, 10);
  return Number.isNaN(n) ? 0 : n;
}

function parseBigIntLiteral(s: string): bigint {
  const t = s.trim();
  if (t.startsWith("0x") || t.startsWith("0X")) return BigInt("0x" + t.slice(2));
  if (t === "None") return 0n;
  try {
    return BigInt(t);
  } catch {
    return 0n;
  }
}

// ---------------------------------------------------------------------------
// JSON node accessors — defensive helpers
// ---------------------------------------------------------------------------

/** The TDESC's `:@` attribute bag. Untyped at the JSON boundary. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ReadonlyAttrs = Readonly<Record<string, any>>;

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function readAttrs(node: unknown): ReadonlyAttrs {
  if (!isObject(node)) return {};
  const at = node[":@"];
  return isObject(at) ? (at as ReadonlyAttrs) : {};
}

function readString(attrs: ReadonlyAttrs, key: string): string | undefined {
  const v = attrs[key];
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return undefined;
}

function readBoolean(attrs: ReadonlyAttrs, key: string): boolean {
  const v = attrs[key];
  return v === true || v === "True" || v === "true" || v === "1";
}

function readArray(node: unknown, key: string): readonly unknown[] {
  if (!isObject(node)) return [];
  const v = node[key];
  return Array.isArray(v) ? v : [];
}

function readTuningRoot(doc: unknown): unknown {
  if (!isObject(doc)) throw new Error("TDESC parse: expected an object at the top level.");
  const arr = doc["TuningRoot"];
  if (!Array.isArray(arr) || arr.length === 0) {
    throw new Error("TDESC parse: expected `TuningRoot` to be a non-empty array.");
  }
  return arr[0];
}

/**
 * Get the body array under a node's class key (e.g. `node.TunableList`).
 * Falls back to scanning for any non-`:@` array property if the canonical
 * key isn't present (some serializers normalize differently).
 */
function getBody(node: unknown, expectedKey: string): readonly unknown[] {
  if (!isObject(node)) return [];
  const v = node[expectedKey];
  if (Array.isArray(v)) return v;
  // Fallback scan.
  for (const [k, val] of Object.entries(node)) {
    if (k === ":@") continue;
    if (Array.isArray(val)) return val;
  }
  return [];
}

/**
 * Iterate the body children of a node, defaulting to the canonical body key
 * but falling back to scanning if necessary.
 */
function iterChildren(node: unknown, expectedKey: string): readonly unknown[] {
  return getBody(node, expectedKey);
}
