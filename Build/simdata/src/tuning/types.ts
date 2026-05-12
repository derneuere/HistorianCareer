// Tuning XML tree types. The Sims 4 tuning XML grammar is small but uses one-letter
// element tags for compactness, so we mirror those tags as discriminator strings.
//
// Tag legend (per EA's xml_tuning module):
//   <I>  Instance — the root element of a tuning file. Carries `c=` (class), `i=` (i-attr),
//        `n=` (instance name), `s=` (instance id as decimal), and `m=` (module path).
//   <T>  Tunable — a leaf scalar/value, with an optional `n=` for its slot.
//   <E>  Enum literal — same shape as <T> but the value is an enum name (e.g. "ADULT").
//   <V>  Variant — has `t=` (variant case tag) and exactly one named child for that case.
//   <U>  Tuple/tuple-like aggregate — children are slot-named <T>/<U>/<V>/<L>/<E>s.
//   <L>  List — children are unnamed (positional) items of the same type.
//
// Nodes with `n=` slot names are addressed by name from their parent. List children
// have no `n=`.

/**
 * A generic node in a tuning tree.
 */
export type TuningNode =
  | TuningTNode
  | TuningENode
  | TuningVNode
  | TuningUNode
  | TuningLNode;

/** <T n="..."?>value</T> — a scalar/leaf value as a string. */
export interface TuningTNode {
  readonly kind: "T";
  readonly name?: string;
  /** Raw textual value. Empty string if the element is self-closing. */
  readonly value: string;
}

/** <E n="..."?>EnumName</E>. */
export interface TuningENode {
  readonly kind: "E";
  readonly name?: string;
  readonly value: string;
}

/**
 * <V n="..."? t="case">…</V>. The child is the named tunable corresponding to the case,
 * or `undefined` if the variant is "enabled but empty" (e.g. `<V t="enabled"/>`).
 */
export interface TuningVNode {
  readonly kind: "V";
  readonly name?: string;
  readonly variantTag: string;
  readonly child?: TuningNode;
}

/** <U n="..."?>…</U>. Named children. */
export interface TuningUNode {
  readonly kind: "U";
  readonly name?: string;
  readonly children: readonly TuningNode[];
}

/** <L n="..."?>…</L>. Unnamed children. */
export interface TuningLNode {
  readonly kind: "L";
  readonly name?: string;
  readonly children: readonly TuningNode[];
}

/** A parsed tuning XML file. */
export interface TuningTree {
  /** Value of the `c=` attribute on the root <I>, e.g. "Trait", "Career". */
  readonly rootClass: string;
  /** Value of the `i=` attribute on the root <I>, e.g. "trait", "career". */
  readonly rootKind: string;
  /** Value of the `n=` attribute (the tuning instance name). */
  readonly instanceName: string;
  /** Value of the `s=` attribute parsed as a bigint. `0n` if absent or "TBD_INSTANCE_ID". */
  readonly instanceId: bigint;
  /** Value of the `m=` attribute, the Python module path. May be empty. */
  readonly modulePath: string;
  /** Top-level slot-named children of <I>. */
  readonly children: readonly TuningNode[];
}
