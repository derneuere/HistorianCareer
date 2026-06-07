# sims4ctl -- Architecture

This document explains *why* sims4ctl is built the way it is. The normative wire
protocol and verb list live in `../_BUILD_SPEC.md`; the user-facing overview lives in
`../README.md`. Here we cover the design taxonomy, the transport choice and its
tradeoffs, the correlation protocol, the thread-safety discipline, the verb catalogue,
and the "always re-query" rule.

## 1. The agent-vs-game taxonomy: pixels vs memory vs scripting API

An external agent can interface with a game in one of three categories. Choosing the
right one is the single most important architectural decision, because everything else
(robustness, what state is observable, how actions are issued) follows from it.

### (a) Pixels -- screen scraping + synthetic input

The agent reads the rendered frame buffer and synthesizes mouse/keyboard events. This
is the most general approach (it works on *any* game) but the weakest:

- **Brittle.** Any change to UI layout, theme, resolution, DPI, or localization breaks
  it. A patch that moves a button silently invalidates the agent.
- **Blind to hidden state.** Most of a simulation is not on screen. A Sim's exact skill
  level, the per-hour pay of a career rank, or a trait GUID simply isn't rendered.
- **Slow and ambiguous.** OCR/vision is lossy; reading a number you could have asked
  for directly is wasted effort and a source of errors.

### (b) Memory -- process inspection / address reading

The agent attaches to the process and reads or writes raw memory. More direct than
pixels, but:

- **Fragile across builds.** Struct layouts and addresses shift between patches;
  pointer-chasing must be re-derived every update.
- **Dangerous.** A wrong write corrupts the heap and crashes (or worse, silently
  corrupts saves). There is no type safety.
- **Opaque.** You're reverse-engineering data structures the game never documented.

### (c) A first-class scripting API -- call into the game's own runtime

The agent runs code *inside* the game, in the game's own language, using the same
objects the engine uses. This is the strongest position when it's available:

- **Stable.** Cosmetic UI changes don't matter; you call the same `services` API the
  game's own logic calls. Tuning IDs and class names are far more stable than pixel
  coordinates.
- **Total observability.** You ask the simulation directly, so *all* state is reachable
  -- including everything that's never drawn on screen.
- **Sanctioned actions.** You act through the engine's real code paths (commands,
  interactions, clock service), so effects are consistent with normal play.

### Why The Sims 4 is category (c)

The Sims 4 engine embeds **CPython 3.7** and loads `.ts4script` mods (zipped Python)
that monkey-patch the live runtime at load time. EA's own gameplay is authored in this
same Python layer. That means a mod can:

- import `services` and read any live object (sim infos, careers, statistics, the game
  clock, tuning managers);
- call `sims4.commands.execute(...)` to run the same console commands the cheat box
  uses;
- `eval`/`exec` arbitrary Python against the live namespace.

So we get category (c) "for free" -- an in-process scripting API is the native modding
model. sims4ctl is simply a disciplined wrapper around it: a stable file protocol on
the outside, a thin tick-driven dispatcher on the inside.

This is not theoretical. The pattern is demonstrated by **ts4mp** (Sims 4 Multiplayer:
socket -> queue -> drain on `core_services.on_tick` -> `server_commands.*`),
**Sims4TikTokMod** (sidecar <-> `127.0.0.1` <-> in-game commands), and **dnavaria/sims4ai**
(in-game `.ts4script` + a sidecar reading live Sim state). The "thin wire command ->
rich in-game function -> typed result" shape is lifted from Factorio's RCON/Lua and the
**Factorio Learning Environment**; the "expose structured observations/actions, don't
scrape the UI" stance is **PySC2**'s; the "agent drives a live game" lineage is
**Voyager/Mineflayer**.

## 2. Transport: file IPC vs socket/HTTP

The host and the bridge are two separate processes that must exchange a request and a
response. The candidates were a local TCP/HTTP socket and a file-based channel. We
chose **file-based request/response** in a directory under the Sims 4 user folder.

### Why files

- **Zero dependencies on both sides.** No socket server inside the game, no HTTP
  framework. Just `os`, `json`, `os.replace`. This matters doubly inside the game,
  where the bridge must be CPython-3.7-safe and stdlib-only.
- **Robust across restarts and ordering.** Either process can start first, crash, or
  restart; the channel is just files that persist. There's no connection to drop, no
  port to collide, no handshake to get wrong.
- **Trivially debuggable.** When something is off, you `cat request.json` /
  `response.json` / `heartbeat.json` and *see* the exact wire state. The protocol is
  human-readable by construction.
