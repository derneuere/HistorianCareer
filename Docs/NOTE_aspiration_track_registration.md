# NOTE — Why our custom AspirationTrack is invisible in the aspiration picker

**Status:** research only — no code changed.
**Confidence:** **HIGH** for one concrete bug (invalid enum value). **MEDIUM** for whether fixing that bug is *sufficient* (vs. partial). See "Confidence and remaining unknowns" at the bottom.

## Executive summary

Sims 4 *does* register mod-added `AspirationTrack` tunings into the runtime instance manager — that part of the pipeline works fine for us, exactly the same way it works for EA tracks. The reason our `aspiration_track_HistorianCalling` is silently filtered out of the **Aspiration Picker** dialog (the `SimPersonalityAssignmentDialog` that runs on age-up, adoption, in-game re-pick, and the "first time exiting CAS" flow) is that **our Tier-1 aspiration ships with an invalid enum string for `aspiration_valid_age_type`**. The XML sets `<E n="aspiration_valid_age_type">YAE_ONLY</E>` — but `YAE_ONLY` is **not** a member of the current `AspirationValidAgeType` enum (the real members are `INVALID`, `TODDLER_ONLY`, `CHILD_ONLY`, `TEEN_ONLY`, `TEEN_OR_OLDER`). At load time the string fails name lookup, the parser falls back to `default = INVALID = 0`, and the filter chain `aspiration_track.is_valid_for_sim(sim_info)` evaluates to `sim_info.age & 0 = 0` → falsy → track filtered. The fix is a one-character XML edit on each of `aspiration_HistorianCalling_T1.xml`..`T4.xml`: `YAE_ONLY` → `TEEN_OR_OLDER`. No Python `.ts4script` injection is needed. No SimData change is needed.

