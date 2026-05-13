# NOTE — Custom PieMenuCategory needs a SimData companion (issue #14, smoking gun)

**Status:** research only — no code changed.
**Confidence:** **HIGH** for the root cause and proposed fix. See "Remaining unknowns" at the bottom.

## Executive summary

The Olympus UI error `Failed to locate category info for interaction category with key: 1653363664` is caused by our PieMenuCategory tuning shipping **without a SimData companion**. Every one of EA's 165 base-game `PieMenuCategory` tunings ships with a paired `SimData` resource (type `0x545AC67A`) at the matching instance ID — verified by enumerating `Data/Simulation/SimulationFullBuild0.package` AND `Data/Client/ClientFullBuild0.package`. The Python side of the pipeline works fine (the `<T n="category">1653363664</T>` reference resolves to our category's `guid64` exactly as EA intends), but when the Python serializer hands the `category_key` to the Olympus Flash UI in `SendUIMessage`, the UI's category-info lookup is backed by the `PieMenuCategory` SimData resources — not by the tuning XML and not by an in-Python registry. No SimData ⇒ UI can't find the category ⇒ exception ⇒ the whole right-click pie menu silently aborts. The fix is to add `PieMenuCategory` to our s4tk-builder's `NEEDS_SIMDATA` set and teach the `simdata` library to emit the 7-column `PieMenuCategory` schema (hash `0x022065c1`).

---

## 1. Where do EA's PieMenuCategory tunings get delivered to the Olympus UI?

### Data-flow trace (verified)

The pie-menu code path runs in this order (file references are paths inside the EA Python that ships in `Data/Simulation/Gameplay/{base,core,simulation}.zip`):

1. **Player right-clicks an object.** The UI sends a request to the Python game over `SendUIMessage`.

2. **Python builds the choice menu.** `T:\InGame\Gameplay\Scripts\Server\interactions\choices.py` (decompiled from `simulation.zip!interactions/pie_menu_category.pyc` and `simulation.zip!interactions/choices.pyc`):
    ```python
    def _add_menu_item(self, aop, context, result):
        category = (aop.affordance.get_pie_menu_category)(**aop.interaction_parameters)
        category_key = None if category is None else category.guid64
        self.menu_items[aop.aop_id] = MenuItem(aop, context, result, category_key)
    ```
    For our SuperInteraction with `<T n="category">1653363664</T>`, `aop.affordance.get_pie_menu_category()` returns the loaded `HC_PieMenuCategory_Historian` PieMenuCategory class — and `category.guid64` resolves to **`1653363664`** (= `0x628c53d0`). That's *literally the value* in the error message — so this half of the system works.

3. **How `guid64` is set.** `T:\InGame\Gameplay\Scripts\Core\sims4\tuning\instances.py` (`core.zip!sims4/tuning/instances.pyc`):
    ```python
    class HashedTunedInstanceMetaclass(TunedInstanceMetaclass):
        @staticmethod
        def assign_guid(tuning_inst, name):
            tuning_inst.guid = sims4.hash_util.hash32(name)
            if not tuning_inst.tuning_manager.use_guid_for_ref:
                tuning_inst.guid64 = sims4.hash_util.hash64(name)
            return tuning_inst
    ```
    But `PIE_MENU_CATEGORY` is registered with `_add_inst_tuning("pie_menu_category", resource_type=65657188, require_reference=True)` in `core.zip!sims4/resources.pyc`, and `InstanceTuningDefinition.__init__` defaults `use_guid_for_ref=True`. So `guid64` is NOT assigned by `assign_guid`; instead it comes from `InstanceManager.register_tuned_class` (`core.zip!sims4/tuning/instance_manager.pyc`):
    ```python
    def register_tuned_class(self, instance, resource_key):
        ...
        if self.use_guid_for_ref:
            instance.guid64 = resource_key.instance
    ```
    So `guid64 = our XML's s="1653363664"`. This is why our 31-bit-ID fix from issue #14 lines up with EA's pattern (EA PMC instance IDs are 13–17 bit — max is 100,333 = 17 bits).

4. **Python pushes the choices to the UI.** `ChoiceMenu` is consumed by `widgets.Gameplay.PieMenu` on the Flash/ActionScript side (the Olympus UI). The `category_key` (= our `1653363664`) is sent.

