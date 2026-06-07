# HistorianCareer

A Sims 4 mod that adds a **Historian career** modelled on the German academic *Karriereleiter* — **ten ranks** from *Hobbyhistoriker:in* to *Direktor:in*. The career is **open to anyone**; a History major from the *Discover University* expansion is an optional **fast-track**, not a requirement.

Built without Sims 4 Studio. The full pipeline — tuning XML, SimData binaries, string tables, and the `.ts4script` — is generated from source by a TypeScript/Node toolchain in this repo.

This README is the single human-facing doc. It folds in what used to live under `Docs/` (design, build runbook, test plan, and the reverse-engineering notes). Sections:

- [For players — install](#for-players--install)
- [What's in the box](#whats-in-the-box)
- [Design](#design) — the ten ranks, fast-track, affordances, skill gates, employers
- [Build](#build) — building from source, project layout, the build pipeline
- [Testing](#testing) — cheat-driven in-game verification
- [Notes](#notes) — hard-won EA-internals findings (pie menu, aspiration track, career-panel icon)
- [Status](#status), [Credits](#credits), [Disclaimer](#disclaimer), [License](#license)

---

## For players — install

1. Download `HistorianCareer-vX.Y.Z.zip` from the [latest release](../../releases).
2. Extract into `Documents\Electronic Arts\The Sims 4\Mods\HistorianCareer\`.
3. Enable **Custom Content** and **Script Mods** in *Options → Other*. Restart the game.
4. Delete `Documents\Electronic Arts\The Sims 4\localthumbcache.package` once.
5. Make a young-adult+ Sim and apply via phone → *Find a Job* → **Historian**. No degree needed to start at L1. If your Sim completed the **History** major at university, a separate **Historian (Research Assistant)** entry also appears that starts at **L5 Wissenschaftliche Hilfskraft** (see [Discover University fast-track](#discover-university-fast-track)).

Right-click a computer (or, at the right ranks, a bookshelf) to also see the **Historian** pie-menu category — flavour interactions that grant money, buffs, and progress independently of the job.

## What's in the box

- **Ten-rank career** with German titles, single track, skill-gated promotions, pay from §14/h to §340/h.
- **Open to all** — start at L1 with no prerequisites; History-degree holders fast-track to L5.
- **Per-rank affordances** — 8 new custom interactions + 5 re-banded existing ones + 2 career-wide social overlays, each available only within its narrative rank band.
- **One randomly-rotated daily task per day** (script-driven) plus a pure-tuning fallback pool.
- **Work-From-Home shifts** with two randomized tasks per shift.
- **Long aspiration** *Historian's Calling* — 4 tiers tied to career milestones, granting the *Habilitation Renown* reward trait.
- **Chance card** (Plagiatsvorwurf), work schedule, and the *Historiker:in* pie-menu category.
- **Bilingual (EN/DE).**
- **No runtime dependencies** — affordance injection is done in our own `.ts4script`; no XML Injector needed.

---

# Design

Why this mod exists, how its ten ranks map to the German academic system, and the small set of design decisions worth flagging.

## The career: German *Karriereleiter* in ten ranks

Standard Sims 4 careers are 10-level ladders. The Historian career matches that length but its shape is honest to the German academic world: a four-stage *pre-academic* entry track (amateur → museum guide → intern → trainee), the five real ranks of the *Karriereleiter* (HiWi → PhD → Postdoc → Junior Prof → W3 Prof), and a single *Direktor:in* capstone.

| L | German title | English (in-game) | §/h | aspiration ref |
|---|---|---|---|---|
| 1 | Hobbyhistoriker:in | Hobby Historian | §14 | aspiration_career_Historian_L1 |
| 2 | Museumswärter:in | Museum Attendant | §22 | aspiration_career_Historian_L2 |
| 3 | Praktikant:in | Intern | §18 | aspiration_career_Historian_L3 |
| 4 | Volontariat | Trainee | §30 | aspiration_career_Historian_L4 |
| 5 | Wissenschaftliche Hilfskraft | Research Assistant (HiWi) | §40 | aspiration_career_Historian_L5 |
| 6 | Doktorand:in | PhD Candidate | §60 | aspiration_career_Historian_L6 |
| 7 | Postdoktorand:in | Postdoctoral Researcher | §90 | aspiration_career_Historian_L7 |
| 8 | Juniorprofessor:in | Junior Professor | §140 | aspiration_career_Historian_L8 |
| 9 | Professor:in (W3) | Full Professor | §220 | aspiration_career_Historian_L9 |
| 10 | Direktor:in | Institute Director | §340 | aspiration_career_Historian_L10 |

The pre-academic ranks (L1–L4) reflect the typical real paths *into* academic history work in Germany: self-study, museum attendant, internship, Volontariat. They're playable as a complete arc on their own — a Sim without Discover University can still progress L1 → L4 and feel they've "had a career."

The five academic ranks (L5–L9) are unchanged in concept from the original five-rank design, just renumbered.

The **L10 Direktor:in** role is a single rank that flavour-encompasses the several real positions a former W3 Professor:in might take: Institutsdirektor:in of a research institute, Generaldirektor:in of a foundation, Direktor:in of a museum or Gedenkstätte, or Dekan:in of a faculty. The Sim's randomly-assigned employer (see [Employers](#employers)) gives the specific narrative skin. No `branch_selection` block — still single-track.

**Pay shape** is anchored to EA's Writer / Education comparators, not to prestige careers like Secret Agent Villain. The full L1 → L10 climb is ~24x (Writer Author is 18x; Tech Guru Start-up is ~16x). The §340 cap at L10 is intentionally below EA's L10 median of ~§400–§440 — this is a humanities career, and the player accepts a modest top wage in exchange for the longest, most narrative-rich ladder in the game.

Schedules progress part-time → full-time → prestige: L1–L2 part-time mornings, L3–L5 mid-length, L6–L9 full 8-hour days, L10 a prestige (later-start) schedule.

## Discover University fast-track

The career is **open to anyone**. Hobbyhistoriker:in needs no degree, and the regular **Historian** entry in *Find a Job* always starts at **L1**.

**But** if the Sim has completed a History major from Discover University, *Find a Job* shows a **second, separate entry** — **Historian (Research Assistant)** / *Historiker:in (Wiss. Hilfskraft)* — that starts **directly at L5 Wissenschaftliche Hilfskraft**, skipping the four entry-track stages. This is a fast-track shortcut, not a hard gate: a degree holder can still pick the regular entry and grind from L1, and a Sim without the degree simply doesn't see the HiWi entry.

Implemented in pure tuning as a dedicated Career + CareerTrack pair (`career_Adult_Historian_HiWi` + `career_track_Adult_Historian_HiWi`):

1. The HiWi Career is **degree-gated** via `career_availablity_tests` on the History-degree trait (**`trait_University_DegreeTraits_History` = 230331**, EA's hidden trait granted for any History degree), so the entry only appears for degree holders.
2. It carries an **unconditional** `start_level_modifiers` **+4** on the base start level of 1, so joining it begins at L5.
3. Both tracks share the same ten `career_level_Adult_Historian_L{1..10}` levels, so gameplay above the entry point is identical. The Python `.ts4script` (affordance level-gate + daily-task rotation) recognises a Sim in **either** entry.

Because the HiWi entry is degree-gated, on a **base-game install** (no Discover University, so the trait never loads) it correctly does not appear — only the regular L1 Historian entry is shown. If a future patch renames the degree trait, the failure mode is "the HiWi entry stops appearing", not "the career disappears" — resolve the trait name (see [Resolving EA trait/skill names](#resolving-ea-traitskill-names)) and rebuild.

## Two layers, by intent

**Layer A — custom interactions, anywhere.** Pie-menu work the Sim can run outside scheduled hours. Custom affordances are **per-rank** (each has a narrative band; an L10 Direktor:in no longer sees the L2 Museumswärter affordances), with EA precedent — the Law career's "File Court Documents" affordance is similarly band-gated. See [The ten-rank affordance map](#the-ten-rank-affordance-map).

**Layer B — the actual job.** Apply via phone → Find a Job → Historian (degree holders also get a separate "Historian (Research Assistant)" entry that starts at L5). Full work schedule, **one randomly-rotated daily task per day** (script-driven), **two randomized Work-From-Home tasks per WFH shift** (pure-tuning EA pattern), promotion gates, the chance card, the *Historian's Calling* aspiration, and the *Habilitation Renown* reward trait at L9.

You can play with one or both. Layer B uses the `.ts4script` for two mechanics: (a) affordance injection onto EA computer / bookshelf / social super-affordances, and (b) per-day daily-task rotation.

## Employers

When a Sim joins, the runtime picks one of five German academic institutions at random (`career_location.company_names`). They drive flavour, not mechanics — daily tasks and pay are identical across employers. At L10 the random employer flavours the specific "Direktor:in of *what*" narrative.

| Employer | Flavour |
|---|---|
| Universität Berlin | Generalist teaching university; the "default" academic posting. |
| Stiftung Preußischer Kulturbesitz | Foundation behind Berlin's state museums and libraries; archive- and exhibition-leaning. |
| Bundesarchiv | Federal archive; deep document work, the most archive-heavy posting. |
| Humboldt-Institut für Geschichtswissenschaften | Pure research institute; conference and publication focus. |
| Leibniz-Gesellschaft | Grant-driven research association; project-funded historian. |

Per-employer perks (Archive Access at the Bundesarchiv, conference-travel buffs at the Humboldt-Institut, …) are out of scope for now.

## Daily-task structure

EA's typical career repeats the same daily task at every rank. The Historian career uses a richer pattern: **each rank has a small pool of valid daily tasks; the script picks one at random at the start of each in-game day**. The career-UI daily-task slot always shows exactly one thing to do today, and that one thing varies day-to-day.

- The pool is encoded as a per-rank aspiration whose `objective_completion_type` is `complete_subset` with `number_required = 1` (a single objective satisfies the day). The script (`daily_task_rotation.py`) swaps which objective is *visible* on the panel each in-game day.
- The pure-tuning fallback (without script) is `complete_subset / number_required = 1` with all pool items visible at once and the player picking — equivalent gameplay outcome, weaker "feels different each day" vibe. The script is the canonical path; the tuning pool is the working fallback. Treat the rotation script as best-effort.

## Work-from-home shift pool

When the Sim takes a Work-From-Home shift, the career UI shows **two activities** for that shift, drawn at random from a larger per-rank Home Office pool. Completing them fills the WFH performance bar. Standard EA tuning (Writer / Engineer / Painter all use it). Enabled via `career_messages.work_from_home_text`.

## The ten-rank affordance map

**Career-wide overlays** (every rank, no rank gate):
- *Drop a History Fact* (overlay on Small Talk)
- *Tell a Historical-Reference Joke* (overlay on Tell Joke / Funny branch)

Either satisfies the "Geschichts-Sozial" daily-task pool item.

**Vanilla baseline** (EA, always available where narratively used): Computer research (ticks Research & Debate), TV News, any non-fiction book, visiting a museum/gallery venue.

**Per-rank custom + relevant baseline:**

| L | Title | Home Office (off-shift) | Daily Task pool (script picks 1/day) | WFH shift pool (game picks 2/shift) |
|---|---|---|---|---|
| 1 | Hobbyhistoriker:in | Computer-Recherche · TV-Nachrichten · Sachbuch · Museum · **Blogeintrag** *[L1–L2]* · Geschichts-Sozial | Blogeintrag · Sachbuch · Museum | Blogeintrag · Computer-Recherche · Sachbuch · TV-Nachrichten · Geschichts-Sozial |
| 2 | Museumswärter:in | Computer-Recherche · Sachbuch · Museum · **Blogeintrag** *[L1–L2]* · **Objektgeschichte** *[L2]* · Geschichts-Sozial | Blogeintrag · Geschichts-Sozial | Blogeintrag · Objektgeschichte · Computer-Recherche · Sachbuch · Geschichts-Sozial |
| 3 | Praktikant:in | Computer-Recherche · Sachbuch · **Bücherregal-Recherche** *[L3–L9]* · **Cross-Reference** *[L3–L4]* · Geschichts-Sozial | Bücherregal-Recherche · Geschichts-Sozial | Bücherregal-Recherche · Cross-Reference · Computer-Recherche · Sachbuch · Geschichts-Sozial |
| 4 | Volontariat | Computer-Recherche · Bücherregal-Recherche *[L3–L9]* · Cross-Reference *[L3–L4]* · **Bildrechte** *[L4]* · **Online-Fortbildung** *[L4]* · Transcribe *[L4–L6]* · **Zeitzeugen** *[L4–L8]* · Geschichts-Sozial | Transcribe · Zeitzeugen | Transcribe · Zeitzeugen · Bildrechte · Online-Fortbildung · Bücherregal-Recherche |
| 5 | Wiss. Hilfskraft | Computer-Recherche · Bücherregal-Recherche *[L3–L9]* · Transcribe *[L4–L6]* · Analyze Source *[L5–L7]* · Zeitzeugen *[L4–L8]* · Geschichts-Sozial | Transcribe · Zeitzeugen | Transcribe · Analyze Source · Zeitzeugen · Bücherregal-Recherche · Computer-Recherche |
| 6 | Doktorand:in | Computer-Recherche · Bücherregal-Recherche *[L3–L9]* · Transcribe *[L4–L6]* · Analyze Source *[L5–L7]* · Zeitzeugen *[L4–L8]* · Geschichts-Sozial | Analyze Source · Transcribe · Zeitzeugen | Analyze Source · Transcribe · Zeitzeugen · Bücherregal-Recherche · Computer-Recherche |
| 7 | Postdoc | Computer-Recherche · Bücherregal-Recherche *[L3–L9]* · Analyze Source *[L5–L7]* · Symposium *[L7–L8]* · Zeitzeugen *[L4–L8]* · Geschichts-Sozial | Symposium · Analyze Source · Zeitzeugen | Symposium · Analyze Source · Zeitzeugen · Bücherregal-Recherche · Computer-Recherche |
| 8 | Juniorprofessor:in | Computer-Recherche · Bücherregal-Recherche *[L3–L9]* · Symposium *[L7–L8]* · Habilitation Lecture *[L8–L9]* · Zeitzeugen *[L4–L8]* · Geschichts-Sozial | Habilitation Lecture · Symposium · Zeitzeugen | Habilitation Lecture · Symposium · Zeitzeugen · Bücherregal-Recherche · Computer-Recherche |
| 9 | W3 Professor:in | Computer-Recherche · Bücherregal-Recherche *[L3–L9]* · Habilitation Lecture *[L8–L9]* · Supervise *[L9–L10]* · Geschichts-Sozial | Supervise · Habilitation Lecture | Supervise · Habilitation Lecture · Bücherregal-Recherche · Computer-Recherche |
| 10 | Direktor:in | Computer-Recherche · Supervise *[L9–L10]* · **Drittmittel** *[L10]* · Geschichts-Sozial | Drittmittel · Supervise | Drittmittel · Supervise · Computer-Recherche · Geschichts-Sozial |

Bracketed `[Lx–Ly]` is the rank band where each custom affordance is mechanically available (enforced by `level_gate.py`). The 5 existing affordances (Transcribe, Analyze, Symposium, Habilitation Lecture, Supervise) keep their loot/names/behaviour but get new bands.

**Build cost** — 8 new custom affordances + 5 existing (re-banded) + 2 career-wide social overlays:

| New affordance | Object surface | Band |
|---|---|---|
| Blogeintrag schreiben | Computer | L1–L2 |
| Objektgeschichte recherchieren | Bookshelf (museum-exhibit surface unavailable; ships on bookshelf, framed as cataloguing) | L2 |
| Recherchieren am Bücherregal | Bookshelf | L3–L9 |
| Cross-Reference Sources at Bookshelf | Bookshelf | L3–L4 |
| Bildrechte recherchieren | Computer | L4 |
| Online-Fortbildung teilnehmen | Computer | L4 |
| Zeitzeugen-Interview | Social, Elder target | L4–L8 |
| Acquire Drittmittel | Computer | L10 |
| Drop a History Fact | Small Talk overlay | L1–L10 |
| Tell a Historical-Reference Joke | Tell Joke overlay | L1–L10 |

The social affordances (Zeitzeugen + the two overlays) are `SocialSuperInteraction`s targeting a Sim; the rest are object `SuperInteraction`s. Social injection is best-effort — if a clean injection target is unavailable in a given save, the overlays may not appear. Flag this for in-game test.

## Skill gates and promotion requirements

The career uses three existing EA skills — **Writing** (16714), **Research & Debate** (Discover University, 221014), and **Charisma** (16699) — to gate promotions. **No new skill is introduced.** Charisma matters only at the social-heavy low rank and the leadership capstone; the academic middle is Charisma-neutral.

| Promotion | Skill gate (in addition to performance) |
|---|---|
| L1 → L2 | Writing ≥ 2 **and** Charisma ≥ 1 |
| L2 → L3 | *(open — performance only)* |
| L3 → L4 | *(open)* |
| L4 → L5 | *(open)* |
| L5 → L6 | *(open)* |
| L6 → L7 | Research & Debate ≥ 7 |
| L7 → L8 | Writing ≥ 7 |
| L8 → L9 | **Habilitation**: Research & Debate = 10 **and** Writing = 10 |
| L9 → L10 | Charisma ≥ 5 |

Implemented via `block_promotion_tests` on the Career resource. A test-group BLOCKS a promotion when it PASSES; the outer list is OR (any group blocks), each inner group is AND. To require skill ≥ N at a specific transition the group is `[career_level test for the FROM level] AND [skill test that passes only when the skill is BELOW N]`. These gates are only truly verifiable in-game — flag for in-game test.

The four middle promotions (L2 → L3 through L5 → L6) are deliberately performance-only — gentler for casual players. Whether to add gates there is an open question (see [Open design questions](#open-design-questions)).

## Social interactions

**Career-wide flavour overlays** at every rank, custom-injected on EA's Small Talk and Tell Joke socials. Either can satisfy the "Geschichts-Sozial" daily-task pool item.

**One rank-gated career social: Zeitzeugen-Interview.** Custom social affordance, band L4 → L8. Target requirement: **Elder Sim**. Ticks Research & Debate and Charisma. A daily-task pool option at every rank in the band. (The earlier two-tier split + "Discuss Habilitation Plans" + a reserved third slot are all dropped — one five-rank-band affordance is simpler and avoids duplicate content.)

## Bookshelf research

Two bookshelf affordances, both injected onto EA bookshelves (fuzzy name-prefix `object_book`) via the `.ts4script`:

- **Recherchieren am Bücherregal** — the main bookshelf-research affordance. Band L3–L9. Ticks Research & Debate. Daily-task pool option at L3.
- **Cross-Reference Sources at Bookshelf** — a specialized lookup. Band L3–L4. Home Office and WFH pool only; **not** in the daily-task pool.

`SimRanInteraction`-based objectives drive the daily-task pool entries directly, so no custom bookshelf statistic is needed.

## Reward traits

**Habilitation Renown** — granted on completion of the long aspiration *Historian's Calling* (which completes around the L8 → L9 Habilitation promotion). Small passive +Focused buff in libraries. A second top-rank trait (a Lebenswerk/Institutsdirektor:innen renown at L10) is future polish.

## Chance cards

One chance card ships: **Plagiatsvorwurf** ("A Plagiarism Accusation"). Two more — Conference Invitation and a Drittmittel Grant Application — are designed but not yet implemented. The Drittmittel card now has a natural anchor (the L10 *Acquire Drittmittel* affordance).

## Languages

English and German strings ship in `Build/s4tk-builder/strings.json`. The ten-rank expansion adds the level titles/descriptions/dailies (L1–L10), promotion-tier strings, the new affordance names + tooltips, and the new objective texts. Every new STBL key must exist with both `en` and `de`. See [String tables](#string-tables-stbl) under Build.

## Things deliberately not in scope

- **A custom skill.** Existing EA skills only (Research & Debate, Writing, Charisma). No "Historiography" skill.
- **Per-level outfits.** EA default Adult outfits; custom uniforms are future polish.
- **The other two chance cards.** Plagiarism only for now.
- **Per-employer perks.** The five institutions are flavour.
- **A real L10 branch.** Direktor:in is a single rank flavour-encompassing the post-W3 possibilities; a `branch_selection` block can be added later without breaking saves.
- **A second top-rank reward trait.** Habilitation Renown lands at L9; an L10 trait is future polish.

## Open design questions

1. **Intermediate skill-gate density.** Locked gates: L1→L2, L6→L7, L7→L8, L8→L9, L9→L10. The four in between (L2→L3 … L5→L6) are performance-only. Denser = every promotion is a "level up your skill" beat; sparser = gentler for casual players.
2. **Museum-exhibit affordance injection.** Objektgeschichte (L2) currently ships on the **bookshelf** surface (no clean museum-exhibit object exists to inject onto). If a stable exhibit target surfaces later, it can move.
3. **Social-overlay injection robustness.** The two career-wide overlays and Zeitzeugen inject onto EA socials best-effort; their reliability across saves is the main thing to confirm in-game.

---

# Build

This mod builds **without Sims 4 Studio**. `@s4tk/models` authors the `.package` directly, a TypeScript SimData generator emits the binary companions S4S would normally produce, and Sims 4's CPython 3.7 compiles the shipped `.py` sources on first import (so no `.pyc` is shipped).

## Build from source

From the project root (`HistorianCareer/`):

```bash
# Default: full build (Layer A + B), install to your Mods folder, clear Sims 4 caches.
node Build/build.mjs

# Build only — write artifacts to Build/out/ without touching the Mods folder.
# This is the green-build invariant the toolchain must always satisfy:
node Build/build.mjs --no-install --no-cache-clear

# Faster iteration on Layer A (no Career/Aspiration SimData) — drop-in .package only.
node Build/build.mjs --no-layer-b --package-only

# Other useful flags:
#   --package-only       skip the .ts4script
#   --script-only        skip the .package
#   --no-cache-clear     leave Sims 4 thumb/cache files alone
#   --mods-folder PATH   override the auto-detected Mods folder
```

Outputs to `Build/out/`:
- `HistorianCareer_Tuning.package` — DBPF v2.1: tuning + SimData + STBL + DDS icons
- `HistorianCareer.ts4script` — raw `.py` sources, deflate-zipped

### Tools you need
- **Node.js 16+** — for the s4tk-builder, the simdata library, and the orchestrator (`Build/build.mjs`).

That's it. **Sims 4 Studio is not required** — the SimData companions are generated by [`Build/simdata`](Build/simdata) (a TypeScript SimData generator built for this project; see its [README](Build/simdata/README.md)). **Python is not required** at build time either — Sims 4's CPython 3.7 compiles `.py` sources on first import, so the build ships raw sources rather than bytecode.

### Prerequisites for running in-game
- The Sims 4 (the History-degree fast-track and Research & Debate skill come from the **Discover University** EP, but the career itself runs without it).
- Custom Content + Script Mods enabled in *Options → Other*.

## What the build does

`node Build/build.mjs` runs two stages:

1. **`Build/s4tk-builder`** reads every XML under `Tuning/` plus `Build/s4tk-builder/strings.json`, then:
   - hashes each tuning `n=` name with FNV-64 to compute the Instance ID (replacing `s="TBD_INSTANCE_ID"`);
   - resolves OUR tuning-name references (e.g. `<T>aspiration_career_Historian_L6</T>`) to those hashes;
   - replaces each `0xTBD_STBL_KEY_<KEY>` placeholder with the FNV-32 of the matching `strings.json` key (build fails on an unknown key);
   - generates SimData companions for the classes that need them (Career, CareerTrack, CareerLevel, Aspiration, AspirationTrack, AspirationCareer, Trait, Objective, CareerChanceCard, **PieMenuCategory** — see Notes);
   - converts source PNGs under `Build/icons/` to DDS;
   - writes everything into `Build/out/HistorianCareer_Tuning.package`.
2. The orchestrator zips `Scripts/historian_career/*.py` into `Build/out/HistorianCareer.ts4script`.

XML comments are stripped at build time. Keep new comments short and ASCII — large non-ASCII comment blocks have caused silent rejection in-game (the strip mitigates it, but stay clean).

## Authoring conventions

- **EA references → use the NUMERIC instance ID** as the element body (e.g. `<T>230331</T>`), never the EA name. The name-resolver only knows OUR tuning names; an EA *name* would be wrongly FNV-hashed.
- **OUR tunings → reference by `n=` name** (e.g. `<T>HC_Loot_Add_HistorianLevel_Small</T>`); the resolver maps them.
- **New instance IDs** — leave `s="TBD_INSTANCE_ID"`; the builder hashes the name. Exception: the AspirationTrack + its 4 tier aspirations keep their hand-picked IDs.
- **STBL placeholders** — write `0xTBD_STBL_KEY_<KEYNAME>` in XML and add `<KEYNAME>` to `strings.json` (`en` required, `de` too).
- Match existing file patterns — read a sibling file of the same kind before writing a new one.
- A recon helper reads the installed game for confirming any EA id/shape: `node Build/s4tk-builder/_recon.mjs find|body|simdata|grep <args>`.

### Verified EA facts (patch 1.124.55)
- History-degree trait (hidden, granted for any History degree): `trait_University_DegreeTraits_History` = **230331**.
- Skills: Research & Debate = **221014**, Writing = **16714**, Charisma = **16699**.
- Aspiration category Knowledge = **25385**; Knowledge `primary_trait` = **27086**; AspirationRewards 27489 / 27490 / 27491.
- Bookshelf objects to fuzzy-match on prefix `object_book`: `object_bookshelf` (14837), `object_bookshelf_library` (100180), various `object_bookcaseFloor*`.

### Resolving EA trait/skill names

If a future EP patch renames the History-degree trait, the fast-track (and the Python safety-net) stop working — the career still loads, it just no longer skip-hires to L5. To re-resolve: in Sims 4 Studio → **Tools → Game File Cruiser** search the trait list for `trait_University` and find the History degree trait, or use `_recon.mjs grep` against the installed game; update the numeric ID and rebuild.

## String tables (STBL)

All keys live in `Build/s4tk-builder/strings.json` with `en` and `de` values. The expansion's key families:

- **Level strings** `HC_LEVEL_{n}_TITLE` / `_DESC` / `_DAILY` for n = 1..10 (titles per the ten-rank table above; the original five-rank titles are superseded — L5 is now HiWi, not "Research Assistant").
- **Promotion tiers** `HC_PROMO_TIER_1..10` ("You are now <title>." / "Sie sind jetzt <title>.").
- **New affordance names + tooltips** `HC_INTERACTION_BLOGEINTRAG` (+`_TT`), `_OBJEKTGESCHICHTE`, `_BUECHERREGAL`, `_CROSSREF`, `_BILDRECHTE`, `_FORTBILDUNG`, `_ZEITZEUGEN`, `_DRITTMITTEL`, `_HISTORYFACT`, `_HISTORYJOKE`.
- **New objective texts** `HC_OBJ_BLOG`, `HC_OBJ_OBJEKT`, `HC_OBJ_BUECHERREGAL`, `HC_OBJ_CROSSREF`, `HC_OBJ_BILDRECHTE`, `HC_OBJ_FORTBILDUNG`, `HC_OBJ_ZEITZEUGEN`, `HC_OBJ_DRITTMITTEL`, `HC_OBJ_HISTORYSOCIAL`.
- **WFH** `HC_CAREER_WFH_TEXT` (the "Work from home" action label).
- Existing company names, career name/desc, notifications, aspiration-track keys, trait keys, chance-card keys are kept.

## Scripts

`Scripts/historian_career/` (bundled into the `.ts4script`):

- `affordance_injector.py` — injects the custom computer/bookshelf affordances onto EA objects (fuzzy prefix `object_book` for bookshelves) and the social affordances onto Sims (best-effort). Idempotent, with logging.
- `level_gate.py` — per-affordance rank **bands** (min and max `user_level`); the gate returns False outside `[min, max]`.
- `historian_career.py` — the promotion-tier table (German titles for all 10 ranks) and the History-degree safety-net.
- `daily_task_rotation.py` — best-effort: on career day-change, picks one objective from the rank's pool as the visible daily task. Defensive; the tuning pool is the working fallback.
- `__init__.py` — module registration.

## Project layout

```
HistorianCareer/
├── Tuning/                    tuning XMLs (interactions, statistics, career, levels, aspirations, …)
├── Scripts/historian_career/  Python (.py): affordance injector, level gate, career tiers, daily-task rotation, notifications
├── Build/
│   ├── build.mjs              Top-level orchestrator (produces both artifacts, installs, clears caches)
│   ├── icons/                 Source PNGs for career/aspiration icons (converted to DDS at build)
│   ├── s4tk-builder/          Node.js bundler: XML + STBL + icons → .package (+ strings.json, _recon.mjs, validators)
│   └── simdata/               TypeScript SimData generator (replaces the Sims 4 Studio step)
├── _BUILD_SPEC.md             Authoritative build spec (names/IDs/keys are LAW) — under Build/s4tk-builder/
├── NOTICE.md                  Attribution
├── LICENSE                    MIT
└── README.md                  ← you are here
```

---

# Testing

A practical, cheat-driven workflow: don't grind a real save through ten ranks — use the console to teleport through every state, confirm each piece works, and watch for `LastException.txt`. **The career UI strings are German on a German install** (`Die Sims 4`); adjust folder paths accordingly.

## One-time setup (every session)

1. **Pin the patch you're testing against** (Main Menu → bottom right). EA renumbers tuning hashes on patches; tests are only valid for the patch you built against (this work targets **1.124.55**).
2. **Back up your save** — copy `Documents\Electronic Arts\The Sims 4\saves\slot_*` somewhere safe. Custom careers can break ongoing saves if uninstalled mid-career.
3. **Use a clean Mods folder for the first run** — leave only `HistorianCareer_Tuning.package` + `HistorianCareer.ts4script`.
4. **Delete the cache:** `localthumbcache.package` (and, for a deep reset, see the cache list under [Notes → cache nuke](#when-a-package-passes-but-the-ui-still-fails)).
5. **Enable Custom Content + Script Mods** (*Options → Other*), restart.
6. **Start a fresh save** with a young-adult Sim.
7. **Open the console** (`Ctrl + Shift + C`) → `testingcheats true`.

## Smoke test (does it load at all?)

Type `help` — output should scroll without errors. Then check `Documents\Electronic Arts\The Sims 4\LastException*.txt` and `lastUIException.txt`. Any file timestamped after launch → **stop and read it**; the stack trace names the resource that failed to load. Most common cause: a tuning name reference that didn't resolve to a hash.

## Test Layer A — pie-menu interactions

These run independently of the full Career. Grant the skills, then right-click a computer (or, at the right ranks, a bookshelf):

```
testingcheats true
stats.set_skill_level Major_ResearchDebate 10
stats.set_skill_level Major_Writing 10
```

- [ ] **Historian** ("Historiker:in") sub-menu visible (not a flat list — see [Notes → pie-menu](#pie-menu-the-historiker-submenu)).
- [ ] Each affordance only appears within its rank band (`level_gate.py`).
- [ ] Running one grants its loot / buff / progress.

To inspect/reset the performance statistic mid-flight, use `stats.set_stat HC_PerformanceStat_Historian <n>`.

## Test Layer B — the real career

```
careers.add_career career_Adult_Historian
```

- [ ] No console error; career panel shows "Historian" at L1 "Hobbyhistoriker:in", §14/h.
- [ ] Daily-task panel shows the L1 aspiration objective(s).

A Sim with the History degree should *also* see a **separate** *Find a Job* entry, **Historian (Research Assistant)**, that starts at **L5**. Test both: the regular **Historian** entry always starts at L1; the degree-only **Historian (Research Assistant)** entry starts at L5 Wissenschaftliche Hilfskraft. On a base-game install (no Discover University) only the regular entry appears.

Jump through every rank (run repeatedly, cheating skills to clear gates):

```
stats.set_skill_level Major_ResearchDebate 10
stats.set_skill_level Major_Writing 10
stats.set_skill_level Major_Charisma 10
careers.promote career_Adult_Historian
```

- [ ] The panel title updates through all ten German titles; pay climbs 14 → 22 → 18 → 30 → 40 → 60 → 90 → 140 → 220 → 340.
- [ ] Around L9 the Sim gets **Habilitation Renown** (check Simology).
- [ ] Daily tasks update per rank.
- [ ] If a promotion silently does nothing, a `block_promotion_tests` gate is firing — confirm the skill levels meet that transition's gate (these gates are only truly verifiable in-game).

Verify schedule, WFH, the chance card, the long aspiration, and demote/retire/remove:

```
careers.go_to_work
careers.fire_chance_card career_Adult_Historian
aspirations.add_aspiration aspiration_track_HistorianCalling
aspirations.complete_current_milestone
careers.demote career_Adult_Historian
careers.retire career_Adult_Historian
careers.remove_career career_Adult_Historian
```

- [ ] WFH shift shows two activities; completing them fills the WFH bar.
- [ ] The Plagiarism dialog appears with two options; option A drops performance + applies an embarrassed buff; option B is a 50/50 roll.
- [ ] The aspiration panel shows "Historian's Calling" / "Berufung Historiker:in"; milestones advance; tier-4 completion awards Habilitation Renown.
- [ ] Each career command runs without exception; after `remove_career` the panel clears.

## Negative / gate tests

- [ ] A degree-less Sim joins the regular **Historian** entry fine and starts at **L1** (open to all — no availability gate), and sees **no** HiWi entry.
- [ ] A History-degree Sim sees the separate **Historian (Research Assistant)** entry and joins it at **L5**; the regular Historian entry still starts at L1.
- [ ] Promotion gates hold: e.g. with Writing = 1, L1 → L2 should refuse (needs Writing ≥ 2 AND Charisma ≥ 1); with Research & Debate = 9 OR Writing = 9, L8 → L9 should refuse (Habilitation needs both at 10).

## Stability test (before any release)

- [ ] Play a full sim-week with the career active (`time.gameplay_clock_speed 3` to speed up). Check for new `LastException*.txt` / `lastUIException.txt`.
- [ ] Save, exit, relaunch, load — career state persists (title, level, performance, trait).
- [ ] Restore the kitchen-sink Mods folder and repeat. Conflicts are usually with mods that override `careers.career_tuning` or the computer/bookshelf object.

## Cheat cheat-sheet

| Command | Effect |
|---|---|
| `testingcheats true` | Enables the others |
| `careers.add_career career_Adult_Historian` | Hire into Historian |
| `careers.promote / demote career_Adult_Historian` | ±1 level (respects gates) |
| `careers.remove_career / retire career_Adult_Historian` | Quit / retire |
| `careers.go_to_work` | Send to work now |
| `careers.fire_chance_card career_Adult_Historian` | Trigger a chance card |
| `stats.set_skill_level Major_ResearchDebate 10` | Max Research & Debate |
| `stats.set_skill_level Major_Writing 10` | Max Writing |
| `stats.set_skill_level Major_Charisma 10` | Max Charisma |
| `traits.equip_trait trait_University_DegreeTraits_History` | Grant the History degree (fast-track to L5) |
| `aspirations.add_aspiration aspiration_track_HistorianCalling` | Add the long aspiration |
| `aspirations.complete_current_milestone` | Advance an aspiration tier |

## When a test fails

Always read `LastException*.txt` / `lastUIException.txt` first. Patterns:

- **`KeyError` / "Could not find tuning"** — a name reference doesn't resolve; check the named XML's Instance ID and class.
- **`AttributeError` inside a tuning class** — a tunable field is the wrong shape (`<T>` vs `<V>` vs `<U>`); compare against the EA original.
- **Nothing visible happened, no exception** — a resource loaded but a test block filtered everything; temporarily comment out the `test_globals` / promotion / level-gate block, confirm the rest works, then restore and find the bad test.

---

# Notes

Hard-won findings from reverse-engineering EA internals while getting custom resources to actually register in the game. These explain *why* certain build steps exist; if something regresses in-game, start here. (Patch 1.124.55. Reverse-engineering used JPEXS Free Flash Decompiler against EA's shipped Scaleform GFX UI and disassembly of the shipped CPython `.pyc`.)

## AspirationTrack: the schema and the age-type bug

Two separate issues, both resolved:

1. **The 11-column adult schema.** The earlier AspirationTrack SimData crashed the game (AS3 `#1009` null-reference in `AspirationTrackStaticData/INIT_DATA()`). The generator now emits the patched **11-column** adult schema (schema `0x1544019c`, inner `AspirationsMappingTuple` `0xd012f9dc`, version `0x101`), byte-identical to the game's own `Track_Knowledge_A` (adding `is_hidden_unlockable` and `override_traits` over the older 9-column form). Do not hand-edit the generator's track schema.

2. **`aspiration_valid_age_type` must be valid.** Each tier aspiration's `<E n="aspiration_valid_age_type">` must be a real enum member or the parser silently falls back to `INVALID = 0`, and `Aspiration.is_valid_for_sim` (`sim_info.age & age_type`) then returns falsy for every Sim — filtering the track out of the aspiration picker, the age-up dialog, and the primary-aspiration fallback. The valid members are `INVALID`, `TODDLER_ONLY` (2), `CHILD_ONLY` (4), `TEEN_ONLY` (8), `TEEN_OR_OLDER` (120 = TEEN|YOUNGADULT|ADULT|ELDER). Historian uses **`TEEN_OR_OLDER`**. The local enum table in `Build/simdata/src/build/enums.ts` must use these bitmask values (not 0,1,2,3,4,5).

**Registration is automatic** — mod AspirationTracks at `group=0` are loaded into the runtime instance manager via the same merged-tuning path as EA tracks. No Python injection is needed to register a track.

**CAS-picker caveat (MEDIUM confidence).** The initial-CAS aspiration picker is a Scaleform GFX widget that calls **native C++ engine** GameService RPCs (`CasGetAspirationCategories`, `CasGetAspirationTracksByCategory`, `GetAspirationTrackStaticData`), not Python — so there is no Python hook to monkey-patch the picker. The engine does enumerate mod packages (our track ships at `type=0x545AC67A, group=0x0020FC6D, instance=0x6621FF4B`, byte-equivalent to EA's), so it *should* appear. If it doesn't after the age-type fix, the prime suspect is stale per-account cache (see below) or a runtime AS3 desync; `Scripts/historian_career/aspiration_diag.py` logs whether our track and its tiers are in the instance managers with the right age-type and `is_valid_for_sim` result.

## Pie menu: the "Historiker:in" submenu

For the five (now more) computer/bookshelf interactions to nest under a "Historiker:in" submenu rather than appear flat, two things are required:

1. **`PieMenuCategory` needs a SimData companion.** The Olympus UI builds its category map at boot from `PieMenuCategory` **SimData** resources (type `0x545AC67A`), not from tuning XML. Without it the UI throws "Failed to locate category info for interaction category with key: …" and silently drops the whole pie menu. So `PieMenuCategory` is in the builder's `NEEDS_SIMDATA` set and the generator emits the **7-column** schema, hash **`0x022065c1`** (`_collapsible`, `_display_name`, `_display_priority`, `_icon`, `_parent`, `_special_category`, `mood_overrides`). The PMC SimData group is class-specific (`0x00E9D967`), not 0.
2. **A small (≤ 2^31-1) instance ID + `interaction_category_tags`.** The PMC uses a 31-bit instance ID (the default 64-bit FNV would crash the category resolver). Each SuperInteraction carries `interaction_category_tags` (Super + All) and `<T n="category">HC_PieMenuCategory_Historian</T>` (resolved to the PMC's decimal id at build).

Validate a built package with `node Build/s4tk-builder/inspect-pie-menu.mjs [path-to-installed-package]`.

## Career-panel icon

- The **bottom-right HUD briefcase** widget is a hardcoded Flash symbol — it shows the same briefcase for *every* career and never reflects a custom icon. This is EA design, not a bug. Don't use it as a test target.
- The **expanded career panel** (click the briefcase to open it) reads `CareerTrack.icon` (`type=0x00B2D882` DDS) via the same asset-load path as the join-career notification — so our `Career_Historian_Main.png` renders there. `CareerTrack.icon_high_res` is declared but **read by nothing** in the current client; we still emit it (pointed at the same art). Don't try to rewrite the DDS encoder (it's byte-equal to EA) or inject a Python icon override (the SWF reads the SimData blob directly — there's no intercept point).

## When a package PASSES but the UI still fails

A byte-correct package can still misbehave in-game because the Olympus UI builds its registries from binary indexes at launch and saves persist stale references. If a validator says PASS but the submenu is flat / the track is missing:

1. **Cold restart with a full cache nuke.** `node Build/build.mjs` clears caches on install, but if the game was running or a save was loaded mid-build you can hold stale state. For a deep reset, with the game closed, delete: `localthumbcache.package`, `localsimtravelthumbcache.package`, `localsimtexturecache.package`, `avatarcache.package`, `clientDB.package`, `accountDataDB.package`, `onlinethumbnailcache/`, and `cachestr/`. Then start a **new** save to test before loading an old one.
2. **Save-state contamination.** Saves opened under older builds (notably earlier hand-picked instance IDs) can hold stale per-object interaction routing that survives rebuilds. Test on a brand-new save and a fresh object first; if a new save works but an old one doesn't, the old save is the culprit.
3. **Duplicate packages.** Sims 4 loads every `.package` under `Mods/` recursively. Make sure there's exactly one `HistorianCareer_Tuning.package` and one `.ts4script` — stray copies from earlier dev rounds shadow the build.

---

## Status

This work expands the original five-rank v0.4 design to the full **ten-rank** ladder, with the AspirationTrack fixed to the patched 11-column adult schema, the new per-rank affordances + social overlays, the Discover University fast-track, and the script-driven daily-task rotation.

What's solid:
- The build pipeline is green (`node Build/build.mjs --no-install --no-cache-clear`) and the simdata generator's unit + golden-byte tests pass.
- Trait, Buff, AspirationTrack (11-col), and PieMenuCategory SimData byte-match EA fixtures.
- The package is well-formed per `@s4tk/models` and the pie-menu / aspiration-track shapes match EA's own resources.

What still needs in-game verification (flagged throughout):
- **Promotion skill gates** (`block_promotion_tests`) are only truly verifiable in-game — implemented per EA's block-on-pass logic.
- **Social-affordance injection** (the two overlays + Zeitzeugen) is best-effort.
- **Daily-task rotation** is the canonical path but the tuning pool is the working fallback.
- **CAS aspiration-picker visibility** post age-type fix (see Notes) and the per-account cache interactions.

## Credits

- Scaffold structure inspired by [rhavari22/UXMod-Sims4](https://github.com/rhavari22/UXMod-Sims4) (MIT). See [`NOTICE.md`](NOTICE.md).
- Built on [Sims 4 Toolkit](https://sims4toolkit.com) (`@s4tk/models`, `@s4tk/hashing`, `@s4tk/xml-dom`, MIT).
- TDESC schemas served by [Lot 51's TDESC API](https://tdesc.lot51.cc) (EA's public tuning descriptions).
- EA-internals reverse-engineering used [JPEXS Free Flash Decompiler](https://github.com/jindrapetrik/jpexs-decompiler) (MIT).

## Disclaimer

This project is not affiliated with or endorsed by Electronic Arts or Maxis. *The Sims* and related marks are trademarks of Electronic Arts Inc. No EA/Maxis game assets are redistributed in this repository.

## License

MIT — see [`LICENSE`](LICENSE).
