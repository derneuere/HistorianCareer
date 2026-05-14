# Design — Historian Career

Why this mod exists, how its five ranks map to the German academic system, and the small set of design decisions worth flagging.

## The career: German *Karriereleiter* in five ranks

Most Sims 4 careers are 10‑level corporate ladders. The Historian career is single‑track with five ranks, because that is what the German academic system actually looks like.

| L | German | English (in‑game) | Pay/h | Promotion gate (in addition to performance) |
|---|---|---|---|---|
| 1 | Wissenschaftliche Hilfskraft | Research Assistant (HiWi) | §40 | Completed History major |
| 2 | Doktorand:in | PhD Candidate | §70 | — |
| 3 | Postdoktorand:in / Wiss. Mitarbeiter:in | Postdoctoral Researcher | §120 | Research & Debate ≥ 7 |
| 4 | Juniorprofessor:in / Habilitand:in | Junior Professor | §200 | Writing ≥ 7 |
| 5 | Professor:in (W3) | Full Professor | §340 | Research & Debate = 10 **and** Writing = 10 (Habilitation) |

No branches. The German *Karriereleiter* is linear; mid‑career specialisation happens through the *Habilitation*, modelled here as the L4→L5 gate.

Reward trait at L5: **Habilitation Renown** — a small passive +focused buff in libraries.

## University prerequisite

The career is gated on a **completed History major** from the *Discover University* expansion. This is enforced two ways:

1. **At hire** — the `career_availability_test` block in `career_Adult_Historian.xml` checks for a History‑degree trait. If the Sim does not have it, the career does not appear in the phone's "Find a Job" dialog.
2. **At pie‑menu entry** — the L1 interaction `HC_Interaction_TranscribeManuscript` runs the same test, so the optional Layer A workflow (without joining the career) is also degree‑gated.

The exact EA trait name (`trait_University_Major_History_Completed`) is the most likely candidate and we use it as a placeholder; if a game patch renames it, change one string in two XML files. See [`Docs/IMPLEMENTATION_GUIDE.md`](IMPLEMENTATION_GUIDE.md) §2 for resolving it in Sims 4 Studio if needed.

## Two layers, by intent

The mod ships two complementary feature sets that work independently:

**Layer A — custom interactions, anywhere.** Pie‑menu work the Sim can run outside of scheduled hours:
- *Computer affordances* — "Transcribe Manuscript", "Analyze Primary Source", "Present at Symposium", "Habilitation Lecture", "Supervise Dissertation".
- *Bookshelf affordances* — "Cross‑Reference Sources" (see §Bookshelf research, below).
- *Social affordances* — career‑themed overlays on existing EA socials, plus a small set of rank‑gated career socials (see §Social interactions, below).

Each grants money or a buff (or both), ticks a custom statistic, and contributes to Layer B's daily tasks where applicable. A bilingual promotion popup fires at each tier.

**Layer B — the actual job.** Apply via phone → Find a Job → Historian. Full work schedule, daily tasks, chance cards, the long aspiration *Historian's Calling*, and the W3 reward trait. The 5‑rank progression mirrors Layer A's tier promotions.

You can play with one or both. Layer B does not require the `.ts4script` (the Python‑side affordance injector). Layer A does, because injection is how the custom affordances get attached to EA's computer, bookshelf, and social super‑affordance lists.

## Employers — five German academic institutions

When a Sim joins the career the runtime picks one of the following as their employer at random (`career_location.company_names` in `career_Adult_Historian.xml`). They drive flavour, not mechanics — the daily tasks and pay are identical across employers.

| Employer | Flavour |
|---|---|
| Universität Berlin | Generalist teaching university; the "default" academic posting. |
| Stiftung Preußischer Kulturbesitz | Foundation behind Berlin's state museums and libraries; archive‑ and exhibition‑leaning. |
| Bundesarchiv | Federal archive; deep document work, the most archive‑heavy posting. |
| Humboldt‑Institut für Geschichtswissenschaften | Pure research institute; conference and publication focus. |
| Leibniz‑Gesellschaft | Grant‑driven research association; project‑funded historian. |

Per‑employer perks (e.g. an Archive Access buff at the Bundesarchiv) are out of scope for v0.1.

