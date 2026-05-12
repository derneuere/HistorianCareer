# NOTE — PieMenuCategory needs a 31-bit instance ID (issue #14 → handoff to #15)

**Author:** issue #14 agent
**Audience:** issue #15 agent (owns `Build/s4tk-builder/build-package.mjs`)
**Status:** investigation finding — recommended integration follows.

## TL;DR

EA's `PieMenuCategory` instance IDs are 16–32 bit (`computer_Handiness` = 37041 = 0x90B1; other EA categories in the same range up to ~40000). Our default builder hashes every tuning name with `fnv64(name, highBit=true)` and produces a 64-bit value.

In v0.2.1, adding `<T n="category">{decimal_instance_id}</T>` to a `SuperInteraction` with that 64-bit ID **crashes the pie-menu generator with no `lastException` entry**. Hypothesis 1 from issue #14: the `category` field is a `TunableReference` constrained to ≤ 2^31 — the resolver chokes on 64-bit values.

The fix: build `PieMenuCategory` resources with a small instance ID (≤ 2^31 - 1) and emit the same value when serialising any `<T n="category">` reference that targets one. Logic is implemented in `Build/s4tk-builder/pie-menu-category-id.mjs` (sibling helper, ready to import).

## What I changed in this PR

- `Tuning/HC_Interaction_*.xml` (×5): added `<L n="interaction_category_tags">` with `Interaction_Super` + `Interaction_All` (hypothesis 2 from #14 — 1,124/1,124 EA SIs carry this list; likely required infrastructure).
- `Build/s4tk-builder/pie-menu-category-id.mjs`: new helper exporting `smallInstanceIdFor(tuningName)`, `SMALL_ID_CLASSES`, and `assertNoCollisions(map)`.
- This NOTE.
- **I did NOT touch `build-package.mjs`** because issue #15 is editing it in parallel.

`<T n="category">` is **deliberately still absent** from the 5 `HC_Interaction_*.xml` files — wiring it in needs the 31-bit ID change to land first.

## Recommended integration in `build-package.mjs`

When you walk `Tuning/*.xml` and compute the instance ID, branch on the class attribute:

```js
import {
    SMALL_ID_CLASSES,
    smallInstanceIdFor,
    assertNoCollisions,
} from "./pie-menu-category-id.mjs";

// ...inside the per-file loop, after parsing attrs.c:
const instance = SMALL_ID_CLASSES.has(cAttr)
    ? smallInstanceIdFor(tuningName)
    : fnv64(tuningName, true);
```

The existing `usedInstances` map will still catch cross-file collisions. If you want belt-and-braces, also call `assertNoCollisions` on just the small-ID subset before writing the package — gives a clearer error message if two category names happen to alias.

## How `<T n="category">` should be emitted on a SuperInteraction

For each SI that wants to attach to a category by name (e.g. `HC_PieMenuCategory_Historian`), it will need a new XML line:

```xml
<T n="category">{decimal_id_of_HC_PieMenuCategory_Historian}</T>
```

There are two ways to wire this:

1. **Post-process on emit (cleanest).** The source XML uses a placeholder like `<T n="category">HC_PieMenuCategory_Historian</T>` (tuning-name reference). The builder, when emitting a SuperInteraction, replaces that text with `smallInstanceIdFor("HC_PieMenuCategory_Historian").toString()` — a decimal integer.
2. **Macro placeholder.** Same as the `0xTBD_STBL_KEY_*` and `s="TBD_INSTANCE_ID"` substitutions you already do, but for category refs. Pattern: `0xTBD_CATEGORY_ID_<TuningName>` → decimal small ID.

I'd recommend (1) — it's symmetric with how every other tuning-name reference works (e.g. `<T>HC_Loot_Add_HistorianLevel_Small</T>` in `loot_list`), and the rule "anything referencing a PieMenuCategory tuning name gets resolved to a 31-bit decimal" is local to one place in the builder.

## Open question — do NOT auto-enable on the 5 SIs yet

Even with a 31-bit ID, hypothesis 2 (interaction_category_tags required) may also be a precondition. I've added the tags but **left `<T n="category">` off the SIs** because the crash in v0.2.1 occurred with no `lastException` — i.e. it's silent and hard to debug. Once your 31-bit ID work is in, try the change in this order:

1. Build the package as-is. Confirm the 5 interactions still appear flat in the pie menu (regression check; `interaction_category_tags` alone should not change behaviour).
2. Add `<T n="category">HC_PieMenuCategory_Historian</T>` to **one** SI (e.g. `HC_Interaction_TranscribeManuscript.xml`). Rebuild, install, test. Either the Historian submenu appears with one item, or the pie menu silently breaks again.
3. If (2) works, add to the remaining 4. If (2) fails, hypothesis 3 (different mechanism — Snippet, reverse listing, object_tag_set) is live and we need another round of EA goldens.

## Test coverage

`Build/simdata/test/` only covers the 9 classes the simdata generator handles; SuperInteraction isn't one of them (it's pure XML). No existing test file is the right place for the 31-bit-ID logic. If you want a quick guard, a tiny test file inside `Build/s4tk-builder/` (e.g. `pie-menu-category-id.test.mjs` driven by `node --test`) is the lowest-friction add. Sample assertions:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { smallInstanceIdFor, PIE_MENU_CATEGORY_ID_MASK } from "./pie-menu-category-id.mjs";

test("smallInstanceIdFor stays in [1, 2^31 - 1]", () => {
    const id = smallInstanceIdFor("HC_PieMenuCategory_Historian");
    assert.ok(id >= 1n);
    assert.ok(id <= PIE_MENU_CATEGORY_ID_MASK);
});

test("smallInstanceIdFor is deterministic", () => {
    const a = smallInstanceIdFor("HC_PieMenuCategory_Historian");
    const b = smallInstanceIdFor("HC_PieMenuCategory_Historian");
    assert.equal(a, b);
});
```

## References

- Issue #14 — pie menu submenu grouping investigation.
- `Build/s4tk-builder/pie-menu-category-id.mjs` — the helper module.
- `Tuning/HC_PieMenuCategory_Historian.xml` — the target resource (still uses `s="TBD_INSTANCE_ID"`; you'll resolve it to the 31-bit value).
- `Tuning/HC_Interaction_*.xml` — five SIs, all now carry `interaction_category_tags`, none yet carry `<T n="category">`.
