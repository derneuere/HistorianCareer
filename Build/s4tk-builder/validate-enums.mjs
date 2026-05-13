// validate-enums.mjs — build-time assertion that <E n="…">VALUE</E> bodies in
// tuning XML are real members of EA's enum class for that field.
//
// Background (issue #17): EA's Tunable XML parser silently falls back to the
// enum's `default` value (typically the INVALID = 0 sentinel) when it
// encounters an unknown member name. Downstream code then evaluates the field
// against runtime data (e.g. `sim_info.age & aspiration_valid_age_type`),
// returns falsy, and the affected resource disappears from the relevant UI
// without ever surfacing an exception in `lastException.txt`.
//
// Our `Tuning/aspiration_HistorianCalling_T*.xml` files originally shipped
// `<E n="aspiration_valid_age_type">YAE_ONLY</E>`. `YAE_ONLY` is not a real
// member of `aspirations.aspiration_tuning.AspirationValidAgeType` (real
// members: INVALID, TODDLER_ONLY, CHILD_ONLY, TEEN_ONLY, TEEN_OR_OLDER). At
// game load it silently fell back to INVALID and the AspirationTrack was
// filtered out of the CAS picker, the age-up dialog, and the primary-
// aspiration fallback. See Docs/NOTE_aspiration_track_registration.md.
//
// To prevent the same class of silent-fallback bug from recurring, this
// module validates that every `<E n="<field>">` body whose field is in
// FIELD_ENUMS uses a known member name. Numeric bodies are allowed (the
// parser maps numeric strings via the underlying-int path), and `INVALID`
// is rejected explicitly — it's never what you want to ship.
//
// This is intentionally a partial table; only fields whose silent-fallback
// behavior we've burnt ourselves on get an entry. Adding a new field here
// requires knowing EA's real enum members for it (decompile the relevant
// `.pyc` and read `co_names`, as we did for AspirationValidAgeType).
//
// Pure: no I/O. Tested in validate-enums.test.mjs.

/**
 * Map<XML field name (the value of `n=` on `<E …>`), Set<allowed member names>>.
 *
 * Members come from EA's decompiled source (see comments below). INVALID is
 * never in the allowed set — if a tuning needs to opt out of an enum filter
 * the convention is to omit the field, not to write INVALID explicitly.
 */
export const FIELD_ENUMS = Object.freeze({
  // AspirationValidAgeType — see Docs/NOTE_aspiration_track_registration.md.
  // Class definition: simulation.zip!aspirations/aspiration_tuning.pyc.
  // Real co_names: INVALID, TODDLER_ONLY, CHILD_ONLY, TEEN_ONLY, TEEN_OR_OLDER.
  // INVALID (= 0) is the silent-fallback target — explicitly disallowed here.
  aspiration_valid_age_type: new Set([
    "TODDLER_ONLY",
    "CHILD_ONLY",
    "TEEN_ONLY",
    "TEEN_OR_OLDER",
  ]),
});

// `<E n="<field>"[...optional attrs...]>BODY</E>` — captures the field name
// from `n="..."` and the body. Multi-line bodies and attribute orderings are
// supported. We deliberately do NOT match `<E>` without an `n=` attribute,
// since those are positional enum refs (caught by the name-resolver pass).
const E_FIELD_RE = /<E\s+[^>]*\bn="([^"]+)"[^>]*>([\s\S]*?)<\/E>/g;

const NUMERIC_RE = /^\s*(?:0[xX][0-9a-fA-F]+|-?[0-9]+)\s*$/;

/**
 * Scan one XML body for `<E n="<field>">VALUE</E>` violations.
 *
 * Returns an array of `{ field, value }` for each disallowed value found.
 * Numeric bodies (e.g. `<E n="…">8</E>`) are skipped — EA's parser maps
 * those via the underlying-int path and they don't trigger the
 * silent-fallback bug this validator is designed to catch. (We still
 * recommend named members for readability, but it's not a build error.)
 *
 * @param {string} xml
 * @returns {{ field: string, value: string }[]}
 */
export function findInvalidEnumValues(xml) {
  const violations = [];
  let m;
  // Reset regex state between calls (the regex object is shared / module-level).
  E_FIELD_RE.lastIndex = 0;
  while ((m = E_FIELD_RE.exec(xml)) !== null) {
    const field = m[1];
    const allowed = FIELD_ENUMS[field];
    if (!allowed) continue; // not a tracked field
    const value = m[2].trim();
    if (value === "") continue; // empty body — different concern, not ours
    if (NUMERIC_RE.test(value)) continue; // numeric literal — bypasses name lookup
    if (!allowed.has(value)) {
      violations.push({ field, value });
    }
  }
  return violations;
}

/**
 * Validate every XML in a file map. Throws on the first file that contains
 * disallowed enum values; the error message lists every violation in that
 * file (so a multi-typo run still surfaces them all together).
 *
 * @param {Iterable<[string, string]>} xmlEntries  Iterable of [filename, xml].
 * @throws {Error} if any file has a disallowed `<E n="…">` value.
 */
export function assertKnownEnumValues(xmlEntries) {
  /** @type {{ file: string, field: string, value: string }[]} */
  const allViolations = [];
  for (const [file, xml] of xmlEntries) {
    for (const v of findInvalidEnumValues(xml)) {
      allViolations.push({ file, ...v });
    }
  }
  if (allViolations.length === 0) return;

  const lines = allViolations.map(({ file, field, value }) => {
    const allowed = [...FIELD_ENUMS[field]].sort().join(", ");
    return (
      `  ${file}: <E n="${field}">${value}</E> — '${value}' is not a known ` +
      `member of EA's enum for this field. Allowed: ${allowed}.`
    );
  });
  throw new Error(
    `assertKnownEnumValues: ${allViolations.length} disallowed enum value(s) ` +
      `found. At XML load time EA's Tunable parser silently falls back to the ` +
      `enum default (typically INVALID = 0) on an unknown member name, which ` +
      `causes the affected resource to disappear from runtime UI without an ` +
      `exception (issue #17). Fix:\n${lines.join("\n")}`,
  );
}
