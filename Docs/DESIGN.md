# Design — Historian Career

Why this mod exists, how its ten ranks map to the German academic system, and the small set of design decisions worth flagging.

## The career: German *Karriereleiter* in ten ranks

Standard Sims 4 careers are 10‑level ladders. The Historian career matches that length but its shape is honest to the German academic world: a four‑stage *pre‑academic* entry track (amateur → museum guide → intern → trainee), the five real ranks of the *Karriereleiter* (HiWi → PhD → Postdoc → Junior Prof → W3 Prof), and a single *Direktor:in* capstone.

| L | German title | English (in‑game) | §/h |
|---|---|---|---|
| 1 | Hobbyhistoriker:in | Hobby Historian | §14 |
| 2 | Museumswärter:in | Museum Attendant | §22 |
| 3 | Praktikant:in | Intern | §18 |
| 4 | Volontariat | Trainee | §30 |
| 5 | Wissenschaftliche Hilfskraft | Research Assistant (HiWi) | §40 |
| 6 | Doktorand:in | PhD Candidate | §60 |
| 7 | Postdoktorand:in | Postdoctoral Researcher | §90 |
| 8 | Juniorprofessor:in | Junior Professor | §140 |
| 9 | Professor:in (W3) | Full Professor | §220 |
| 10 | Direktor:in | Institute Director | §340 |

The pre‑academic ranks (L1–L4) reflect the typical real paths *into* academic history work in Germany: self‑study, museum attendant, internship, Volontariat. They're playable as a complete arc on their own — a Sim without Discover University can still progress L1 → L4 and feel they've "had a career."

The five academic ranks (L5–L9) are unchanged in concept from the v0.1 five‑rank design, just renumbered.

The **L10 Direktor:in** role is a single rank that flavour‑encompasses the several real positions a former W3 Professor:in might take: Institutsdirektor:in of a research institute, Generaldirektor:in of a foundation, Direktor:in of a museum or Gedenkstätte, or Dekan:in of a faculty. The Sim's randomly‑assigned employer (§Employers) gives the specific narrative skin. No `branch_selection` block — still single‑track.

**Pay shape** is anchored to EA's Writer / Education comparators, not to prestige careers like Secret Agent Villain. The full L1→L10 climb is ~24× (Writer Author is 18×; Tech Guru Start‑up is ~16×). The §340 cap at L10 is intentionally below EA's L10 median of ~§400–§440 — this is a humanities career, and the player accepts a modest top wage in exchange for the longest, most narrative‑rich ladder in the game.

## Discover University fast‑track

The career is **open to anyone**. Hobbyhistoriker:in needs no degree.

**But** if the Sim has completed a History major from Discover University, they enter the career **directly at L5 Wissenschaftliche Hilfskraft**, skipping the four entry‑track stages. This is a fast‑track shortcut, not a hard gate — a Sim without the degree can still grind from L1 to L10.

Implemented in pure tuning as a `start_level_modifiers` block on the Career resource: a `trait` test for `trait_University_Major_History_Completed` adds `+4` to the base start level of 1 (see [`career_Teen_Retail.tuning.xml:264-295`](../Build/simdata/test/golden/Career/career_Teen_Retail.tuning.xml) for the EA pattern). No Python required.

Three knock‑on changes from the v0.1 design:

1. The `career_availability_test` block (which made the whole career invisible without the degree) is **removed**.
2. The trait test on the L1 Transcribe Manuscript pie‑menu affordance is **dropped** — by the time a Sim reaches that affordance's new band (L4–L6), they either skip‑hired with the degree or regular‑promoted past the entry track, so the affordance's own trait gate is redundant.
3. `Docs/IMPLEMENTATION_GUIDE.md` §2 still applies for resolving the exact trait name if a future patch renames it — just now the failure mode is "fast‑track stops working", not "career disappears".

## Two layers, by intent

**Layer A — custom interactions, anywhere.** Pie‑menu work the Sim can run outside scheduled hours. Custom affordances are **per‑rank** (each has a narrative band; an L10 Direktor:in no longer sees the L2 Museumswärter affordances), with EA precedent — the Law career's "File Court Documents" affordance is similarly band‑gated. See §The ten‑rank affordance map.