- **No network surface.** Nothing binds a socket; nothing listens. A dev tool that can
  `eval` arbitrary code in the game must never be reachable over the network, and files
  give us that for free (see Security in the README).
- **Naturally throttle-friendly.** The bridge already runs work on `on_tick`; polling a
  file every ~15 ticks is cheap and fits the tick model perfectly. A socket would want
  its own accept/recv loop -- i.e. a background thread -- which is exactly what we want to
  avoid (see Sec. 4).

### Tradeoffs we accept

- **Latency is polling-bounded.** A response isn't instantaneous; it's available within
  one poll interval (a handful of ticks). For test automation this is irrelevant -- we're
  not driving real-time input.
- **One in-flight request at a time.** The single `request.json`/`response.json` pair is
  a request/response rendezvous, not a queue. That's intentional: the CLI issues one
  verb, waits for its `seq`, and returns. Sequencing keeps it unambiguous (see Sec. 3).
- **Atomic-write discipline is mandatory.** A naive `open(..., "w")` could let a reader
  observe a half-written file. We avoid this with tmp-file + `os.replace()` on every
  write (atomic rename on the same filesystem). This is a small rule, rigorously
  applied, rather than a locking protocol.

A socket would buy lower latency and multiplexing -- neither of which the testing use
case needs -- at the cost of a server loop, a port, a network surface, and a background
thread. Files win for this problem.

## 3. The sequence / correlation protocol

Because the channel is a single mutable file pair, the host and bridge must agree on
*which* request a given response answers. We use a monotonic sequence number.

- Every `request.json` carries an integer `seq`.
- The host chooses the next `seq` as
  `max(seq in request.json, seq in response.json) + 1`. Reading both files means the
  host recovers the right next value even after a restart, where it has no in-memory
  counter -- it derives state from the files themselves, never from cached memory.
- The bridge tracks `last_handled_seq`. On each poll it reads `request.json` and acts
  **only when `request.seq > last_handled_seq`**. This makes re-reading the same request
  idempotent: the bridge won't re-execute a verb just because it polled again.
- After executing, the bridge writes `response.json` with the **same `seq`**, plus
  `ok`, `result`, `error`, and `ts`.
- The host polls `response.json` until it sees a response whose `seq` matches the one it
  wrote, or until a timeout (default **15s**) elapses. A matching `seq` with `ok:false`
  is a *handled* failure (the verb ran and reported an error); a timeout is an
  *unreachable* failure (bridge not running, no zone, game paused at a blocking modal).

Wire shapes (normative copy in `_BUILD_SPEC.md`):

```
request.json    { "seq": <int>, "verb": <str>, "args": <object> }
response.json   { "seq": <int>, "ok": <bool>, "result": <any>, "error": <str|null>, "ts": <float> }
heartbeat.json  { "tick": <int>, "zone_loaded": <bool>, "active_sim": <str|null>,
                  "bridge_version": <str>, "ts": <float> }
```

`heartbeat.json` is independent of the request/response rendezvous: the bridge refreshes
it ~2x/second regardless of traffic, so the host can answer "is the bridge alive and is
a zone loaded?" without issuing a verb. `sims4ctl doctor` reports its freshness.

## 4. Thread-safety discipline -- the one hard rule

**The Sims 4 simulation runs on exactly one main thread.** Reading or writing
`services`, sim objects, statistics, the clock, or tuning from any other thread can
corrupt the engine -- often as a delayed, unreproducible crash rather than an immediate
one.

The discipline that follows is absolute and simple:

> **All game access happens on the main thread, driven from `core_services.on_tick`.**

The bridge implements this by:

1. **Wrapping `on_tick`.** At import it saves the original `on_tick` and installs a
   wrapper that does our work first, then calls the original -- exactly the
   monkey-patch idiom the reference `affordance_injector.py` uses for
   `zone.Zone.do_zone_spin_up`. Installation is guarded by a module-level flag so a
   re-import can't double-wrap.
2. **No background threads at all (MVP).** The on_tick wrapper is the *only* code that
   ever touches game state. Because file polling also happens inside on_tick, there is
   no second thread to race with. Thread-safety is guaranteed by construction, not by
   locking. (This is the key reason we chose files over a socket: a socket server wants
   its own thread; files let everything live on the tick.)
3. **Throttling the poll.** Reading `request.json` every tick would be wasteful, so the
   wrapper only polls roughly every ~15 ticks. The simulation runs at many ticks per
   second, so this is sub-100ms responsiveness at negligible cost.
4. **Total defensive wrapping.** Every game touch is null-checked and wrapped in
   try/except, and the whole tick handler is wrapped too. A malformed request, a missing
   service, or a serializer bug becomes an `ok:false` response with an `error` string --
   never a crashed tick. Failures are appended to `bridge.log`.