5. **The Olympus UI tries to resolve the `category_key` to display name + icon + priority.** Per the user-supplied stack trace:
    ```
    gamedata.Gameplay.InteractionMenu::InteractionCategory/Create()
    gamedata.Gameplay.InteractionMenu::InteractionMenuData/FetchCategory()
    gamedata.Gameplay.InteractionMenu::InteractionMenuData/PopulateMap()
    gamedata.Gameplay.InteractionMenu::InteractionMenuData/GenerateTree()
    widgets.Gameplay.PieMenu::PieMenuMain/HandlePieMenuCreate()
    ```
    `FetchCategory` looks up the key in a registry the UI loaded at game start. The error message `Failed to locate category info for interaction category with key: 1653363664` is emitted from that lookup miss.

### Hypothesis verdict

- **(a) Python serializes category metadata inline with each pie-menu message.** **FALSE** for the metadata. Python only sends `category_key` (the guid64). The metadata (display name, icon, priority, collapsible flag, parent, mood overrides) is NOT included in the per-menu message — the UI keeps it in its own registry.
- **(b) Olympus UI maintains a separate static registry, loaded at game start.** **TRUE**. And it's not a hand-built list — it's all `PieMenuCategory` SimData resources discovered by the Olympus client at boot.
- **(c) EA's Python pushes the PieMenuCategory tunings to the UI via a one-time CommunicationObject.** **FALSE** in the way the hypothesis was framed. The Python side never explicitly "pushes" PieMenuCategory data to the UI — the Olympus side independently scans the package indexes (specifically `Data/Client/ClientFullBuild*.package`) for SimData resources whose schema name is `PieMenuCategory` and builds its own dictionary keyed by `resource.instance`.

### How I verified

| Check | File | Result |
|---|---|---|
| EA Python class definition | `simulation.zip!interactions/pie_menu_category.pyc` | `PieMenuCategory` has 7 tunables: `_display_name`, `_icon`, `_collapsible`, `_parent`, `_special_category`, `_display_priority`, `mood_overrides`. Six are `ExportModes.All`, one is `ClientBinary`. **All 7 are exported to the client.** |
| `_collapsible` and `_display_name` `export_modes` | `core.zip!sims4/tuning/tunable_base.pyc` | `class ExportModes: ClientBinary, ServerBinary, ServerXML; All = (ClientBinary, ServerBinary, ServerXML)`. `ClientBinary` means "send this column to the Flash UI via SimData." |
| 165/165 EA PMC tunings have SimData | enumerate `SimulationFullBuild0.package` CombinedTuning + match against SimData index | 165 PieMenuCategory tunings in EA's CombinedTuning, 165 SimData resources at the matching instance IDs (range 8264–100333; bit width 13–17). |
| Same SimData also in Client package | enumerate `Data/Client/ClientFullBuild0.package` | 5,925 SimData entries; **all 165 PMC instances** present here too. This is the dictionary the Olympus UI reads on boot. |
| MC5 also emits a SimData companion | `reference/mod-constructor-5/Constructor5.Elements/PieMenuCategories/PieMenuCategory.cs` | `tuning.SimDataHandler = new SimDataHandler("SimData/PieMenuCategory.data");` then `Write(64, Collapsible); WriteText(68, …Name); Write(72, DisplayPriority); WriteTGI(80, Icon, …); Write(96, …Parent);` — confirms the byte layout. |
| Sims 4 Studio uses the same `SimData/PieMenuCategory.data` template (implied) | Both MC5 and S4S read the same `SimData/*.data` template directory. | When S4S users "Add Type → PieMenuCategory" or use "Generate SimData," the SimData companion is auto-created and saved alongside the tuning resource. |

### lot51-core does NOT push the PMC to the UI itself

`reference/lot51-core/snippets/tested_pie_menu_category.py` provides a Snippet-based reskin of `ChoiceMenu._add_menu_item`. It re-assigns `menu_item.category_key = new_category.guid64` **using an existing PieMenuCategory** — i.e. it presumes the new category already has a SimData companion the UI can find. The library doesn't do anything to register a brand-new PMC; it just swaps which existing PMC an aop is bucketed under.