A subtle caveat: this bug *definitely* breaks the in-game `SimPersonalityAssignmentDialog` path. Whether it *also* breaks the very-first-time-in-CAS aspiration picker on the Olympus client (which is built before any Sim exists, and we couldn't decompile) is *empirically uncertain* — but the same enum-defaults-to-INVALID flow shows EA's adult aspirations (e.g. `aspiration_Knowledge_A1`, 127 of 139 EA aspirations) visible in CAS, which suggests CAS may pull from a path that doesn't gate on `is_valid_for_sim` — in which case we may have *two* bugs, with the enum bug being just one of them. Plan accordingly: fix the enum and observe.

---

## Q1. Does Sims 4 enumerate AspirationTracks from CombinedTuning or from per-resource SimData?

**Answer: Neither. It uses the `MergedTuningManager` which loads BOTH (a) EA's CombinedTuning blob *and* (b) loose tuning resources from mod packages, into a single `InstanceManager[ASPIRATION_TRACK]`.** Mod-added tracks DO get registered into the manager — the manager isn't the gate. The gate is downstream filter logic.

### Resource-type definition

`core.zip!sims4/resources.pyc` →
```python
ASPIRATION_TRACK = _add_inst_tuning("aspiration_track", resource_type=3223387309)
```
Defaults: `use_guid_for_ref=True`, `require_reference=False`, `base_game_only=False`, `manager_type=None` (→ default `InstanceManager`, NOT a specialized subclass). Type = `0xC020FCAD`.

### Load path (mod tunings → instance manager)

`core.zip!sims4/tuning/instance_manager.pyc:InstanceManager.create_class_instances`:

```python
def create_class_instances(self, packs_to_load=None, ...):
    mtg = get_manager()                                   # MergedTuningManager
    res_id_list = mtg.get_all_res_ids(self.TYPE)          # ALL aspiration_track resource IDs
    for group_id, instance_id in res_id_list:
        res_key = sims4.resources.Key(self.TYPE, instance_id, group_id)
        self._create_class_instance(res_key, group_id)    # → register_tuned_class()
```

`MergedTuningManager.get_all_res_ids` (`core.zip!sims4/tuning/merged_tuning_manager.pyc`):

```python
def get_all_res_ids(self, res_type):
    res_ext = sims4.resources.TYPE_RES_DICT[res_type]
    result_set = set()
    if res_ext in self._tuning_resources:                 # from EA CombinedTuning
        res_dict = self._tuning_resources[res_ext]
        result_set.update(((self.res_id_group_map.get(r, 0), r) for r in res_dict))
    if res_type in self.local_key_map:                    # from MOD packages
        result_set.update(self.local_key_map[res_type])
    if res_type in self.local_deleted_key_map:
        result_set -= set(self.local_deleted_key_map[res_type])
    return result_set
```

And `MergedTuningManager._load_combined_file_by_key` populates `local_key_map` by scanning live resource indexes (which include mod packages):

```python
local_files_tuple = sims4.resources.list_local(key=loader.resource_key, packed_types=tuning_resource_types)
local_key_list, local_deleted_list = local_files_tuple
for key in local_key_list:
    if key.type in tuning_resource_types and is_available_pack(key.group):
        self.local_key_map[key.type].add((key.group, key.instance))
```

So mod tunings at `group=0` (our build outputs all tunings at group=0; `Pack.BASE_GAME=0` from `core.zip!sims4/common.pyc:Pack`) get picked up here. `is_available_pack(0)` is True for the base game. Our `AspirationTrack` resource (type `0xC020FCAD`, group=0, instance=0x6621FF4B) gets added to `local_key_map[ASPIRATION_TRACK]`, then enumerated by `get_all_res_ids`, then loaded via `serialization.load_from_xml`:

`core.zip!sims4/tuning/serialization.pyc:load_from_xml`:
```python
if from_reload or mtg.local_key_exists(resource_key):
    loader = ResourceLoader(resource_key, resource_type)
    tuning_file = loader.load()
    if tuning_file is not None:
        return tuning_loader.feed(tuning_file)          # parse our XML
if mtg.has_combined_tuning_loaded:
    root_node = mtg.get_tuning_res(resource_key)        # else fall back to CombinedTuning
    if root_node is not None:
        return tuning_loader.feed_node(root_node)
```

For our mod, `local_key_exists` is True → it loads our XML directly. The class is then registered in `_tuned_classes` keyed by `(type=ASPIRATION_TRACK, instance=0x6621FF4B)`, and `guid64` is set to `0x6621FF4B`.

**Verdict**: hypothesis 1 from issue #17 ("the CAS picker reads its registry from CombinedTuning at boot, not per-resource") is **FALSE**. Mod tracks ARE loaded into the runtime instance manager. The problem is downstream.

---

## Q2. How do MC5 + lot51-core mods actually register their custom AspirationTracks?

**They don't do anything special — they ship the same shape we ship (tuning XML + SimData companion). This is consistent with the load path in Q1.**

### Mod-Constructor-5

`reference/mod-constructor-5/Constructor5.Elements/AspirationTracks/AspirationTrack.cs`:

```csharp
void IExportableElement.OnExport()
{
    var tuning = ElementTuning.Create(this);
    tuning.Class = "AspirationTrack";
    tuning.InstanceType = "aspiration_track";
    tuning.Module = "aspirations.aspiration_tuning";
    tuning.SimDataHandler = new SimDataHandler($"SimData/{GetSimDataFileName()}.data");
    ...
    TuningExport.AddToQueue(tuning);
}
```

Plus `AspirationTrackInfoComponent.cs` writes:
- `<T n="primary_trait">…` (mapped from `Category` ID via `GetDefaultCASTrait` — our mod implements the exact same mapping: Knowledge category 25385 → trait 27086)
- SimData offsets 136 (category), 144 (description), 148 (name), 152 (icon), 200 (primary_trait)

Plus `AspirationTrackMilestonesComponent.cs` writes the aspirations list to SimData offset 232. No Python registration.

### lot51-core

`reference/lot51-core/` has helpers for trait injection, whim-set injection, and pie-menu category remapping (`tested_pie_menu_category.py`) — **no AspirationTrack registration helper**. The library's `on_load_complete` decorator (`utils/injection.py:436-443`) is the only relevant primitive, and no consumer in the repo uses it for `Types.ASPIRATION_TRACK`.

### Verdict

Both reference mod tools rely on pure package-only load. So either (a) MC5/lot51 aspiration mods work in current Sims 4 via the package-only load path (matching the Q1 trace), or (b) MC5 aspiration mods don't actually work and no one has noticed. The forum chatter we've previously sampled suggests (a) — MC5 aspiration mods are in active use. So the package-only path **does** suffice when the tuning is well-formed.

---

## Q3. Canonical Python hook for registering a mod aspiration

**Not needed.** The instance manager already picks up our XML at boot. A Python `.ts4script` is unnecessary for this issue.

For completeness, if it ever WERE needed, the pattern would be:

```python
import services, sims4.resources
from sims4.tuning.instance_manager import InstanceManager

def _register_track(track_cls):
    mgr = services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK)
    if mgr is None:
        return
    res_key = sims4.resources.Key(sims4.resources.Types.ASPIRATION_TRACK, track_cls.guid64)
    mgr.register_tuned_class(track_cls, res_key)

# Or, more idiomatically, hook the manager's load-complete callback:
services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK).add_on_load_complete(
    lambda mgr: _do_post_load_work(mgr)
)
```

This pattern (`add_on_load_complete`) is the standard one used by lot51-core (`utils/injection.py:436`). But for *registering* a new track this isn't useful — the registration has already happened by the time the callback fires.

The only Python hook that would actually be needed is if we wanted to **bypass** the `is_valid_for_sim` filter — which is a separate (and worse) idea than fixing our enum value.

---

## Q4. The XML-only fix (the actual fix)

### Root cause — invalid enum value

`AspirationValidAgeType` is defined in `simulation.zip!aspirations/aspiration_tuning.pyc` (decompiled):

```python
class AspirationValidAgeType(enum.Int):
    INVALID = 0
    TODDLER_ONLY = Age.TODDLER         # = 2
    CHILD_ONLY = Age.CHILD             # = 4
    TEEN_ONLY = Age.TEEN               # = 8
    TEEN_OR_OLDER = Age.TEEN.value | Age.YOUNGADULT.value | Age.ADULT.value | Age.ELDER.value   # = 120
```

Member names (verified by disassembling the `.pyc`'s `co_names`):
```
('__name__', '__module__', '__qualname__', 'INVALID', 'Age', 'TODDLER',
 'TODDLER_ONLY', 'CHILD', 'CHILD_ONLY', 'TEEN', 'TEEN_ONLY', 'value',
 'YOUNGADULT', 'ADULT', 'ELDER', 'TEEN_OR_OLDER')
```

**`YAE_ONLY` is NOT in this list.** It does not exist as an enum member.

Our `Tuning/aspiration_HistorianCalling_T1.xml` (and T2, T3, T4) ships:
```xml
<E n="aspiration_valid_age_type">YAE_ONLY</E>
```

### What happens at load time

`core.zip!sims4/tuning/tunable.pyc:Tunable.load_etree_node` (line 1089 in the decompile):

```python
def load_etree_node(self, node, source, expect_error):
    if node is None: return self.default
    if node.text is None: ... return self.default
    try:
        content = node.text   # "YAE_ONLY"
        value = self._convert_to_value(content)
    except (ValueError, TypeError, KeyError):
        if getattr(self, "pack_safe", False):
            raise UnavailablePackSafeResourceError
        ...logs an error...
        return self.default   # default = AspirationValidAgeType.INVALID (= 0)
    else:
        return value
```

`TunableEnumEntry._convert_to_value`:
```python
def _convert_to_value(self, content):
    if content is None: return
    ...
    value = self._type(content)   # AspirationValidAgeType("YAE_ONLY")
    ...
```

Calling `AspirationValidAgeType("YAE_ONLY")` invokes the custom `enum.Metaclass.__call__` (`core.zip!enum.pyc`):
```python
def __call__(cls, value, names=None):
    ...
    if isinstance(value, str):
        try:
            return cls.name_to_value[value]              # KeyError — "YAE_ONLY" not in dict
        except KeyError:
            value = cls.underlying_type(value)           # int("YAE_ONLY") → ValueError
    ...
```

The `ValueError` propagates out, gets caught by `Tunable.load_etree_node`, falls back to `self.default = AspirationValidAgeType.INVALID (0)`. **Confirmed empirically** with a Python 3.7 simulation of the exact same metaclass call shape (see investigation log).

### What the loaded value means downstream

`Aspiration.is_valid_for_sim` (`simulation.zip!aspirations/aspiration_tuning.pyc`, decompiled bytecode — disassembled to confirm no rewrites):

```python
@blueprintmethod
def is_valid_for_sim(self, sim_info):
    return sim_info.age & self.aspiration_valid_age_type
```

`AspirationTrack.is_valid_for_sim` (classmethod, same module):

```python
@classmethod
def is_valid_for_sim(cls, sim_info):
    return cls._sorted_aspirations[0][1].is_valid_for_sim(sim_info)
```

`_sorted_aspirations[0]` is `(LEVEL_1, <aspiration_HistorianCalling_T1>)`. Calling `.is_valid_for_sim(sim_info)` returns `sim_info.age & 0`.

`enum.Int.__and__` (`core.zip!enum.pyc:230`):
```python
def __and__(self, other):
    int_result = super().__and__(other)
    if int_result:
        return type(self)(int_result)
    return type.__call__(type(self), 0)        # ← falsy 0-instance
```

So the AND with 0 returns a zero-valued enum instance — falsy in `if x:` context.

### Where the filter applies

Found three concrete callsites in EA's decompiled code:

1. **`simulation.zip!sims/sim_dialogs.pyc:SimPersonalityAssignmentDialog.build_msg` (line 122)** — the in-game "Choose Aspiration" dialog. Shown on age-up, adoption, "first time exiting CAS" follow-up, manual re-pick from the aspiration panel.
    ```python
    for aspiration_track in aspiration_track_manager.types.values():
        if (aspiration_tracker.is_aspiration_track_visible(aspiration_track)
            and aspiration_track.is_valid_for_sim(self._assignment_sim_info)
            and services.is_granted_or_non_account_reward_item(aspiration_track.guid64, AccountRewardType.ASPIRATIONTRACK)):
            msg.available_aspiration_ids.append(aspiration_track.guid64)
    ```

2. **`simulation.zip!sims/aging/aging_mixin.pyc:583`** — random aspiration pick during age-up.
    ```python
    if track_available and aspiration_track.is_valid_for_sim(self):
        ...
        self.primary_aspiration = random.choice(available_aspirations)
    ```

3. **`simulation.zip!sims/sim_info.pyc:114820`** — primary aspiration fallback when none is set on load.
    ```python
    for aspiration_track in aspiration_track_manager.types.values():
        if not aspiration_track.is_hidden_unlockable:
            if aspiration_track.is_valid_for_sim(self):
                ...
                available_aspirations.append(aspiration_track)
    ```

All three paths gate on `is_valid_for_sim`. All three are guaranteed to filter our track out as long as `aspiration_valid_age_type=INVALID`.

### The fix

For each of `Tuning/aspiration_HistorianCalling_T1.xml` through `T4.xml`:

```diff
-  <E n="aspiration_valid_age_type">YAE_ONLY</E>
+  <E n="aspiration_valid_age_type">TEEN_OR_OLDER</E>
```

`TEEN_OR_OLDER` has bitmask value `120 = Age.TEEN | Age.YOUNGADULT | Age.ADULT | Age.ELDER`, which correctly matches Young-Adult / Adult / Elder Sims (the audience for the Historian career) and also teens (a side benefit — teens can complete adult aspirations per the TDESC: *"Teen can complete both teen and YAE aspiration but YAE can not complete teen aspiration."*).

Also fix the comment in T1's header — the old commit's claim about "IndexError: tuple index out of range" is **wrong** (no tuple indexing exists in the current `is_valid_for_sim`). The actual mechanism is bitwise AND. The comment can be rewritten to reflect that, but the code fix is the same.

Also update `Build/simdata/src/build/enums.ts:100-107`. The current local enum table is **wrong**:
```typescript
export const ASPIRATION_VALID_AGE_TYPE: EnumMap = Object.freeze({
  INVALID: 0n,
  TODDLER_ONLY: 1n,    // WRONG — actual value is 2 (= Age.TODDLER)
  CHILD_ONLY: 2n,      // WRONG — actual value is 4 (= Age.CHILD)
  TEEN_AND_YAE: 3n,    // WRONG — doesn't exist as an enum member
  TEEN_ONLY: 4n,       // WRONG — actual value is 8 (= Age.TEEN)
  YAE_ONLY: 5n,        // WRONG — doesn't exist as an enum member
});
```

Should be:
```typescript
export const ASPIRATION_VALID_AGE_TYPE: EnumMap = Object.freeze({
  INVALID: 0n,
  TODDLER_ONLY: 2n,
  CHILD_ONLY: 4n,
  TEEN_ONLY: 8n,
  TEEN_OR_OLDER: 120n,  // = TEEN | YOUNGADULT | ADULT | ELDER = 8|16|32|64
});
```

(The `enums.ts` table is used by the SimData export to translate enum names to numeric values for binary serialization. We currently filter `aspiration_valid_age_type` *out* of the AspirationTrack and Aspiration SimData schemas — see `Build/simdata/src/build/classes/schemas.ts:75-82` — so the table isn't actively breaking us via SimData. But it's wrong, and we should fix it so future code that references the enum doesn't go astray.)

---

## Q5. The CAS UI SWF — is the picker ALSO filtered there?

**Inconclusive.** We did not extract or decompile the Olympus client SWF that backs CAS character creation. Two scenarios remain:

### Scenario A (likely): the initial-CAS picker uses the same Python `is_valid_for_sim` filter

If the Olympus CAS picker, when a player creates a new Sim, sends a `SimPersonalityAssignmentDialog`-equivalent request to the Python game (or invokes the same `SimPersonalityAssignmentDialog.build_msg` path), then our enum fix **is** the complete fix.

Indirect evidence in favor: the dialog class is `SimPersonalityAssignmentDialog`, named like an assignment-flow primitive, and `aging_mixin.py` and `sim_info.py` both use the same `is_valid_for_sim` gate when picking primary aspirations programmatically. So we'd expect the CAS picker to too.

### Scenario B: the initial-CAS picker uses a purely binary path (frozen ClientFullBuild index)

If the CAS picker scans `Data/Client/ClientFullBuild0.package` (and pack-delta equivalents) for `AspirationTrack` SimData resources WITHOUT going through Python and WITHOUT subscribing to mod-package SimData scan, then mods are locked out *regardless of XML correctness*. This is the PieMenuCategory pattern (verified for PMC by enumerating ClientFullBuild0 → 5,925 SimData entries, all 165 EA PMC instances present), except that for PMC mods CAN extend the index (the user's PMC fix shipped a mod-package SimData at the class-specific group and it WAS visible).

By analogy with the verified PMC fix, AspirationTrack mods *should* also extend the index — we ship SimData at `(type=0x545AC67A, group=0x0020FC6D, instance=0x6621FF4B)` and the UI should pick it up. But we have **no direct decompilation of the CAS SWF** to confirm.

### Why we couldn't fully verify

To distinguish A vs B with HIGH confidence we'd need either:

- **JPEXS Free Flash Decompiler (ffdec)** + extract the CAS UI SWF from `Data/Client/ClientFullBuild0.package` (or wherever the CAS Olympus app lives — the resource type for the SWF is unclear; candidates from the type-count table include `0x067CAA11`, `0x015A1849`, `0x01661233`), then find the function that backs `BuildAspirationList()` or equivalent. This is the gold-standard answer but takes 2-4 more hours.
- OR an in-game smoke test where we **first** ship the enum fix, then **independently** add a Python `.ts4script` that just logs `len(mgr.types)` for ASPIRATION_TRACK, then check the lastException / log files. If our track is in `mgr.types` and `is_valid_for_sim(adult_sim) == True` post-fix, AND we still don't see it in CAS, scenario B is real.

### Suspicious counter-evidence to Scenario A

EA's `aspiration_Knowledge_A1` (and 126 other EA aspirations — 127 of 139 total) ships **without** setting `aspiration_valid_age_type` at all, which means it loads with the same `default = INVALID = 0`. So those aspirations ALSO have `is_valid_for_sim() → falsy`. Yet they ARE visible in CAS. This suggests the initial-CAS picker may NOT actually call `is_valid_for_sim`. If true:

- Our enum fix **definitely** fixes the in-game aging-up dialog and the `sim_info.py` primary-aspiration fallback.
- It **may or may not** fix the initial-CAS picker.

If the enum fix alone doesn't restore initial-CAS visibility, the next investigation step is the SWF decompilation OR direct empirical test against the live game.

---

## Proposed fix (copy-pasteable)

### Patch 1 — fix the enum string in 4 aspiration tunings

For each of `Tuning/aspiration_HistorianCalling_T1.xml`, `_T2.xml`, `_T3.xml`, `_T4.xml`:

```diff
-  <E n="aspiration_valid_age_type">YAE_ONLY</E>
+  <E n="aspiration_valid_age_type">TEEN_OR_OLDER</E>
```

And update the inline comment block in T1.xml to reflect the actual mechanism (bitwise AND on `Age` flags, not tuple indexing):

```xml
<!--
  aspiration_valid_age_type must be set to a non-INVALID enum value that
  matches the target Sim's age bitmask (issue #13).

  Mechanism: at runtime EA's `Aspiration.is_valid_for_sim`
  (aspirations/aspiration_tuning.py) returns `sim_info.age & self.aspiration_valid_age_type`.
  If the field is `INVALID` (= 0), the AND is 0 (falsy) for every Sim →
  `AspirationTrack.is_valid_for_sim` (which checks LEVEL_1 only) also
  returns falsy → the track is filtered out of the SimPersonalityAssignmentDialog
  picker (sim_dialogs.py), the age-up dialog (aging_mixin.py), and the primary-
  aspiration fallback (sim_info.py).

  Valid enum members (verified by disassembling
  `simulation.zip!aspirations/aspiration_tuning.pyc` co_names):
    INVALID, TODDLER_ONLY, CHILD_ONLY, TEEN_ONLY, TEEN_OR_OLDER.
  Numeric bitmasks (from Age enum): TEEN_OR_OLDER = TEEN(8) | YOUNGADULT(16)
  | ADULT(32) | ELDER(64) = 120.

  Historian is an adult-only career, so TEEN_OR_OLDER is the right pick
  (teens can complete YAE aspirations per the TDESC).
-->
```

### Patch 2 — fix the local TypeScript enum table

In `Build/simdata/src/build/enums.ts:100-107`:

```diff
 export const ASPIRATION_VALID_AGE_TYPE: EnumMap = Object.freeze({
   INVALID: 0n,
-  TODDLER_ONLY: 1n,
-  CHILD_ONLY: 2n,
-  TEEN_AND_YAE: 3n,
-  TEEN_ONLY: 4n,
-  YAE_ONLY: 5n,
+  // Values are bitmasks from sims.sim_info_types.Age:
+  //   BABY=1, TODDLER=2, CHILD=4, TEEN=8, YOUNGADULT=16, ADULT=32, ELDER=64, INFANT=128
+  // Source: simulation.zip!aspirations/aspiration_tuning.pyc — class AspirationValidAgeType.
+  TODDLER_ONLY: 2n,
+  CHILD_ONLY: 4n,
+  TEEN_ONLY: 8n,
+  TEEN_OR_OLDER: 120n,   // = 8 | 16 | 32 | 64
 });
```

(Also bump `Build/simdata/src/build/enums.test.ts` if it asserts member-name list.)

### Verification

After patching, before reinstalling:

1. `cd Build/simdata && npm test` — should still be 69/69 (the schema doesn't include `aspiration_valid_age_type` in either AspirationTrack or Aspiration SimData; the only thing that touches `ASPIRATION_VALID_AGE_TYPE` is `enums.test.ts`, which we updated).
2. `cd Build/s4tk-builder && node build-package.mjs` — should produce a package indistinguishable in SimData layout from the current one (since SimData doesn't carry this field) but with the corrected XML.
3. **Critically**, fully clear the Sims 4 client/local caches: `localthumbcache.package`, `localsimtravelthumbcache.package`, and `cachestr/`, AND `Saves/Sims4.ver` if present — the prior broken state at our IDs likely cached the track in a "skip" state.
4. Install. Create a fresh save. Create a new young-adult Sim. Open CAS aspiration picker → "Wissen". Our "Historian's Calling" track should be visible.
5. If it's NOT visible: open `Documents/Electronic Arts/Die Sims 4/lastException.txt` (or `lastExceptionPyXX.txt`) and grep for `aspiration_HistorianCalling` and for `AspirationTrack`. Also enumerate `services.get_instance_manager(Types.ASPIRATION_TRACK).types` from a `.ts4script` console helper — verify our track is in the dict.

---

## Confidence and remaining unknowns

| Claim | Confidence |
|---|---|
| Mod AspirationTracks ARE loaded into the runtime instance manager via the same path as EA tracks | **HIGH** — verified by decompiling `merged_tuning_manager.pyc`, `instance_manager.pyc`, `serialization.pyc`. |
| `YAE_ONLY` is not a valid `AspirationValidAgeType` member in the current Sims 4 (1.124.55) | **HIGH** — verified by disassembling `aspiration_tuning.pyc`'s `co_names`. |
| `YAE_ONLY` at load time silently falls back to `INVALID = 0` | **HIGH** — verified by reading `Tunable.load_etree_node` (catches `ValueError, TypeError, KeyError`) and `enum.Metaclass.__call__` (raises `ValueError` from `int("YAE_ONLY")`), reproduced in a Python 3.7 simulation. |
| `is_valid_for_sim` returning falsy filters the track out of `SimPersonalityAssignmentDialog`, age-up, and the `sim_info.py` primary-aspiration fallback | **HIGH** — direct read of `sim_dialogs.py:122`, `aging_mixin.py:583`, `sim_info.py:114820`. |
| The recommended `TEEN_OR_OLDER` fix is sufficient for the in-game (post-CAS) aspiration UI | **HIGH** — direct consequence of the above. |
| The recommended fix is sufficient for the **initial CAS picker** during character creation | **MEDIUM** — depends on whether the Olympus CAS UI proxies the same Python filter or pulls from a binary index. We did not decompile the SWF. Counter-evidence: EA's adult aspirations also default to INVALID and show in CAS, suggesting the CAS UI may NOT actually call `is_valid_for_sim` — in which case our track might still be missing for a *different* reason (and the enum fix wouldn't be enough). |
| No Python `.ts4script` injection is needed for AspirationTrack registration | **HIGH** — Q1 trace shows the track is already in the instance manager, exactly the same shape as EA tracks. |

### Why MEDIUM (not HIGH) for "fix is sufficient"

EA's `aspiration_Knowledge_A1` (instance 25447, the L1 of EA's Renaissance Sim track) ships with NO `aspiration_valid_age_type` field set — it loads with `default = INVALID = 0`. So EA's own `is_valid_for_sim(adult_sim) → sim_info.age & 0 → 0`, which is falsy. Yet this aspiration IS visible in CAS.

Hypothesis (unverified): the Olympus CAS UI builds its track list from binary SimData scans (the PieMenuCategory pattern), bypassing the Python `is_valid_for_sim` filter entirely. The filter applies only to in-game aspiration *reassignment* dialogs, not initial CAS.

If that hypothesis is correct, then *something else* is filtering our track in CAS. Candidates we considered but couldn't decisively rule out:

- The CAS SWF requires a specific column-presence pattern in the AspirationTrack SimData (e.g., `primary_trait` non-zero, `category` resolvable). Our SimData has all of these. Byte diff (`Build/_research_tmp/ea_track_knowledge_a.simdata` vs `hc_track_historian.simdata`) shows the same 13-column schema, same hash `0x54FDB5FC`, same layout, only different name-hash / aspiration-instance-IDs / name string. So this is unlikely but not ruled out.
- The CAS SWF maintains a separate, install-time-frozen AspirationTrack catalog that pack updates extend but mods cannot. This would invalidate the PMC analogy. We have no direct evidence either way.
- The CAS save's previous broken state (when we shipped tier IDs that broke the career UI) is cached in `Documents/Sims4/...cache` and the cache hasn't been fully cleared. The user's earlier hand-picked 17-bit IDs broke the career UI — that suggests a heavy cache effect that may persist across rebuilds.

### What would lift confidence to HIGH

To get HIGH confidence that this is the complete fix:

1. **Ship Patch 1 (enum string fix), nuke all Sims4 caches, retest.** Two outcomes:
   - Track now visible in CAS → the in-game `is_valid_for_sim` filter *was* what CAS uses (scenario A). Done.
   - Track still missing → scenario B is real; proceed to step 2.

2. **Install JPEXS Free Flash Decompiler** (`https://github.com/jindrapetrik/jpexs-decompiler/releases` — single Windows exe, MIT). Bulk-extract `Data/Client/ClientFullBuild0.package` SWF-typed resources, run `ffdec` over them, search for `aspiration` / `Aspiration` / `Track_Knowledge`. Find the function that backs the CAS aspiration list (analogous to `InteractionMenuData/FetchCategory` for pie menu). That function will tell us exactly what catalog the CAS picker reads, and whether mod packages contribute to it.

3. **Alternative: a `.ts4script` diagnostic shim** under `Scripts/historian_career/_diag.py`:

```python
import services, sims4.resources, sims4.log
logger = sims4.log.Logger("HC_DIAG")

@services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK).add_on_load_complete
def _log_tracks(mgr):
    tracks = list(mgr.types.values())
    logger.always("AspirationTrack count: {}", len(tracks))
    for t in tracks:
        name = getattr(t, "__name__", "?")
        guid = getattr(t, "guid64", 0)
        if "HistorianCalling" in name or "Historian" in name:
            logger.always("  *** OUR TRACK: name={} guid64={:#x}", name, guid)
            # Probe is_valid_for_sim with a synthetic age
            try:
                first = t._sorted_aspirations[0][1]
                age_type = getattr(first, "aspiration_valid_age_type", "MISSING")
                logger.always("     T1 aspiration={} age_type={}", first.__name__, age_type)
            except Exception as e:
                logger.always("     T1 probe failed: {}", e)
```

This won't tell us about CAS specifically but will confirm our track is in `mgr.types` AND show us the loaded value of `aspiration_valid_age_type`. (We'd expect to see `AspirationValidAgeType.INVALID` pre-fix and `AspirationValidAgeType.TEEN_OR_OLDER` post-fix.)

### Final recommendation

**Ship Patch 1 + Patch 2, then retest with a full cache nuke.** If the track appears, we're done with **HIGH** confidence. If it doesn't, the diagnostic shim (or SWF decompile) is the next step. No Python injection is needed *for registration*; one may be needed *for diagnostics* if Patch 1 alone is insufficient.

### One-line action item

Replace `YAE_ONLY` with `TEEN_OR_OLDER` in all 4 `Tuning/aspiration_HistorianCalling_T*.xml` files. Also fix the values in `Build/simdata/src/build/enums.ts`. Rebuild, nuke caches, re-test.
