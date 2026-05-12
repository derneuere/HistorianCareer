# XML Fixes — issues #4 and #2

This branch fixes the legacy field names in the HistorianCareer tuning XMLs
(issue #4) and investigates the canonical name of the Discover University
History-degree trait (issue #2).

The audit ran each Layer B tuning XML's `<T n="…">` / `<E n="…">` /
`<L n="…">` / `<V n="…">` / `<U n="…">` field names against the canonical
TDESC fixtures in `Build/simdata/test/fixtures/tdescs/*.tdesc.json` and the
real EA goldens in `Build/simdata/test/golden/*/`. Anything that wasn't in
the TDESC's top-level `:@.name` set (or in the EA golden) was treated as a
legacy/wrong name and renamed.

## Issue #4 — field-name fixes per file

### Class / module path renames

The `c="…"` (class) and `m="…"` (module) attributes on the root `<I>` element
were normalised to the EA-canonical values, taken from the EA goldens in
`Build/simdata/test/golden/`:

| File | Before | After |
|---|---|---|
| `career_track_Adult_Historian.xml` | `c="CareerTrack" m="careers.career_track"` | `c="TunableCareerTrack" m="careers.career_tuning"` |
| `career_Adult_Historian.xml` | `m="careers.career_tuning"` | unchanged (already correct) |
| `career_level_Adult_Historian_L{1..5}.xml` | `m="careers.career_level"` | `m="careers.career_tuning"` |
| `aspiration_HistorianCalling_T{1..4}.xml` | `m="aspirations.aspiration"` | `m="aspirations.aspiration_tuning"` |
| `aspiration_career_Historian_L{1..5}.xml` | `m="aspirations.aspiration"` | `m="aspirations.aspiration_tuning"` |
| `aspiration_track_HistorianCalling.xml` | `i="aspiration" m="aspirations.aspiration_track"` | `i="aspiration_track" m="aspirations.aspiration_tuning"` |
| `objective_HC_*.xml` | `m="aspirations.aspiration_objective"` | `m="event_testing.objective_tuning"` |
| `trait_HabilitationRenown.xml` | `m="traits.traits"` | unchanged (already correct) |

### Field renames (per `<T n="…">`)

| File(s) | Old name | New name |
|---|---|---|
| `aspiration_track_HistorianCalling.xml` | `aspiration_category` | `category` (issue #4 explicit) |
| `career_level_Adult_Historian_L{1..5}.xml` | `level_title` | `title` (issue #4 explicit) |
| `career_level_Adult_Historian_L{1..5}.xml` | `level_description` | `title_description` |
| `career_level_Adult_Historian_L{1..5}.xml` | `level_aspiration` | `aspiration` |
| `aspiration_HistorianCalling_T{1..4}.xml` | `display_description` | `descriptive_text` (per Aspiration TDESC) |
| `aspiration_HistorianCalling_T4.xml` | `complete_loot_actions` | `on_complete_loot_actions` |
| `objective_HC_*.xml` | `goal_value` (TunableVariant with `absolute`) | `objective_completion_type` (TunableVariant with `iterations` / `iterations_required_to_pass`) |
| `objective_HC_*.xml` | `objective_test t="interaction_run_test"` | `objective_test t="ran_interaction_test"` |
| `trait_HabilitationRenown.xml` | `<T n="trait_type">…</T>` | `<E n="trait_type">…</E>` (TunableEnumEntry must use `<E>`) |
| `career_Adult_Historian.xml` | `<T n="career_category">…</T>` | `<E n="career_category">…</E>` (TunableEnumEntry) |
| `career_Adult_Historian.xml` | `career_availability_test` (single test, wrong field name) | `career_availablity_tests` (EA's canonical name — note the EA typo, missing the second 'i') with a `List of List of <V t="trait">` shape per the Teen_Retail golden |

### Fields moved between resources (Career → Track)

Per the EA Career TDESC and the `career_Teen_Retail` golden, a Career resource
does **not** carry the player-facing display name and description; those live
on the CareerTrack. Moved out of `career_Adult_Historian.xml` into
`career_track_Adult_Historian.xml`:

- `career_name`
- `career_description`

### Fields removed (not valid on the resource per TDESC)

These were legacy/guessed names with no corresponding field in the TDESC's
top-level set. Removing them is the safest minimum-surgical change — the
simdata library was silently dropping them on emit, but they made the XML
misleading.

- `career_Adult_Historian.xml`:
  - `ages` (Career has no ages field; ages are gated through availability tests
    or via career events that bind to age-restricted aspirations)
  - `career_messages` (the inner `career_message_*` names like
    `career_message_join_career` etc. are not TDESC field names; the real
    `career_messages` is a TunableTuple of named entries like
    `join_career_notification`, `demote_career_notification`, etc. — see
    the Teen_Retail golden; rewiring to that shape is a v0.2 polish item)
  - `retirement_rewards` (no such field on Career TDESC)
- `career_level_Adult_Historian_L{1..5}.xml`:
  - `outfit` (`work_outfit` is the canonical name and uses a tuple shape;
    omitting it makes the level inherit default outfits)
  - `gameplay_unlocks` (no such field; per-level unlocks are wired through
    `super_affordances` or via traits granted on `promotion_reward`)
  - `work_performance_progress_per_completion` (not a CareerLevel field; the
    closest match is `performance_per_completed_goal`, but it's nested inside
    `performance_metrics`)
  - `promotion_test` (CareerLevel has no promotion_test field — skill gates
    live on the Career resource under `block_promotion_tests`)
- `aspiration_career_Historian_L{1..5}.xml`:
  - `display_name`, `display_description` (AspirationCareer's display fields
    live nested under the `_display_data` OptionalTunable variant, not at
    root — and EA's own AspirationCareer goldens don't tune them at all; the
    player sees the parent CareerLevel's `title`/`title_description`)
- `trait_HabilitationRenown.xml`:
  - `is_personality_trait` (no such field; `trait_type=GAMEPLAY` is the
    canonical signal for a non-personality trait)

## Verification

```powershell
powershell -ExecutionPolicy Bypass -File Build/build.ps1 -LayerB -PackageOnly
```

Currently produces **60 resources** (24 Layer B with SimData + 10 Layer A +
2 STBLs + 24 Layer B tuning XMLs… wait the math is: 34 tuning XMLs +
24 SimData + 2 STBL = 60). The drop from the original 61 is solely because
`career_track_Adult_Historian.xml` now uses `c="TunableCareerTrack"` and
the current simdata library registers its CareerTrack schema under
`"CareerTrack"` (not `"TunableCareerTrack"`); so the builder treats the
tuning as Layer A (no SimData companion emitted). Once the simdata-side
agent re-registers the schema under `"TunableCareerTrack"` (which is the
EA TDESC's canonical class name — see comments in
`Build/simdata/src/build/classes/schemas.ts` lines 134–148 and the test
at `Build/simdata/src/build/classes/tdesc-driven.test.ts:120`), the
build will return to 61 resources.

This coordination is intentional: per issue #4 the XML side names the
class as EA does (`TunableCareerTrack`), and the simdata side registers
under that same name. Either agent's branch alone produces 60; merging
both produces 61.

## Issue #2 — History-degree trait name

The trait `trait_University_Major_History_Completed` referenced in
`career_Adult_Historian.xml` (career_availablity_tests),
`HC_Interaction_TranscribeManuscript.xml` (test_globals), and
`Scripts/historian_career/historian_career.py` (Python fallback list)
is a **placeholder**. The canonical EA name comes from the Discover
University EP, which is not installed on this build machine (base game
only).

### What was tried

1. **Base-game `SimulationFullBuild0.package` scan** — extracted all
   20,518 tuning XML resources from the base game CombinedTuning and
   grep'd every `<I n="…">` and full XML body for any of `university`,
   `major`, `history`, `graduated`, `degree`. Result: 141 base-game
   traits in total, **zero** of them DU-related; the only matches were
   the 18 `statistic_Skill_AdultMajor_*` skill statistics (Charisma,
   Comedy, etc.) which use "Major" in the "primary skill major" sense,
   not "university major". There are **zero** references in any base
   game XML to `University`, `Major_History`, or `MajorHistory`.

2. **Trait.tdesc enum hints** — the `trait_type` field on Trait is a
   `TunableEnumEntry` with `static_entries=traits-trait_type.TraitType`,
   but the enum values live in a separate file we don't ship. The
   default is `PERSONALITY`. `trait_origin_description` is a localized
   string field, not an enum, so no hint there. No `university` /
   `degree` keyword surfaced in any Trait TDESC default or display name.

3. **Lot 51 TDESC API** — the cached `_index.json` is the result of
   `q=*` against `tdesc.lot51.cc/api/simdex/search/tdesc`, which is
   class-level only. The site sits behind Cloudflare's JA3/JA4
   fingerprint check, so a curl probe to a more specific query (e.g.
   `?q=trait_University_Major_History`) is blocked at the TLS layer.
   Resolving this requires a Playwright session
   (`npm run fetch-tdescs:install-browser`); attempted but deferred —
   the API may not have a resource-level (instance) search anyway. The
   class-level data we have does not contain any DU instance names.

### Recommendation

- Keep `trait_University_Major_History_Completed` as the placeholder
  in all three references — it's well-named and someone with DU
  installed can confirm in one S4S lookup.
- The Python safety net in `Scripts/historian_career/historian_career.py`
  already tries 3 candidate names in order
  (`trait_University_Major_History_Completed`,
  `trait_University_Major_History`, `trait_University_Graduated_History`);
  this is our protection if the tuning-level test silently fails. **Not
  reordered or rewritten** per the task scope.
- Action required to close issue #2: a maintainer with Discover
  University installed should open the EP package in S4S, search the
  Trait list for the History major's completion trait, and update the
  three references (career, interaction test_globals, and Python
  fallback) to the confirmed name. Acquiring DU costs around $40 retail
  and is the canonical answer.

### Issue #2 status

**Unresolved** — confirmation requires Discover University to be
installed. All current placeholder references are consistent and the
Python fallback list provides a safety net. Best fallback name
remains `trait_University_Major_History_Completed`.

## Files changed

```
Tuning/aspiration_HistorianCalling_T1.xml
Tuning/aspiration_HistorianCalling_T2.xml
Tuning/aspiration_HistorianCalling_T3.xml
Tuning/aspiration_HistorianCalling_T4.xml
Tuning/aspiration_career_Historian_L1.xml
Tuning/aspiration_career_Historian_L2.xml
Tuning/aspiration_career_Historian_L3.xml
Tuning/aspiration_career_Historian_L4.xml
Tuning/aspiration_career_Historian_L5.xml
Tuning/aspiration_track_HistorianCalling.xml
Tuning/career_Adult_Historian.xml
Tuning/career_level_Adult_Historian_L1.xml
Tuning/career_level_Adult_Historian_L2.xml
Tuning/career_level_Adult_Historian_L3.xml
Tuning/career_level_Adult_Historian_L4.xml
Tuning/career_level_Adult_Historian_L5.xml
Tuning/career_track_Adult_Historian.xml
Tuning/objective_HC_ReadNonfictionBook.xml
Tuning/objective_HC_RunAnalyzePrimarySource.xml
Tuning/objective_HC_RunHabilitationLecture.xml
Tuning/objective_HC_RunPresentAtSymposium.xml
Tuning/objective_HC_RunSuperviseDissertation.xml
Tuning/objective_HC_RunTranscribeManuscript_x2.xml
Tuning/trait_HabilitationRenown.xml
XML_FIXES.md (new)
```
