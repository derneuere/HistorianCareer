# Recipe B — the input-automation autonomous loop

`sims4ctl` can drive a *running* The Sims 4 once a save is loaded, but the game
exposes **no Python API to get from the main menu into a loaded save** (proven
exhaustively in `docs/AUTOMATION_PLAN.md`: the load direction is C++ → Python
only). "Recipe B" fills that one gap from **outside** the game with OS-level
window control and synthetic mouse clicks, so the full loop becomes unattended:

```
   start            load-save                          run-scenario        stop
 ┌────────┐   ┌───────────────────────────┐   ┌──────────────────┐   ┌──────────┐
 │ launch │ → │ focus → dismiss MODS dialog│ → │ bridge runs the  │ → │ save +   │
 │ TS4 →  │   │   → click "Spiel fortsetzen"│   │ test scenario    │   │ taskkill │
 │ MENU   │   │   → wait for ZONE_LOADED    │   │ (existing path)  │   │ TS4_x64  │
 └────────┘   └───────────────────────────┘   └──────────────────┘   └──────────┘
```

Everything below the click is verifiable: the in-game bridge's `heartbeat.json`
is the **ground truth** that the load succeeded (`zone_loaded:true`, fresh
`tick`), so even a brittle click fails *loudly* instead of silently.

> This document describes the **mechanism + CLI**. The exact click coordinates
> and button templates are **placeholders** and MUST be calibrated against the
> live game (see [Calibration](#calibration)) before the loop will actually load
> a save.

---

## The state machine (`gamestate.py`)

A single source of truth reduces three observable signals into four states:

| State | Signal | Derived from |
|---|---|---|
| **DOWN** | no `TS4_x64.exe` process | `tasklist` → ctypes `CreateToolhelp32Snapshot` fallback (no psutil) |
| **MENU** | process up, **no fresh zone heartbeat** (or `zone_loaded:false`) | process check + `client.read_heartbeat` / `heartbeat_age` |
| **LOADING** | process up, heartbeat stale while the last value claimed a zone | best-effort transient — usually just waited through |
| **ZONE_LOADED** | process up, **fresh** heartbeat **and** `zone_loaded:true` | `heartbeat_age() ≤ 5 s` + `zone_loaded` |

`GameState.current_state()` returns one of these; `GameState.wait_for(state,
timeout, poll)` blocks until it's reached or raises `StateTimeout` (→ CLI exits
non-zero). Crashes are **orthogonal** — gate on them with `crashes --since-mark`.

Inspect it any time:

```
sims4ctl state --menu-aware            # DOWN/MENU/LOADING/ZONE_LOADED (+JSON with --json)
sims4ctl wait-for ZONE_LOADED --timeout 180
```

`state --menu-aware` never calls the bridge, so it works at the menu and never
blocks on a bridge timeout.

---

## The OS primitives (`winauto.py`)

DirectX games typically **ignore synthetic keystrokes** but **accept synthetic
mouse clicks**, and only when the window is **foreground**. `winauto` provides:

- `find_game_window(title_substr="Sims")` → `{hwnd, title, client_rect (screen
  coords), width, height}` or `None`. Prefers **pywin32**, falls back to pure
  **ctypes user32** `EnumWindows`. The live German title is `Die Sims™ 4`;
  `"Sims"` matches every locale.
- `focus_window(hwnd)` — `SetForegroundWindow` with the **ALT-key-tap
  workaround** for Windows' foreground lock; returns whether focus was actually
  grabbed (re-assert before each click).
- `capture(region=None)` → BGR numpy image via **mss** (region = a window's
  `client_rect`).
- `locate_template(png, region, threshold=0.85, scales=None)` → match **center**
  in screen coords via OpenCV `matchTemplate` (optional multi-scale).
- `click(x, y)` / `move(x, y)` — **ctypes `SendInput`** absolute mouse events
  (the DirectX-friendly path). `backend="pydirectinput"` is an optional
  fallback if that package is importable.
- `client_norm_to_screen(window, nx, ny)` — convert normalized client fractions
  to screen pixels (pure arithmetic, no deps).

**Import contract:** `winauto` imports with **zero** third-party packages. Every
dep is imported *lazily inside the function that needs it*; a missing one raises
`AutomationDepsMissing` with `pip install sims4ctl[automation]`. So the base CLI
and the whole test suite stay dependency-free.

---

## Configurable click targets (`automation_config.json`)

Click targets are **data, not code**, so the orchestrator can calibrate them
without editing Python. Each target is **either**:

- `{"norm": [x, y]}` — `x,y ∈ [0,1]` as a fraction of the **client rect**
  (resolution-tolerant), **or**
- `{"template": "name.png", "threshold": 0.85}` — an OpenCV template match.

If both are present, the **template is tried first** and `norm` is the fallback.
`enabled: false` skips an optional step (e.g. the MODS dialog when it isn't
shown). The shipped targets:

| Target | German button | Used by |
|---|---|---|
| `mods_dialog_dismiss` | startup **MODS** notice close `[X]`/OK | `load-save` (best-effort, pre-click) |
| `continue` | **Spiel fortsetzen** (Continue = most-recent save) | `load-save --continue` (default) |
| `load_game` | **Spiel laden** (Load Game → picker) | `load-save --slot N` |
| `load_confirm` | **Spielen**/confirm in the picker | `load-save --slot N` |
| `new_game` | **Neues Spiel** (New Game) | `new-game` |
| `save_slots["<id>"]` | a slot thumbnail in the picker | `load-save --slot N` |

> **All of these are PLACEHOLDERS.** They each carry a `norm` fallback so a click
> can be *derived* immediately, but the fractions are guesses — calibrate before
> live use.

Override the config file with `--config PATH` or `$SIMS4CTL_AUTOMATION_CONFIG`.
Calibrated template PNGs live in `host/sims4ctl/templates/` (`templates_dir`).

---

## Calibration

The orchestrator derives real coordinates from a captured frame — no clicking:

```
# 1. Pin a fixed windowed resolution + uiscale=100 in Options.ini (game closed)
#    so templates/fractions are scale-stable.

# 2. Launch to the main menu, then capture the window geometry + a PNG:
sims4ctl calibrate --out C:\tmp\menu.png
#   -> prints: title, hwnd, client_rect (screen coords), WIDTHxHEIGHT, deps{}

# 3. Read button pixel boxes off menu.png. Either:
#    (a) compute normalized coords = (px - client_left)/width, etc. and edit
#        automation_config.json targets.*.norm, OR
#    (b) save template crops (client-local pixels) for robust matching:
sims4ctl calibrate --crop continue 600 380 760 430 \
                   --crop load_game 600 450 760 500 \
                   --out C:\tmp\menu.png
#   -> writes host/sims4ctl/templates/continue.png, load_game.png
```

`calibrate` needs the `[automation]` deps **only** when `--out`/`--crop` capture
is requested; printing the rect alone needs just the window lookup.

---

## The CLI loop

```
sims4ctl start                       # launch (steam://rungameid/<appid>) → wait MENU
sims4ctl load-save --continue        # focus → dismiss MODS → click Continue → wait ZONE_LOADED
sims4ctl load-save --slot 255        # instead: Load Game → slot 0xFF thumbnail → confirm
sims4ctl run-scenario historian_career --auto   # ensure a zone, then run the scenario
sims4ctl stop --save                 # in-game save (bridge) → taskkill TS4_x64.exe
```

- **`start`** reads the appid from the game's `steam_appid.txt` (next to
  `TS4_x64.exe`), falling back to `1222670`, and launches via
  `steam://rungameid/<appid>` so the Steam/EA entitlement bridge negotiates
  (`--exe` forces the raw exe, which only works if EA Desktop is already up).
  Then it blocks on `wait_for(MENU)`.
