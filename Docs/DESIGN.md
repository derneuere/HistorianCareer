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

**Layer A — pie‑menu interactions on computers.** Run "Transcribe Manuscript", "Analyze Primary Source", "Present at Symposium", "Habilitation Lecture", "Supervise Dissertation" directly from any computer. Each grants money, a buff, and ticks a custom statistic; a bilingual promotion popup fires at each tier. Designed for Sims who don't want to leave the house.

**Layer B — the actual job.** Apply via phone → Find a Job → Historian. Full work schedule, daily tasks, chance cards, the long aspiration *Historian's Calling*, and the W3 reward trait. The 5‑rank progression mirrors Layer A's tier promotions.

You can play with one or both. Layer B does not require the `.ts4script` (the Python‑side affordance injector). Layer A does.

## Daily tasks per rank

The career UI's daily‑task panel pulls from per‑level aspirations.

| Rank | Tasks |
|---|---|
| L1 HiWi | Read a non‑fiction book; Transcribe a manuscript ×2 |
| L2 Doktorand:in | Analyze a primary source; Transcribe a manuscript ×2 |
| L3 Postdoc | Present at a symposium; Analyze a primary source |
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

## Attribution

The scaffold structure (Tuning/Scripts/Docs layout, the Python notification helper) is inspired by [rhavari22/UXMod‑Sims4](https://github.com/rhavari22/UXMod-Sims4) (MIT). All Historian XML is original; no EA/Maxis assets are redistributed. See [`NOTICE.md`](../NOTICE.md).
