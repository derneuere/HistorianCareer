# NOTE — What slot drives the career panel's icon (issue #18)

**Status:** SWF-decompile research, refs #18.
**Confidence:** **HIGH** on the slot binding (decompiled directly from EA's shipped UI SWF). **MEDIUM** on whether the user's reported "panel placeholder" is actually a bug vs. a misread of EA's design.

## Executive summary

Decompiling the Sims 4 Olympus career-panel widgets reveals:

1. **The bottom-right HUD briefcase widget (`CareerPanelButton`) does NOT read any per-career icon at all.** It shows EA's hardcoded Flash-embedded briefcase animation (`symbol255`). Every career — EA's and ours — shows the same briefcase in that slot. **This is not a placeholder; it is the design.**
2. **The expanded career panel (clicked-open `SimInfoCareerPanelMain`) reads `CareerTrack.icon`** via `JobInfoCellView.mcIcon.LoadImage(careerInfo.icon)`. That getter returns `mTrackStaticData.icon.instance` — i.e., the 64-bit instance hex of the resource in the **`icon`** SimData column, type `0x00B2D882`. This is the **same** resource the join-career notification path resolves; both succeed against our mod package.
3. **`CareerTrack.icon_high_res` is declared in the data class but NEVER consumed by any AS3 code in any UI SWF in `Data/Client/UI.package`.** It is dead weight in the current Olympus client. Our `icon_high_res` slot can point anywhere (or be omitted) without affecting any rendered widget.
4. The instance hex is passed as `"img://<instance>"` to `flash.display.Loader.load()`, which the native Sims 4 engine resolves against the live resource index (UI.package + Mods/ packages). The icon type is implicit — the asset loader resolves the instance against whatever DDS exists at that instance ID.

Consequence: **The expanded career panel SHOULD already render our `Career_Historian_Main.png` correctly** — same code path, same resource key, same byte stream as the working notification icon. The "panel placeholder" symptom is most likely the user observing the always-hardcoded **bottom-right briefcase HUD widget**, which never reflects our custom icon and never will.

A separate real bug found while investigating: `Build/icons/Career_Historian_hires.png` is byte-identical to `Aspiration_HistorianCalling.png` (MD5 `9ab6492f8572f7d64e0a850f3bee1f57`) — it is the aspiration art accidentally copied into the hi-res slot, with opaque white corners (no alpha channel). Even though no widget reads `icon_high_res` today, shipping wrong placeholder art at that slot is sloppy. Fix in this commit: point both `icon` and `icon_high_res` at `Career_Historian_Main.png` (the correct transparent book+quill artwork) and remove the bogus placeholder PNG from `Build/icons/`.

## Q1. Which UI module hosts the expanded career-panel widgets?

`Data/Client/UI.package` contains **258** Adobe Scaleform GFX resources at type `0x62ECC59A`. **One** — instance `0x8869cd575c5993e6` (1.72 MB) — contains the full `SimInfoCareerPanelMain` widget tree along with `CareerCellView`, `RegularCareerCellView`, `JobInfoCellView`, `CareerInfo`, `CareerTrackStaticData`, and the `olympus.controls.IconComponent`/`olympus.resources.ImageLoader`/`olympus.io.AssetLoader` infrastructure.

Extracted to `swf-extracts/gfx_out/8869cd575c5993e6/` via JPEXS `ffdec -export script`.

## Q2. Which AS3 code path renders the icon in the panel?

`widgets.Gameplay.SimInfoHUD.CareerPanel.SimInfoCareerPanelMain` dispatches per `CareerInfo.career_panel_type` to one of:

- `RegularCareerCellView` (default; what our Historian career uses — `career_panel_type` is unset)
- `AgentBasedCareerCellView`, `GigCareerCellView`, `UniversityCareerCellView`, … (other specializations)

`RegularCareerCellView extends CareerExpandingCellView extends ExpandingPanel`. Its `Draw(...)` calls `super.Draw` and then composes `mcJobInfoCellView.Draw(param1, param2)`. `mcJobInfoCellView` is a `widgets.shared.controls.Careers.JobInfoCellView`, whose `Draw` method contains the **load**:

```actionscript
// JobInfoCellView.as, line 141 (decompiled)
this.mcIcon.LoadImage(_loc3_.icon);    // _loc3_ is param1 as CareerInfo
```

`mcIcon` is an `olympus.controls.IconComponent`. `CareerInfo.icon` is a getter:

```actionscript
// CareerInfo.as, line 626-629
public function get icon() : String
{
   return this.mTrackStaticData.icon.instance;
}
```

`mTrackStaticData` is the `CareerTrackStaticData` for the Sim's current career-track UID. Its `icon` field is a `ResourceKey` populated from the SimData blob the Python game sends to Olympus. **Therefore the rendered icon is `CareerTrack.icon.instance`.**

`IconComponent.LoadImage` delegates to `ImageLoader.LoadImage`, which:

```actionscript
// ImageLoader.as, line 192-197
if (param1.substr(0, 6) != "img://")
   param1 = "img://" + param1;
...
this.mLoadUrl = AssetLoader.Load(param1, _loc4_);
```

`AssetLoader.Load` calls `Loader.load(new URLRequest("img://<hex>"))`. The `img://` scheme is intercepted by the native game engine and resolves to a DDS resource at instance `<hex>`, type implicitly `0x00B2D882`.

This is the **same** resolution mechanism the join-career notification uses (which the user empirically confirmed works against our mod package). So the panel and the notification share the underlying asset-load path — neither has a privileged "EA-only" index.

## Q3. What about `CareerTrack.icon_high_res`?

**Dead.** The string `icon_high_res` appears in 135 of the 258 GFX resources (because the `CareerInfo` and `CareerTrackStaticData` data-class declarations are bundled into every widget SWF that imports them), but **zero** AS3 functions read `mTrackStaticData.icon_high_res` or `CareerInfo.icon_high_res`. The only references are:

- Field declarations: `public var icon_high_res:ResourceKey = new ResourceKey();` (in `CareerTrackStaticData.as` and `UniversityMajorStaticData.as`)
- A getter that nothing calls: `CareerInfo.icon_high_res` (returns `mTrackStaticData.icon_high_res.instance`)

Confirmed by grepping the full AS3 export from `8869cd575c5993e6` (the panel SWF) AND `ebe6b358f78cde18` (a representative larger UI SWF). Neither contains a `LoadImage(...icon_high_res...)` or `mTrackStaticData.icon_high_res` consumer call.

(EA may have used `icon_high_res` in an older Olympus build, or may add a consumer in a future patch — the column is still part of the schema, so we still emit it. But today it's load-bearing for nothing.)

## Q4. What about `Career.career_affordance`?

`career_affordance` is a tuning reference to an interaction (`SuperInteraction`), not a resource key. It drives the "Go To Work" rabbit-hole interaction; it has no icon role. The panel never reads it for visual purposes.

## Q5. What about `Career.career_messages.*.dialog.icon`?

That's a separate `ResourceKey` field on a `career_messages.<event>.dialog` block, used for notification widgets. In our `career_Adult_Historian.xml`:

- `career_missing_work.dialog.icon`: EA's headline_careersimoleons (`2f7d0004:00000000:617140672fa22f7b`)
- `career_performance_warning.dialog.icon`: same EA headline
- `join_career_notification`: **no `dialog.icon` set** — the notification widget likely falls back to `mTrackStaticData.icon` (same as the panel) when no override is given

So the user's "✅ icon rendered correctly in the join-career notification popup" observation corresponds to **the same `CareerTrack.icon` resource key the expanded panel reads**. Both should render the same icon.

## Q6. What about the bottom-right HUD briefcase widget?

`widgets.Gameplay.SimInfoHUD.SimInfoTray.controllers.CareerPanelButton` (in the `5ffb8ae26bc11e96` SimInfoTray SWF) is a `SimInfoPanelButton` with a pre-baked Flash MovieClip art symbol (`[Embed(source="/_assets/assets.swf", symbol="symbol255")]`). It has **no** `LoadImage` call for the career icon. Its `Draw` method only updates **tooltips** and the work-status sub-clip's animation frame (`gotoAndStop(AT_HOME_LABEL)`, etc.) — none of which load a per-career image.

The briefcase art is therefore identical for every career in the game. EA's Writer, Painter, Astronaut, and our Historian all render the same briefcase in that slot. If the user has been comparing the bottom-right briefcase widget against another career's briefcase and concluding "ours shows a placeholder", **that is a misreading of the UI**: the briefcase is hardcoded, not data-driven.

The first widget that actually reads our custom icon is the **expanded** career panel — the popup that appears when the briefcase is clicked. That's where `JobInfoCellView.mcIcon` lives.

## Implications and fix

1. **No code or tuning change is needed** to make `CareerTrack.icon` render in the expanded panel. The current build already wires the right resource key into the right SimData column. The user should test by **clicking the briefcase** to open the expanded career panel and verifying the icon there. The bottom-right briefcase widget is not a useful test target.

2. **Source-art fix:** `Build/icons/Career_Historian_hires.png` is bogus (byte-identical to `Aspiration_HistorianCalling.png`, no transparency). Even though `icon_high_res` is currently unread, we should not ship the wrong artwork in that slot. Resolution: delete the bogus PNG and point the `<T n="icon_high_res">` reference in `Tuning/career_track_Adult_Historian.xml` at `Career_Historian_Main.png` (the real transparent book+quill). The build's icon-rewrite step will emit a single DDS resource (instance `0xc02ff5c58bd43882`) and both XML columns will reference it.

3. **If, after the user verifies the expanded panel shows our icon, the symptom persists**: the next step is the empirical swap test described in `--include-layer-b`-built scratch commit (Hypothesis 1, below). Replace `<T n="icon">Career_Historian_Main.png</T>` with `2f7d0004:00000000:bd8b5595b9d6e694` (EA's Writer career icon, instance verified in `ClientFullBuild7.package`), rebuild, run `careers.add_career career_Adult_Historian` in-game, open the career panel — if EA's Writer icon now appears in the panel, the slot binding is confirmed and our DDS encoder is the next suspect. If the panel still shows EA's hardcoded briefcase, the user is looking at the wrong widget.

## Verification: build artifacts

Built `Build/out/HistorianCareer_Tuning.package` and binary-inspected the `CareerTrack` SimData (instance `0x29351d7a`, type `0x545AC67A`, group `0xc75cab`):

```
CareerTrack SimData size: 570 bytes
  icon          @ offset 128:  instance=0xc02ff5c58bd43882 (Career_Historian_Main.png)
                @ offset 136:  type=0x00B2D882 (DDS image)
  icon_high_res @ offset 144:  instance=0xe0fd110fd392b178 (Career_Historian_hires.png, pre-fix)
  image         @ offset 160:  instance=0x6665077284098fa2 (EA universal track-background)
  - no 0x2F7D0004 marker bytes anywhere (cells.ts RESOURCE_TYPE_REWRITES applied correctly)
```

DDS payload at type `0x00B2D882`, instance `0xc02ff5c58bd43882`: 65,664 bytes (128 header + 128×128×4 BGRA pixels), starts with `DDS ` magic. Confirmed in the deployed package output.

## Anti-trap

Do **not** try to rewrite the DDS encoder. It's correct and byte-equal to EA. Do **not** try to inject a Python override for `CareerInfo.icon` — the SWF reads directly from the SimData blob; there's no Python intercept point. The icon binding is purely declarative through `CareerTrack.icon`.

## Tools used

- `ffdec` (JPEXS Free Flash Decompiler) v26.0.0 — portable zip from <https://github.com/jindrapetrik/jpexs-decompiler/releases>. Used `ffdec -export script <out> <swf>` to dump ActionScript 3 from the GFX (Scaleform-flavor SWF) resources.
- `@s4tk/models` `Package.from(buffer)` to enumerate `UI.package` and find GFX resources by type+content.
- Extracts and decompiled scripts live under `swf-extracts/` (gitignored).

Decompiled file paths referenced above (rooted at `swf-extracts/gfx_out/8869cd575c5993e6/scripts/`):
- `widgets/Gameplay/SimInfoHUD/CareerPanel/SimInfoCareerPanelMain.as`
- `widgets/Gameplay/SimInfoHUD/CareerPanel/CareerCellView.as` (dispatcher)
- `widgets/Gameplay/SimInfoHUD/CareerPanel/RegularCareerCellView.as` (`mcJobInfoCellView` host)
- `widgets/shared/controls/Careers/JobInfoCellView.as` (the actual `LoadImage(icon)` call site)
- `gamedata/Gameplay/shared/CareerInfo.as` (`icon` and `icon_high_res` getters)
- `gamedata/Gameplay/shared/definitions/CareerTrackStaticData.as` (`icon:ResourceKey` field)
- `olympus/controls/IconComponent.as` + `olympus/resources/ImageLoader.as` + `olympus/io/AssetLoader.as` (the `img://` URL pipeline)

And in `swf-extracts/gfx_out/5ffb8ae26bc11e96/scripts/`:
- `widgets/Gameplay/SimInfoHUD/SimInfoTray/controllers/CareerPanelButton.as` (the bottom-right briefcase widget — confirmed not to read any per-career icon)
