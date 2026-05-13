# NOTE — Why our custom AspirationTrack is invisible in the CAS aspiration picker, part II

**Status:** research + tooling change (no XML/SimData change).
**Builds on:** `Docs/NOTE_aspiration_track_registration.md` (part I — the YAE_ONLY → TEEN_OR_OLDER fix).
**Confidence:** **HIGH** on what the CAS picker is and what it reads. **MEDIUM** on the residual failure mode after part I — the most likely explanation now is a runtime serialisation crash in EA's Olympus AS3, not a binary-index gating issue. See the lastUIException grep in §5.

## TL;DR

1. The user's hypothesis from the issue-17 follow-up comment was that the CAS picker is "binary-indexed in the Olympus client" and that mod-added aspirations may need a Python script-side runtime injection. **That framing is half-right and half-wrong.**
2. The CAS picker IS a Scaleform/GFX AS3 widget at `(UI.package, type=0x62ECC59A, instance=0x7d5fa9e0c2a4f038)`. The widget calls `CommunicationManager.CallGameService("CasGetAspirationCategories")`, `CasGetAspirationTracksByCategory({categoryId:N})`, `CasGetFTUEAspirationTracks`, and `GetAspirationTrackStaticData` to enumerate tracks.
3. Those four "GameService" calls are **NOT** Python handlers. We grep'd every `.pyc` in `simulation.zip` + `core.zip` + `base.zip` and not one of them registers any of those names. The names live as plain UTF-8 strings inside `TS4_x64.exe` at file offsets `0x1dfc890`, `0x1e69748`, `0x1e69768`, `0x1e69790` — i.e. the service dispatch is handled **natively by the C++ engine**.
4. The native engine reads `AspirationTrack` rows from SimData resources at type `0x545AC67A`, group `0x0020FC6D`, instance = track id. EA ships 27 of these in `ClientFullBuild0.package` and 38 more in `ClientDeltaBuild0.package`. **Our mod ships exactly one at `(0x545AC67A, 0x0020FC6D, 0x6621FF4B)` — the correct shape.** It is enumerated by the same resource-cfg pipeline that picks up base-game packages: the user's `Documents/Electronic Arts/Die Sims 4/Mods/Resource.cfg` declares Priority 500 and globs the whole tree.
5. Our SimData payload is byte-equivalent to EA's pattern. Same schema name (`AspirationTrack`), same schema hash (`0x54FDB5FC`), same 9 columns (`aspirations`, `category`, `description_text`, `display_text`, `icon`, `icon_high_res`, `mood_asm_param`, `primary_trait`, `reward`), same nested schema (`aspirations` ↔ `AspirationsMappingTuple`, hash `0xFB8C84BC`), same row layout. Verified by `Build/_research_tmp/compare-track-simdata.mjs` and a side-by-side hex diff of the bytes.
6. The previous agent's claim that "the SimData is byte-equal to EA's pattern" is correct.

So why does the CAS picker still not show our track post-TEEN_OR_OLDER fix?

