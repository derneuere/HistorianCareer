# sims4ctl Autonomous Loop Plan: open → load save → run tests → close

Status: decision-ready synthesis of five investigations (launch/quit, python-load-API,
main-menu tick-hook, input-automation, saves/state/prior-art). Target build observed live:
**1.124.63.1020** (task said 1.124.55 — re-verify the `.ts4script` still loads on .63; pyc magic
is still 3.7 so it should). Steam edition, appid `1222670`, EA Desktop DRM bridge required.

---

## 1. Problem framing

The autonomous loop is **open → load a known save → run in-game tests → close**. Three of those
four steps are already solved or trivially solvable; one is the crux.

- **Launch — easy (external process).** `TS4_x64.exe` runs orphaned/standalone once started, but the
  Steam copy needs **EA Desktop already running and signed in** to entitle (via `EASteamProxy.exe`).
  Launch via `steam://rungameid/1222670` (lets Steam+EA negotiate) or the raw exe (only works if EA
  Desktop is up). `sims4ctl launch` already does the raw-exe path (`cli.py:249`).
- **Quit — easy (external process).** There is **no in-Python application-quit** (exhaustive `.pyc`
  scan: only career/zone teardown exists). Use `Stop-Process -Name TS4_x64 -Force`. TS4 does **not**
  autosave on exit, so save through the bridge first (`persistence.save_game`) while a zone is loaded,
  then kill. Avoid killing mid-save (corrupts the active slot; rotated `.verN` backups usually recover).
- **Run tests — solved.** Once a zone is loaded the existing bridge drains commands normally
  (`cmd`, `eval`, `state`, `advance`, the `historian_career` scenario). No change needed.
- **Load a known save — THE CRUX.** The bridge is **dormant at the main menu**. Its drain loop is a
  real-time alarm started only from `zone.Zone.do_zone_spin_up` (`bridge.py:357,396,412`), and that
  alarm needs `time_service()`, which is `None` until `start_services()` runs at zone load. Empirically
  confirmed: `heartbeat.json` freezes (stale, `tick:204`) at the menu while `bridge.log` shows the hook
  re-installing — the drain stops firing pre-zone. **And there is no Python load API**: exhaustive
  identifier search across `sim_extract` found zero `load_game`/`load_slot`/`set_save_slot`/
  `select_save_game` entry points. The load direction is **C++ → Python** (`areaserver.c_api_zone_init`
  receives already-selected `save_slot_data_bytes` *inward*); `persistence_service` and
  `server_commands/persistence_commands` are **save-only**. So nothing reachable from the bridge can move
  menu → loaded zone. **The menu→zone jump must be driven from outside Python.**

---

## 2. Ranked end-to-end recipes

### Recipe B (RECOMMENDED) — "hybrid input": launch → synthetic click of Continue/Load → bridge takes over
**Pipeline:** `start` (launch + wait-for-menu) → input-automation focuses the window and clicks
**"Weiter"** (Continue, most-recent save) → poll `heartbeat.json` until `zone_loaded:true` → bridge
runs tests → `persistence.save_game` → `stop` (`Stop-Process -Force`).

