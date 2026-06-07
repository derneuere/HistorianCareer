# sims4ctl -- In-Game Spike (first manual end-to-end verification)

This is the **first** real-game proof that the whole loop works: build the bridge,
install it, launch the game, load a save, and watch a `ping` round-trip and a
`state career` come back from the live simulation. Everything else (host tests, the
build, the Python-3.7 syntax check) runs **without** the game; this spike is the one
step that needs The Sims 4 actually running.

Do this once on a fresh machine, and any time the bridge or protocol changes.

## Prerequisites

- The Sims 4 installed (target patch **1.124.55**) and launchable.
- The host CLI runnable (`sims4ctl ...` or `python -m sims4ctl ...`), Python 3.8+.
- A save you can load (any household with at least one Sim; ideally a Sim who has a
  career, so `state career` returns something non-empty).

Throughout, `<USERDATA>` = your Sims 4 user folder, i.e.
`Documents/Electronic Arts/{The|Die|Les|Los} Sims 4` (the one that contains
`Options.ini`). Run `sims4ctl doctor` to print the exact resolved path.

## Steps

### 1. Build the bridge

```
python build/build.py
```

Expect `build/out/sims4ctl_bridge.ts4script` to be produced. If you see a warning that
**Python 3.7 was not found**, install it from
https://www.python.org/downloads/release/python-379/ and rebuild -- the game may
silently refuse to load a `.ts4script` containing raw `.py` instead of `.pyc`.

### 2. Install the bridge into the Mods folder

```
sims4ctl install
```

This copies the `.ts4script` to `<USERDATA>/Mods/sims4ctl/`. Confirm with:

```
sims4ctl doctor
```

which prints the resolved USERDATA / Mods / bridge directories and the detected game
folder. The bridge `.ts4script` should be listed under the Mods/sims4ctl path.

### 3. Enable script mods

In the game (or before launching, in `Options.ini` if you prefer):

- **Game Options -> Other -> Enable Custom Content and Mods** = on
- **Enable Script Mods** = on
- **Restart the game** after changing these. Script mods are off by default and the
  setting only takes effect on a fresh launch.

### 4. Launch and load a save

```
sims4ctl launch
```

(or start the game however you normally do). Then, at the main menu, **load a save
manually** -- there is no headless mode and no save-load CLI argument in the MVP. The
bridge will report `zone_loaded: false` until a zone (a loaded lot) is actually live.

### 5. Confirm the bridge came up

Before issuing a verb, check the heartbeat:

```
sims4ctl doctor
```

A **fresh** heartbeat (recent `ts`) with `zone_loaded: true` means the bridge is wrapped
onto `on_tick` and a save is loaded. If the heartbeat is missing or stale, jump to
"If it fails" below.

### 6. Ping

```
sims4ctl ping
```

**Success looks like:**

```
{"pong": true, "zone_loaded": true, "active_sim": "<some Sim name>", "bridge_version": "<version>"}
```

The key signals are `pong: true` and `zone_loaded: true`. This proves the full
round-trip: the host wrote `request.json` with a fresh `seq`, the bridge picked it up on
a tick, executed on the main thread, and wrote a matching `response.json`.

### 7. State career

```
sims4ctl state career
```

**Success looks like** a JSON list of the active Sim's careers, each with live fields:

```
[{"name": "...", "user_level": 5, "simoleons_per_hour": 95, "track": "...", "title_stbl": "..."}]
```

An **empty list** is a valid result too -- it just means the active Sim has no career.
To get a non-empty result, load a save whose active Sim is employed (or assign one a
career first). `simoleons_per_hour` and `title_stbl` are read live from the current
`CareerLevel` tuning, so they always reflect the Sim's actual rank.

## What success means

If steps 6 and 7 both return as above, the end-to-end loop is verified:
host CLI -> `request.json` -> on_tick poll -> main-thread dispatch -> live `services`
read -> `response.json` -> host. From here the example scenario
(`scenarios/historian_career.py`) and any CI gate can drive the game with confidence.

## If it fails

Work down this list; the heartbeat and the log are your two best signals.

1. **`ping` times out / heartbeat missing or stale.** The bridge isn't running.
   - Open `<USERDATA>/sims4ctl/heartbeat.json`. Missing = the `.ts4script` never
     loaded. Present but old `ts` = the bridge stopped ticking (e.g. you returned to the
     main menu). Present and fresh but `zone_loaded: false` = bridge is alive, no save
     loaded -- load a save.
2. **Read the bridge log.** `<USERDATA>/sims4ctl/bridge.log` is append-only and records
   the install of the on_tick hook and every request handled.
   - **No log file at all** -> the package didn't load. Re-check that script mods are
     enabled *and* that you restarted the game after enabling them; confirm the
     `.ts4script` is in `<USERDATA>/Mods/sims4ctl/` (via `sims4ctl doctor`); and that the
     build shipped `.pyc` (not raw `.py`).
   - **Log shows the hook installed but no requests handled** -> the host and bridge may
     be looking at different directories. Re-run `sims4ctl doctor` and verify both sides
     resolve the same `<USERDATA>/sims4ctl/`.
   - **Log shows an exception while handling a request** -> that's a bug in the verb/
     serializer; the corresponding `response.json` will have `ok:false` and an `error`.