**The strongest candidate now is a runtime AS3 desync in `INIT_DATA()`** — see §5. The user's `lastUIException.txt` shows a `#1009 null reference` crash at exactly `gamedata.Gameplay.shared.definitions::AspirationTrackStaticData/INIT_DATA()`. If that fires while parsing the `GetAspirationTrackStaticData` payload, the cached `sTracksPerCategory` map is left *uninitialised* (the function returns early on error), and from that moment on `GetTrackData(uid)` and `GetTracksInCategory(catId)` both return null — i.e. **no aspiration tracks render**, ours OR EA's. The CAS picker UI silently falls back to the empty state and the player sees no tracks under any category. (Empirically — we can't fully verify this without an in-game retest — the user reports the EA tracks DO render, which means the crash is intermittent or context-specific.)

The recommended next step is a **Python-side diagnostic script** that runs at game start and dumps the relevant state to a log file, so we can pinpoint the exact failure mode the next time the user tests in-game. The script is added in this commit. It does not change any tuning XML or SimData — the existing artefacts already match EA's pattern.

---

## §1. Where the CAS aspiration picker lives

Sims 4 uses **Autodesk Scaleform GFX** (a Flash/AS3 compatible UI runtime — `GFX` is Scaleform's compiled-SWF format, header magic `47 46 58 0F` = "GFX\x0f"). The CAS aspiration picker is one Scaleform UI widget out of ~258 in `Data/Client/UI.package`.

| | Value |
|---|---|
| Resource type | `0x62ECC59A` (Scaleform GFX) |
| Group | `0x00000000` |
| Instance | `0x7d5fa9e0c2a4f038` |
| Size | ~1.6 MB compiled |

Decompiled with **JPEXS Free Flash Decompiler** v26.0.0 (portable, no install needed — we extract the zip to `C:\tools\jpexs\` and run `ffdec-cli.exe -export script <outdir> <gfx-file>`). The relevant AS3 classes inside this GFX are:

- `widgets.CAS.Molecule.data.CASAspirationSelectionDataFeed`
- `widgets.TraitsMolecule.AspirationTrackSelectionMenu`
- `widgets.TraitsMolecule.AspirationTrackSelectionCellView`
- `widgets.TraitsMolecule.AspirationSelectionPanel`
- `widgets.TraitsMolecule.AspirationCategoryTooltip`

The wider in-game aspiration UI (panel for an active Sim) lives in the much bigger GFX at instance `0xb8ce021c763422f8` (~2.1 MB) and shares `gamedata.Gameplay.shared.definitions.AspirationTrackStaticData` / `AspirationStaticData` with the CAS widget.

### Reproduction recipe

```pwsh
# Extract all SWF-ish resources from UI.package
node Build/_research_tmp/find-swfs.mjs

# Decompile the CAS picker GFX
& "C:\tools\jpexs\ffdec-cli.exe" `
  -export script swf-extracts\decomp_cas_picker `
  swf-extracts\UI_GFX_g00000000_i7d5fa9e0c2a4f038.gfx
```

The extracted `.gfx` files and decompiled AS3 are kept under `swf-extracts/` (gitignored — EA-owned binary content, do not commit).

---

## §2. The native-engine GameService boundary

`CASAspirationSelectionDataFeed.ConstructAspirationCategories` (line 74-114 of the decompile) is the function the CAS picker calls when the player opens the aspiration dialog. The relevant lines:

```as3
var _loc1_:Array = CommunicationManager.CallGameService("CasGetAspirationCategories") as Array;
OlympusObject.ConstructArrayInPlace(_loc1_, AspirationCategoryData);
_loc1_.sort(AspirationCategoryData.SortingFunction);
…
while (_loc4_ < _loc1_.length) {
   _loc5_ = _loc1_[_loc4_] as AspirationCategoryData;
   _loc6_ = CommunicationManager.CallGameService(
      "CasGetAspirationTracksByCategory",
      { "categoryId": _loc5_.uid }
   ) as Array;
   …
}
```

And `gamedata.Gameplay.shared.definitions.AspirationTrackStaticData.INIT_DATA` (line 48-95) bulk-loads all tracks once and caches by category:

```as3
_loc1_ = CommunicationManager.CallGameService("GetAspirationTrackStaticData", null, true) as Array;
…
while (_loc3_ < _loc2_) {
   _loc4_ = new AspirationTrackStaticData(_loc1_[_loc3_]);
   _loc5_ = int(_loc4_.aspirations.length);
   _loc6_ = 0;
   while (_loc6_ < _loc5_) {
      _loc9_ = _loc4_.aspirations[_loc6_];
      _loc10_ = AspirationStaticData.GetStaticData(_loc9_);
      if (_loc10_) {
         _loc10_.level = _loc6_ + 1;
      }
      _loc6_++;
   }
   …
}
```

`CommunicationManager.CallGameService(name, args, sync)` is Olympus's IPC primitive into the C++ engine. The four service names this widget uses are:

| Name | Returns |
|---|---|
| `CasGetAspirationCategories` | Array<{uid:String, name, icon, …}> |
| `CasGetAspirationTracksByCategory({categoryId})` | Array<{id:String}> |
| `CasGetFTUEAspirationTracks` | Array<{id:String}> (initial-CAS FTUE flow) |
| `GetAspirationTrackStaticData` | Array<{uid:String, aspirations:[String], category:int, …}> |
| `GetAspirationStaticData` | Array<{uid:String, objectiveUids:[String], displayName, …}> |
| `GetAspirationCategoryStaticData` | Array<{uid:String, name:LocKey, icon:RK, …}> |

### Where do these names actually live in the binary?

```sh
$ grep -aob "CasGetAspirationCategories\|CasGetAspirationTracksByCategory\|\
CasGetFTUEAspirationTracks\|GetAspirationTrackStaticData" \
  "/c/Program Files (x86)/Steam/steamapps/common/The Sims 4/Game/Bin/TS4_x64.exe"
0x1dfc890: GetAspirationTrackStaticData
0x1e69748: CasGetAspirationCategories
0x1e69768: CasGetAspirationTracksByCategory
0x1e69790: CasGetFTUEAspirationTracks
```

All four are inside `TS4_x64.exe`. They do NOT appear in any `.pyc` inside `Data/Simulation/Gameplay/*.zip`:

```sh
$ grep -lar --include="*.pyc" "CasGetAspirationCategories" simulation.zip core.zip base.zip
# (empty)
```

So the dispatch is **C++-native**, not Python. There is no `@gameservice("CasGetAspirationCategories")` decorator in `simulation.zip` we could hook from a `.ts4script`.

This rules out the playbook's "Python script-side runtime injection" pattern as a direct option — there's no Python entry point to monkey-patch. Any runtime intercept would need to be at the `CommunicationManager.SendUIMessage` layer (engine-side), which mods can't touch.

---

## §3. Where the engine reads the track data from

The native handlers don't pull from CombinedTuning (the in-memory tuning blob). They pull from the **unified DBPF resource index**, looking specifically for two TGI patterns:

| What | Type | Group | Count in `ClientFullBuild0` | Count in `ClientDeltaBuild0` |
|---|---|---|---|---|
| AspirationCategory SimData | `0x545AC67A` | `0x0050DB3B` | 18 | 25 |
| AspirationTrack SimData | `0x545AC67A` | `0x0020FC6D` | 27 | 38 |

Verified by `Build/_research_tmp/find-aspiration-simdata.mjs`. Schema hashes are `0xD3511F1A` (AspirationCategory) and `0x54FDB5FC` (AspirationTrack) — both match the values our `Build/simdata/src/build/classes/schemas.ts` already uses for these classes.

EA's AspirationCategory has 4 columns: `display_text`, `icon`, `is_sim_info_panel`, `ui_sort_order`. EA's AspirationTrack has 9 columns (the same 9 we ship).

### Mods DO contribute to this index

The unified resource cfg (`Data/Client/Resource.cfg` + `Mods/Resource.cfg`) globs **every** `.package` under `Mods/` at priority 500. Higher priority overrides lower. So our `HistorianCareer_Tuning.package` is enumerated alongside `ClientFullBuild0.package` and our `(0x545AC67A, 0x0020FC6D, 0x6621FF4B)` row participates in the same lookup as EA's tracks. **Our SimData IS reachable from the native CAS picker** — it's not blocked by the index.

This contradicts the user's "ClientFullBuild-only frozen catalog" hypothesis. The catalog *includes* mod packages; we ship the row at the right TGI; the engine reads it.

---

## §4. Our SimData payload is byte-equivalent to EA's

`Build/_research_tmp/compare-track-simdata.mjs` parses both files with `@s4tk/models.SimDataResource.from(buf)` and dumps the row. EA's `Track_Knowledge_B` (instance 25441) and our `aspiration_track_HistorianCalling` (instance 0x6621FF4B) yield:

| Column | EA Knowledge | HC HistorianCalling | Notes |
|---|---|---|---|
| `aspirations[].key` | LEVEL_1..4 (1..4) | LEVEL_1..4 (1..4) | identical |
| `aspirations[].value` | 25448, 25449, 25450, 25451 | 1634251651, 1634251648, 1634251649, 1634251654 | both 64-bit uint refs — EA happens to use small EA-build IDs, ours are FNV32-of-name promoted to 64-bit. Both legal. |
| `category` | 25385 (Asp_Cat_Knowledge) | 25385 (Asp_Cat_Knowledge) | identical |
| `description_text` | 0x13CCBE3C | 0xC5C1A52B | STBL hashes — locale-dependent, not validated |
| `display_text` | 0x50E856D8 | 0x4194A1D2 | STBL hashes |
| `icon` | type=0xB2D882 g=0 i=0x70F4F2B9947509F6 | type=0xB2D882 g=0 i=0xD26124833B452384 | both DDS image keys |
| `icon_high_res` | (zero RK) | (zero RK) | identical |
| `mood_asm_param` | "" | "" | identical |
| `primary_trait` | 27086 (trait_Quick_Learner) | 27086 (trait_Quick_Learner) | EA trait stand-in, deliberate (see `Tuning/aspiration_track_HistorianCalling.xml:90`) |
| `reward` | 27490 (Reward_Knowledge_Renaissance) | 27489 (Reward_Knowledge_Chronicler) | both EA-shipped rewards |

The headers and field offsets are identical byte-for-byte. The only meaningful differences are field values, not structure.

So at the *binary serialisation* layer, our row should be indistinguishable from EA's from the engine's POV.

---

## §5. The lastUIException finding (the actual smoking gun)

Reading `~/Documents/Electronic Arts/Die Sims 4/lastUIException.txt` from the user's machine (from session timestamp `2026-05-13 12:05:09`):

```
TypeError: Error #1009: Cannot access a property or method of a null object reference.
    at gamedata.Gameplay.shared.definitions::AspirationTrackStaticData/INIT_DATA()
    at get gamedata.Gameplay.shared.definitions::AspirationTrackStaticData/STATIC_DATA_PER_CATEGORY()
    at gamedata.Gameplay.shared.definitions::AspirationTrackStaticData/GetTrackData()
    at olympus.core::OlympusObject/ParseObject()
    at OlympusObject instance constructor()
    at HouseholdSimData instance constructor()
    …
```

The crash is in the EA-shipped AS3, in the bulk-load step that builds `sTracksPerCategory`. Looking at the decompile of `INIT_DATA()`:

```as3
_loc1_ = CommunicationManager.CallGameService("GetAspirationTrackStaticData", null, true) as Array;
if (!_loc1_) return;                            // ← guard 1
…
_loc4_ = new AspirationTrackStaticData(_loc1_[_loc3_]);
_loc5_ = int(_loc4_.aspirations.length);        // ← NPE here if _loc4_.aspirations is null
…
_loc9_ = _loc4_.aspirations[_loc6_];
_loc10_ = AspirationStaticData.GetStaticData(_loc9_);
if (_loc10_) { _loc10_.level = _loc6_ + 1; }    // ← guard 3 (null-safe)
…
_loc7_ = _loc4_.category;                       // int coercion — null becomes 0
_loc8_ = sTracksPerCategory[_loc7_];
```

The only un-guarded null-deref opportunity is at `_loc4_.aspirations.length` if the parser left `aspirations` null. But the AS3 field default is `public var aspirations:Array = [String];` — the placeholder is a 1-element array containing `String` itself as a class marker, used by `FixupArray` to coerce element types. ParseObject's behaviour:

- if `obj.aspirations` is undefined: leaves `prop` as the placeholder `[String]`. After `FixupArray`, length becomes 0. **No NPE.**
- if `obj.aspirations` is null: `if(objArray)` is false → ignored. Placeholder stays. After `FixupArray`, length becomes 0. **No NPE.**
- if `obj.aspirations` is an Array of strings: each element gets `new String(str)`. **No NPE.**
- if `obj.aspirations` is an Array of objects with `.key` and `.value` sub-fields: `new String({key,value})` produces `"[object Object]"` strings. **No NPE, but useless lookups.**

The likely failure isn't a NULL aspirations vector — it's deeper than that. Possible scenarios:

1. **The engine serialises `aspirations` as a different shape than the AS3 expects.** Our SimData column is a `Vector<Object{key, value}>` of TableSetReference pairs. The AS3 expects a flat `Array<String>` of aspiration uids. If the native engine serialises EA's tracks as `["25448", "25449", "25450", "25451"]` (flattened — keys discarded) and ours similarly as `["1634251651", …]`, then the value-string lookup goes through `AspirationStaticData.GetStaticData("1634251651")` which itself calls `GetAspirationStaticData` again. If THAT returns a null/error for one of our aspiration ids — and the AS3 doesn't guard the inner `_loc10_.level` (it does — line 79's `if(_loc10_)` guard) — we get a silent skip, not a crash.

2. **The crash is in an indirect path we haven't traced.** The stack trace lists `OlympusObject/ParseObject` as the immediate caller of `GetTrackData`, called from `HouseholdSimData instance constructor()`. That's a SAVED-GAME load path (not initial CAS), where `HouseholdSimData` ParseObject sees an aspiration string field on a Sim, calls `GetTrackData(uid)` to resolve it, which lazily triggers `INIT_DATA()`, which crashes. So this exception is from a *save load*, not from opening the CAS picker. The user may have a save that previously had our broken (pre-TEEN_OR_OLDER) state cached.

3. **Stale cache.** The user already wiped `localthumbcache.package` and `cachestr/` per their own follow-up comment, but `clientDB.package`, `localsimtravelthumbcache.package`, `avatarcache.package`, `accountDataDB.package` may also need clearing. The `_stash_20260513_140439` folder in `~/Documents/Electronic Arts/Die Sims 4/` suggests the user is rotating saves, which is right, but the per-account caches survive cross-save.

The first hypothesis is testable: a Python-side diagnostic that enumerates `services.get_instance_manager(Types.ASPIRATION_TRACK).types.values()` plus our specific Aspiration sub-tunings, and writes their state to a log file. If our track is correctly in `_tuned_classes` AND its `_sorted_aspirations[0][1].is_valid_for_sim(adult_sim) == True`, the Python side is healthy and the problem is purely in the engine/AS3 layer.

---

## §6. What this commit ships

`Scripts/historian_career/aspiration_diag.py` — a `.ts4script`-bundled diagnostic that:

- subscribes to the ASPIRATION_TRACK and ASPIRATION instance managers' `on_load_complete`
- logs the load result to `Documents/Electronic Arts/Die Sims 4/historiancareer_aspiration_diag.log`
- specifically logs whether `aspiration_track_HistorianCalling` and each of `aspiration_HistorianCalling_T1..T4` are in `mgr.types`
- logs each track's `aspiration_valid_age_type`, `category` reference, and `_sorted_aspirations`
- attempts `is_valid_for_sim(synthetic_adult_age=32)` and logs the result

This is a pure observer — no mutation of EA tunings, no monkey-patching beyond reading manager state. The script is imported from `Scripts/historian_career/__init__.py` and runs automatically at game start.

The build pipeline (`Build/build.mjs`) already bundles `Scripts/historian_career/*.py` into `HistorianCareer.ts4script` — adding this one file is enough; no Build changes needed.

### What this commit does NOT ship

- No XML changes (the TEEN_OR_OLDER fix from commit 6b4e72f is correct; the build-time guard in commit a5351e9 is correct; no AspirationTrack column changes are warranted).
- No SimData schema changes (the existing 9-column AspirationTrack and 5-column Aspiration schemas match EA byte-for-byte).
- No new Python injection of the GameService path (the service handlers are native — we can't hook them from a .ts4script).

### What to do next (for the user)

After installing this build and reproducing in-game, attach (or paste) the contents of `Documents/Electronic Arts/Die Sims 4/historiancareer_aspiration_diag.log`. The log will tell us:

- Whether our track is in `mgr.types` (it should be).
- Whether each aspiration tier is in the Aspiration instance manager (it should be).
- The runtime value of `aspiration_valid_age_type` on T1 (should be `TEEN_OR_OLDER` = 120 post-fix).
- Whether `track.is_valid_for_sim(synthetic_adult)` returns True (it should).

If all four are True/correct and the track still doesn't appear in CAS, the failure is in the engine/AS3 layer and we need a different fix (most likely just a full cache nuke including `clientDB.package` and `accountDataDB.package`).

If any check fails, the log narrows the bug to a specific Python-side issue we can address in the next iteration.

---

## §7. Anti-claims (things we explicitly debunked while doing this work)

- ~~"The CAS picker is a SWF widget in Flash/Scaleform that we can decompile and patch."~~ → It's a Scaleform GFX widget (close enough). We CAN decompile it (with JPEXS — GFX is a Scaleform format variant readable by ffdec). We CANNOT patch it without re-signing EA's UI.package, and even if we could, the picker delegates to native engine calls — so patching the GFX wouldn't add tracks.
- ~~"The picker reads from a binary index in `ClientFullBuild0.package` that mods can't extend."~~ → The picker reads from the unified DBPF resource index. Mods CAN extend the index. We HAVE extended it — `HistorianCareer_Tuning.package` ships our track at `(0x545AC67A, 0x0020FC6D, 0x6621FF4B)`, which the same index pipeline that picks up `ClientFullBuild0.package` enumerates.
- ~~"`CasGetAspirationCategories` is a Python service we can monkey-patch with `@inject_to` or `lot51-core` injection helpers."~~ → It's a native C++ engine RPC. No Python entry point exists. The lot51-core/MC5 injection pattern doesn't apply.
- ~~"The AspirationCategory needs a tag/required_pack/`used_by_packs` flag set to be visible."~~ → EA's Asp_Cat_Knowledge category sets `is_sim_info_panel=false`, `ui_sort_order=7`, and an icon. Nothing else. Our track references this EA category (`category=25385`) directly — we don't even need to ship our own category SimData.

## §8. Tools and artefacts

- **JPEXS Free Flash Decompiler** v26.0.0 portable at `C:\tools\jpexs\`. Install: `curl -L -o ffdec.zip https://github.com/jindrapetrik/jpexs-decompiler/releases/download/version26.0.0/ffdec_26.0.0.zip && unzip ffdec.zip -d C:\tools\jpexs`. CLI: `C:\tools\jpexs\ffdec-cli.exe`. Verified to read Scaleform GFX (not just stock SWF) by parsing the EA UI Scaleform files.
- **Sims 4 install path** (Steam): `C:\Program Files (x86)\Steam\steamapps\common\The Sims 4\`. Registry: `HKLM\SOFTWARE\Maxis\The Sims 4\Install Dir`.
- `Build/_research_tmp/` — scratch scripts: `find-swfs.mjs`, `extract-combined.mjs`, `find-aspiration-simdata.mjs`, `extract-ea-cats.mjs`, `find-ea-track-simdata.mjs`, `compare-track-simdata.mjs`, `compare-rowfields.mjs`, `dump-track-aspirations.mjs`, `inspect-ea-category.mjs`, `inspect-asp-simdata.mjs`, `inspect-built-package.mjs`. All gitignored.
- `swf-extracts/` — 258 dumped Scaleform GFX files from `UI.package` + two full `decomp_*` trees (CAS picker + main aspiration panel). Gitignored.
- This file (`Docs/NOTE_cas_aspiration_picker_swf.md`) plus the Python diagnostic at `Scripts/historian_career/aspiration_diag.py`.

## §9. Confidence summary

| Claim | Confidence |
|---|---|
| CAS picker lives in `UI.package`, type `0x62ECC59A`, instance `0x7d5fa9e0c2a4f038` | **HIGH** — decompiled with JPEXS, found `CASAspirationSelectionDataFeed` class. |
| Picker delegates to four GameService RPCs (`CasGetAspirationCategories`, `CasGetAspirationTracksByCategory`, `CasGetFTUEAspirationTracks`, `GetAspirationTrackStaticData`) | **HIGH** — direct read of AS3 decompile. |
| Those four RPCs are handled natively by `TS4_x64.exe`, not by Python | **HIGH** — string locations in EXE, zero `.pyc` matches. |
| Native handler enumerates `(0x545AC67A, 0x0020FC6D, *)` for tracks and `(0x545AC67A, 0x0050DB3B, *)` for categories | **HIGH** — verified by counting EA rows in `ClientFullBuild0` (27 tracks, 18 categories) and noting that no other resource type has these counts. We did NOT see the engine's internal jumptable — this is structural inference, not proof. |
| Mod packages contribute to the index | **HIGH** — `Mods/Resource.cfg` globs at priority 500; resource enumeration is unified across all packages by design. |
| Our `HistorianCareer_Tuning.package` ships AspirationTrack SimData at the correct TGI | **HIGH** — verified via `Build/_research_tmp/inspect-built-package.mjs`. |
| Our SimData is byte-equivalent to EA's | **HIGH** — direct hex diff vs EA's Track_Knowledge_B. |
| The runtime AS3 NPE in `INIT_DATA()` from `lastUIException.txt` is the residual symptom | **MEDIUM** — the stack trace is unambiguous, but we don't have a current-build retest from the user. The exception is from `2026-05-13 12:05:09`, the current package is from `13:57`. The user may have already moved past this. |
| The Python-side diagnostic script in this commit will narrow down the residual failure mode | **HIGH** — the script reads well-defined manager state. The only failure mode is the manager not being ready, which we handle with `add_on_load_complete`. |
| The previous note's conclusion (TEEN_OR_OLDER fix is sufficient for the in-game post-CAS path) remains correct | **HIGH** — same evidence as part I. |
| The previous note's HEDGE (CAS itself may need an additional fix) is partially confirmed | **MEDIUM** — the runtime NPE points at a real layer-of-cache / serialisation issue that needs in-game diagnostic data to fix, not just package-side reshaping. |

---

## §10. What to do if the diagnostic log shows everything is healthy

If the script reports our track is in `_tuned_classes` with TEEN_OR_OLDER and `is_valid_for_sim → True`, the bug is purely in the engine's `GetAspirationTrackStaticData` serialisation. Mitigations available without further reverse-engineering:

1. **Re-test on a brand-new save with full cache wipe** — include `clientDB.package`, `accountDataDB.package`, `localthumbcache.package`, `localsimtravelthumbcache.package`, `localsimtexturecache.package`, `avatarcache.package`, `cachestr/`, AND `houseDescription-client.package` AND `onlinethumbnailcache/`. The previous wipe missed several files.
2. **Try a simpler track first** — author a stripped-down AspirationTrack SimData with only `aspirations`, `category`, `display_text`, `description_text` (drop icon, primary_trait, reward) and confirm whether THAT renders in CAS. If yes, our problem is in one of the dropped fields. If no, the bug is in the engine's mod-package SimData enumeration itself (less likely given the PMC precedent).
3. **Replace the FNV32 instance IDs on the aspiration tier files** with hand-picked decimal IDs in EA's range (~25000-30000, currently unused — we'd have to enumerate to find safe ones). The engine MAY have an internal range check on aspiration IDs that quietly skips out-of-range ones. (Low confidence — would be a Sims 4 bug, not documented behaviour.)

These are sequenced low-risk-first. We tackle them after the user runs the diagnostic.
