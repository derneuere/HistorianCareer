# sims4ctl

A game-generic CLI and in-game bridge that drives a **running** copy of The Sims 4
from the outside, so an agent (or a human) can run automated, repeatable in-game
tests. You install a tiny `.ts4script` mod, launch the game, load a save, and then
poke the live simulation from your terminal:

```
sims4ctl ping
sims4ctl state career
sims4ctl advance 4h
sims4ctl crashes --since-mark
```

It is NOT specific to any one mod; it ships an example scenario that exercises the
sibling `HistorianCareer` mod, but the bridge and CLI know nothing about it.

## Why a scripting API beats pixels and memory

There are three ways an external agent can observe and act on a game, and they are
not equal:

- **(a) Pixels** -- screen-scrape the rendered frame and synthesize mouse/keyboard.
  Brittle: breaks on any UI/theme/resolution change, can't read hidden state
  (a Sim's skill level isn't on screen), and slow.
- **(b) Memory** -- attach to the process and read/write raw addresses. Fragile
  across patches, address-hunting is painful, and a wrong write corrupts the heap.
- **(c) A first-class scripting API** -- call into the game's own runtime in its own
  language, using the same objects the game uses. Stable across cosmetic changes,
  sees *all* state (it asks the simulation directly), and acts through sanctioned
  code paths.

The Sims 4 is squarely category **(c)**: the engine embeds **CPython 3.7** and loads
`.ts4script` mods that monkey-patch the live runtime. That gives us an in-process
scripting channel -- the most reliable agent<->game link available. `sims4ctl` is built
on this fact. Real mods prove the pattern (see Prior art below); the lesson we borrow
from Factorio's RCON/Lua and the Factorio Learning Environment is: keep the wire
command thin, do the rich work as an in-game function that returns typed JSON, and
**always re-query live state -- never trust a cached snapshot.**

## Architecture

Two processes talk over a tiny file channel in the Sims 4 user-data folder.

```
  +-----------------------------+                         +-------------------------------------+
  |   host CLI: sims4ctl        |                         |   in-game bridge (.ts4script)       |
  |   Python 3.8+, stdlib only  |                         |   CPython 3.7, stdlib only          |
  |                             |   file IPC (request/    |                                     |
  |   write  request.json  -----+---  response JSON in ---+--->  on_tick poll (throttled)       |
  |   poll   response.json <-----+---  <USERDATA>/sims4ctl/ <---  dispatch on the MAIN thread   |
  |   read   heartbeat.json <----+-------------------------+----  services.* / sim_info.* -> dict|
  |   watch  lastException*.txt  |                         |   json.dumps -> response.json       |
  +-----------------------------+                         +-------------------------------------+
            terminal / CI                                       inside the live game process

  request.json   { seq, verb, args }            heartbeat.json  { tick, zone_loaded, active_sim, ... }
  response.json  { seq, ok, result, error, ts } bridge.log      append-only debug trail
```

- **host CLI** writes `request.json`, then polls `response.json` until the matching
  `seq` appears (or it times out). It also watches the game's crash logs and never
  needs the game to be installed to run its own tests.
- **in-game bridge** wraps `core_services.on_tick`. On each tick (throttled to roughly
  every ~15 ticks) it reads `request.json`, and if there is new work, executes it **on
  the main thread**, serializes the result, and atomically writes `response.json`. It
  refreshes `heartbeat.json` ~2x/second so the host can tell the bridge is alive and
  whether a zone (save) is loaded.

Transport is **file-based request/response** on purpose: zero dependencies, robust
across process restarts, trivially inspectable (just open the JSON), and nothing is
ever bound to a network socket.

## Install & quickstart

The bridge is the only piece that must run *inside* the game. The host CLI runs in
your terminal.