**Layer B — the actual job.** Apply via phone → Find a Job → Historian (or fast‑track directly to L5). Full work schedule, **one randomly‑rotated daily task per day** (script‑driven), **two randomized Work‑From‑Home tasks per WFH shift** (pure‑tuning EA pattern), promotion gates, chance cards, the aspiration *Historian's Calling*, and the Habilitation Renown reward trait at L9.

You can play with one or both. Layer B requires the `.ts4script` for two new mechanics: (a) affordance injection onto EA computer / bookshelf / museum‑exhibit / social super‑affordances, and (b) per‑day daily‑task rotation (see §Daily‑task structure).

## Employers — five German academic institutions

When a Sim joins the career the runtime picks one of the following as their employer at random (`career_location.company_names` in `career_Adult_Historian.xml`). They drive flavour, not mechanics — daily tasks and pay are identical across employers. At L10 the random employer flavours the specific "Direktor:in of *what*" narrative.

| Employer | Flavour |
|---|---|
| Universität Berlin | Generalist teaching university; the "default" academic posting. |
| Stiftung Preußischer Kulturbesitz | Foundation behind Berlin's state museums and libraries; archive‑ and exhibition‑leaning. |
| Bundesarchiv | Federal archive; deep document work, the most archive‑heavy posting. |
| Humboldt‑Institut für Geschichtswissenschaften | Pure research institute; conference and publication focus. |
| Leibniz‑Gesellschaft | Grant‑driven research association; project‑funded historian. |

Per‑employer perks (Archive Access buff at the Bundesarchiv, conference‑travel buffs at the Humboldt‑Institut, …) are out of scope for v0.1.

## Daily‑task structure

EA's typical career repeats the same daily task at every rank ("Read Books" L1–L2, "Write Books" L3–L5 in Writer). The Historian career uses a richer pattern: **each rank has a small pool of valid daily tasks; the script picks one at random at the start of each in‑game day**. The career‑UI daily‑task slot always shows exactly one thing to do today, and that one thing varies day‑to‑day.

Two implementation notes:

- The pool is encoded as a per‑rank aspiration whose `objective_completion_type` is `complete_subset` with `number_required = 1` (so a single objective satisfies the day). The script swaps which objective is *visible* on the panel each in‑game day.
- The pure‑tuning fallback (without script) is `complete_subset / number_required = 1` with all pool items visible at once and the player picking — equivalent gameplay outcome, weaker "feels different each day" vibe. The script is the canonical path.

## Work‑from‑home shift pool

When the Sim takes a Work‑From‑Home shift, the career UI shows **two activities** for that shift, drawn at random from a larger per‑rank Home Office pool. Completing them fills the WFH performance bar. Standard EA tuning (Writer / Engineer / Painter all use it).

## The ten‑rank affordance map

**Career‑wide overlays** (available at every rank, no rank gate):
- 🟪 *Drop a History Fact* (overlay on Small Talk)
- 🟪 *Tell a Historical‑Reference Joke* (overlay on Tell Joke / Funny branch)

Either satisfies a "Geschichtsinteraktion" daily‑task pool item.

**Vanilla baseline** (EA, always available — listed here per rank where narratively used):
- 📖 Recherchieren am Computer (ticks Research & Debate, vanilla)
- 📖 Nachrichten beim Fernseher (vanilla Watch TV with News channel)
- 📖 Read any non‑fiction book (vanilla)
- 📖 Visit museum / gallery venue (vanilla travel to community lot)

**Per‑rank custom + relevant baseline:**