## Social interactions

Two tiers, both gameplay‑focused:

**Career‑themed flavour overlays.** Added to existing EA socials and available to any Sim with the Historian career (or, optionally, the History‑major trait — gating TBD in tuning):
- *Drop a History Fact* — added to the Small Talk branch; pulls a random line from a localised pool.
- *Tell a Historical‑Reference Joke* — added to the Tell Joke / Funny branch; mild +Playful, very small Charisma tick.

These are pure flavour: no money, no daily‑task counter. They exist so that being a historian feels visible in idle conversation.

**Rank‑gated career socials.** Appear on the pie menu only when the actor's career rank — and, where noted, the target's age/career — match:

| Interaction | Unlocks at | Target requirement | Effect |
|---|---|---|---|
| *Conduct Zeitzeugen‑Interview* | L3 Postdoc | Elder Sim | Builds Research & Debate; ticks the L3 "Analyze a primary source" daily‑task counter. |
| *Discuss Habilitation Plans* | L4 Junior Prof | Has History‑major trait **or** is in the Historian career | Builds Writing; small +Focused for both Sims. |
| (one reserved slot) | TBD | TBD | TBD |

Gating is implemented as `test` blocks on the affordance, the same pattern already used by the L1 computer interaction.

## Bookshelf research interactions

The mod injects custom affordances onto EA bookshelf objects via the `.ts4script` affordance injector. Bookshelf research is **its own daily‑task track**, with its own statistic (`HC_Stat_BookshelfResearch`) — not a substitute for the computer "Analyze a Primary Source" interaction.

- *Cross‑Reference Sources at Bookshelf* — slow, Focused‑mood interaction; no money; ticks `HC_Stat_BookshelfResearch`. Available from L2.

The daily‑task table below adds a "Cross‑reference sources at a bookshelf" line at the ranks where it applies.

## Daily tasks per rank

The career UI's daily‑task panel pulls from per‑level aspirations.

| Rank | Tasks |
|---|---|
| L1 HiWi | Read a non‑fiction book; Transcribe a manuscript ×2 |
| L2 Doktorand:in | Analyze a primary source; Transcribe a manuscript ×2; Cross‑reference sources at a bookshelf |
| L3 Postdoc | Present at a symposium; Analyze a primary source; Cross‑reference sources at a bookshelf |
| L4 Juniorprofessor:in | Deliver a Habilitation lecture; speak at a symposium |
| L5 Professor:in | Supervise a dissertation; keep publishing |

## Chance cards

One chance card ships in v0.1: **Plagiatsvorwurf** ("A Plagiarism Accusation"). Two response options, one of which has a 50/50 outcome (career performance gain on a successful stonewall vs. demotion on a failed one).

Two more — Conference Invitation and Drittmittel Grant Application — are stubbed as design but not yet implemented.

## Languages

English and German strings ship in v0.1 (`Build/s4tk-builder/strings.json`). Adding a locale is a 50‑key translation pass; the build re‑emits the STBL automatically.

## Things deliberately *not* in scope

- **Per‑level outfits.** EA's default Adult outfits are used. Custom uniforms are a v1.1 polish item.
- **A custom skill.** The career uses existing EA skills (Research & Debate, Writing) rather than introducing "Historiography" — keeps the install footprint small and avoids needing to balance a fresh skill.
- **The other two chance cards.** Plagiarism is the most thematically loaded; the others can be added in a content patch.
- **Per‑employer perks.** The five institutions are flavour in v0.1; an Archive Access buff at the Bundesarchiv, conference‑travel buffs at the Humboldt‑Institut, etc. are a v1.x idea.
- **The third rank‑gated social.** Two ship in v0.1 (Zeitzeugen‑Interview, Habilitation Plans); the third reserved slot is left open for playtest feedback.

## Attribution

The scaffold structure (Tuning/Scripts/Docs layout, the Python notification helper) is inspired by [rhavari22/UXMod‑Sims4](https://github.com/rhavari22/UXMod-Sims4) (MIT). All Historian XML is original; no EA/Maxis assets are redistributed. See [`NOTICE.md`](../NOTICE.md).
