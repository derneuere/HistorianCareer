"""client.py — the file-protocol client (host side of the request/response
channel defined in _BUILD_SPEC.md).

Wire format (EXACT — the in-game bridge implements the mirror of this):

  request.json   (host->bridge): {"seq": int, "verb": str, "args": object}
  response.json  (bridge->host): {"seq": int, "ok": bool, "result": any,
                                  "error": str|null, "ts": float}
  heartbeat.json (bridge->host): {"tick": int, "zone_loaded": bool,
                                  "active_sim": str|null,
                                  "bridge_version": str, "ts": float}

Correlation: the host picks ``seq = max(seq-in-request, seq-in-response) + 1``,
writes ``request.json`` atomically, then polls ``response.json`` until a
response with the *matching* seq appears (or the timeout elapses). The bridge
only acts when ``request.seq > last_handled_seq`` and writes ``response.json``
with the same seq.

Atomic writes: write ``<name>.tmp`` then ``os.replace()`` to the final name, so
a reader never sees a half-written file. Reads tolerate a torn/partial file
(JSON decode error) by treating it as "not there yet" and polling again.
"""

import json
import os
import time
from pathlib import Path


class BridgeError(Exception):
    """Bridge returned ``ok: false`` — carries the bridge-side error string."""


class BridgeTimeout(Exception):
    """No matching response appeared within the timeout window."""


class Client(object):
    """Talks to the in-game bridge through files in ``<USERDATA>/sims4ctl/``.

    The constructor does NOT require the directory to exist; ``send`` creates it
    on first write (a freshly-installed bridge may not have created it yet).
    """

    REQUEST_NAME = "request.json"
    RESPONSE_NAME = "response.json"
    HEARTBEAT_NAME = "heartbeat.json"

    def __init__(self, bridge_dir, poll_interval=0.1):
        if bridge_dir is None:
            raise ValueError(
                "bridge_dir is None — could not resolve <USERDATA>/sims4ctl/. "
                "Pass --userdata or set SIMS4CTL_USERDATA."
            )
        self.bridge_dir = Path(bridge_dir)
        self.poll_interval = poll_interval

    # -- paths ---------------------------------------------------------------

    @property
    def request_path(self):
        return self.bridge_dir / self.REQUEST_NAME

    @property
    def response_path(self):
        return self.bridge_dir / self.RESPONSE_NAME

    @property
    def heartbeat_path(self):
        return self.bridge_dir / self.HEARTBEAT_NAME

    # -- low-level json IO ---------------------------------------------------

    @staticmethod
    def _read_json(path):
        """Read+parse a JSON file. Returns ``None`` if it is missing or torn
        (a concurrent atomic write between open and read can yield a partial
        read on some platforms; we treat any decode/IO error as "not ready")."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _write_json_atomic(path, obj):
        """Write ``obj`` as JSON to ``path`` atomically: ``path.tmp`` then
        ``os.replace``. The directory is created if needed."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        data = json.dumps(obj, ensure_ascii=False)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))

    # -- seq correlation -----------------------------------------------------

    def _next_seq(self):
        """seq = max(seq in request.json, seq in response.json) + 1.

        Both files may be absent (fresh channel) — missing/torn reads count as
        seq 0. Reading BOTH (not just the request) avoids reusing a seq the
        bridge has already answered, which would make a stale response look
        like a match for the new request.
        """
        req = self._read_json(self.request_path) or {}
        resp = self._read_json(self.response_path) or {}
        max_seq = 0
        for d in (req, resp):
            try:
                s = int(d.get("seq", 0))
            except (TypeError, ValueError):
                s = 0
            if s > max_seq:
                max_seq = s
        return max_seq + 1

    # -- the one verb-sending primitive --------------------------------------

    def send(self, verb, args=None, timeout=15):
        """Send a request and block until the matching response arrives.

        Returns the ``result`` field on success. Raises:
          * ``BridgeError`` if the response has ``ok: false``,
          * ``BridgeTimeout`` if no matching-seq response arrives in ``timeout``
            seconds.

        ``args`` defaults to ``{}``. ``seq`` is chosen via :meth:`_next_seq` so
        each call is uniquely correlatable even across process restarts.
        """
        if args is None:
            args = {}
        seq = self._next_seq()
        request = {"seq": seq, "verb": verb, "args": args}
        self._write_json_atomic(self.request_path, request)

        deadline = time.time() + timeout
        # Poll until a response whose seq matches THIS request appears. A
        # response with a smaller seq is a leftover from a previous call; a
        # larger seq should never happen (the bridge echoes our seq) but we
        # still only accept an exact match.
        while True:
            resp = self._read_json(self.response_path)
            if resp is not None:
                try:
                    rseq = int(resp.get("seq", -1))
                except (TypeError, ValueError):
                    rseq = -1
                if rseq == seq:
                    if resp.get("ok", False):
                        return resp.get("result")
                    raise BridgeError(
                        resp.get("error") or "bridge returned ok=false with no error"
                    )
            if time.time() >= deadline:
                raise BridgeTimeout(
                    "no response with seq={0} for verb {1!r} within {2}s "
                    "(is the game running with the bridge installed and a "
                    "zone loaded?)".format(seq, verb, timeout)
                )
            time.sleep(self.poll_interval)

    # -- heartbeat -----------------------------------------------------------

    def read_heartbeat(self):
        """Return the parsed ``heartbeat.json`` dict, or ``None`` if absent/torn.

        The bridge refreshes this ~2x/sec while loaded; callers compare its
        ``ts`` to ``time.time()`` to judge freshness (see ``doctor``).
        """
        return self._read_json(self.heartbeat_path)

    def heartbeat_age(self, now=None):
        """Seconds since the last heartbeat ``ts``, or ``None`` if no heartbeat.

        A large/negative value means the bridge isn't writing (game closed, no
        zone, or clock skew). ``now`` is injectable for tests.
        """
        hb = self.read_heartbeat()
        if not hb or "ts" not in hb:
            return None
        if now is None:
            now = time.time()
        try:
            return now - float(hb["ts"])
        except (TypeError, ValueError):
            return None