- **`load-save`** is the **crux**. It finds + focuses the window, optionally
  dismisses the MODS dialog, clicks the configured target(s), then
  `wait_for(ZONE_LOADED)`. `--continue` is a single click of the most-recent
  save (default); `--slot N` walks the Load-Game picker.
  > One-click "Spiel fortsetzen" load (no confirmation dialog) is **UNVERIFIED**
  > on this build — keep the `--slot` picker path as a fallback.
- **`new-game`** clicks **Neues Spiel** (a stub — it does not drive CAS to a
  zone; that's out of scope for the scaffold).
- **`run-scenario <name> --auto`** self-bootstraps: if the state isn't
  `ZONE_LOADED` it runs `start` + `load-save --continue` first, then runs
  `scenarios/<name>.py` as a child process and returns its exit code.
- **`stop --save`** best-effort triggers an in-game `save` via the bridge `cmd`
  verb **only when a zone is loaded** (TS4 does **not** autosave on exit; never
  kill mid-save), then `taskkill /IM TS4_x64.exe` escalating to `/F`.

Every command exits **non-zero on failure** (timeout, missing window, missing
deps, unresolved paths) so a CI job or orchestrator can gate on it.

---

## Test-save safety (`saves.py`)

Runs mutate the world, so they target a **reserved disposable slot** and never
touch player saves:

- **Reserved test slot: `0x000000FF` → `Slot_000000FF.save`.** High in the
  range and not used by the player here (observed player slots `00000002`,
  `00000003`, which are **guarded** — `backup`/`restore` refuse them without
  `force=True`).
- `backup_test_slot()` copies the live slot **and its rotated siblings**
  (`.ver0..4`, `.day.ver0`) into a **read-only** baseline at
  `<USERDATA>/sims4ctl/saves_baseline/`.
- `restore_test_slot()` `os.replace`-s the baseline back over the live slot
  **before each run**, so every run starts byte-identical.

Create the test save **once** in-game (a save-as into slot 0xFF) before the
first `backup_test_slot()`. Enumerate everything with `saves.list_saves()`.

---

## Dependencies

The base CLI + the whole test suite are **dependency-free**. Driving the live
game (capture / template match / mouse click) needs the optional extra:

```
pip install sims4ctl[automation]
```

which pulls in **pywin32** (Windows window control; ctypes is the fallback),
**mss** (capture), **opencv-python** + **numpy** (template match), and
**pydirectinput** (optional fallback input backend). The default click path is
pure ctypes `SendInput`, so the *code* imports without any of these — they are
required only when a feature actually runs.

---

## Reliability notes / gotchas

- **Re-assert focus before every click** — another app can steal the foreground
  between steps (`focus_window` returns whether it succeeded; the CLI retries
  `focus_retries` times).
- **Pin resolution + `uiscale=100`** before calibrating; templates and `norm`
  fractions drift with UI scale and resolution.
- **A modal can overlay the menu** (update / CC / unsaved-data) — the
  `mods_dialog_dismiss` step handles the startup MODS notice; add detect-and-
  dismiss for others if they appear.
- **The heartbeat is the verifier** — `load-save` only "succeeds" when the
  bridge reports a fresh `zone_loaded:true`; a mis-calibrated click times out at
  `wait_for(ZONE_LOADED)` and exits non-zero rather than pretending it worked.
- This recipe is **the only end-to-end unattended path today**; the parallel
  "menu-tick-hook" (Recipe A) is useful infra but **cannot load a save** (no
  Python load API). See `docs/AUTOMATION_PLAN.md`.