- **Mechanism:** `FindWindowW("Die Sims™ 4")` (German title, windowed, client rect 1363×796 measured) →
  ALT-tap + `SetForegroundWindow` to grab foreground → `dxcam`/`mss` capture → OpenCV `matchTemplate`
  to locate "Weiter" → `SendInput` mouse move+click (mouse clicks register in DirectX even when
  keystrokes don't; PyDirectInput scan-code path kept ready for keys). Fallback path: click "Spiel
  laden" → match save-slot thumbnail → click → "Spielen".
- **Reliability:** Medium-high once tuned. Mouse clicks are robust; the fragile parts are foreground
  stealing (re-assert focus before each click), template drift (pin `Options.ini` resolution +
  `uiscale=100` while game is closed; version the templates), and a possible modal over the menu
  (update/CC/unsaved-data prompt — detect-and-dismiss before clicking). **"Weiter" = one-click-load is
  UNVERIFIED on this build** — must confirm live; keep the save-picker fallback.
- **Effort:** Medium. New `input_automation` module + template assets + `pip install dxcam mss
  opencv-python pyautogui pydirectinput pywin32`. No game-mod changes.
- **Evidence:** input-automation (entire recipe, measured window facts, DirectX/SendInput caveats);
  saves-state-priorart (heartbeat as the post-load ground-truth, "even ts4mp loads by hand"); launch-quit
  (window title, foreground caveat). Negative results from python-loadapi + mainmenu-tick-hook are what
  *force* this recipe.

### Recipe A — "pure-API": launch → main-menu tick-hook services a `load_save` verb → ??? loads slot
**Pipeline:** `start` → bridge's **new** `areaserver.c_api_server_tick` wrapper drains commands *at the
menu* → host sends a `load_save` verb → verb calls a save-load API → zone loads → bridge takes over.

- **Mechanism:** mainmenu-tick-hook found a **clean pre-zone main-thread hook**: the engine calls
  `areaserver.c_api_server_tick(absolute_ticks)` every frame including at the menu, running
  `sims4.core_services.on_tick()` + `get_distributor_service().on_tick()` before any zone check. Wrap it
  at `.ts4script` import (mirrors the existing zone hook) and throttle drains. This **makes the bridge
  live at the menu** — that half is feasible and high-confidence.
- **The blocker:** there is **no save-load API to call from that verb.** python-loadapi proved (high
  confidence, exhaustive search + decompiled `areaserver.py`) that Python is only *called into*; no
  outbound load request exists, persistence is save-only, `travel_service` needs an already-loaded zone,
  and `on_enter_main_menu()` is an empty stub. **So Recipe A's `load_save` verb has nothing to invoke.**
  It is **NOT feasible today as a true pure-API load.** The tick-hook is still worth building because it
  unlocks pre-zone state reporting and *running setup cheats the instant a zone exists*.
- **Reliability:** Hook = high; **the load itself = currently impossible from Python.**
- **Effort:** Low-medium for the hook; the load step is blocked pending a live discovery.
- **Evidence:** mainmenu-tick-hook (hook is real, cross-confirmed bytecode + EA source); python-loadapi
  (decisive negative on the load API). These two together say: build the hook, but it can't load a save.

### Recipe C — "continue-shortcut via `--on_startup_commands`": launch with an automation arg
**Pipeline:** launch `TS4_x64.exe --on_startup_commands C:\...\boot.txt` → if the engine can be made to
auto-enter a zone, the game runs your cheats the instant the zone is live.

- **Mechanism:** saves-state-priorart disassembled `ZoneSpinUpService._StartupCommandsState.on_enter`:
  the game parses **its own command line** and, if `--on_startup_commands <file>` is present, runs
  `sims4.command_script.run_script(file, client_id)` after **every zone spin-up** (lines with `|` →
  server `execute`, others → `client_cheat`). EA also ships a `paths.AUTOMATION_MODE`.
- **The blocker:** this fires **after** a zone loads — it does **not select which slot to load** or make
  the menu→zone jump. No companion "load slot N" arg has been found. So by itself it does **not** solve
  the crux; it's a **post-load cheat-injection** mechanism (a cleaner alternative to the bridge for
  startup cheats), not a loader.
- **Reliability:** High as a post-load hook; **does not solve menu→zone.** CLI args are also unreliable
  via the EA App/Steam shortcut path (must be a direct exe shortcut or launcher "command line arguments"
  field).
- **Effort:** Low to test.
- **Evidence:** saves-state-priorart (disassembly + EA `command_script.py` + Run-Cheat-Commands prior
  art). launch-quit + input-automation independently confirm **no documented `-loadsave`/headless flag**.

**Ranking: B > A (hook only) > C.** Only Recipe B delivers an end-to-end unattended loop today. A and C
each solve a *different* half (live-at-menu / post-load cheats) but **neither performs the menu→zone load**
— the live experiments below exist to try to promote one of them past that wall.

---

## 3. Recommendation

**Ship Recipe B (hybrid input) now** as the working unattended loop, and **build the Recipe A tick-hook
in parallel** as infrastructure (it's cheap, high-confidence, and independently useful for pre-zone state
+ post-load cheat injection). **Do not block on a pure-API load — it does not exist in Python today**
(high-confidence negative from python-loadapi). Run the live experiments (§5) to learn whether
`--on_startup_commands`/`AUTOMATION_MODE` or an undocumented load arg can replace the click; if one pans
out, swap Recipe B's click step for it and keep everything else.