### Where the EA Python file lives (file references)

| What | Path inside EA install | Path-on-disk |
|---|---|---|
| `PieMenuCategory` class | `T:\InGame\Gameplay\Scripts\Server\interactions\pie_menu_category.py` | `Data/Simulation/Gameplay/simulation.zip!interactions/pie_menu_category.pyc` |
| `ChoiceMenu._add_menu_item` | `T:\InGame\Gameplay\Scripts\Server\interactions\choices.py` | `simulation.zip!interactions/choices.pyc` |
| `HashedTunedInstanceMetaclass` | `T:\InGame\Gameplay\Scripts\Core\sims4\tuning\instances.py` | `core.zip!sims4/tuning/instances.pyc` |
| `InstanceManager.register_tuned_class` | `T:\InGame\Gameplay\Scripts\Core\sims4\tuning\instance_manager.py` | `core.zip!sims4/tuning/instance_manager.pyc` |
| `Types.PIE_MENU_CATEGORY` (resource type 65657188 = `0x03E9D964`) | `T:\InGame\Gameplay\Scripts\Core\sims4\resources.py` | `core.zip!sims4/resources.pyc` |

---

## 2. Why does our PieMenuCategory tuning load but not register in the UI?

Field-by-field comparison of `Tuning/HC_PieMenuCategory_Historian.xml` (ours) vs. EA's `computer_Handiness` (extracted from CombinedTuning):

```xml
<!-- ours (our build resolves s= to 1653363664) -->
<I c="PieMenuCategory" i="pie_menu_category" m="interactions.pie_menu_category" n="HC_PieMenuCategory_Historian" s="1653363664">
  <T n="_display_name">0x58F3DC50</T>
  <T n="_display_priority">0</T>
</I>

<!-- EA -->
<I c="PieMenuCategory" i="pie_menu_category" m="interactions.pie_menu_category" n="computer_Handiness" s="37041">
  <T n="_display_name">0xC098CD4E</T>
  <T n="_display_priority">0</T>
</I>
```