| L | Title | Home Office (available off‑shift) | Daily Task pool (script picks 1/day) | WFH shift pool (game picks 2/shift) |
|---|---|---|---|---|
| 1 | Hobbyhistoriker:in | 📖 Computer‑Recherche · 📖 TV‑Nachrichten · 📖 Sachbuch · 📖 Museum · 🟩 **Blogeintrag** *[L1‑L2]* · 🟪 Geschichts‑Sozial | 🟩 Blogeintrag · 📖 Sachbuch · 📖 Museum | 🟩 Blogeintrag · 📖 Computer‑Recherche · 📖 Sachbuch · 📖 TV‑Nachrichten · 🟪 Geschichts‑Sozial |
| 2 | Museumswärter:in | 📖 Computer‑Recherche · 📖 Sachbuch · 📖 Museum · 🟩 **Blogeintrag** *[L1‑L2]* · 🟩 **Objektgeschichte** *[L2]* · 🟪 Geschichts‑Sozial | 🟩 Blogeintrag · 🟪 Geschichts‑Sozial | 🟩 Blogeintrag · 🟩 Objektgeschichte · 📖 Computer‑Recherche · 📖 Sachbuch · 🟪 Geschichts‑Sozial |
| 3 | Praktikant:in | 📖 Computer‑Recherche · 📖 Sachbuch · 🟩 **Bücherregal‑Recherche** *[L3‑L9]* · 🟩 **Cross‑Reference** *[L3‑L4]* · 🟪 Geschichts‑Sozial | 🟩 Bücherregal‑Recherche · 🟪 Geschichts‑Sozial | 🟩 Bücherregal‑Recherche · 🟩 Cross‑Reference · 📖 Computer‑Recherche · 📖 Sachbuch · 🟪 Geschichts‑Sozial |
| 4 | Volontariat | 📖 Computer‑Recherche · 🟩 Bücherregal‑Recherche *[L3‑L9]* · 🟩 Cross‑Reference *[L3‑L4]* · 🟩 **Bildrechte** *[L4]* · 🟩 **Online‑Fortbildung** *[L4]* · 🟦 **Transcribe** *[L4‑L6]* · 🟩 **Zeitzeugen** *[L4‑L8]* · 🟪 Geschichts‑Sozial | 🟦 Transcribe · 🟩 Zeitzeugen | 🟦 Transcribe · 🟩 Zeitzeugen · 🟩 Bildrechte · 🟩 Online‑Fortbildung · 🟩 Bücherregal‑Recherche |
| 5 | Wiss. Hilfskraft | 📖 Computer‑Recherche · 🟩 Bücherregal‑Recherche *[L3‑L9]* · 🟦 Transcribe *[L4‑L6]* · 🟦 **Analyze Source** *[L5‑L7]* · 🟩 Zeitzeugen *[L4‑L8]* · 🟪 Geschichts‑Sozial | 🟦 Transcribe · 🟩 Zeitzeugen | 🟦 Transcribe · 🟦 Analyze Source · 🟩 Zeitzeugen · 🟩 Bücherregal‑Recherche · 📖 Computer‑Recherche |
| 6 | Doktorand:in | 📖 Computer‑Recherche · 🟩 Bücherregal‑Recherche *[L3‑L9]* · 🟦 Transcribe *[L4‑L6]* · 🟦 Analyze Source *[L5‑L7]* · 🟩 Zeitzeugen *[L4‑L8]* · 🟪 Geschichts‑Sozial | 🟦 Analyze Source · 🟦 Transcribe · 🟩 Zeitzeugen | 🟦 Analyze Source · 🟦 Transcribe · 🟩 Zeitzeugen · 🟩 Bücherregal‑Recherche · 📖 Computer‑Recherche |
| 7 | Postdoc | 📖 Computer‑Recherche · 🟩 Bücherregal‑Recherche *[L3‑L9]* · 🟦 Analyze Source *[L5‑L7]* · 🟦 **Symposium** *[L7‑L8]* · 🟩 Zeitzeugen *[L4‑L8]* · 🟪 Geschichts‑Sozial | 🟦 Symposium · 🟦 Analyze Source · 🟩 Zeitzeugen | 🟦 Symposium · 🟦 Analyze Source · 🟩 Zeitzeugen · 🟩 Bücherregal‑Recherche · 📖 Computer‑Recherche |
| 8 | Juniorprofessor:in | 📖 Computer‑Recherche · 🟩 Bücherregal‑Recherche *[L3‑L9]* · 🟦 Symposium *[L7‑L8]* · 🟦 **Habilitation Lecture** *[L8‑L9]* · 🟩 Zeitzeugen *[L4‑L8]* · 🟪 Geschichts‑Sozial | 🟦 Habilitation Lecture · 🟦 Symposium · 🟩 Zeitzeugen | 🟦 Habilitation Lecture · 🟦 Symposium · 🟩 Zeitzeugen · 🟩 Bücherregal‑Recherche · 📖 Computer‑Recherche |
| 9 | W3 Professor:in | 📖 Computer‑Recherche · 🟩 Bücherregal‑Recherche *[L3‑L9]* · 🟦 Habilitation Lecture *[L8‑L9]* · 🟦 **Supervise** *[L9‑L10]* · 🟪 Geschichts‑Sozial | 🟦 Supervise · 🟦 Habilitation Lecture | 🟦 Supervise · 🟦 Habilitation Lecture · 🟩 Bücherregal‑Recherche · 📖 Computer‑Recherche |
| 10 | Direktor:in | 📖 Computer‑Recherche · 🟦 Supervise *[L9‑L10]* · 🟩 **Drittmittel** *[L10]* · 🟪 Geschichts‑Sozial | 🟩 Drittmittel · 🟦 Supervise | 🟩 Drittmittel · 🟦 Supervise · 📖 Computer‑Recherche · 🟪 Geschichts‑Sozial |

