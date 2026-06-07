"""Wire-protocol cross-check: the REAL bridge protocol vs the REAL host client.

Every OTHER test in this suite mocks one side of the channel. This one does not.
It wires the actual in-game bridge module ``sims4_test_bridge.protocol`` (the
code that ships inside the .ts4script) to the actual host ``sims4ctl.client``
across a shared temp directory, and proves a full request/response round-trip
works end to end. That validates the two independently-authored halves agree on:

  * the channel PATH (``<USERDATA>/sims4ctl/`` — same dir name on both sides),
  * the FILE NAMES (request.json / response.json / heartbeat.json),
  * the JSON SHAPES ({seq,verb,args} -> {seq,ok,result,error,ts}),
  * the SEQ correlation rule (host: max(req,resp)+1; bridge: act only on a
    newer seq, echo it back), and
  * the ATOMIC-WRITE discipline (.tmp then os.replace, no torn reads).

How both halves share a directory with no game installed: BOTH sides honour the
``SIMS4CTL_USERDATA`` env var. The host's gamepaths already did; the bridge's
``protocol.resolve_userdata_dir`` honours it too (the override never fires
in-game). We point both at one tempdir and let the real code resolve
``<USERDATA>/sims4ctl/`` itself — we do NOT hand either side the path, so this
also proves they DERIVE the same path independently.

The "bridge" here runs in a background thread executing a minimal copy of the
real ``bridge.drain()`` loop: read_request -> dispatch -> write_response, using
the bridge's own protocol functions. (We don't import bridge.py wholesale only
because it tries to wrap ``core_services.on_tick``; the drain logic it would run
is reproduced faithfully below against the same protocol primitives.)
"""

import importlib
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# Host package (host/) — same bootstrap the other tests use.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Bridge package parent (…/sims4ctl/bridge) so ``import sims4_test_bridge`` finds
# the REAL in-game protocol module.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE_PARENT = _REPO_ROOT / "bridge"
sys.path.insert(0, str(_BRIDGE_PARENT))

from sims4ctl import gamepaths  # noqa: E402
from sims4ctl.client import Client  # noqa: E402


class _RealBridgeLoop(object):
    """Background thread running the bridge's real protocol read/write in a
    drain loop, mimicking ``bridge.drain()`` on the main thread (here: a thread,
    but it only ever touches files via the bridge's own protocol module).
    """

    # Heartbeat cadence (seconds). The real bridge throttles to ~2x/sec via its
    # DRAIN_EVERY_TICKS gate; we mirror that here so heartbeat fsync IO doesn't
    # starve the request/response path (and doesn't hammer the FS during
    # teardown). Requests are still polled on every loop iteration.
    _HEARTBEAT_PERIOD = 0.5

    def __init__(self, protocol):
        self.protocol = protocol
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True
        self._last_handled = None
        self._last_hb = 0.0
        self.error = None

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    # The verbs the harness answers — a tiny stand-in for bridge._DISPATCH, but
    # driven through the SAME protocol.write_response the real bridge uses.
    def _dispatch(self, verb, args):
        if verb == "ping":
            return True, {
                "pong": True,
                "zone_loaded": False,        # no game in this harness
                "active_sim": None,
                "bridge_version": self.protocol.BRIDGE_VERSION,
            }, None
        if verb == "state":
            topic = (args or {}).get("topic", "all")
            # Re-query-live contract: we just echo a deterministic structure so
            # the host can assert the round-trip carried the args + shape.
            return True, {"topic": topic, "career": [], "echo_args": args}, None
        return False, None, "unknown verb: {0!r}".format(verb)

    def _run(self):
        try:
            p = self.protocol
            while not self._stop.is_set():
                # Heartbeat, exactly as the real drain does each throttled tick.
                # Re-check stop right before each FS touch so we don't race the
                # tempdir teardown (a stopped loop never writes again).
                if self._stop.is_set():
                    break
                # Throttled heartbeat (~2x/sec), like the real drain. Only while
                # the channel dir still exists, so a write never races
                # tearDown's rmtree (the real bridge swallows such an error
                # anyway; we just keep the test output clean).
                now = time.time()
                if now - self._last_hb >= self._HEARTBEAT_PERIOD:
                    self._last_hb = now
                    try:
                        ch = p.resolve_channel_dir()
                        if ch and os.path.isdir(ch):
                            p.write_heartbeat(1, False, None)
                    except Exception:
                        pass
                if self._stop.is_set():
                    break
                req = p.read_request()
                if req:
                    seq = req.get("seq")
                    if isinstance(seq, int) and (
                        self._last_handled is None or seq > self._last_handled
                    ):
                        ok, result, error = self._dispatch(
                            req.get("verb"), req.get("args") or {}
                        )
                        if not self._stop.is_set():
                            p.write_response(seq, ok, result, error)
                            self._last_handled = seq
                time.sleep(0.01)
        except Exception as e:  # pragma: no cover - surfaced via self.error
            self.error = e