Rationale: Recipe B is the only path that closes the loop end-to-end with **only external, well-understood
Windows tooling** and no dependency on an API that the investigators proved absent. The heartbeat gives a
**clean ground-truth** that the load succeeded (`zone_loaded:true`, fresh `tick`), so even a brittle click
is *verifiable* — the loop fails loudly instead of silently. The tick-hook is low-risk insurance that pays
off the moment a live load mechanism is found.

---

## 4. Concrete sims4ctl changes

### New CLI commands (`host/sims4ctl/cli.py` — extends the existing `cmd_*` + `add_parser` pattern at lines 106–414)
- `start` — launch (`steam://rungameid/1222670` preferred, raw exe fallback; ensure EA Desktop is up
  first) **and** block on wait-for-menu (see state machine). Supersedes/wraps current `launch`.
- `stop [--save]` — if `--save` and a zone is loaded, send `persistence.save_game` via the bridge and
  wait for the save, then `Stop-Process -Name TS4_x64 -Force`. Never kill mid-save.
- `load-save <slot>` — Recipe B: focus window, click Continue/Load (or pick slot), poll until
  `zone_loaded:true`. (If a live load arg is found, this becomes a launch-arg call instead.)
- `new-game` — Recipe B variant clicking "New Game"/fixed CAS path (later; optional).
- `run-scenario <name>` — orchestrate `start → load-save → <scenario> → stop`, wrapping the existing
  `scenarios/historian_career.py`. This is the top-level unattended entry point.
- `wait-for <state> [--timeout]` — poll the state machine (below) until DOWN/MENU/LOADING/ZONE_LOADED
  or a crash; exit non-zero on timeout/crash. Reuses `client.read_heartbeat`/`heartbeat_age` +
  `crashwatch`.
- `state --menu-aware` — extend `cmd_state` (`cli.py:143`) to report DOWN/MENU/LOADING/ZONE_LOADED
  instead of only in-zone state.