3. **Clear caches and relaunch.** Delete `localthumbcache.package`, and the contents of
   the `cache/` and `cachestr/` folders under `<USERDATA>`, then relaunch. A stale cache
   can hide a freshly installed mod.
4. **Check for game crashes.** `sims4ctl crashes` (works with no bridge) diffs
   `lastException*.txt` / `lastUIException*.txt` under `<USERDATA>` -- use
   `sims4ctl crashes --mark` before a run and `sims4ctl crashes --since-mark` after to
   see if the game logged a new exception.

## Reading bridge.log

`bridge.log` lives at `<USERDATA>/sims4ctl/bridge.log`, is plain text, and is
append-only (the bridge never truncates it). You'll see, roughly in order:

- a module-import / hook-install line when the `.ts4script` loads,
- periodic heartbeat or tick activity,
- one line per request handled, with the `seq`, the `verb`, and whether it succeeded;
  failures include the exception and traceback.

Tail it while you run CLI commands to watch requests arrive and responses go out in
real time -- it's the ground truth for "did the bridge actually see my request."

## Results -- verified in-game (patch 1.124.55)

The spike was run end-to-end against a live game on **The Sims 4 patch 1.124.55**.
The full loop works: the game launches, loads a save, and the bridge round-trips
every verb. Below are the concrete findings.

### Real bugs the live spike surfaced in the bridge (and the fixes)

The bridge was written against the documented design, but running it inside the
real game exposed three bugs that only the live runtime could reveal:

1. **`core_services` is NOT an importable module.** The design (and prior-art
   write-ups) referred to `core_services.on_tick`, but in 1.124.55 there is no
   importable `core_services` to hook -- the import fails at module load and the
   bridge never installs. **Fix:** hook the zone spin-up instead by wrapping
   `zone.Zone.do_zone_spin_up` (save the original, call it, then start our
   per-tick drain). That is a stable, importable seam that fires exactly when a
   zone becomes live, which is also precisely when `services.*` become usable.

2. **`add_alarm_real_time` has no `repeating_time_span` argument.** The first
   attempt scheduled the drain via a real-time alarm using a `repeating_time_span`
   keyword; in 1.124.55 that argument does not exist and the call raised. **Fix:**
   schedule the alarm with the signature the runtime actually accepts (a single
   repeating interval), dropping the unsupported keyword.

3. **(The important one.) The repeating `AlarmHandle` must be retained at module
   scope or it is garbage-collected and the alarm silently stops.** When the
   handle returned by the alarm-registration call was only a local variable, it
   was collected after spin-up returned, the alarm was torn down, and the bridge
   went silent with **no error in the log** -- the hardest failure mode to
   diagnose. **Fix:** store the `AlarmHandle` in a module-level global so it stays
   alive for the life of the process; the drain then fires reliably for the whole
   session.

### Verbs confirmed round-tripping live

With the bridge installed and a save loaded, every verb round-trips against the
live simulation:

- **`ping`** -> `pong: true`, `zone_loaded: true`, the active Sim's name, and the
  bridge version.
- **`state`** -> `sim`, `career`, and `clock` topics all return live, correct data
  re-queried each call (career pulls level/pay/title from the current
  `CareerLevel` tuning; clock returns the in-game day/time and speed).
- **`eval`** -> evaluates expressions in-game and returns the repr/JSON value.
- **`cmd`** -> runs cheat-console commands via `sims4.commands.execute`.
- **`crashes`** -> diffs `lastException*.txt` / `lastUIException*.txt` (host-side,
  works with no bridge).

### Confirmed the HistorianCareer issue-#24 AspirationTrack fix in-game

The spike was used to validate the sibling `HistorianCareer` mod's issue-#24
AspirationTrack fix on this patch. With the fixed package installed, the **game
launches and loads the save clean** -- the adult AspirationTrack tuning loads
without error and **no new `lastUIException`** is produced (verified with
`crashes --mark` before / `crashes --since-mark` after). The earlier
column-count mismatch no longer crashes the load.

### Caught a real HistorianCareer bug: the career paid §0/h

While walking the career levels live, `state career` reported
`simoleons_per_hour: 0` at every level -- the Historian career **paid §0/h**. The
root cause: the level tunings used the deprecated **`simoleons_per_hour`** field
instead of the current **`pay_type`** mechanism, so the runtime computed no wage.
This was a genuine content bug in the mod that only surfaced because the bridge
could read the Sim's *actual* live pay rather than the authored tuning value.
(This is also why the bridge now exposes an explicit `pay` field mirroring
`simoleons_per_hour` in the `career` state -- so the pay signal is unambiguous.)
