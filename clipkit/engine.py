"""Clipboard-sync decision logic, platform- and transport-agnostic. Decides what
to publish and what to apply, and prevents echo loops via a single last-value
hash. All I/O is injected as callbacks; the engine touches neither sockets nor
clipboards, so it is fully unit-testable with fakes."""
import hashlib


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Engine:
    def __init__(self, seal_fn, open_fn, send_fn, apply_fn, max_bytes=1_000_000):
        """seal_fn(text)->frame; open_fn(frame)->str|None; send_fn(frame) delivers
        to all peers; apply_fn(text) sets the local clipboard. max_bytes caps the
        payload we will publish."""
        self._seal = seal_fn
        self._open = open_fn
        self._send = send_fn
        self._apply = apply_fn
        self._max_bytes = max_bytes
        self._last_value_hash = None

    def on_local_change(self, text):
        if not text or len(text.encode("utf-8")) > self._max_bytes:
            return
        h = _hash(text)
        if h == self._last_value_hash:        # echo of a value we just applied/sent
            return
        self._last_value_hash = h
        self._send(self._seal(text))

    def on_remote_frame(self, frame):
        text = self._open(frame)
        if not text:                          # None (bad frame) or empty
            return
        h = _hash(text)
        if h == self._last_value_hash:        # echo of a value we just sent/applied
            return
        self._last_value_hash = h
        self._apply(text)