Legend: 🟦 existing affordance in v0.1 tuning · 🟩 new custom affordance to build · 🟪 career‑wide social overlay · 📖 EA vanilla. Bracketed `[Lx–Ly]` shows the rank band where each custom affordance is mechanically available.

**Build cost** — 8 new custom affordances + 5 existing (re‑banded) + 2 career‑wide social overlays:

| New | Object surface |
|---|---|
| 🟩 Blogeintrag schreiben (L1–L2) | Computer |
| 🟩 Objektgeschichte recherchieren (L2) | Museum / gallery exhibit object |
| 🟩 Recherchieren am Bücherregal (L3–L9) | Bookshelf |
| 🟩 Cross‑Reference Sources at Bookshelf (L3–L4) | Bookshelf |
| 🟩 Bildrechte recherchieren (L4) | Computer |
| 🟩 Online Fortbildung teilnehmen (L4) | Computer |
| 🟩 Zeitzeugen‑Interview (L4–L8) | Social, Elder target |
| 🟩 Acquire Drittmittel (L10) | Computer |
| 🟪 Drop a History Fact | Small Talk overlay |
| 🟪 Tell a Historical‑Reference Joke | Tell Joke overlay |

The 5 existing affordances ([HC_Interaction_*.xml](../Tuning/)) get new rank‑band tests but their loot, names, and behaviour are unchanged from v0.1.

## Skill gates and promotion requirements

The career uses three existing EA skills — **Writing**, **Research & Debate** (Discover University), and **Charisma** — to gate promotions. **No new skill is introduced.** Charisma is capped at level 5 for promotion gates: lower‑rank social work (L2 Museumswärter:in) and the leadership capstone (L10 Direktor:in) need it; the academic middle is Charisma‑neutral.

| Promotion | Skill gate (in addition to performance) |
|---|---|
| L1 → L2 | Writing ≥ 2 **and** Charisma ≥ 1 |
| L2 → L3 | *(open — see Open design questions)* |
| L3 → L4 | *(open)* |
| L4 → L5 | *(open)* |
| L5 → L6 | *(open)* |
| L6 → L7 | Research & Debate ≥ 7 |
| L7 → L8 | Writing ≥ 7 |
| L8 → L9 | **Habilitation**: Research & Debate = 10 **and** Writing = 10 |
| L9 → L10 | Charisma ≥ 5 |

Implemented via `block_promotion_tests` on the Career resource ([`career_level_Adult_Historian_L3.xml:7-9`](../Tuning/career_level_Adult_Historian_L3.xml) flagged this as the canonical place; v0.2 implements it).

## Social interactions

**Career‑wide flavour overlays** at every rank. Custom‑injected on EA's existing Small Talk and Tell Joke socials. Either can satisfy the "Geschichts‑Sozial" daily‑task pool item.

**One rank‑gated career social: Zeitzeugen‑Interview.** Custom social affordance, band **L4 Volontariat → L8 Juniorprofessor:in**. Target requirement: **Elder Sim**. Ticks Research & Debate and Charisma. Daily‑task pool option at every rank in the band.

The v0.1 design proposed a two‑tier split (Junior at L3 / Academic at L7) plus a separate "Discuss Habilitation Plans" affordance and a third reserved slot. **All three of those are dropped.** One Zeitzeugen‑Interview affordance with a five‑rank band is simpler, matches the gameplay direction, and avoids duplicate content for similar verbs.

