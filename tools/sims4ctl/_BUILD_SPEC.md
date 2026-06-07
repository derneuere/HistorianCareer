# sims4ctl — BUILD SPEC (single source of truth)

`sims4ctl` is a **game-generic CLI to drive & inspect a running The Sims 4 from outside**, so an
agent (or a human) can run automated in-game tests. It is NOT specific to the Historian mod, but
ships an example scenario that tests it.

New self-contained folder: `C:\Users\Niaz\sims4mod\sims4ctl\` (sibling of `HistorianCareer`).
Patch target: The Sims 4 **1.124.55**; the game embeds **CPython 3.7** (bridge code MUST be 3.7-safe).

## Why this design (grounded in prior art — put a short version in the README)
The Sims 4 engine embeds CPython 3.7 and loads `.ts4script` mods that monkey-patch the runtime, so
we get a first-class **in-process scripting API** — the most reliable agent↔game channel (vs pixels
or memory-reading). Proven by real mods: **ts4mp** (Sims 4 Multiplayer: socket→queue→drain on
`core_services.on_tick`→`server_commands.*`), **Sims4TikTokMod** (sidecar↔127.0.0.1↔in-game cmds),
**dnavaria/sims4ai** (in-game `.ts4script` + sidecar reading live Sim state). Architecture lesson
from Factorio's RCON/Lua + the FLE: thin wire command → rich in-game function → returns typed JSON;
**always re-query state, never trust a cached snapshot.**

**THE ONE HARD RULE:** the game simulation runs on ONE main thread; touching `services`/sim objects
off-thread corrupts the engine. So all game access happens on the main thread, driven from
`core_services.on_tick`. For the MVP we avoid background threads entirely: the on_tick handler polls
the request file and executes on the main thread. (Document this prominently.)

## Architecture (two processes + a file channel)
```
host CLI (sims4ctl, Python 3.8+) ──file IPC──▶ in-game bridge (.ts4script, CPython 3.7)
   writes request.json / reads response.json        on_tick poll → execute on MAIN thread → write response.json
   watches last*Exception.txt for crashes           services.* / sim_info.* → dict → json.dumps