class WireRoundTripTest(unittest.TestCase):
    """One shared tempdir, real client + real bridge protocol, both resolving
    the channel path themselves from SIMS4CTL_USERDATA."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved_env = {}
        for var in (gamepaths.ENV_USERDATA, gamepaths.ENV_MODS):
            self._saved_env[var] = os.environ.get(var)
        # Point BOTH halves at the same user-data root.
        os.environ[gamepaths.ENV_USERDATA] = self.tmp
        os.environ.pop(gamepaths.ENV_MODS, None)

        # Import the REAL bridge protocol fresh, AFTER the env is set, and reset
        # its module-level path caches so it resolves our tempdir (the module may
        # already be imported+cached from a prior test).
        import sims4_test_bridge.protocol as protocol  # noqa: E402
        importlib.reload(protocol)
        protocol._userdata_dir = None
        protocol._channel_dir = None
        self.protocol = protocol

        self.bridge = _RealBridgeLoop(protocol)
        self.bridge.start()

    def tearDown(self):
        if self.bridge:
            self.bridge.stop()
        for var, val in self._saved_env.items():
            if val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = val
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _client(self):
        # Resolve the bridge dir via the host's own logic (NOT hand-built), so
        # we exercise host path resolution too.
        bridge_dir = gamepaths.find_bridge_dir()
        self.assertIsNotNone(bridge_dir, "host failed to resolve bridge dir")
        return Client(bridge_dir, poll_interval=0.02)

    def test_both_sides_resolve_the_same_channel_dir(self):
        host_dir = Path(gamepaths.find_bridge_dir())
        bridge_dir = Path(self.protocol.resolve_channel_dir())
        self.assertEqual(host_dir, bridge_dir)
        # And it's the spec'd <USERDATA>/sims4ctl/.
        self.assertEqual(bridge_dir, Path(self.tmp) / "sims4ctl")

    def test_ping_round_trips_through_real_bridge_protocol(self):
        client = self._client()
        result = client.send("ping", {}, timeout=5)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["pong"])
        self.assertEqual(result["zone_loaded"], False)
        self.assertEqual(result["bridge_version"], self.protocol.BRIDGE_VERSION)

    def test_state_round_trips_with_args_and_shape(self):
        client = self._client()
        result = client.send("state", {"topic": "career"}, timeout=5)
        self.assertEqual(result["topic"], "career")
        self.assertEqual(result["career"], [])
        self.assertEqual(result["echo_args"], {"topic": "career"})

    def test_seq_correlation_across_two_calls(self):
        client = self._client()
        client.send("ping", {}, timeout=5)
        # The bridge wrote response.json with the first seq; the host must pick a
        # strictly greater seq for the second call and only accept the matching
        # fresh response (not the stale first one).
        result2 = client.send("state", {"topic": "sim"}, timeout=5)
        self.assertEqual(result2["topic"], "sim")
        # Confirm the on-disk response seq advanced and matches the request seq.
        resp = self.protocol.read_response()
        req = self.protocol.read_request()
        self.assertEqual(resp["seq"], req["seq"])
        self.assertGreaterEqual(resp["seq"], 2)

    def test_unknown_verb_surfaces_as_bridge_error(self):
        from sims4ctl.client import BridgeError

        client = self._client()
        with self.assertRaises(BridgeError):
            client.send("nonesuch", {}, timeout=5)

    def test_heartbeat_written_by_real_bridge_is_read_by_host(self):
        client = self._client()
        # Give the loop a moment to emit at least one heartbeat.
        deadline = time.time() + 5
        hb = None
        while time.time() < deadline:
            hb = client.read_heartbeat()
            if hb is not None:
                break
            time.sleep(0.02)
        self.assertIsNotNone(hb, "no heartbeat appeared from the real bridge")
        self.assertEqual(hb["bridge_version"], self.protocol.BRIDGE_VERSION)
        self.assertIn("ts", hb)
        self.assertIsNone(self.bridge.error)

    def test_no_tmp_files_leak(self):
        client = self._client()
        client.send("ping", {}, timeout=5)
        # Let a heartbeat or two land too.
        time.sleep(0.05)
        leftovers = [
            f for f in os.listdir(self.protocol.resolve_channel_dir())
            if f.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