## Bookshelf research

Two bookshelf affordances, both injected onto EA bookshelves via the `.ts4script`:

- 🟩 **Recherchieren am Bücherregal** — the main bookshelf‑research affordance. Band L3–L9. Ticks Research & Debate. Daily‑task pool option at L3 Praktikant.
- 🟩 **Cross‑Reference Sources at Bookshelf** — a specialized lookup activity. Band L3–L4. Home Office and WFH pool only; **not** in the daily‑task pool.

The custom statistic `HC_Stat_BookshelfResearch` introduced for v0.1 is **probably redundant now** — `SimRanInteraction`‑based objectives can drive the daily‑task pool entries directly without a counter. See §Open design questions.

## Reward traits

**Habilitation Renown** — reward trait granted on completion of the long aspiration *Historian's Calling* (which itself completes around the L8 → L9 Habilitation promotion in the new numbering). Small passive +Focused buff in libraries. Unchanged from v0.1 in concept, just relocated from "L5" (old) to "L9" (new).

A second top‑rank trait (Lebenswerk‑Renommee or Institutsdirektor:innen‑Renommee at L10) is v1.x polish, not v0.2.

## Chance cards

One chance card ships: **Plagiatsvorwurf** ("A Plagiarism Accusation"), unchanged from v0.1.

Two more — Conference Invitation and Drittmittel Grant Application — are stubbed as design but not yet implemented. The Drittmittel chance card now has a natural mechanical anchor (the L10 *Acquire Drittmittel* affordance), so it likely lands in v0.3.

## Languages

English and German strings ship in v0.1 (`Build/s4tk-builder/strings.json`). The 10‑rank expansion adds ~30 STBL keys per language (level titles, descriptions, new affordance names + tooltips, Direktor:in capstone description). Translation effort stays a single 80‑key pass per added locale.

## Things deliberately *not* in scope

- **A custom skill.** The career uses existing EA skills (Research & Debate, Writing, Charisma). No "Historiography" skill.
- **Per‑level outfits.** EA's default Adult outfits are used. Custom uniforms are a v1.1 polish item.
- **The other two chance cards.** Plagiarism only in v0.2; Conference Invitation and Drittmittel for later.
- **Per‑employer perks.** The five institutions are flavour; per‑employer buffs (Bundesarchiv Archive Access etc.) are v1.x.
- **A real L10 branch.** Direktor:in is a single rank that flavour‑encompasses the four real "what comes after a W3 Prof" possibilities. A `branch_selection` block letting the player pick is additive — can be added later without breaking existing saves.
- **A second top‑rank reward trait.** Habilitation Renown lands at L9 as before; an L10 Lebenswerk trait is v1.x.

## Open design questions

Three decisions surfaced during the 10‑rank design pass that are not yet locked:

1. **Intermediate skill gate density.** Locked gates: L1→L2, L6→L7, L7→L8, L8→L9, L9→L10 (five of nine promotions gated). The four promotions in between (L2→L3, L3→L4, L4→L5, L5→L6) are currently performance‑only. Should they get gates too? *Denser* — every promotion is a measurable "level up your skill" beat, feels academic. *Sparser* — gentler for casual players, fewer ways to feel stuck.
2. **Museum‑exhibit affordance injection feasibility.** Objektgeschichte recherchieren (L2) injects onto EA museum / gallery exhibit objects. The exact EA object tags and injection target need verification — if the injection surface is fragile, the affordance moves to a more stable object (bookshelf? computer with a "browse museum catalogue" framing?).
3. **HC_Stat_BookshelfResearch — keep or drop.** v0.1 introduced this custom statistic for bookshelf‑research objectives. With the script‑driven daily‑task rotation, `SimRanInteraction` objectives are sufficient and the statistic is redundant. Open: drop and remove the file, or keep for v0.2 forward‑compatibility if a future feature would want a long‑term counter.

## Attribution

The scaffold structure (Tuning/Scripts/Docs layout, the Python notification helper) is inspired by [rhavari22/UXMod‑Sims4](https://github.com/rhavari22/UXMod-Sims4) (MIT). All Historian XML is original; no EA/Maxis assets are redistributed. See [`NOTICE.md`](../NOTICE.md).
