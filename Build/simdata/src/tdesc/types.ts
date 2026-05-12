// TDESC schema types. See ../../docs/tdesc-format.md for the rationale behind these
// names and the mapping to EA's TDESC XML.
//
// All schemas are immutable. After `parseTdesc()` returns, the object is `Object.freeze()`d
// recursively so downstream code (build/, emit/) cannot mutate the schema.

/**
 * A primitive scalar kind. Maps directly onto `@s4tk/models`'s DataType enum at
 * the build/emit boundary.
 */
export type TdescScalarKind =
  | "bool"
  | "int8"
  | "uint8"
  | "int16"
  | "uint16"
  | "int32"
  | "uint32"
  | "int64"
  | "uint64"
  | "float"
  | "string"
  | "hashed-string"
  | "string-key" // STBL key — stored as uint32 LocalizationKey in SimData
  | "resource-key" // TGI triple — stored as 16-byte ResourceKey in SimData
  | "table-set-reference" // 64-bit instance ID — stored as TableSetReference (uint64) in SimData
  | "float2"
  | "float3"
  | "float4";

/**
 * A type in the TDESC schema. Tagged union; `kind` selects the shape.
 *
 * Recursive shapes (object/vector/variant) carry their own substructure.
 */
export type TdescType =
  | { readonly kind: TdescScalarKind }
  | { readonly kind: "enum"; readonly enumName: string; readonly values: readonly string[] }
  | { readonly kind: "object"; readonly schemaName: string; readonly columns: readonly TdescColumn[] }
  | { readonly kind: "vector"; readonly elem: TdescType }
  | { readonly kind: "variant"; readonly variantName: string; readonly cases: readonly TdescVariantCase[] };

/** One case of a TunableVariant. */
export interface TdescVariantCase {
  readonly name: string; // the case tag — matches `t=` on a tuning <V> node
  readonly type: TdescType;
}

/** One column / field in a TDESC class. */
export interface TdescColumn {
  /** Matches the `n=` attribute on the corresponding tuning <T>/<V>/<U>/<L>. */
  readonly name: string;
  readonly type: TdescType;
  /**
   * The default value if the tuning XML omits this field. May be `undefined`
   * if the TDESC didn't specify one. The shape depends on `type`:
   * - bool/scalar: a JS primitive
   * - enum: the string value (the enum literal name)
   * - vector: an empty array (the only sensible vector default)
   * - object/variant: `null` (treated as "absent")
   * - resource-key / table-set-reference / string-key: 0 / 0n / "0:0:0"
   */
  readonly defaultValue?: unknown;
  /**
   * True iff this column is exported into SimData. See
   * docs/tdesc-format.md for the rules around this flag.
   */
  readonly persistedToSimData: boolean;
}

/** The parsed TDESC for one tuning class. */
export interface TdescSchema {
  /** The tuning class name, e.g. "Trait", "Career", "CareerLevel". */
  readonly className: string;
  /** The fully-qualified Python path, e.g. "traits.traits.Trait" (may be empty). */
  readonly classPath: string;
  /**
   * Columns of this class in the order EA declared them. The build layer
   * sorts them alphabetically by `name` before emitting (SimData convention),
   * so this order is informational only.
   */
  readonly rootColumns: readonly TdescColumn[];
}

/**
 * Deep-freezes a value (the freeze stops at primitives/Buffer/Date instances).
 * Internal helper for the parser to make the returned schema immutable.
 */
export function deepFreeze<T>(value: T): T {
  if (value === null || typeof value !== "object") return value;
  if (Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const key of Object.keys(value)) {
    deepFreeze((value as Record<string, unknown>)[key]);
  }
  return value;
}