The tuning XMLs are structurally identical. Class, instance-type attribute, module, root tag, field names, field types are all correct. The only **load-time** difference is the instance ID (ours is 31-bit `1653363664`, EA's is 16-bit `37041`) — but EA's manager has `use_guid_for_ref=True` and accepts any 64-bit value as `resource_key.instance` (verified in `instance_manager.py:register_tuned_class`). EA's own PieMenuCategory IDs go up to 100,333 (17 bits) but nothing in the load path constrains them.

**What's actually missing: the SimData companion resource.**

Our build output `Build/out/HistorianCareer_Tuning.package` contains exactly **one** PieMenuCategory tuning resource (`type=0x03E9D964 instance=1653363664`) and **zero** SimData resources at instance `1653363664`. By contrast, every one of EA's 165 PMCs has a SimData (`type=0x545AC67A`) at the same instance ID.

The reason this isn't being generated by our build pipeline:

- `Build/s4tk-builder/build-package.mjs` line 98–101 defines `NEEDS_SIMDATA`:
  ```js
  const NEEDS_SIMDATA = new Set([
      "Career", "CareerTrack", "TunableCareerTrack", "CareerLevel",
      "Aspiration", "AspirationTrack", "AspirationCareer",
      "Trait", "Objective", "CareerChanceCard",
  ]);
  ```
  `PieMenuCategory` is missing.

- `Build/simdata/dist/build/classes/index.js` registers nine classes (`Trait`, `Objective`, `Aspiration`, `AspirationCareer`, `AspirationTrack`, `CareerChanceCard`, `CareerLevel`, `CareerTrack`/`TunableCareerTrack`, `Career`, `Buff`). `PieMenuCategory` is not registered.

- The comment in `Tuning/HC_PieMenuCategory_Historian.xml` and `Docs/NOTE_pie_menu_category_ids.md` both implicitly assumed PieMenuCategory was "Layer A" (XML-only, no SimData) — which was incorrect.

**Cross-reference**: the failure pattern matches the smaller-IDs-only diagnosis we already documented in `pie-menu-category-id.mjs` for the upstream Career family: tuning loads, cross-refs resolve, but the downstream consumer (here: the Olympus UI; for Career it was the icon resolver) silently rejects the resource because the SimData backing isn't in the package. With PieMenuCategory, the symptom is louder (UIException) because the UI has an explicit guard.

### Other hypotheses we can rule out

- **Wrong tuning class / instance / module attrs:** No — they exactly match EA's PieMenuCategory tunings.
- **Missing required field:** No — `_display_name` is technically the only mandatory one for layout; EA-shipped PMCs commonly skip `_icon`, `_parent`, and `_display_priority`. Compare e.g. EA's `TurnOff` which only has `_display_name`.
- **Missing Python injection:** No — EA's load path doesn't require Python to "register" the category; the Olympus UI reads the SimData index at startup.
- **31-bit ID problem:** No — `instance_manager.py:register_tuned_class` accepts any 64-bit value as `guid64`. EA's PMCs are all 13–17 bit only because EA hand-picks them; nothing in the runtime enforces it.
- **`use_guid_for_ref` problem:** No — verified in `core.zip!sims4/resources.pyc`: the default is `True` and `PIE_MENU_CATEGORY` uses the default. `guid64 = resource_key.instance` works for any value.

---

## 3. What's the minimal change for our custom PieMenuCategory to register?

**Add a SimData companion resource** for `HC_PieMenuCategory_Historian` at instance `1653363664` (`0x628c53d0`). Two implementation options follow; option A is recommended.

### Option A (recommended): teach `simdata/` to emit `PieMenuCategory`, and add it to `NEEDS_SIMDATA`

**Schema we need** (extracted from EA's `computer_Handiness.simdata`, hex-verified):

| Column | SimData type code | Notes |
|---|---|---|
| `_collapsible` | `0` (Boolean) | Default `True` in tunable — but EA's `cheat_emotionintensity` golden has `_collapsible=1` even though we don't tune it. Use `True` as default. |
| `_display_name` | `20` (LocalizationKey, 4-byte STBL key) | Required. Our XML's `0x58F3DC50` value (fnv32 of our STBL key) goes here. |
| `_display_priority` | `6` (Int32) | Default `1` per tunable; our XML sets it to `0`. |
| `_icon` | `19` (ResourceKey, TGI 16 bytes) | Default empty (all-zero TGI). |
| `_parent` | `18` (TableSetReference, 4 bytes) | Default `0` (null — no parent). |
| `_special_category` | `8` (UInt32 / enum) | Default `0` = `NO_CATEGORY`. |
| `mood_overrides` | `14` (Vector → schema `mood_to_override_data`) | Default empty vector. Nested schema is `{ mood: TableSetReference, override_data: Object → text_overrides{name_override, tooltip} }`. Likely safe to omit/empty for us. |

**Schema hash:** `0x022065c1`. This is what the Olympus parser uses to identify the schema; **must** match (it's not derivable from the schema name alone — see `KNOWN_SCHEMA_HASHES` discussion in `Build/simdata/dist/build/classes/schemas.js`).

**Concrete file changes** (no code applied — just the recipe):

1. In `Build/s4tk-builder/build-package.mjs`, line 98–101, add `PieMenuCategory` to `NEEDS_SIMDATA`:
   ```js
   const NEEDS_SIMDATA = new Set([
       "Career", "CareerTrack", "TunableCareerTrack", "CareerLevel",
       "Aspiration", "AspirationTrack", "AspirationCareer",
       "Trait", "Objective", "CareerChanceCard",
       "PieMenuCategory",  // issue #14: UI needs SimData to register the category
   ]);
   ```

2. In `Build/simdata/src/build/classes/schemas.ts`, add a `PIE_MENU_CATEGORY_SCHEMA`. The schema mirrors EA's column list (all 7 columns) and gets the `0x022065c1` hash. The seven columns above map cleanly to existing column kinds (`bool`, `string-key`, `int32`, `resource-key`, `table-set-reference`, `uint32`/`enum`, `vector` of object).

3. In `Build/simdata/src/build/classes/index.ts`, register `PieMenuCategory`:
   ```ts
   registerClass({ className: "PieMenuCategory", schema: PIE_MENU_CATEGORY_SCHEMA });
   ```
   And add the hash to `KNOWN_SCHEMA_HASHES`:
   ```ts
   PieMenuCategory: 0x022065c1,
   // and the nested schemas if we ever populate mood_overrides:
   mood_to_override_data: 0xeac32ff0,
   text_overrides: 0x9c77ff5d,
   ```

4. Optional but recommended: write a vitest case using `compare-against-goldens.mjs` to byte-compare our emitted SimData against EA's `cheat_emotionintensity.simdata` golden (after tweaking the STBL key + name). This is the same pattern used for the other 9 schema classes.

5. Rebuild. The resulting package will contain BOTH `0x03E9D964:0:1653363664` (PieMenuCategory tuning) AND `0x545AC67A:0:1653363664` (PieMenuCategory SimData). Re-enable `<T n="category">HC_PieMenuCategory_Historian</T>` on the five SIs. Right-click the computer in-game.

**Why this works:** The Olympus client at boot enumerates SimData resources by schema hash. As soon as our package ships `0x545AC67A:0:1653363664` with schema hash `0x022065c1`, the Olympus UI's `InteractionMenuData/FetchCategory` lookup table contains an entry keyed by `1653363664`, and our `_display_name` is what it shows.

### Option B (fallback): reuse an existing EA category

If Option A turns out to be blocked by some unknown SimData-encoding issue, the workaround is to set `<T n="category">37041</T>` (= `computer_Handiness`) directly in our SuperInteractions and accept that our 5 interactions are bucketed under "Handiness" in the right-click menu. **Tradeoffs:** the user sees "Handiness" instead of "Historian"; depending on EA-PMC `_collapsible` semantics + which interactions co-occur, our items might or might not surface as expected; the German localization is whatever EA uses for that category. Not great for UX, but it does sidestep the registration problem entirely.

### Option C (not recommended): runtime Python injection that creates the category at game start

In principle a `ts4script` could create a `PieMenuCategory` instance at game start via the affordance manager and stuff it into a category dict. In practice EA's Olympus UI registry is built once at boot from the *package* index — there is no API to push a new category from server-side Python to client-side Flash mid-game. Library `lot51-core` confirms this: their snippet (`tested_pie_menu_category.py`) only **re-buckets** aops into existing categories; it never creates new ones at runtime. We could ship a Python script that calls `services.get_instance_manager(Types.PIE_MENU_CATEGORY)._tuned_classes[...] = our_inst`, but the Flash UI would still not know about it because the Flash UI reads the SimData index at boot, before any mod Python runs in a way that could affect it. So this option is a dead end.

### What Python injection IS useful for (and might be optional)

If after shipping the SimData our category still doesn't appear in pie-menu output, it might be because the Python `affordance.get_pie_menu_category()` returns None (e.g. our `<T n="category">…</T>` reference doesn't resolve at affordance-load time). To diagnose, a tiny ts4script that logs at startup whether our PMC is in `services.get_instance_manager(Types.PIE_MENU_CATEGORY)._tuned_classes` would tell us instantly. Sample (Python 3.7):

```python
# Scripts/historian_career/diagnostics.py
import services, sims4.resources

def log_pmc_state():
    mgr = services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY)
    for key, cls in mgr.types.items():
        if cls.__name__.startswith("HC_"):
            print(f"[HC] PMC loaded: name={cls.__name__} guid64={cls.guid64} key={key}")
```

But this is a debug aid, not a fix. The actual fix is the SimData companion in Option A.

---

## 4. Bonus — what's actually in the Olympus UI registry?

We can't decompile the SWF in this environment (no `ffdec` / JPEXS Free Flash Decompiler installed; if the user wants to dig further they could install `ffdec` from https://github.com/jindrapetrik/jpexs-decompiler/releases and feed it the `*.swf`/`*.bin` resources extracted from `Data/Client/ClientFullBuild0.package`). The Olympus SWFs aren't loose `.swf` files on disk — they're stored inside the client packages as resources whose type we'd need to map out separately.

That said, we don't need the SWF to be confident, because the **data side** is unambiguous: every PMC in `ClientFullBuild0.package` carries a SimData resource at the same instance ID as its tuning, the schema hash is uniform (`0x022065c1`), and every ActionScript `InteractionMenuData/FetchCategory` lookup that doesn't hit produces the exact error string we see. The only unknown is whether the Flash UI also indexes by `group` (it shouldn't — `group=0` is universal here) or whether there's a max-entries cap (no evidence of one).

If future Diagnostics show our SimData being ingested but the UI still failing, the next step would be:
1. Extract one of the SWFs from `Data/Client/ClientFullBuild0.package` (open it in S4PE or a custom script — likely `type=0x0030D469` or similar; we'd need to look at the type counts in that package and identify the ActionScript blob).
2. Decompile with `ffdec`. Search for `FetchCategory` and `InteractionMenuData`.
3. Look at how the registry is populated — most likely via a SimData enumeration call against the package indexes, keyed by schema hash `0x022065c1`.

---

## Proposed fix — copy-pasteable starting point

### Patch 1 — `Build/s4tk-builder/build-package.mjs` (one-line addition)

```diff
 const NEEDS_SIMDATA = new Set([
     "Career", "CareerTrack", "TunableCareerTrack", "CareerLevel",
     "Aspiration", "AspirationTrack", "AspirationCareer",
     "Trait", "Objective", "CareerChanceCard",
+    "PieMenuCategory",
 ]);
```

### Patch 2 — `Build/simdata/src/build/classes/schemas.ts` (new schema)

```ts
// ---------------------------------------------------------------------------
// PieMenuCategory. Verified against EA's computer_Handiness.simdata (instance
// 37041 in Data/Simulation/SimulationFullBuild0.package). Without this
// SimData companion, the Olympus UI fails to register a custom PMC and
// right-clicks silently drop the pie menu with
//   "Failed to locate category info for interaction category with key: …"
// (Issue #14 follow-up — see Docs/NOTE_pie_menu_category_registration.md.)
//
// Schema hash 0x022065c1 — extracted from the binary; the schema-hash table
// in EA's runtime uses this value to recognize a PieMenuCategory row.
// ---------------------------------------------------------------------------
const TEXT_OVERRIDES = {
    kind: "object" as const,
    schemaName: "text_overrides",
    columns: [
        col("name_override", STRING_KEY),
        col("tooltip", STRING_KEY),
    ],
};
const MOOD_OVERRIDE_ROW = {
    kind: "object" as const,
    schemaName: "mood_to_override_data",
    columns: [
        col("mood", REF),
        col("override_data", TEXT_OVERRIDES),
    ],
};
export const PIE_MENU_CATEGORY_SCHEMA = deepFreeze({
    className: "PieMenuCategory",
    classPath: "interactions.pie_menu_category.PieMenuCategory",
    rootColumns: [
        col("_collapsible",       { kind: "bool" },     true),
        col("_display_name",      STRING_KEY),
        col("_display_priority",  { kind: "int32" },    1),
        col("_icon",              { kind: "resource-key" }),
        col("_parent",            REF),
        col("_special_category",  { kind: "uint32" },   0),     // SpecialPieMenuCategoryType.NO_CATEGORY
        col("mood_overrides",     { kind: "vector", elem: MOOD_OVERRIDE_ROW }),
    ],
});
```

(Exact column-kind names — `bool`, `string-key`, `int32`, `resource-key`, `table-set-reference`, `uint32`, `vector`, `object` — need to match whatever the simdata library already uses. See how `BUFF_SCHEMA` and `CAREER_SCHEMA` are built for the existing conventions. The names listed are the ones I observed in `schemas.js`/`schemas.d.ts`.)

### Patch 3 — `Build/simdata/src/build/classes/index.ts`

```diff
     registerClass({ className: "Buff", schema: BUFF_SCHEMA });
+    registerClass({ className: "PieMenuCategory", schema: PIE_MENU_CATEGORY_SCHEMA });
```

And in `KNOWN_SCHEMA_HASHES`:

```diff
     Buff: 0x83a7824a,
+    PieMenuCategory: 0x022065c1,
+    mood_to_override_data: 0xeac32ff0,
+    text_overrides: 0x9c77ff5d,
```

### Patch 4 — re-enable the SuperInteraction wiring

After the build emits SimData for `HC_PieMenuCategory_Historian`, restore on each of the 5 SIs in `Tuning/HC_Interaction_*.xml`:

```xml
<T n="category">HC_PieMenuCategory_Historian</T>
```

(Our resolver in `Build/s4tk-builder/resolve-names.mjs` will swap that name for `1653363664` at build time, which is the value the loaded PMC will register as `guid64`.)

### Verification

After rebuilding, `node Build/s4tk-builder/_inspect-our.mjs` (style check; trivial 5-line script) should show:
```
PieMenuCategory entries: 1
SimData companion at instance 1653363664: EXISTS (~420B)
```
Install. Right-click computer. Expect to see the "Historiker:in" submenu.

---

## Confidence and remaining unknowns

| Claim | Confidence |
|---|---|
| The error is caused by missing SimData companion | **HIGH** — 165/165 EA PMCs have a SimData, our package has zero, the error message is keyed by the exact instance ID we ship, and MC5's exporter confirms the SimData is mandatory. |
| Schema hash is `0x022065c1` | **HIGH** — read directly from 4 EA-shipped binaries (`computer_Handiness`, `computer_Programming`, `cheat_emotionintensity`, `computer_PlayGame`). |
| Column types and offsets in the proposed schema | **HIGH** — column names + types validated by both s4tk's `SimDataResource.from()` parse AND MC5's `SimDataHandler.Write` byte offsets (offset 64/68/72/80/96 = `_collapsible/_display_name/_display_priority/_icon/_parent`). |
| Option A (add SimData) is sufficient | **HIGH** — this is what every working EA category does and what MC5 does. The only way it could be insufficient is if Olympus also requires the package to be tagged in some way (e.g. specific group ID) — but EA's PMCs all use `group=0`, same as our build. |
| Nested schema hashes (`mood_to_override_data` = `0xeac32ff0`, `text_overrides` = `0x9c77ff5d`) | **MEDIUM** — read from EA's `computer_Programming.simdata`. They only matter if we ever populate `mood_overrides`. For the initial fix we don't, so empty-vector emission is fine. |
| Our 31-bit instance ID (1,653,363,664) works | **HIGH** — verified that `instance_manager.py` assigns `guid64 = resource_key.instance` unconditionally when `use_guid_for_ref=True` (the default). The 17-bit ceiling on EA's IDs is purely a stylistic choice, not a runtime constraint. |
| Olympus SWF internals match this picture | **MEDIUM** — we didn't decompile the SWF. We're inferring from the error message, EA Python side, EA SimData layout, and the fact that all 165 PMCs do ship a SimData. To upgrade this to HIGH we'd need to install ffdec/JPEXS and inspect `FetchCategory()`. |

### What I couldn't determine

- **Whether `0x022065c1` is the only schema hash Olympus accepts for PMC.** It's possible (unlikely) that recent game patches introduced an additional schema variant. To check: scan a fresh `Data/Client/ClientFullBuild*.package` for any SimData whose schema name (offset varies) is `PieMenuCategory` and tally the schema hashes. Our quick check on `SimulationFullBuild0.package` shows all 4 sampled entries use the same `0x022065c1` — looks unanimous.
- **Exact SWF location.** Identifying which resource in `ClientFullBuild0.package` is the Olympus pie-menu SWF requires either inspecting the resource types (one of `0x067CAA11`, `0x015A1849`, `0x01661233`, etc., based on type counts) or extracting all candidates and string-grepping for `InteractionMenuData`. This is overkill if Option A works.
- **What additional access would be needed:** install JPEXS Free Flash Decompiler (a.k.a. `ffdec` — Windows-friendly, MIT-licensed, https://github.com/jindrapetrik/jpexs-decompiler/releases) AND a way to bulk-extract SWFs from `*.package` resources (s4pe or a tiny @s4tk script). With those, we could read `FetchCategory()` directly and lift this issue's confidence to "absolute."

### One-line action item

Add `PieMenuCategory` to `NEEDS_SIMDATA` in `Build/s4tk-builder/build-package.mjs` AND teach `Build/simdata` to emit the `PieMenuCategory` schema (hash `0x022065c1`, 7 columns). Then re-enable the `<T n="category">` reference on the 5 SIs.
