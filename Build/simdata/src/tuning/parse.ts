// parseTuning(xml) — convert a tuning XML string into a TuningTree.
//
// The tuning XML grammar is small (see ./types.ts). This module is a thin walker
// over `@s4tk/xml-dom`: we parse the document, then translate XmlNode → TuningNode
// preserving only what the build layer needs.
//
// PRE-PROCESSING: tuning XMLs in our repo contain placeholders like
// `s="TBD_INSTANCE_ID"` and STBL key tokens like `0xTBD_STBL_KEY_X`. The parser
// treats these uniformly:
//   - `s="TBD_INSTANCE_ID"` → instanceId = 0n.
//   - `0xTBD_STBL_KEY_*` inside a <T> value is preserved as the raw string; the
//     build layer is responsible for resolving it.
//
// Pure function: no I/O, no globals, no time/random.

import { XmlDocumentNode } from "@s4tk/xml-dom";
import type { XmlNode } from "@s4tk/xml-dom";
import { deepFreeze } from "../tdesc/types.js";
import type {
  TuningNode,
  TuningTree,
  TuningTNode,
  TuningENode,
  TuningVNode,
  TuningUNode,
  TuningLNode,
} from "./types.js";

/** Parse a tuning XML string into an immutable TuningTree. */
export function parseTuning(xml: string): TuningTree {
  const doc = XmlDocumentNode.from(xml, { ignoreComments: true });
  const root = doc.child;
  if (!root) throw new Error("parseTuning: empty document.");
  if (root.tag !== "I") {
    throw new Error(`parseTuning: expected root <I>, got <${root.tag}>.`);
  }

  const rootClass = root.attributes["c"] ?? "";
  const rootKind = root.attributes["i"] ?? "";
  const instanceName = root.attributes["n"] ?? "";
  const modulePath = root.attributes["m"] ?? "";
  const instanceId = parseInstanceId(root.attributes["s"]);

  const children: TuningNode[] = [];
  if (root.hasChildren) {
    for (const c of root.children) {
      const node = mapNode(c);
      if (node) children.push(node);
    }
  }

  const tree: TuningTree = {
    rootClass,
    rootKind,
    instanceName,
    instanceId,
    modulePath,
    children,
  };

  return deepFreeze(tree);
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

function parseInstanceId(raw: string | undefined): bigint {
  if (!raw) return 0n;
  const trimmed = raw.trim();
  if (!trimmed || trimmed === "TBD_INSTANCE_ID") return 0n;
  if (trimmed.startsWith("0x") || trimmed.startsWith("0X")) {
    return BigInt("0x" + trimmed.slice(2));
  }
  return BigInt(trimmed);
}

/**
 * Translate one DOM node into a TuningNode. Returns `undefined` for
 * unhandled tag types (comments, processing instructions). Throws if
 * the document contains something we genuinely don't recognize.
 */
function mapNode(node: XmlNode): TuningNode | undefined {
  switch (node.tag) {
    case "T":
      return mapT(node);
    case "E":
      return mapE(node);
    case "V":
      return mapV(node);
    case "U":
      return mapU(node);
    case "L":
      return mapL(node);
    case undefined:
    case "":
      // Value or comment node at the top level — ignore.
      return undefined;
    default:
      // Unknown tag. Tuning XML shouldn't contain anything else, but be
      // forgiving: skip it. (We could throw; for v0.1 we choose mercy.)
      return undefined;
  }
}

function mapT(node: XmlNode): TuningTNode {
  return {
    kind: "T",
    ...(node.attributes["n"] !== undefined ? { name: node.attributes["n"]! } : {}),
    value: extractTextValue(node),
  };
}

function mapE(node: XmlNode): TuningENode {
  return {
    kind: "E",
    ...(node.attributes["n"] !== undefined ? { name: node.attributes["n"]! } : {}),
    value: extractTextValue(node),
  };
}

function mapV(node: XmlNode): TuningVNode {
  const variantTag = node.attributes["t"] ?? "";
  let childNode: TuningNode | undefined;
  if (node.hasChildren) {
    for (const c of node.children) {
      const mapped = mapNode(c);
      if (mapped) {
        childNode = mapped;
        break;
      }
    }
  }
  return {
    kind: "V",
    ...(node.attributes["n"] !== undefined ? { name: node.attributes["n"]! } : {}),
    variantTag,
    ...(childNode !== undefined ? { child: childNode } : {}),
  };
}

function mapU(node: XmlNode): TuningUNode {
  const children: TuningNode[] = [];
  if (node.hasChildren) {
    for (const c of node.children) {
      const mapped = mapNode(c);
      if (mapped) children.push(mapped);
    }
  }
  return {
    kind: "U",
    ...(node.attributes["n"] !== undefined ? { name: node.attributes["n"]! } : {}),
    children,
  };
}

function mapL(node: XmlNode): TuningLNode {
  const children: TuningNode[] = [];
  if (node.hasChildren) {
    for (const c of node.children) {
      const mapped = mapNode(c);
      if (mapped) children.push(mapped);
    }
  }
  return {
    kind: "L",
    ...(node.attributes["n"] !== undefined ? { name: node.attributes["n"]! } : {}),
    children,
  };
}

/**
 * A leaf <T>/<E> can be self-closing (empty), have a value-only child, or have
 * an explicit text child. We collapse all forms to a single string.
 */
function extractTextValue(node: XmlNode): string {
  if (!node.hasChildren) return "";
  // The xml-dom library wraps text content in value nodes; node.innerValue is
  // a setter/getter that returns the value of the first child if any.
  // It can also be a number/bigint; coerce to string.
  const inner = node.innerValue;
  if (inner === undefined || inner === null) return "";
  return String(inner);
}

// ---------------------------------------------------------------------------
// Convenience helpers exported for the build layer.
// ---------------------------------------------------------------------------

/**
 * Find the top-level child of a tuning tree with the given slot name.
 * Returns `undefined` if not present.
 */
export function findChildByName(
  tree: TuningTree | TuningUNode | TuningVNode,
  slotName: string,
): TuningNode | undefined {
  const children =
    "children" in tree
      ? tree.children
      : tree.child !== undefined
      ? [tree.child]
      : [];
  for (const child of children) {
    if ("name" in child && child.name === slotName) return child;
  }
  return undefined;
}