```
Transport = **file-based request/response** (zero deps, robust, easy to debug). Both sides use the
same directory under the Sims 4 user-data folder.

## File protocol (EXACT — both sides implement this)
Directory: `<USERDATA>/sims4ctl/` where `<USERDATA>` = the Sims 4 user folder
(`Documents/Electronic Arts/{The|Die|Les|Los} Sims 4` containing `Options.ini`). Files:
- `request.json`  (host→bridge): `{"seq": <int>, "verb": <str>, "args": <object>}`
- `response.json` (bridge→host): `{"seq": <int>, "ok": <bool>, "result": <any>, "error": <str|null>, "ts": <float>}`
- `heartbeat.json`(bridge→host, refreshed ~2x/sec): `{"tick": <int>, "zone_loaded": <bool>, "active_sim": <str|null>, "bridge_version": <str>, "ts": <float>}`
- `bridge.log`    (bridge append-only debug log)
**Atomic writes:** write `<name>.tmp` then `os.replace()` to the final name. **Correlation:** host
picks `seq = max(seq in request.json, seq in response.json) + 1`; bridge only acts when
`request.seq > last_handled_seq`, then writes `response.json` with the same `seq`. Host polls
`response.json` until `seq` matches or a timeout (default 15s) elapses.

## Bridge verbs (args → result)
- `ping` → `{pong:true, zone_loaded, active_sim, bridge_version}`
- `cmd` `{command:str}` → run `sims4.commands.execute(command, None)`; result `{executed:true, output:<captured if available>}`. (Cheat output capture via `CheatOutput` is best-effort; note the limitation.)
- `eval` `{code:str, mode:"eval"|"exec"}` → eval: `{repr:<repr>, json:<value if JSON-serializable else null>}`; exec: `{stdout:<captured>}`. Namespace exposes `services`, `sims4`, and a `hc` helpers module.
- `state` `{topic:"career"|"skills"|"traits"|"sim"|"clock"|"all", career?:str}` → structured dict (re-queried live each call):
  - `career`: active sim's careers → list of `{name, user_level, simoleons_per_hour, track, title_stbl}` (pull `simoleons_per_hour`/title from the current `CareerLevel` tuning; resolve via `career.current_level_tuning`).
  - `skills`: `{<skill_name_or_guid>: <level int>}` from the sim's skill statistics.
  - `traits`: list of equipped trait names/guids.
  - `sim`: `{first_name,last_name,age,gender,household,mood,sim_id}`.
  - `clock`: `{now:<"D H:M">, speed:<int>, ticks}`.
- `advance` `{hours?:int, minutes?:int}` → `set_clock_speed(ClockSpeedMode.SUPER_SPEED3,...)`, then `services.game_clock_service().advance_game_time(...)`; return new `clock`. Document the constraint: time won't advance while paused / in a modal / in CAS/Build, and blocking interactions force normal speed.

## Host CLI commands (`sims4ctl <cmd>`)
`ping` · `cmd "<cheat>"` · `eval "<code>" [--exec]` · `state [topic] [--career NAME]` · `advance <4h|30m|2h30m>` ·
`crashes [--mark | --since-mark]` (host-side: snapshot/diff `lastException*.txt` + `lastUIException*.txt` mtime+size under `<USERDATA>`; report new/changed — works with NO bridge) ·
`install` (build bridge → .ts4script, copy to `<MODS>/sims4ctl/`) · `launch` (start `TS4_x64.exe`; Steam path `C:/Program Files (x86)/Steam/steamapps/common/The Sims 4/Game/Bin/TS4_x64.exe`; optional) ·
`doctor` (print resolved USERDATA/Mods/bridge dir; report heartbeat freshness & game-folder detection).
Exit non-zero on assertion-style failures so scripts/CI can gate. Add a `--json` flag to print raw JSON.

## Layout to create
```
sims4ctl/
  README.md                      <-- REQUIRED: overview, why-API-not-pixels (short), architecture diagram,
                                       install, quickstart, command reference, the on_tick/main-thread rule,
                                       LIMITS (no headless, no save-load CLI arg — load a save manually for MVP),
                                       security note (eval/cmd run arbitrary code; dev-only; local files only),
                                       troubleshooting, prior-art credits (ts4mp, Sims4TikTokMod, sims4ai, FLE).
  docs/ARCHITECTURE.md           deeper design: transport choice, thread-safety, sequence protocol, the
                                 research-backed taxonomy (pixels vs memory vs scripting-API), prior-art links.
  docs/IN_GAME_SPIKE.md          the FIRST manual verification: install, launch, load a save, `sims4ctl ping`
                                 then `sims4ctl state career` — what success looks like.
  bridge/sims4_test_bridge/      the in-game mod (CPython 3.7 ONLY; stdlib only: os, json, traceback, functools)
    __init__.py                  installs the on_tick hook on import (like HistorianCareer's injector auto-install)
    bridge.py                    on_tick wrap + throttled poll + dispatch + atomic response/heartbeat writes + log
    protocol.py                  paths (resolve USERDATA), atomic read/write request/response/heartbeat
    state.py                     the state serializers (career/skills/traits/sim/clock) — defensive, null-checked
    commands.py                  optional: register `@sims4.commands.Command('s4ctl.ping', ...)` as a manual probe
  host/sims4ctl/                 the host CLI (Python 3.8+; stdlib only — argparse, json, pathlib, time, subprocess)
    __init__.py  __main__.py  cli.py  client.py  crashwatch.py  gamepaths.py
  host/tests/                    pytest/unittest: loopback mock of the bridge (a thread that answers request.json),
                                 gamepaths detection, crashwatch diff. MUST pass without the game.
  build/build.py                 compile bridge .py → .pyc with Python 3.7 (find `py -3.7`/`python3.7`; like
                                 HistorianCareer/Build/build.mjs), zip → build/out/sims4ctl_bridge.ts4script.
                                 If 3.7 missing, warn + ship raw .py (note Sims4 may not load raw .py).
  scenarios/historian_career.py  EXAMPLE: drives the CLI's client to run the Historian assertions (add career →
                                 walk L1..L10 titles+pay 14..340 → fast-track via trait_University_DegreeTraits_History
                                 (230331) starts at L5 → skill gates → add aspiration_track_HistorianCalling →
                                 `crashes` shows 0 new UI exceptions). Documented as "launch + load a save first".
  pyproject.toml                 console_scripts entry point `sims4ctl = sims4ctl.cli:main` (host pkg). Keep deps = none.
```

## Conventions / rules
- **Bridge = CPython 3.7-safe**, stdlib only, every game touch null-checked + wrapped in try/except; never touch
  `services` off the main thread; wrap `core_services.on_tick` (save original, call it after our drain), throttle
  the file poll (e.g. every ~15 ticks) and guard with a module-level installed flag (idempotent on re-import).
- **Host = Python 3.8+**, stdlib only (no pip deps), cross-platform-ish but Windows-first paths.
- Reuse HistorianCareer's user-folder detection (`Documents/Electronic Arts/{The|Die|Les|Los} Sims 4` w/ Options.ini)
  and its Python-3.7 compile+zip approach (see `HistorianCareer/Build/build.mjs`) — port the logic, don't import it.
- Verify offline: `python build/build.py` produces the .ts4script; `python -m pytest host/tests` (or unittest) green;
  bridge `.py` passes a Python-3.7 `compile()` syntax check. The real in-game round-trip is the documented spike.
- Do NOT require the game to be installed for the host tests/build to pass (mock it).
