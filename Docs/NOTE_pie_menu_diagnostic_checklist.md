# NOTE — Pie-menu submenu still flat in-game: diagnostic checklist

**Audience:** anyone reporting that the 5 Historian computer interactions appear ungrouped (flat) in the pie menu, while at least one earlier build did show the "Historiker:in" submenu correctly.
**Status:** active reference. Covers issue #21.

## TL;DR

If the pie menu shows all 5 interactions but they're flat — not nested under a "Historiker:in" submenu — and you previously saw the submenu work on an older build of this mod, the regression is **almost certainly environmental** (save state or game cache), not a package-side bug. The diagnostic tool below validates the package; the four-step recovery further down restores a clean game environment.

## Run the package validator first

```
node Build/s4tk-builder/inspect-pie-menu.mjs
```

This reads `Build/out/HistorianCareer_Tuning.package` and checks every field the Olympus pie-menu UI cares about (PMC tuning TGI, PMC SimData companion, schema hash 0x022065C1, all 7 columns, all 5 SuperInteractions referencing the category). To inspect the package that's actually installed in your Mods folder:

```
node Build/s4tk-builder/inspect-pie-menu.mjs "$HOME/Documents/Electronic Arts/Die Sims 4/Mods/HistorianCareer/HistorianCareer_Tuning.package"
```

Adjust the path for English / French / Spanish folders ("The Sims 4" / "Les Sims 4" / "Los Sims 4").

If the script reports `FAIL`, the package is malformed — file a bug against this mod with the script's output.
If the script reports `PASS`, the package is byte-correct and the next section applies.

## Why a "package PASS" can still produce a flat pie menu in-game

The Olympus Flash UI builds its `InteractionMenuData` category map once at game launch, then again at any subsequent reload of the package list. Even with a correct package:

1. **Save corruption from earlier experiments.** Saves persist references to instance IDs the game has seen before. If a save was opened while an older build with different IDs was installed (most commonly: the small-ID aspiration experiment with instances 99800–99803 from issue #17), the save can hold stale per-object interaction routing. This survives across mod rebuilds because saves aren't in the cache files.

2. **Cache files predate the current package.** Sims 4's `localthumbcache.package`, `Onlinethumbnailcache.package`, `avatarcache.package`, and the contents of `cachestr/` + `cache/` snapshot some of the binary indexes the UI consults. `node Build/build.mjs` now clears these on every install, but if a save was loaded before the clean install (or you launched the game during a partial build), you can be holding cached state from before the fix.

3. **Game wasn't fully restarted.** If you reinstalled the mod while Sims 4 was running, the UI registries are not re-read.

## Recovery checklist (do in order; stop when the submenu reappears)

The point of this list is to isolate save-state from cache from package. Use the package validator (see above) to confirm `PASS` before running these — there's no point chasing environment if the package itself is wrong.

### Step 1 — Hard reinstall + cache nuke + cold restart

```
# Close Sims 4 completely (Task Manager → end TS4_x64.exe / Sims4.exe if needed).
node Build/build.mjs
# build.mjs default already: builds, installs, clears caches.
# Wait until "[ok]" prints and the process exits cleanly.
# Launch The Sims 4 fresh — DO NOT load any existing save yet.
```

Then **start a brand-new game** (Saves → New). Load any household onto a lot, place a computer, right-click it.

- If the "Historiker:in" submenu IS visible in the new save → confirmed save-state contamination on the older save. See Step 2 to recover.
- If the submenu is still missing in a new save → something is wrong upstream; re-run the package validator on the installed copy (path above) and inspect the output.

### Step 2 — Test the suspected-contaminated save in isolation

```
# Make a backup of your current Saves folder first.
cp -r "$HOME/Documents/Electronic Arts/Die Sims 4/saves" \
      "$HOME/Documents/Electronic Arts/Die Sims 4/saves.backup-$(date +%Y%m%d)"
```

Then in-game, load the suspect save (the one that has been opened with prior mod builds), travel to a lot that you have NEVER opened in this save, place a fresh computer, right-click it.

- If the new computer DOES show the submenu but the old one doesn't → the per-object routing on that specific computer is stale. Delete and replace that one object via build mode. (`bb.moveobjects on` and `bb.showhiddenobjects` can help with stuck props.)
- If even a fresh object on a fresh lot in the existing save STILL doesn't show the submenu → the save's interaction registry is corrupted. Save → quit → manually patch by either (a) starting from a save backup made before the mod was first installed or (b) using a save-editor like Sims4ModManager / Sims 4 Studio's save tools to clear the cached interaction map.

### Step 3 — Confirm Mods folder isn't shadowing the build

If you've ever manually copied .package files into the Mods folder during prior dev/test rounds, an older HistorianCareer*.package may still be sitting in a sibling subfolder. Sims 4 loads every .package under `Mods/` recursively up to depth 5. List them all:

```
find "$HOME/Documents/Electronic Arts/Die Sims 4/Mods" -name "HistorianCareer*"
```

There should be exactly one `.package` and one `.ts4script` (both under `Mods/HistorianCareer/`). If you see additional copies anywhere else under `Mods/`, delete them. The build script writes only the canonical path; duplicates are leftovers.

### Step 4 — Confirm via Python-side diagnostic

If steps 1-3 don't restore the submenu, the next step is server-side Python introspection. Drop the snippet from `Docs/NOTE_pie_menu_category_registration.md` § "What Python injection IS useful for" into a small `Scripts/historian_career/diagnostics.py`, rebuild, and check `lastException.txt` after a load. The expected output line:

```
[HC] PMC loaded: name=HC_PieMenuCategory_Historian guid64=1653363664 key=<resource_key>
```

If that line is missing, the PMC isn't registering at all — file an upstream issue.
If that line is present but the UI still doesn't group → the Olympus SWF lookup is failing despite a registered PMC; this is the harder failure mode and requires JPEXS Free Flash Decompiler to inspect `InteractionMenuData/FetchCategory()` in the client SWF.

## What the package actually contains (reference)

The validator confirms these entries in every successful build (verified against commit `6b4e72f`, the "regressed" commit per issue #21 — its package wiring is byte-correct):

| Resource | TGI | Notes |
|---|---|---|
| PMC tuning | type=0x03E9D964 group=0 instance=0x628c53d0 | `<I c="PieMenuCategory" n="HC_PieMenuCategory_Historian" s="1653363664">` |
| PMC SimData | type=0x545AC67A group=**0x00E9D967** instance=0x628c53d0 | schema hash 0x022065C1; group is class-specific (NOT 0) |
| SuperInteraction × 5 | type=0xE882D22F (Tuning) various instances | each carries `<T n="category">1653363664</T>` + `interaction_category_tags` |

The PMC SimData columns the validator reads back:

| Column | Type | Value |
|---|---|---|
| `_collapsible` | bool | `true` (required for submenu rendering) |
| `_display_name` | LocalizationKey | `0x58F3DC50` (STBL key for "Historiker:in") |
| `_display_priority` | int32 | `0` |
| `_icon` | ResourceKey | empty (acceptable; no submenu icon) |
| `_parent` | TableSetReference | `0n` = null (top-level category) |
| `_special_category` | uint32 | `0` (NO_CATEGORY) |
| `mood_overrides` | vector | empty |

If the package validator reports any other layout, the package is wrong and the in-game flat-menu symptom is the correct downstream effect.

## Provenance

- Issue #21 — pie-menu submenu regressed after commit 6b4e72f.
- Issue #14 — original investigation that established the 31-bit ID pattern and `interaction_category_tags` requirement.
- `Docs/NOTE_pie_menu_category_ids.md` — small-ID resolver design.
- `Docs/NOTE_pie_menu_category_registration.md` — root-cause analysis of the SimData companion requirement.
- `Build/s4tk-builder/inspect-pie-menu.mjs` — the validator referenced throughout this checklist.
