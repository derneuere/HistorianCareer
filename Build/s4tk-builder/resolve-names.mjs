// resolve-names.mjs — build-time tuning name → decimal instance-ID resolver.
//
// Background (per issue #15): named tuning references like
//   <T n="pie_menu_category">HC_PieMenuCategory_Historian</T>
//   <T>HC_Loot_Add_HistorianLevel_Small</T>
// don't reliably resolve at game runtime — some names hash to a value Sims 4
// finds; others fail silently. The robust workaround is to write the decimal
// instance ID directly. To keep source XML readable, we do that swap at build
// time instead of by hand.
//
// This module exposes two pure functions:
//
//   collectTuningNames(xmlContentsByFile) -> Map<name, bigint>
//     Pass 1. Walks every root <I … n="<name>" s="<id>" …> across all XMLs.
//     For each tuning, records the canonical instance ID:
//       - if s= is a numeric placeholder ("TBD_INSTANCE_ID"-style), use fnv64(name, true)
//       - if s= is a decimal/hex literal, use that (source of truth)
//       - if s= is missing, fall back to fnv64(name, true)
//
//   resolveNamesInXml(xml, nameMap, opts) -> { xml, warnings }
//     Pass 2. Replaces every <T>NAME</T> / <E>NAME</E> body (with or without an
//     n="..." attribute) whose inner text exactly matches a known tuning name
//     with the decimal instance ID. Numeric bodies are left alone. Unknown
//     names that LOOK like HC_-prefixed tuning refs emit a warning.
//
// The module is dependency-light on purpose so it can be unit-tested in
// isolation (see resolve-names.test.mjs).

import { fnv64 } from "@s4tk/hashing/hashing.js";

// Pattern that matches our project-owned tuning names. Anything we emit lives
// under one of these prefixes today; adjust if new top-level naming families
// are introduced.
const HC_NAME_PREFIXES = [
  "HC_",
  "career_",
  "aspiration_",
  "objective_HC_",
  "trait_HabilitationRenown",
];

// Looks like a (decimal or 0x-hex) numeric body? If yes, never touch it.
const NUMERIC_RE = /^\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)\s*$/;

// True when a name looks like it should be one of *our* tunings (project
// prefix or hand-listed match). Used only for the "did you forget to add
// this XML?" warning — never for replacement decisions.
function looksLikeHCName(name) {
  return HC_NAME_PREFIXES.some((p) => name === p || name.startsWith(p));
}

// Permissive: pull n="..." and s="..." from an <I ...> attribute string.
function parseRootAttrs(attrString) {
  const out = {};
  const re = /(\w+)="([^"]*)"/g;
  let m;
  while ((m = re.exec(attrString)) !== null) {
    out[m[1]] = m[2];
  }
  return out;
}

/**
 * Pass 1: collect every tuning's canonical instance ID from a set of XMLs.
 *
 * @param {Iterable<[string, string]>} xmlEntries  Iterable of [filename, xml] pairs.
 * @returns {Map<string, bigint>} name → instance ID
 */
export function collectTuningNames(xmlEntries) {
  const nameToInstance = new Map();
  for (const [file, xml] of xmlEntries) {
    const rootMatch = xml.match(/<I\s+([^>]+)>/);
    if (!rootMatch) continue;
    const attrs = parseRootAttrs(rootMatch[1]);
    const tuningName = attrs.n;
    if (!tuningName) continue;

    let instance;
    const sAttr = attrs.s;
    if (sAttr && /^[0-9]+$/.test(sAttr)) {
      // s= is a real decimal literal — that's the source of truth.
      instance = BigInt(sAttr);
    } else if (sAttr && /^0[xX][0-9a-fA-F]+$/.test(sAttr)) {
      instance = BigInt(sAttr);
    } else {
      // s= is "TBD_INSTANCE_ID" or missing → compute from the name.
      instance = fnv64(tuningName, true);
    }

    if (nameToInstance.has(tuningName)) {
      const prev = nameToInstance.get(tuningName);
      if (prev !== instance) {
        throw new Error(
          `collectTuningNames: ${file} re-defines '${tuningName}' with a different instance ID ` +
            `(prev=${prev.toString()} new=${instance.toString()})`,
        );
      }
    }
    nameToInstance.set(tuningName, instance);
  }
  return nameToInstance;
}

/**
 * Pass 2: replace tuning-name references in a single XML body with the
 * canonical decimal instance ID.
 *
 * Handles these body shapes:
 *   <T>HC_Loot_*</T>                     -- bare list member
 *   <E>SOMETHING</E>                     -- enum-style ref by name
 *   <T n="pie_menu_category">HC_*</T>    -- named reference field
 *   <E n="something">HC_*</E>            -- named enum-ref field
 *
 * @param {string} xml
 * @param {Map<string, bigint>} nameToInstance
 * @param {{ file?: string }} [opts]
 * @returns {{ xml: string, warnings: string[] }}
 */
export function resolveNamesInXml(xml, nameToInstance, opts = {}) {
  const warnings = [];
  const file = opts.file ?? "<inline>";

  // Match <T>BODY</T> or <T n="...">BODY</T> (same for <E>). BODY captures a
  // single token with no whitespace and no angle brackets — i.e. a name like
  // HC_Loot_X or a numeric literal. We deliberately keep the open-tag intact
  // (any attributes preserved) and only swap the inner text.
  //
  // We do NOT match <T n="...">...</T> when BODY is empty or contains spaces;
  // that filters out things like <T n="display_name">0xTBD_STBL_KEY_FOO</T>'s
  // post-resolved form (the body has 0x… digits, which NUMERIC_RE catches) and
  // any prose / multi-token values.
  const elementRe = /(<(T|E)(\s+[^>]*)?>)([^<>\s]+)(<\/\2>)/g;

  const out = xml.replace(elementRe, (match, open, _tag, _attrs, body, close) => {
    const trimmed = body.trim();
    if (trimmed === "") return match;
    if (NUMERIC_RE.test(trimmed)) return match; // already a literal — leave it
    const id = nameToInstance.get(trimmed);
    if (id !== undefined) {
      return `${open}${id.toString()}${close}`;
    }
    // Not a known name. Warn if it *looks* like one of ours that we should
    // recognize but don't — usually means a missing XML or a typo.
    if (looksLikeHCName(trimmed)) {
      warnings.push(
        `${file}: <${_tag}>${trimmed}</${_tag}> looks like an HC tuning ref ` +
          `but no matching XML was found — left as-is.`,
      );
    }
    return match;
  });

  return { xml: out, warnings };
}
