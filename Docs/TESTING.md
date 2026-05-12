# Testing Guide — Historian Career

A practical, cheat‑driven workflow. The idea: don't grind a real game through 5 careers — use the console to teleport through every state, confirm each piece works, and look for `LastException.txt`.

---

## 0) One‑time setup (every test session)

1. **Pin the game patch you're testing against.** Note the patch version (Main Menu → bottom right) in your build notes. EA renumbers tuning hashes on patches, so tests are only valid for the patch you built against.
2. **Back up your save.** `Documents\Electronic Arts\The Sims 4\saves\` — copy the `slot_*` files somewhere safe. Custom careers can break ongoing saves if you uninstall mid‑career.
3. **Use a clean Mods folder for the first run.** Move all other mods to `Mods_OFF\`, leaving only:
   - `HistorianCareer_Tuning.package`
   - `HistorianCareer.ts4script`
   - `XmlInjector_v4.ts4script` (Scumbumbo's, if you're using the injector path)
4. **Delete the cache:** `Documents\Electronic Arts\The Sims 4\localthumbcache.package`.
5. **Enable script mods** in‑game: `Options → Other → Enable Custom Content and Mods` + `Enable Script Mods` → restart.
6. **Start a fresh save** with a young‑adult Sim in any world. Don't bother with Career Counsellor / aging — we'll cheat past everything.
7. **Open the console:** `Ctrl + Shift + C` → type `testingcheats true` → Enter.

---

## 1) Smoke test (does it load at all? — ~30 seconds)

After enabling cheats:

```
help
```
Output should scroll without errors. Now look at `Documents\Electronic Arts\The Sims 4\LastException*.txt` — if any file appears with a timestamp from after launch, **stop and read it**. A stack trace inside means a tuning resource failed to load; the file name in the trace tells you which one. Most common cause: a tuning name reference like `HC_Interaction_TranscribeManuscript` that S4S didn't find a hash for (rename mismatch).

If `LastException` is clean: proceed.

---

## 2) Test Layer A — pie‑menu interactions (5 minutes)

These run independently of the full Career.

```
testingcheats true
stats.set_skill_level Major_ResearchDebate 10
stats.set_skill_level Major_Writing 10
```

Now grant the History major trait (you'll need the exact resolved trait name — see Implementation Guide step 2; if you went with EA's name, the most common one is shown below):

```
traits.equip_trait trait_University_Major_History_Completed
```

If the trait command errors with "Trait not found", you didn't resolve the placeholder. Fix in S4S, rebuild, retry.

Click a computer:
- [ ] **Historian** sub‑menu visible
- [ ] **Transcribe Manuscript** runs → §, "Wissenschaftliche Hilfskraft" promotion popup, statistic = 1
- [ ] **Analyze Primary Source** now visible (was hidden before stat hit 1) → §§, focused buff, statistic = 2
- [ ] **Present at Symposium** appears at stat 2, runs at skill ≥ 7 → confidence buff, stat = 3
- [ ] **Habilitation Lecture** appears at stat 3, runs at Writing ≥ 7 → stat = 5 (medium loot is +2)
- [ ] **Supervise Dissertation** appears at stat 4, runs only with both skills = 10 → max popups fire

To inspect / reset the statistic mid‑flight:
```
stats.set_stat HC_Statistic_HistorianLevel 0     # reset
stats.set_stat HC_Statistic_HistorianLevel 3     # jump to where L4 interaction unlocks
```

---

## 3) Test Layer B — the real Career (15 minutes)

### Join the career

```
careers.add_career career_Adult_Historian
```

Expected:
- [ ] No error in console
- [ ] Career panel (top‑right of the UI) shows "Historian" with the L1 title "Wissenschaftliche Hilfskraft"
- [ ] Pay/h shows §40
- [ ] Daily task panel shows the L1 aspiration objectives ("Read a non‑fiction book", "Transcribe a manuscript (2)")

Error to expect if the trait gate didn't resolve: **"Career not found"** — means the Career tuning didn't load. Check `LastException`, check that you generated SimData for `career_Adult_Historian` in S4S, check that the trait name in the `career_availability_test` matches the trait that exists in your install.

### Jump through every level

```
careers.promote career_Adult_Historian
```

Run that 4 times. Each time:
- [ ] The career panel title updates to L2, L3, L4, L5 titles
- [ ] Pay rate increases (40 → 70 → 120 → 200 → 340)
- [ ] At L5 (Professor W3) the Sim gets the **Habilitation Renown** trait (check trait list in Simology)
- [ ] Daily tasks update to the per‑level aspiration

If a promotion silently does nothing, the `promotion_test` is failing. The L3 promotion needs Research & Debate 7; L4 needs Writing 7; L5 needs both at 10. Cheat the skills first:

```
stats.set_skill_level Major_ResearchDebate 10
stats.set_skill_level Major_Writing 10
careers.promote career_Adult_Historian
```

### Verify work schedule

- [ ] Without further cheats, advance time (`hover the clock → fast forward`) to 09:00 on a weekday. The Sim should auto‑prepare to go to work. At 13:00 (L1) or 17:00 (L2/L3) or 18:00 (L4/L5) they return.
- [ ] Optional: `careers.go_to_work` to send them immediately.
- [ ] Optional: `careers.toggle_skip_career_career_Adult_Historian` to fast‑complete a workday.

### Verify daily tasks

For the **L1 → L2** transition:
1. Career panel should list daily‑task objectives.
2. Right‑click a computer → run **Transcribe Manuscript** twice and read any book — the objective ticks should reach 100%.
3. Performance bar should fill more than a vanilla workday.

### Verify the chance card

Chance cards fire stochastically. To force one:
```
careers.fire_chance_card career_Adult_Historian
```
(If the command isn't recognised in your patch, the alternative is to use `careers.skip_to_next_day` repeatedly — they fire roughly weekly.)

- [ ] The Plagiarism dialog appears with two options.
- [ ] Picking option A drops performance and applies an embarrassed buff.
- [ ] Picking option B triggers a 50/50 roll — re‑run a few times to see both outcomes.

### Verify the long aspiration

```
aspirations.add_aspiration aspiration_track_HistorianCalling
```

- [ ] Aspiration panel shows "Historian's Calling" / "Berufung Historiker:in"
- [ ] Tier 1 is active with the manuscript objective
- [ ] `aspirations.complete_current_milestone` should advance tiers
- [ ] On tier 4 completion: **Habilitation Renown** trait awarded (also given at career L5, so it's idempotent)

### Demote / fire / retire

```
careers.demote career_Adult_Historian
careers.retire career_Adult_Historian
careers.remove_career career_Adult_Historian
```
- [ ] Each runs without exception
- [ ] After `remove_career`, the career panel clears

---

## 4) Negative tests (verify the gates actually gate)

These matter — if the History‑degree gate doesn't work, the career is just a generic career with a German name.

1. Start a fresh Sim with **no university trait**. Run:
   ```
   careers.add_career career_Adult_Historian
   ```
   - [ ] Should print "Cannot join Historian: missing required trait" (or similar). If the Sim *does* join, the `career_availability_test` block didn't resolve in S4S — the test block is silently no‑op'd by EA when the trait name is unknown. Re‑check step 2 of the Implementation Guide.

2. Equip the wrong major (e.g., Art History trait if it exists, or `trait_University_Major_Biology`):
   ```
   traits.equip_trait trait_University_Major_Biology_Completed
   careers.add_career career_Adult_Historian
   ```
   - [ ] Same expected rejection.

3. Try to promote to L5 with Writing = 9:
   ```
   stats.set_skill_level Major_ResearchDebate 10
   stats.set_skill_level Major_Writing 9
   careers.promote career_Adult_Historian   # repeat until at L4
   careers.promote career_Adult_Historian   # this one should refuse
   ```
   - [ ] L5 promotion does NOT happen. Bump Writing to 10 and it should succeed.

---

## 5) Stability test (run before any release)

- [ ] Play a full sim‑week with the career active. Use `time.gameplay_clock_speed 3` if you want it fast.
- [ ] At the end, check `LastException*.txt` for any new files.
- [ ] Save, exit, relaunch, load. Career state should persist (title, level, statistic value, trait).
- [ ] Move to the "kitchen‑sink" Mods folder (all other mods restored). Repeat steps 2 and 3. If anything breaks, the conflict is almost always with another mod that overrides `careers.career_tuning` or the computer object — name and shame in the README.

---

## 6) Cheat cheat‑sheet (copy‑paste reference)

| Command | Effect |
|---|---|
| `testingcheats true` | Enables the others |
| `careers.add_career career_Adult_Historian` | Hire into Historian |
| `careers.promote career_Adult_Historian` | +1 level (respects promotion_test) |
| `careers.demote career_Adult_Historian` | −1 level |
| `careers.remove_career career_Adult_Historian` | Quit |
| `careers.retire career_Adult_Historian` | Retire (pension) |
| `careers.go_to_work` | Send to work immediately |
| `careers.fire_chance_card career_Adult_Historian` | Trigger a chance card now |
| `stats.set_skill_level Major_ResearchDebate 10` | Max Research & Debate |
| `stats.set_skill_level Major_Writing 10` | Max Writing |
| `stats.set_stat HC_Statistic_HistorianLevel 5` | Force the custom statistic |
| `traits.equip_trait trait_University_Major_History_Completed` | Grant History major (verify exact name in S4S) |
| `traits.equip_trait trait_HabilitationRenown` | Grant the reward trait directly |
| `aspirations.add_aspiration aspiration_track_HistorianCalling` | Add the long aspiration |
| `aspirations.complete_current_milestone` | Advance to next aspiration tier |

---

## 7) When a test fails

The first thing to read is always `Documents\Electronic Arts\The Sims 4\LastException*.txt`. Two patterns to recognise:

- **`KeyError` or "Could not find tuning"**: a name reference in your XML doesn't resolve. Open the named XML in S4S, check its Instance ID is set, check that the resource type matches the `<I c="…">` class.
- **`AttributeError` inside a tuning class**: a tunable field is wrong shape. Compare against the EA original you extracted as a template — `<T>` vs `<V>` vs `<U>` mistakes are common.

If you don't see an exception but in‑game nothing visible happened (no popup, no career panel update), the resource probably loaded fine but a test block silently filtered everything out. Comment out the `test_globals` / `promotion_test` block in the offending XML, rebuild, and confirm the rest works — then add the test back and find what's wrong with it.
