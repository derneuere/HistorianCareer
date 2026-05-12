# Implementation Guide — Historian Career

This is the runbook for turning the files in `Tuning/` and `Scripts/` into a working in‑game mod.

## Two build paths

| Path | What you get | Tools needed |
|---|---|---|
| **CLI build (Layer A)** | Drop‑in `.package` with all 5 pie‑menu interactions + statistic + script injector | Node 16+, Python 3.7.x |
| **S4S build (Layer B)** | Full `Career` tuning (5 ranks, daily tasks, schedule, aspiration, trait, chance card) | Sims 4 Studio (for SimData) |

The CLI build uses `@s4tk/models` to author the `.package` directly — no Sims 4 Studio required. See **§1 CLI build** below.

The S4S build extends the CLI output with SimData companions that the Layer B tuning classes need to load. See **§2 S4S build (Layer B)**.

## Prerequisites
- The Sims 4 with the **Discover University** EP installed (required by design — the career gates on a History major).
- **Node 16+** for the CLI build.
- **Python 3.7.x** on PATH for the `.ts4script` (skip with `-PackageOnly` if you don't have it).
- **Sims 4 Studio** (Wishes / Open Beta channel) — only needed for Layer B SimData generation.
- ~~XML Injector~~ — **no longer needed.** Replaced by `Scripts/historian_career/affordance_injector.py`.

---

## 1) CLI build (Layer A — drop-in)

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File Build\build.ps1
```

That runs two stages:

1. **`Build/s4tk-builder/build-package.mjs`** — reads every XML in `Tuning/` and `Build/s4tk-builder/strings.json`, hashes each tuning name with FNV‑64 to compute the Instance ID, hashes each STBL key with FNV‑32, replaces the `TBD_INSTANCE_ID` / `0xTBD_STBL_KEY_*` placeholders inline, wraps each XML in an `XmlResource`, and writes the result to `Build/out/HistorianCareer_Tuning.package`. By default only Layer A resources are included so the package loads cleanly without SimData.
2. **`build.ps1`** — compiles `Scripts/historian_career/*.py` to `.pyc` and zips it into `Build/out/HistorianCareer.ts4script`.

To install to the Mods folder in the same step:
```powershell
powershell -ExecutionPolicy Bypass -File Build\build.ps1 -InstallToMods
```

The History‑degree trait reference in `HC_Interaction_TranscribeManuscript.xml`
(`trait_University_Major_History_Completed`) is a placeholder. To resolve it:

1. In Sims 4 Studio → **Tools → Game File Cruiser** → search the trait list for `trait_university` and look for the History major's completion trait. EA's naming has drifted between EP patches.
2. If you find the canonical name, paste it in the XML and rebuild.
3. If you can't find it, leave the trait name as is **and** rely on the safety‑net Python check in
   `historian_career.py::sim_has_history_degree`.

---

## 2) S4S build (Layer B)
For the Career/Aspiration/Trait/etc. resources to load in‑game, each needs a binary SimData companion. The CLI builder doesn't generate these (it would require re‑implementing the per‑class SimData schemas that S4S has hardcoded). Steps:

1. **Build the full‑set package** including Layer B XMLs:
   ```powershell
   cd Build\s4tk-builder
   node build-package.mjs --include-layer-b
   ```
2. Open the resulting `Build/out/HistorianCareer_Tuning.package` in Sims 4 Studio.
3. For each Layer B resource (Career, CareerTrack, CareerLevel ×5, AspirationCareer ×5, AspirationTrack, Aspiration ×4, Trait, Objective ×6, CareerChanceCard): right‑click → **Generate SimData**.
4. **Save** the package (S4S writes the SimData binaries back into the same file).
5. Copy to `Documents\Electronic Arts\The Sims 4\Mods\HistorianCareer\`.

### Layer B reference order (when adding by hand instead of from XML)
S4S resolves `<T>name</T>` references at load time, but it's easier to debug if you import in dependency order:
1. Objectives (`objective_HC_*`)
2. Per‑level aspirations (`aspiration_career_Historian_L1..L5`)
3. Trait (`trait_HabilitationRenown`)
4. Long aspirations (`aspiration_HistorianCalling_T1..T4` then `aspiration_track_HistorianCalling`)
5. Chance card (`career_chance_card_Historian_Plagiarism`)
6. Career levels (`career_level_Adult_Historian_L1..L5`)
7. Career track (`career_track_Adult_Historian`)
8. Career (`career_Adult_Historian`) **last** — every reference it makes must exist first.

---

## 3) Install and run

```powershell
powershell -ExecutionPolicy Bypass -File Build\build.ps1 -InstallToMods
```

This copies whatever's in `Build/out/` to `Documents\Electronic Arts\The Sims 4\Mods\HistorianCareer\`. After install:

1. Delete `Documents\Electronic Arts\The Sims 4\localthumbcache.package`.
2. Launch the game. **Options → Other → Enable Script Mods**. Restart.
3. Load any save with a young‑adult+ Sim who completed the **History** major.
4. Right‑click a computer → there should be a **Historian** pie menu sub‑category.
5. Run **Transcribe Manuscript** → expect §, a small focused buff, and a promotion popup the
   moment the statistic hits 1 ("Sie sind jetzt Wissenschaftliche Hilfskraft").
6. Repeat to climb. Sims **without** the History major should not see the pie menu items at all
   (the `test_globals` filter hides them).

## 5) Verify in‑game
See [`TESTING.md`](TESTING.md) for the full cheat‑driven test plan (smoke test, Layer A pie menu, Layer B career flow, negative tests, and the cheat cheat‑sheet).

## 6) Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No "Historian" pie menu | Sim doesn't have the History major trait, or the placeholder trait name didn't resolve | Confirm trait name in step 2; or temporarily comment out the `test_globals` block to verify everything else works first |
| Pie menu present but interactions greyed out | Statistic/skill gates not met | Run the previous level first; or `stats.set_skill_level Major_ResearchDebate 10` in cheats console |
| `LastException.txt` appears | Usually a tuning ID collision or unresolved reference | Open in a text editor, search for `HC_`. Re‑hash any duplicate Instance IDs in S4S |
| Script mods disabled message | Forgot to enable in Options | Options → Other → Enable Script Mods + restart |
| Notifications never fire | Statistic listener not wired (Layer A relies on a manual trigger) | Layer A fires notifications only from the script when called. Wire `check_and_notify_promotion` to the statistic's `add_callback` in a later patch, or call it from a custom LootAction that runs after the stat increment |
