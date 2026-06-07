"""Loopback round-trip test for the file-protocol client.

A background thread plays the role of the in-game bridge: it watches
``request.json`` and, when a new seq appears, writes a canned ``response.json``
with the matching seq (atomic write, exactly like the real bridge). This proves
``Client.send`` correlates seqs, polls, and returns the result — with NO game
installed.
"""

import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sims4ctl.client import BridgeError, BridgeTimeout, Client  # noqa: E402


class _LoopbackBridge(object):
    """A mock bridge: a thread polling request.json, answering response.json.

    ``responder(verb, args)`` returns ``(ok, result, error)`` so individual
    tests can script success/failure. Uses the SAME atomic-write discipline as
    the real bridge (``.tmp`` then ``os.replace``).
    """

    def __init__(self, bridge_dir, responder, poll=0.002):
        self.bridge_dir = bridge_dir
        self.responder = responder
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True
        self._last_handled = 0
        self._poll = poll
        # Every request seq the responder actually observed+answered, in order.
        # Lets tests assert the bridge really saw each call (no missed/dropped
        # request) instead of inferring it from timing.
        self.handled_seqs = []
        self._lock = threading.Lock()
        # Signalled after each request is fully answered (response.json written),
        # so tests can wait on real progress instead of sleeping.
        self.handled_event = threading.Event()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def wait_for_handled(self, count, timeout=10.0):
        """Block until the responder has answered at least ``count`` requests.

        Deterministic: returns as soon as the observed-seq count reaches
        ``count`` (no fixed sleep), and raises on timeout so a stuck responder
        fails loudly instead of letting the test race ahead.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if len(self.handled_seqs) >= count:
                    return list(self.handled_seqs)
            self.handled_event.wait(0.05)
            self.handled_event.clear()
        with self._lock:
            raise AssertionError(
                "responder handled only {0} of {1} expected requests: {2}".format(
                    len(self.handled_seqs), count, self.handled_seqs
                )
            )

    def _read(self, name):
        import json

        try:
            with open(os.path.join(self.bridge_dir, name), "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _write_atomic(self, name, obj):
        import json

        path = os.path.join(self.bridge_dir, name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(obj))
        os.replace(tmp, path)

    def _run(self):
        # Tight poll with NO trailing sleep on the work path: as soon as a new
        # seq appears we answer it and immediately loop to catch the next one,
        # so two back-to-back requests can never be coalesced/missed. We only
        # sleep when idle (nothing new to do).
        while not self._stop.is_set():
            req = self._read("request.json")
            seq = 0
            if req is not None:
                try:
                    seq = int(req.get("seq", 0))
                except (TypeError, ValueError):
                    seq = 0
            if req is not None and seq > self._last_handled:
                self._last_handled = seq
                ok, result, error = self.responder(
                    req.get("verb"), req.get("args") or {}
                )
                self._write_atomic(
                    "response.json",
                    {
                        "seq": seq,
                        "ok": ok,
                        "result": result,
                        "error": error,
                        "ts": time.time(),
                    },
                )
                # Record AFTER the response is durably written, then wake any
                # waiter. Ordering matters: a test that observes the handled
                # count is then guaranteed response.json already exists.
                with self._lock:
                    self.handled_seqs.append(seq)
                self.handled_event.set()
                # Loop again immediately (no sleep) to pick up a queued request.
                continue
            self._stop.wait(self._poll)


class ClientRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = None

    def tearDown(self):
        if self.bridge:
            self.bridge.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _start_bridge(self, responder):
        self.bridge = _LoopbackBridge(self.tmp, responder)
        self.bridge.start()

    def test_send_round_trips_result(self):
        def responder(verb, args):
            self.assertEqual(verb, "ping")
            return True, {"pong": True, "zone_loaded": True, "echo": args}, None

        self._start_bridge(responder)
        client = Client(self.tmp, poll_interval=0.01)
        result = client.send("ping", {"x": 1}, timeout=5)
        self.assertEqual(result["pong"], True)
        self.assertEqual(result["zone_loaded"], True)
        self.assertEqual(result["echo"], {"x": 1})

    def test_seq_increments_across_calls(self):
        def responder(verb, args):
            return True, {"verb": verb}, None

        self._start_bridge(responder)
        client = Client(self.tmp, poll_interval=0.01)

        # First call: send, then block until the responder has DEFINITIVELY
        # observed+answered exactly one request before we sample next-seq. This
        # removes the timing race — we never read _next_seq() while the bridge
        # is mid-flight or while response.json is being replaced.
        client.send("ping", {}, timeout=10)
        self.bridge.wait_for_handled(1)
        seq_after_first = client._next_seq()

        # Second call: same discipline.
        client.send("ping", {}, timeout=10)
        handled = self.bridge.wait_for_handled(2)
        seq_after_second = client._next_seq()

        # Each completed call bumps the max seq, so the next-seq grows.
        self.assertGreater(seq_after_second, seq_after_first)
        # And prove it deterministically at the source: the responder observed
        # two requests whose seqs strictly increase (no reuse, no drop).
        self.assertEqual(len(handled), 2)
        self.assertGreater(handled[1], handled[0])

    def test_ok_false_raises_bridge_error(self):
        def responder(verb, args):
            return False, None, "boom in-game"

        self._start_bridge(responder)
        client = Client(self.tmp, poll_interval=0.01)
        with self.assertRaises(BridgeError) as ctx:
            client.send("cmd", {"command": "nope"}, timeout=5)
        self.assertIn("boom in-game", str(ctx.exception))

    def test_timeout_when_no_bridge(self):
        # No bridge thread started — send must time out, not hang forever.
        client = Client(self.tmp, poll_interval=0.01)
        start = time.time()
        with self.assertRaises(BridgeTimeout):
            client.send("ping", {}, timeout=0.3)
        self.assertLess(time.time() - start, 2.0)

    def test_stale_response_ignored(self):
        # Pre-seed a response with an OLD seq; send must NOT accept it and must
        # wait for the bridge's fresh, matching-seq answer.
        import json

        with open(os.path.join(self.tmp, "response.json"), "w", encoding="utf-8") as fh:
            json.dump({"seq": 1, "ok": True, "result": "STALE", "error": None, "ts": 0}, fh)

        def responder(verb, args):
            return True, "FRESH", None

        self._start_bridge(responder)
        client = Client(self.tmp, poll_interval=0.01)
        result = client.send("ping", {}, timeout=5)
        self.assertEqual(result, "FRESH")

    def test_read_heartbeat(self):
        import json

        with open(os.path.join(self.tmp, "heartbeat.json"), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "tick": 42,
                    "zone_loaded": True,
                    "active_sim": "Bob",
                    "bridge_version": "0.1.0",
                    "ts": time.time(),
                },
                fh,
            )
        client = Client(self.tmp, poll_interval=0.01)
        hb = client.read_heartbeat()
        self.assertEqual(hb["tick"], 42)
        age = client.heartbeat_age()
        self.assertIsNotNone(age)
        self.assertLess(age, 5)

    def test_heartbeat_absent_returns_none(self):
        client = Client(self.tmp, poll_interval=0.01)
        self.assertIsNone(client.read_heartbeat())
        self.assertIsNone(client.heartbeat_age())

    def test_atomic_write_leaves_no_tmp(self):
        def responder(verb, args):
            return True, "ok", None

        self._start_bridge(responder)
        client = Client(self.tmp, poll_interval=0.01)
        client.send("ping", {}, timeout=5)
        # After a completed round trip no .tmp files should remain.
        leftovers = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