5. **Heartbeat from the tick.** The heartbeat is written from on_tick as well (throttled
   to ~2x/sec), so even "is the bridge alive" never touches game state off-thread.

The host side has no such constraint -- it only ever reads and writes files -- so it's
free to use timeouts and polling loops however it likes.

## 5. Verb catalogue

Each verb is a thin wire instruction; the rich work is an in-game function that returns
JSON-serializable data. Args and results (normative copy in `_BUILD_SPEC.md`):

| Verb      | Args | Result |
|-----------|------|--------|
| `ping`    | -- | `{pong: true, zone_loaded, active_sim, bridge_version}` |
| `cmd`     | `{command: str}` | Runs `sims4.commands.execute(command, None)`; `{executed: true, output: <captured if available>}`. Output capture via `CheatOutput` is best-effort. |
| `eval`    | `{code: str, mode: "eval"\|"exec"}` | `eval`: `{repr: <repr>, json: <value if JSON-serializable else null>}`. `exec`: `{stdout: <captured>}`. Namespace exposes `services`, `sims4`, and an `hc` helpers module. |
| `state`   | `{topic: "career"\|"skills"\|"traits"\|"sim"\|"clock"\|"all", career?: str}` | A structured dict, re-queried live each call (see Sec. 6). |
| `advance` | `{hours?: int, minutes?: int}` | Sets `ClockSpeedMode.SUPER_SPEED3`, calls `services.game_clock_service().advance_game_time(...)`, returns the new `clock`. |

### `state` topic shapes

- **`career`** -- the active Sim's careers as a list of
  `{name, user_level, simoleons_per_hour, track, title_stbl}`. The per-hour pay and the
  title are pulled from the *current* `CareerLevel` tuning, resolved via
  `career.current_level_tuning` -- i.e. live, not a stored field.
- **`skills`** -- `{<skill_name_or_guid>: <level int>}` from the Sim's skill statistics.
- **`traits`** -- a list of equipped trait names/GUIDs.
- **`sim`** -- `{first_name, last_name, age, gender, household, mood, sim_id}`.
- **`clock`** -- `{now: "D H:M", speed: <int>, ticks}`.
- **`all`** -- an object combining every topic above.

### `advance` constraints

`advance` is best-effort because the game clock only moves when the simulation is
actually running. The clock will **not** advance while the game is **paused**, in a
**modal dialog**, or in **CAS/Build/Buy**, and a blocking interaction can force the
clock back to normal speed. Callers should re-read `clock` to confirm the move landed.

## 6. State is re-queried each call -- never cached

A core rule, borrowed straight from the Factorio Learning Environment: **the bridge
holds no state between requests; every `state` call re-walks the live game objects.**

Why this matters:

- The simulation changes continuously (Sims age, skills tick up, careers promote, the
  clock advances). A cached snapshot is wrong the instant after it's taken.
- It keeps the bridge stateless and therefore trivially correct under restarts: there's
  no stale cache to invalidate, no coherency protocol to maintain.
- It mirrors the correlation design (Sec. 3), where even the *sequence* state is recovered
  from the files rather than trusted from memory.

Concretely: `state career` does not return a stored level number -- it resolves
`career.current_level_tuning` *now* and reads `simoleons_per_hour`/title off that tuning
*now*. Pay and title therefore always reflect the live rank. The cost (re-walking a few
objects per call) is negligible compared to the correctness it buys.

## 7. References

- **ts4mp -- The Sims 4 Multiplayer Mod** -- socket -> queue -> drain on
  `core_services.on_tick` -> `server_commands.*`.
  https://github.com/the-sims-4-multiplayer-mod/ts4mp
- **Sims4TikTokMod** -- sidecar <-> `127.0.0.1` <-> in-game commands.
  https://github.com/MViMy/Sims4TikTokMod
- **dnavaria/sims4ai** -- in-game `.ts4script` + sidecar reading live Sim state.
  https://github.com/dnavaria/sims4ai
- **Factorio Learning Environment** -- RCON/Lua thin-command -> rich-function -> typed
  result; "always re-query, never cache."
  https://github.com/JackHopkins/factorio-learning-environment
- **Voyager** -- LLM agent driving a live Minecraft via a scripting layer.
  https://github.com/MineDojo/Voyager
- **Mineflayer** -- high-level JS API to a live Minecraft bot; the agent-over-API model.
  https://github.com/PrismarineJS/mineflayer
- **PySC2** -- DeepMind's StarCraft II learning environment: structured observations and
  actions instead of pixel scraping. https://github.com/google-deepmind/pysc2