1. **Build the bridge.** Produces `build/out/sims4ctl_bridge.ts4script`.
   ```
   python build/build.py
   ```
   The build compiles the bridge `.py` to `.pyc` with **Python 3.7** (matching the
   game's interpreter -- `.pyc` bytecode magic is version-locked). If 3.7 is missing
   it warns and ships raw `.py` (which the game may refuse to load -- install 3.7
   from https://www.python.org/downloads/release/python-379/).

2. **Install the bridge into the Mods folder.** Copies the `.ts4script` to
   `<USERDATA>/Mods/sims4ctl/`.
   ```
   sims4ctl install
   ```

3. **Enable script mods.** In the game: **Game Options -> Other -> Enable Custom
   Content and Mods** *and* **Enable Script Mods**, then restart the game once.

4. **Launch the game and load a save.** Optionally `sims4ctl launch` starts
   `TS4_x64.exe`. There is **no headless mode and no save-load CLI argument** for the
   MVP, so once the main menu appears you must **load a save manually** to get into a
   loaded zone. The bridge only sees live state once a zone is loaded.

5. **Probe it.**
   ```
   sims4ctl ping
   # -> {"pong": true, "zone_loaded": true, "active_sim": "Bella Goth", "bridge_version": "..."}

   sims4ctl state career
   # -> [{"name": "...", "user_level": 5, "simoleons_per_hour": 95, "track": "...", "title_stbl": "..."}]
   ```

If `ping` returns `pong: true` and `zone_loaded: true`, the round-trip works. See the
in-game spike checklist in `docs/IN_GAME_SPIKE.md` for the full first-run procedure.

## Command reference

`sims4ctl <command> [args] [--json]`. Commands that need the bridge fail non-zero if
the game/bridge isn't responding so scripts and CI can gate on them. `--json` prints
the raw JSON result.

| Command                         | Needs bridge? | What it does |
|---------------------------------|:-------------:|--------------|
| `ping`                          | yes | Round-trip health check. Returns `{pong, zone_loaded, active_sim, bridge_version}`. |
| `cmd "<cheat>"`                 | yes | Runs a cheat-console command via `sims4.commands.execute`. Returns `{executed, output}` (output capture is best-effort). |
| `eval "<code>" [--exec]`        | yes | Evaluates a Python expression in-game (namespace exposes `services`, `sims4`, `hc`). With `--exec`, runs statements and captures stdout. **Arbitrary code -- dev only.** |
| `state [topic] [--career NAME]` | yes | Re-queries live state. `topic` is one of `career`, `skills`, `traits`, `sim`, `clock`, `all` (default `all`). |
| `advance <4h\|30m\|2h30m>`      | yes | Sets super speed and advances the game clock by the given amount. Returns the new `clock`. Time only moves while unpaused and not in a modal/CAS/Build (see Limits). |
| `crashes [--mark \| --since-mark]` | no | Snapshots/diffs `lastException*.txt` + `lastUIException*.txt` under `<USERDATA>` by mtime+size; reports new/changed. Works with **no bridge running**. |
| `install`                       | no | Builds the bridge `.ts4script` and copies it to `<USERDATA>/Mods/sims4ctl/`. |
| `launch`                        | no | Starts `TS4_x64.exe` (Steam default `C:/Program Files (x86)/Steam/steamapps/common/The Sims 4/Game/Bin/TS4_x64.exe`). |
| `doctor`                        | no | Prints the resolved USERDATA/Mods/bridge directories and reports heartbeat freshness + game-folder detection. |

### Recipe B — autonomous loop (launch → load save → run → quit)

These commands close the **menu → loaded-save** gap that has no in-game Python
API, by launching the game and synthesizing **mouse clicks** against configurable
targets. The click coordinates/templates are **placeholders that must be
calibrated** against the live game first — see [`docs/RECIPE_B.md`](docs/RECIPE_B.md).
Driving the live game needs the optional deps: `pip install sims4ctl[automation]`
(the base CLI stays dependency-free).

| Command                          | Needs bridge? | What it does |
|----------------------------------|:-------------:|--------------|
| `start [--exe]`                  | no | Launch TS4 (`steam://rungameid/<appid>`, appid read from `steam_appid.txt`; `--exe` forces the raw exe) and wait for the main **MENU**. |
| `stop [--save]`                  | optional | With `--save` and a zone loaded, best-effort in-game `save` via the bridge, then `taskkill /IM TS4_x64.exe` (`/F` fallback). TS4 does not autosave on exit. |
| `load-save [--continue \| --slot N]` | yes (to confirm) | Focus the window, optionally dismiss the startup MODS dialog, click **Spiel fortsetzen** (Continue, default) or **Spiel laden → slot → confirm**, then wait for **ZONE_LOADED**. |
| `new-game`                       | no | Click **Neues Spiel** (stub — does not automate CAS to a zone). |
| `run-scenario <name> [--auto]`   | yes | Run `scenarios/<name>.py`. `--auto` ensures ZONE_LOADED first (`start` + `load-save --continue` as needed). Exit code is the scenario's. |
| `wait-for <state> [--timeout]`   | for ZONE_LOADED | Block until `DOWN`/`MENU`/`LOADING`/`ZONE_LOADED` or time out (non-zero). |
| `state --menu-aware`             | no | Report the gamestate (`DOWN`/`MENU`/`LOADING`/`ZONE_LOADED`) instead of in-zone state; never blocks on the bridge. |
| `calibrate [--out PNG] [--crop LABEL L T R B]` | no | Capture the game window and print its client rect + size so click coordinates can be derived; optionally save a PNG and template crops. **No clicking.** |

The loop uses a **file+process+window state machine** (`gamestate.py`), OS
primitives (`winauto.py`), a reserved disposable **test save slot
`Slot_000000FF`** (`saves.py`, with read-only baseline backup/restore so runs
are repeatable and never clobber player saves), and a configurable
`host/sims4ctl/automation_config.json` of click targets. Full write-up:
[`docs/RECIPE_B.md`](docs/RECIPE_B.md).

### State topics

| Topic    | Shape |
|----------|-------|
| `career` | List of `{name, user_level, simoleons_per_hour, track, title_stbl}` for the active Sim's careers (pulled live from the current `CareerLevel` tuning). |
| `skills` | `{<skill_name_or_guid>: <level int>}` from the Sim's skill statistics. |
| `traits` | List of equipped trait names/guids. |
| `sim`    | `{first_name, last_name, age, gender, household, mood, sim_id}`. |
| `clock`  | `{now: "D H:M", speed: <int>, ticks}`. |
| `all`    | An object combining every topic above. |

## File protocol (summary)

The full normative spec is in `_BUILD_SPEC.md`; this is the wire summary both sides
implement byte-for-byte.

- **Directory:** `<USERDATA>/sims4ctl/`, where `<USERDATA>` is the Sims 4 user folder
  (`Documents/Electronic Arts/{The|Die|Les|Los} Sims 4`, identified by containing
  `Options.ini`).
- **`request.json`** (host->bridge): `{"seq": <int>, "verb": <str>, "args": <object>}`
- **`response.json`** (bridge->host): `{"seq": <int>, "ok": <bool>, "result": <any>, "error": <str|null>, "ts": <float>}`
- **`heartbeat.json`** (bridge->host, refreshed ~2x/sec):
  `{"tick": <int>, "zone_loaded": <bool>, "active_sim": <str|null>, "bridge_version": <str>, "ts": <float>}`
- **`bridge.log`** -- append-only bridge debug log.
- **Atomic writes:** every writer writes `<name>.tmp` then `os.replace()` to the final
  name, so a reader never sees a half-written file.
- **Correlation:** the host picks `seq = max(seq in request.json, seq in response.json) + 1`.
  The bridge acts only when `request.seq > last_handled_seq`, then writes
  `response.json` with the **same** `seq`. The host polls `response.json` until the
  `seq` matches or a timeout (default 15s) elapses.

## The main-thread rule

**The Sims 4 simulation runs on exactly one main thread.** Touching `services`, sim
objects, the game clock, or any tuning from another thread corrupts the engine --
sometimes immediately, sometimes as a delayed, unreproducible crash.

So **all game access happens on the main thread**, driven from `core_services.on_tick`.
The bridge wraps `on_tick` (saving the original and calling it after our work), and on
each tick it polls `request.json` and executes any pending verb *inline on that tick*.
There are **no background threads** in the MVP bridge: the on_tick handler is the only
thing that ever reads game state, so thread-safety is guaranteed by construction. The
file poll is throttled (~ every 15 ticks) so it costs almost nothing, and the whole
handler is wrapped in try/except so a bad request can never take down a tick.

The host side is free to use threads/timeouts however it likes -- it only ever touches
files, never the game.

## Limits

- **No headless mode.** The game must be running with its full UI; there is no
  server/headless build to drive.
- **No save-load CLI argument / Python API.** The game offers no way to load a save
  from code. You can still **load manually** from the main menu, or use the **Recipe B**
  input-automation commands (`start` → `load-save` → … ; see the Recipe B table above and
  `docs/RECIPE_B.md`) which drive the menu with synthetic mouse clicks. The bridge reports
  `zone_loaded: false` until a zone is loaded, and state verbs have nothing to return until
  then.
- **Time only advances when the game is actually simulating.** `advance` won't move the
  clock while the game is **paused**, in a **modal dialog**, or in **CAS/Build/Buy**.
  Blocking interactions can also force the clock back to normal speed. Treat `advance`
  as best-effort and re-read `clock` to confirm it moved.
- **Cheat output capture is best-effort.** `cmd` runs the command reliably, but
  capturing the cheat console's textual output via `CheatOutput` is not guaranteed.

## Security

`sims4ctl` is a **developer tool for a local machine only.**

- `eval` and `cmd` execute **arbitrary code** inside the game process. Anyone who can
  write `request.json` can run anything the game can. There is no sandbox.
- The transport is **local files only.** Nothing is ever bound to a network socket,
  and you should not expose the `<USERDATA>/sims4ctl/` directory over a network share.
- Do not ship the bridge to players or leave it installed on a machine you don't
  control. It is for automated testing on your own dev box.

## Troubleshooting

**Bridge not responding** (`ping` times out):
- Check `<USERDATA>/sims4ctl/heartbeat.json`. If it's missing or stale (`ts` far in the
  past), the bridge isn't running. If it's fresh but `zone_loaded` is `false`, the
  bridge is alive but no save is loaded -- load a save.
- Read `<USERDATA>/sims4ctl/bridge.log` -- the bridge logs every install step and every
  request it handles. No log at all means the `.ts4script` never loaded.
- Confirm **script mods are enabled** (Game Options -> Other) and that you restarted the
  game after enabling them. Script mods are off by default and require a restart.
- Confirm the `.ts4script` is actually in `<USERDATA>/Mods/sims4ctl/` (run
  `sims4ctl doctor` to print the resolved paths).
- **Clear the Sims 4 caches** (`localthumbcache.package`, the `cache/` and `cachestr/`
  folders, etc.) and relaunch -- a stale cache can hide a freshly installed mod.

**`advance` doesn't move the clock:** the game is paused, in a modal, or in CAS/Build.
Unpause and make sure a Sim is selected, then retry and re-read `clock`.

**`state career` is empty:** the active Sim has no careers, or no zone is loaded
(`ping` will show `zone_loaded: false`).

**Run `sims4ctl doctor`** any time -- it prints the resolved USERDATA / Mods / bridge
directories and reports heartbeat freshness and whether the game folder was detected.

## Prior art & credits

`sims4ctl` stands on a body of proven in-game-scripting work:

- **ts4mp -- The Sims 4 Multiplayer Mod** -- socket -> queue -> drain on
  `core_services.on_tick` -> `server_commands.*`. The canonical demonstration that you
  can safely marshal external commands onto the Sims 4 main thread.
  https://github.com/the-sims-4-multiplayer-mod/ts4mp
- **Sims4TikTokMod** -- a sidecar process talking to an in-game mod over `127.0.0.1`,
  turning chat events into in-game commands. https://github.com/MViMy/Sims4TikTokMod
- **dnavaria/sims4ai** -- an in-game `.ts4script` plus a sidecar that reads live Sim
  state, an early "AI drives The Sims" experiment. https://github.com/dnavaria/sims4ai
- **Factorio Learning Environment** -- the RCON/Lua "thin wire command -> rich in-game
  function -> typed result" pattern we model the verb layer on.
  https://github.com/JackHopkins/factorio-learning-environment
- **Voyager** (LLM agent in Minecraft) and **Mineflawyer/Mineflayer** -- the
  agent-drives-a-live-game lineage that motivates a clean scripting API over pixels.
  https://github.com/MineDojo/Voyager * https://github.com/PrismarineJS/mineflayer
- **PySC2** (DeepMind's StarCraft II API) -- the reference for "expose game state as
  structured observations and accept structured actions" rather than scraping the UI.
  https://github.com/google-deepmind/pysc2

See `docs/ARCHITECTURE.md` for the deeper design rationale and the full
pixels-vs-memory-vs-scripting-API taxonomy.