### Bridge changes (`bridge/sims4_test_bridge/bridge.py`)
- **Add a pre-zone drain via the per-frame C-API** (Recipe A infra). In `install()` (currently only
  hooks `zone.Zone.do_zone_spin_up` at `bridge.py:412`), **also** wrap
  `areaserver.c_api_server_tick`: call the original, then a **throttled** `drain()` (reuse
  `DRAIN_INTERVAL_REAL_SECONDS` — the C-API fires at 30–60 Hz; do not drain every frame). Wrap your
  suffix in try/except (the engine's `@exception_protected` protects the original body, not your suffix)
  and log to `bridge.log`. This makes `heartbeat.json` refresh at the menu (a real menu-ready signal) and
  lets pre-zone verbs run. Fallback hook if `c_api_server_tick` is awkward to patch:
  `DistributorService.on_tick` or `sims4.core_services.on_tick` (both real, both run pre-zone).
- **`load_save` verb — add the plumbing, leave the body as `ok=false:"no python load api"` for now.**
  Wire the verb so a live experiment can drop a candidate call in one place; do **not** ship it claiming
  to work (python-loadapi: no API exists). Most existing verbs correctly return `ok=false` pre-zone.
- Keep the heartbeat schema (`zone_loaded`, `active_sim`, `tick`, `ts`) — it is the canonical external
  signal for both menu-ready and zone-loaded.

### New input-automation module (Recipe B) — `host/sims4ctl/input_automation.py`
- `find_window()` (`FindWindowW`, title `"Die Sims™ 4"`), `focus(hwnd)` (ALT-tap → `SetForegroundWindow`
  → assert `GetForegroundWindow()==hwnd`), `capture_client(hwnd)` (`dxcam`/`mss`, crop to client rect),
  `locate(template)` (`cv2.matchTemplate`, confidence ≥0.85), `click(x,y)` (`SendInput`; PyDirectInput
  for keys). Versioned template assets per resolution. Deps:
  `pip install dxcam mss opencv-python pyautogui pydirectinput pywin32`.
- **Pin resolution first** (set `Options.ini` to a fixed windowed res + `uiscale=100` while game closed)
  so templates are scale-stable.

### Test-save setup (`saves` management — `host/sims4ctl/gamepaths.py` neighbors)
- Saves dir: `C:\Users\Niaz\Documents\Electronic Arts\Die Sims 4\saves\`, files `Slot_XXXXXXXX.save`
  (8-hex slot id; backups `.ver0`–`.ver4`, `.day.ver0`; format = DBPF package, **name maps the slot, not
  the blob**). Reserve a dedicated **TEST slot** (e.g. `Slot_000000FF.save`), back it up read-only to a
  `saves_baseline/` you own, and `os.replace` it back before each run so state is byte-identical.
  **Never touch the player's `Slot_00000002/3`.** Create the test save once in-game via
  `persistence.save_to_new_slot` / `override_save_slot` (the save-as server commands).

### State machine the CLI polls (file-based, bridge-free except ZONE_LOADED)
| State | Signal | Source |
|---|---|---|
| **DOWN** | no `TS4_x64.exe` process | `tasklist` / `gamepaths.find_ts4_exe()` |
| **MENU** | process up, `heartbeat.json` absent or stale / `zone_loaded:false` | `client.read_heartbeat`/`heartbeat_age`; (with tick-hook, a *fresh* heartbeat with `zone_loaded:false` = solid menu-ready) |
| **LOADING** | process up, no fresh zone heartbeat, `Config.log` mtime advancing | `Die Sims 4/Config.log` mtime; watch `lastException*` for a failed load |
| **ZONE_LOADED** | `heartbeat_age()<~2s` **and** `zone_loaded:true` **and** `active_sim` non-null | `client.heartbeat_age` + `ping` (`pong,zone_loaded,active_sim`) |
| **CRASH (orthogonal)** | new/changed `lastException*.txt`/`lastUIException*.txt` | `crashwatch.CrashWatch.since_mark()` (`--mark` before run, `--since-mark` after) |

---

## 5. Open questions + live experiments

**Open questions (only confirmable against the running game):**
1. Does wrapping `areaserver.c_api_server_tick` actually fire at the main menu in 1.124.63, and does a
   throttled `drain()` there refresh `heartbeat.json` pre-zone? (mainmenu-tick-hook is high-confidence
   from bytecode but **untested live**.)
2. Is there *any* pre-zone-callable path that selects/loads a slot — e.g. something on
   `server.clientmanager`/`server.client`, a hidden persistence method, or an
   `--on_startup_commands`/`AUTOMATION_MODE` companion arg that also picks the slot? (python-loadapi says
   no Python API; saves-state-priorart flags the automation arg as the strongest untested lead.)
3. Does the main menu show **"Weiter"** with a recent save, and is it truly **one click, no confirmation
   dialog**, on this build/locale?

**Top 3 live experiments to run next:**
1. **Menu-tick hook smoke test.** Add the `c_api_server_tick` wrapper (throttled `drain()` + heartbeat
   write), launch to the **main menu**, and watch `heartbeat.json` mtime. If it refreshes pre-zone with
   `zone_loaded:false`, Recipe A's infra works and you have a real menu-ready signal. (Validates Q1; also
   gives `eval` at the menu to probe Q2.)
2. **Pre-zone load-API probe.** With the menu-tick hook live, `sims4ctl eval` at the menu to introspect
   `services`, `server.clientmanager`, persistence, and the `areaserver` c_api surface for *any* callable
   that initiates a load. If found → promote Recipe A to a true pure-API load. If confirmed absent →
   Recipe B is locked in. (Validates Q2.)
3. **`--on_startup_commands` + click smoke test.** Launch via a **direct exe shortcut** with
   `--on_startup_commands boot.txt` (a `|`-prefixed cheat that writes a sentinel file), then perform the
   **single "Weiter" click** (Recipe B) and confirm: (a) the click loads in one action with no modal, and
   (b) the startup-commands file runs at zone spin-up. Confirms the click recipe end-to-end *and* whether
   the automation arg is a usable post-load injector. (Validates Q3 + the Recipe C value.)
