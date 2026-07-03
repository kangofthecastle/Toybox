# Shared Clipboard (LAN peer-to-peer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync the text clipboard between the Windows Toybox machine and a Mac over the LAN, so a copy on either machine appears on the other within about a second.

**Architecture:** A pure-stdlib, side-effect-free core package `clipkit/` (`protocol` crypto, `discovery` beacons, `engine` sync logic, `net` sockets) driven by two thin platform adapters — the existing Windows clipboard toy (`clipboard.pyw` + a testable `clip_sync_win.py` glue module) and a standalone Mac daemon (`clipsync_mac.py`). Peers auto-discover via authenticated UDP broadcast; payloads travel over TCP, encrypted-then-MAC'd with a passphrase-derived HMAC-SHA256 CTR keystream.

**Tech Stack:** Python 3.12 standard library only — `hashlib`, `hmac`, `os`, `socket`, `struct`, `threading`, `queue`, `subprocess`, `tkinter`.

## Global Constraints

Every task's requirements implicitly include these (copied verbatim from the spec):

- **Pure Python 3.12 standard library only. No pip, no third-party packages, ever.**
- **Test runner:** `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path>` from the repo root (`C:/Users/Warren/Toybox`). A bare `python` is broken on this machine.
- **Commit trailer, exactly:** `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **`config.json` is gitignored and holds live secrets** (the GitHub PAT, and the new sync passphrase). Never echo, log, or commit it. All writes go through the scoped `config.update(path, partial)`.
- **After changing any config-save code, restart ALL toys** (hud / clipboard / pet) so a stale in-memory copy can't re-clobber the shared `config.json`.
- **Windows clipboard I/O is via Tkinter** (`root.clipboard_get()` / `clipboard_clear()` / `clipboard_append()`); Tk is only ever touched from the main thread.
- **Fixed ports:** UDP discovery `50505`, TCP payload `50506` (code constants, not user-configurable).
- **Text only.** Images, files, and rich clipboard formats are out of scope.

## File Structure

New package `clipkit/` (matches the `winkit`/`petkit`/`feedkit` convention):

| File | Responsibility |
|------|----------------|
| `clipkit/__init__.py` | Empty package marker. |
| `clipkit/protocol.py` | Key derivation, `seal`, `unseal` — the encrypt-then-MAC wire frame. Pure. |
| `clipkit/discovery.py` | `encode_beacon`/`parse_beacon` + `PeerTable` (TTL expiry). Pure. |
| `clipkit/engine.py` | `Engine` — decide what to publish/apply, loop guard. Pure, callbacks injected. |
| `clipkit/net.py` | `ClipSyncNode` — UDP discovery + TCP payload threads. The only networked module. |
| `clip_sync_win.py` | Windows glue (`sync_enabled`/`make_apply`/`build_node`) — testable without Tk. |
| `clipsync_mac.py` | Standalone Mac daemon (pbpaste/pbcopy adapter + `clipkit` core). |

Modified: `clipboard.pyw` (wire the node into the poll loop + teardown), `config.py` (add `sync`/`sync_passphrase` to the `clipboard` section).

Tests: `tests/test_clip_protocol.py`, `tests/test_clip_discovery.py`, `tests/test_clip_engine.py`, `tests/test_clip_net.py`, `tests/test_clip_net_discovery.py`, `tests/test_clip_sync_win.py`, `tests/test_clipsync_mac.py`, plus additions to `tests/test_config.py` and `tests/test_smoke_clipboard.py`.

**Naming note (spec refinement):** the spec listed the decrypt function as `open()`; the plan uses **`unseal()`** to avoid shadowing the `open` builtin. The engine injects it as `open_fn`, so callers are unaffected.

---

### Task 1: `clipkit/protocol.py` — encrypted, authenticated wire frame

**Files:**
- Create: `clipkit/__init__.py`
- Create: `clipkit/protocol.py`
- Test: `tests/test_clip_protocol.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `derive_keys(passphrase: str) -> (key_enc: bytes, key_mac: bytes)`
  - `seal(key_enc: bytes, key_mac: bytes, text: str) -> bytes`
  - `unseal(key_enc: bytes, key_mac: bytes, frame: bytes) -> str | None`
  - Module constant `MAGIC = b"TBCS"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_clip_protocol.py`:

```python
import unittest

from clipkit import protocol


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.ke, self.km = protocol.derive_keys("correct horse")

    def test_round_trip(self):
        frame = protocol.seal(self.ke, self.km, "hello world")
        self.assertEqual(protocol.unseal(self.ke, self.km, frame), "hello world")

    def test_round_trip_unicode(self):
        frame = protocol.seal(self.ke, self.km, "café — 日本語 🚀")
        self.assertEqual(protocol.unseal(self.ke, self.km, frame), "café — 日本語 🚀")

    def test_empty_string_round_trips(self):
        frame = protocol.seal(self.ke, self.km, "")
        self.assertEqual(protocol.unseal(self.ke, self.km, frame), "")

    def test_wrong_passphrase_returns_none(self):
        frame = protocol.seal(self.ke, self.km, "secret")
        wke, wkm = protocol.derive_keys("wrong passphrase")
        self.assertIsNone(protocol.unseal(wke, wkm, frame))

    def test_tampered_ciphertext_returns_none(self):
        frame = bytearray(protocol.seal(self.ke, self.km, "secret text"))
        frame[-1] ^= 0x01                      # flip a ciphertext bit
        self.assertIsNone(protocol.unseal(self.ke, self.km, bytes(frame)))

    def test_tampered_tag_returns_none(self):
        frame = bytearray(protocol.seal(self.ke, self.km, "secret text"))
        frame[8] ^= 0x01                        # flip a bit inside the tag region
        self.assertIsNone(protocol.unseal(self.ke, self.km, bytes(frame)))

    def test_bad_magic_returns_none(self):
        frame = protocol.seal(self.ke, self.km, "secret")
        self.assertIsNone(protocol.unseal(self.ke, self.km, b"XXXX" + frame[4:]))

    def test_short_frame_returns_none(self):
        self.assertIsNone(protocol.unseal(self.ke, self.km, b"tiny"))

    def test_fresh_nonce_each_call(self):
        a = protocol.seal(self.ke, self.km, "same text")
        b = protocol.seal(self.ke, self.km, "same text")
        self.assertNotEqual(a, b)               # random nonce => different frames

    def test_derive_keys_is_deterministic(self):
        self.assertEqual(protocol.derive_keys("pw"), protocol.derive_keys("pw"))

    def test_derive_keys_splits_enc_and_mac(self):
        ke, km = protocol.derive_keys("pw")
        self.assertEqual((len(ke), len(km)), (32, 32))
        self.assertNotEqual(ke, km)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_protocol -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clipkit'`.

- [ ] **Step 3: Write minimal implementation**

Create `clipkit/__init__.py` (empty file).

Create `clipkit/protocol.py`:

```python
"""Encrypted, authenticated framing for clipboard-sync payloads, pure stdlib.

Encrypt-then-MAC: an HMAC-SHA256 keystream in counter mode gives confidentiality;
a separate HMAC-SHA256 tag over (nonce + ciphertext) gives integrity. Keys are
derived once from the shared passphrase via PBKDF2-HMAC-SHA256 with a fixed
application-label salt (domain separation, not secrecy), so both peers derive
identical keys and the KDF cost is paid once per process, not per message. No
pip, no AES -- everything is composed from hashlib/hmac/os."""
import hashlib
import hmac
import os

MAGIC = b"TBCS"                       # Toy Box Clip Sync, frame v1
_KDF_SALT = b"toybox-clipsync-v1"
_KDF_ITERS = 200_000
_NONCE_LEN = 16
_TAG_LEN = 32
_HEADER_LEN = len(MAGIC) + _NONCE_LEN + _TAG_LEN


def derive_keys(passphrase):
    """Derive (key_enc, key_mac) from a passphrase. Deterministic: the same
    passphrase always yields the same pair, so both machines match."""
    master = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"),
                                 _KDF_SALT, _KDF_ITERS, dklen=64)
    return master[:32], master[32:]


def _keystream(key_enc, nonce, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hmac.new(key_enc, nonce + counter.to_bytes(8, "big"),
                            "sha256").digest())
        counter += 1
    return bytes(out[:length])


def _xor(data, keystream):
    n = len(data)
    return (int.from_bytes(data, "big")
            ^ int.from_bytes(keystream, "big")).to_bytes(n, "big")


def seal(key_enc, key_mac, text):
    """Encrypt-then-MAC `text` into MAGIC(4) | nonce(16) | tag(32) | ciphertext."""
    plaintext = text.encode("utf-8")
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = _xor(plaintext, _keystream(key_enc, nonce, len(plaintext)))
    tag = hmac.new(key_mac, nonce + ciphertext, "sha256").digest()
    return MAGIC + nonce + tag + ciphertext


def unseal(key_enc, key_mac, frame):
    """Inverse of seal(). Return the plaintext str, or None on any tamper, wrong
    key, or malformed input. Never raises on bad input."""
    try:
        if len(frame) < _HEADER_LEN or frame[:len(MAGIC)] != MAGIC:
            return None
        nonce = frame[len(MAGIC):len(MAGIC) + _NONCE_LEN]
        tag = frame[len(MAGIC) + _NONCE_LEN:_HEADER_LEN]
        ciphertext = frame[_HEADER_LEN:]
        expected = hmac.new(key_mac, nonce + ciphertext, "sha256").digest()
        if not hmac.compare_digest(tag, expected):
            return None
        return _xor(ciphertext, _keystream(key_enc, nonce, len(ciphertext))).decode("utf-8")
    except Exception:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_protocol -v`
Expected: PASS — 11 tests OK.

- [ ] **Step 5: Commit**

```bash
git add clipkit/__init__.py clipkit/protocol.py tests/test_clip_protocol.py
git commit -m "feat(clipkit): encrypt-then-MAC wire frame for clipboard sync

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `clipkit/discovery.py` — authenticated beacons + peer table

**Files:**
- Create: `clipkit/discovery.py`
- Test: `tests/test_clip_discovery.py`

**Interfaces:**
- Consumes: nothing (uses `hmac`, `struct`).
- Produces:
  - `encode_beacon(key_mac: bytes, instance_id: str, tcp_port: int) -> bytes`
  - `parse_beacon(key_mac: bytes, data: bytes) -> (instance_id: str, tcp_port: int) | None`
  - `class PeerTable(ttl: float = 15.0)` with `seen(instance_id, addr, tcp_port, now)`, `live_peers(now) -> list[(addr, port)]`, `expire(now)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_clip_discovery.py`:

```python
import unittest

from clipkit import discovery, protocol


class TestBeacon(unittest.TestCase):
    def setUp(self):
        _, self.km = protocol.derive_keys("pw")

    def test_encode_parse_round_trip(self):
        beacon = discovery.encode_beacon(self.km, "node-abc", 50506)
        self.assertEqual(discovery.parse_beacon(self.km, beacon), ("node-abc", 50506))

    def test_bad_hmac_rejected(self):
        beacon = discovery.encode_beacon(self.km, "node-abc", 50506)
        _, wrong = protocol.derive_keys("other")
        self.assertIsNone(discovery.parse_beacon(wrong, beacon))

    def test_tampered_beacon_rejected(self):
        beacon = bytearray(discovery.encode_beacon(self.km, "node-abc", 50506))
        beacon[5] ^= 0x01
        self.assertIsNone(discovery.parse_beacon(self.km, bytes(beacon)))

    def test_garbage_rejected(self):
        self.assertIsNone(discovery.parse_beacon(self.km, b"nonsense"))
        self.assertIsNone(discovery.parse_beacon(self.km, b""))


class TestPeerTable(unittest.TestCase):
    def test_seen_then_live(self):
        pt = discovery.PeerTable(ttl=10.0)
        pt.seen("A", "10.0.0.2", 50506, now=100.0)
        self.assertEqual(pt.live_peers(now=105.0), [("10.0.0.2", 50506)])

    def test_expiry_after_ttl(self):
        pt = discovery.PeerTable(ttl=10.0)
        pt.seen("A", "10.0.0.2", 50506, now=100.0)
        self.assertEqual(pt.live_peers(now=111.0), [])   # 11s > 10s ttl

    def test_refresh_extends_life(self):
        pt = discovery.PeerTable(ttl=10.0)
        pt.seen("A", "10.0.0.2", 50506, now=100.0)
        pt.seen("A", "10.0.0.2", 50506, now=108.0)       # heard again
        self.assertEqual(pt.live_peers(now=115.0), [("10.0.0.2", 50506)])

    def test_multiple_peers(self):
        pt = discovery.PeerTable(ttl=10.0)
        pt.seen("A", "10.0.0.2", 50506, now=100.0)
        pt.seen("B", "10.0.0.3", 50506, now=100.0)
        self.assertEqual(sorted(pt.live_peers(now=105.0)),
                         [("10.0.0.2", 50506), ("10.0.0.3", 50506)])

    def test_expire_prunes_dict(self):
        pt = discovery.PeerTable(ttl=10.0)
        pt.seen("A", "10.0.0.2", 50506, now=100.0)
        pt.expire(now=120.0)
        self.assertEqual(pt.live_peers(now=120.0), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_discovery -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clipkit.discovery'`.

- [ ] **Step 3: Write minimal implementation**

Create `clipkit/discovery.py`:

```python
"""LAN peer discovery for clipboard sync. Agents UDP-broadcast a small,
HMAC-authenticated beacon carrying only their instance id and TCP payload port
(never clipboard content); each agent tracks the peers it hears from and expires
stale ones. Authenticating with the shared passphrase's key_mac means an agent
discovers only its own peers, and a stray beacon cannot point it at a rogue
endpoint."""
import hmac
import struct

_BEACON_MAGIC = b"TBCB"               # Toy Box Clip Beacon
_TAG_LEN = 32
_MIN_LEN = len(_BEACON_MAGIC) + 2 + 1 + _TAG_LEN   # magic + port + id_len + tag


def encode_beacon(key_mac, instance_id, tcp_port):
    """body = magic(4) | tcp_port(2, big-endian) | id_len(1) | instance_id;
    frame = body | HMAC-SHA256(body)."""
    idb = instance_id.encode("utf-8")[:255]
    body = _BEACON_MAGIC + struct.pack(">H", tcp_port) + bytes([len(idb)]) + idb
    return body + hmac.new(key_mac, body, "sha256").digest()


def parse_beacon(key_mac, data):
    """Return (instance_id, tcp_port) if the beacon authenticates, else None."""
    try:
        if len(data) < _MIN_LEN:
            return None
        body, tag = data[:-_TAG_LEN], data[-_TAG_LEN:]
        if body[:len(_BEACON_MAGIC)] != _BEACON_MAGIC:
            return None
        if not hmac.compare_digest(tag, hmac.new(key_mac, body, "sha256").digest()):
            return None
        tcp_port = struct.unpack(">H", body[4:6])[0]
        id_len = body[6]
        idb = body[7:7 + id_len]
        if len(idb) != id_len:
            return None
        return idb.decode("utf-8"), tcp_port
    except Exception:
        return None


class PeerTable:
    """Tracks live peers by instance id with TTL expiry. Times are supplied by the
    caller (monotonic seconds) so the table is testable without real time."""
    def __init__(self, ttl=15.0):
        self.ttl = ttl
        self._peers = {}              # instance_id -> (addr, tcp_port, last_seen)

    def seen(self, instance_id, addr, tcp_port, now):
        self._peers[instance_id] = (addr, tcp_port, now)

    def live_peers(self, now):
        return [(addr, port) for (addr, port, ts) in self._peers.values()
                if now - ts <= self.ttl]

    def expire(self, now):
        self._peers = {k: v for k, v in self._peers.items()
                       if now - v[2] <= self.ttl}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_discovery -v`
Expected: PASS — 10 tests OK.

- [ ] **Step 5: Commit**

```bash
git add clipkit/discovery.py tests/test_clip_discovery.py
git commit -m "feat(clipkit): authenticated UDP beacons and peer table

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `clipkit/engine.py` — sync state machine + loop guard

**Files:**
- Create: `clipkit/engine.py`
- Test: `tests/test_clip_engine.py`

**Interfaces:**
- Consumes: nothing (all I/O injected as callbacks).
- Produces:
  - `class Engine(seal_fn, open_fn, send_fn, apply_fn, max_bytes=1_000_000)` with:
    - `on_local_change(text: str)` — seal + `send_fn(frame)` if the value is new and within `max_bytes`.
    - `on_remote_frame(frame: bytes)` — `open_fn(frame)`; if valid and new, `apply_fn(text)`.
  - Loop guard: a single `_last_value_hash` suppresses the echo of a value we just sent or applied.

- [ ] **Step 1: Write the failing test**

Create `tests/test_clip_engine.py`:

```python
import unittest

from clipkit.engine import Engine


class Recorder:
    """Fake collaborators: seal tags the text, open untags it, send/apply record."""
    def __init__(self):
        self.sent = []
        self.applied = []

    def seal(self, text):
        return b"F:" + text.encode("utf-8")

    def open(self, frame):
        if not frame.startswith(b"F:"):
            return None
        return frame[2:].decode("utf-8")

    def send(self, frame):
        self.sent.append(frame)

    def apply(self, text):
        self.applied.append(text)

    def engine(self, max_bytes=1_000_000):
        return Engine(self.seal, self.open, self.send, self.apply, max_bytes)


class TestEngine(unittest.TestCase):
    def test_local_change_sends_sealed_frame(self):
        r = Recorder(); e = r.engine()
        e.on_local_change("hello")
        self.assertEqual(r.sent, [b"F:hello"])

    def test_remote_frame_applies_once(self):
        r = Recorder(); e = r.engine()
        e.on_remote_frame(b"F:world")
        self.assertEqual(r.applied, ["world"])

    def test_applied_value_is_not_rebroadcast(self):
        # Remote value arrives and is applied; the ensuing local-change echo of
        # that same value must NOT be sent back (loop guard).
        r = Recorder(); e = r.engine()
        e.on_remote_frame(b"F:shared")
        e.on_local_change("shared")
        self.assertEqual(r.sent, [])

    def test_sent_value_is_not_reapplied(self):
        # We publish a value; a remote frame carrying that same value (our own
        # echo bouncing back) must NOT be applied.
        r = Recorder(); e = r.engine()
        e.on_local_change("mine")
        e.on_remote_frame(b"F:mine")
        self.assertEqual(r.applied, [])

    def test_duplicate_local_change_not_resent(self):
        r = Recorder(); e = r.engine()
        e.on_local_change("dup")
        e.on_local_change("dup")
        self.assertEqual(r.sent, [b"F:dup"])

    def test_new_value_after_duplicate_is_sent(self):
        r = Recorder(); e = r.engine()
        e.on_local_change("a")
        e.on_local_change("a")
        e.on_local_change("b")
        self.assertEqual(r.sent, [b"F:a", b"F:b"])

    def test_oversized_value_skipped(self):
        r = Recorder(); e = r.engine(max_bytes=8)
        e.on_local_change("x" * 9)
        self.assertEqual(r.sent, [])

    def test_empty_local_change_ignored(self):
        r = Recorder(); e = r.engine()
        e.on_local_change("")
        self.assertEqual(r.sent, [])

    def test_bad_frame_ignored(self):
        r = Recorder(); e = r.engine()
        e.on_remote_frame(b"garbage")           # open() returns None
        self.assertEqual(r.applied, [])

    def test_empty_remote_text_ignored(self):
        r = Recorder(); e = r.engine()
        e.on_remote_frame(b"F:")                 # opens to ""
        self.assertEqual(r.applied, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_engine -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clipkit.engine'`.

- [ ] **Step 3: Write minimal implementation**

Create `clipkit/engine.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_engine -v`
Expected: PASS — 10 tests OK.

- [ ] **Step 5: Commit**

```bash
git add clipkit/engine.py tests/test_clip_engine.py
git commit -m "feat(clipkit): sync engine with echo-loop guard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `clipkit/net.py` — `ClipSyncNode` TCP payload path

**Files:**
- Create: `clipkit/net.py`
- Test: `tests/test_clip_net.py`

**Interfaces:**
- Consumes: `protocol.derive_keys/seal/unseal`, `discovery.PeerTable`, `engine.Engine`.
- Produces:
  - Module constants `UDP_PORT = 50505`, `TCP_PORT = 50506`.
  - `class ClipSyncNode(passphrase, apply_fn, instance_id, udp_port=UDP_PORT, tcp_port=TCP_PORT, max_bytes=1_000_000)` with:
    - `start()` — bind sockets, launch daemon threads.
    - `stop()` — signal stop, close sockets, join threads (timeout 2s each).
    - `local_change(text: str)` — publish a local clipboard change to peers.
    - `poll_incoming()` — drain received frames and apply them **on the caller's thread**.
    - Attribute `_peers` (a `PeerTable`) so a caller/test can seed peers directly.
  - (Task 5 will add `_handle_beacon` and the UDP loops to this same class.)

This task builds the TCP payload path and the thread lifecycle; peers are injected directly in the test (UDP discovery is Task 5). All blocking network I/O runs off the caller's thread: `local_change` only enqueues; a TX thread does the sending; inbound frames are queued and applied by `poll_incoming` on the caller's thread.

- [ ] **Step 1: Write the failing test**

Create `tests/test_clip_net.py`:

```python
import time
import unittest

from clipkit.net import ClipSyncNode

# Fixed high test ports, distinct from the real 50505/50506 and from each other.
A_UDP, A_TCP = 55010, 55011
B_UDP, B_TCP = 55020, 55021


class TestClipSyncNodeTcp(unittest.TestCase):
    def test_local_change_delivers_to_seeded_peer(self):
        applied = []
        a = ClipSyncNode("pw", lambda t: None, "A", udp_port=A_UDP, tcp_port=A_TCP)
        b = ClipSyncNode("pw", lambda t: applied.append(t),
                         "B", udp_port=B_UDP, tcp_port=B_TCP)
        a.start(); b.start()
        try:
            a._peers.seen("B", "127.0.0.1", B_TCP, now=time.monotonic())  # skip discovery
            a.local_change("hello over tcp")
            deadline = time.monotonic() + 5.0
            while not applied and time.monotonic() < deadline:
                b.poll_incoming()
                time.sleep(0.02)
        finally:
            a.stop(); b.stop()
        self.assertEqual(applied, ["hello over tcp"])

    def test_wrong_passphrase_peer_drops_frame(self):
        applied = []
        a = ClipSyncNode("pw-one", lambda t: None, "A", udp_port=A_UDP, tcp_port=A_TCP)
        b = ClipSyncNode("pw-two", lambda t: applied.append(t),
                         "B", udp_port=B_UDP, tcp_port=B_TCP)
        a.start(); b.start()
        try:
            a._peers.seen("B", "127.0.0.1", B_TCP, now=time.monotonic())
            a.local_change("cannot decrypt this")
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                b.poll_incoming()
                time.sleep(0.02)
        finally:
            a.stop(); b.stop()
        self.assertEqual(applied, [])           # HMAC mismatch => dropped

    def test_stop_is_clean_and_idempotent(self):
        n = ClipSyncNode("pw", lambda t: None, "N", udp_port=A_UDP, tcp_port=A_TCP)
        n.start()
        n.stop()
        n.stop()                                # second stop must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_net -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clipkit.net'`.

- [ ] **Step 3: Write minimal implementation**

Create `clipkit/net.py`:

```python
"""Socket plumbing for clipboard sync: UDP discovery beacons and TCP payload
delivery on background daemon threads. The only module in clipkit that performs
network I/O. Inbound payloads are queued and applied on the CALLER's thread via
poll_incoming(), so a GUI adapter can keep all clipboard access on its main
thread. All blocking sends run on a dedicated TX thread, so local_change() never
blocks the caller."""
import queue
import socket
import struct
import threading
import time

from clipkit import discovery, protocol
from clipkit.engine import Engine

UDP_PORT = 50505
TCP_PORT = 50506
_BEACON_INTERVAL = 3.0
_PEER_TTL = 15.0
_MAX_FRAME = 2_000_000                 # hard cap on a single TCP frame we will read


def _recv_exact(conn, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


class ClipSyncNode:
    def __init__(self, passphrase, apply_fn, instance_id,
                 udp_port=UDP_PORT, tcp_port=TCP_PORT, max_bytes=1_000_000):
        self._instance_id = instance_id
        self._udp_port = udp_port
        self._tcp_port = tcp_port
        self._key_enc, self._key_mac = protocol.derive_keys(passphrase)
        self._peers = discovery.PeerTable(_PEER_TTL)
        self._rx = queue.Queue()          # inbound frames -> drained by poll_incoming
        self._tx = queue.Queue()          # outbound frames -> sent by _tx_loop
        self._engine = Engine(
            seal_fn=lambda text: protocol.seal(self._key_enc, self._key_mac, text),
            open_fn=lambda frame: protocol.unseal(self._key_enc, self._key_mac, frame),
            send_fn=self._tx.put,
            apply_fn=apply_fn,
            max_bytes=max_bytes)
        self._stop = threading.Event()
        self._threads = []
        self._udp_sock = None
        self._tcp_sock = None

    # -- lifecycle --------------------------------------------------------
    def start(self):
        self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._udp_sock.bind(("", self._udp_port))
        self._udp_sock.settimeout(0.5)

        self._tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp_sock.bind(("", self._tcp_port))
        self._tcp_sock.listen(8)
        self._tcp_sock.settimeout(0.5)

        for target in (self._tcp_accept_loop, self._tx_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        for s in (self._udp_sock, self._tcp_sock):
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []

    # -- public API used by the platform adapter --------------------------
    def local_change(self, text):
        self._engine.on_local_change(text)

    def poll_incoming(self):
        """Drain received frames and apply them on the CALLER's thread."""
        while True:
            try:
                frame = self._rx.get_nowait()
            except queue.Empty:
                return
            self._engine.on_remote_frame(frame)

    # -- TCP threads ------------------------------------------------------
    def _tcp_accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._tcp_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                continue
            threading.Thread(target=self._read_conn, args=(conn,),
                             daemon=True).start()

    def _read_conn(self, conn):
        try:
            conn.settimeout(5.0)
            header = _recv_exact(conn, 4)
            if header is None:
                return
            (length,) = struct.unpack(">I", header)
            if length == 0 or length > _MAX_FRAME:
                return
            frame = _recv_exact(conn, length)
            if frame is not None:
                self._rx.put(frame)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _tx_loop(self):
        while not self._stop.is_set():
            try:
                frame = self._tx.get(timeout=0.5)
            except queue.Empty:
                continue
            for addr, port in self._peers.live_peers(time.monotonic()):
                self._send_frame(addr, port, frame)

    def _send_frame(self, addr, port, frame):
        try:
            with socket.create_connection((addr, port), timeout=3.0) as c:
                c.sendall(struct.pack(">I", len(frame)) + frame)
        except OSError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_net -v`
Expected: PASS — 3 tests OK. (The first test exercises a real localhost TCP round-trip; it should complete in well under a second.)

- [ ] **Step 5: Commit**

```bash
git add clipkit/net.py tests/test_clip_net.py
git commit -m "feat(clipkit): ClipSyncNode TCP payload path + thread lifecycle

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `clipkit/net.py` — UDP discovery integration

**Files:**
- Modify: `clipkit/net.py` (add `_handle_beacon`, `_udp_beacon_loop`, `_udp_listen_loop`; start them in `start()`).
- Test: `tests/test_clip_net_discovery.py`

**Interfaces:**
- Consumes: `discovery.encode_beacon/parse_beacon`, the `ClipSyncNode._peers` table from Task 4.
- Produces:
  - `ClipSyncNode._handle_beacon(data: bytes, addr_ip: str, now: float)` — parse a beacon, ignore our own instance id and any that fails to authenticate, otherwise record the peer. (Pure of sockets — directly unit-tested.)
  - Two new daemon threads (`_udp_beacon_loop`, `_udp_listen_loop`) started by `start()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_clip_net_discovery.py`:

```python
import unittest

from clipkit import discovery, protocol
from clipkit.net import ClipSyncNode


class TestHandleBeacon(unittest.TestCase):
    """_handle_beacon is pure of sockets, so construct the node WITHOUT start()."""
    def _node(self):
        return ClipSyncNode("pw", lambda t: None, "SELF",
                            udp_port=55110, tcp_port=55111)

    def test_foreign_beacon_adds_peer(self):
        node = self._node()
        _, km = protocol.derive_keys("pw")
        beacon = discovery.encode_beacon(km, "OTHER", 50506)
        node._handle_beacon(beacon, "10.0.0.5", now=100.0)
        self.assertIn(("10.0.0.5", 50506), node._peers.live_peers(now=100.0))

    def test_self_beacon_ignored(self):
        node = self._node()
        _, km = protocol.derive_keys("pw")
        beacon = discovery.encode_beacon(km, "SELF", 50506)     # our own id
        node._handle_beacon(beacon, "10.0.0.5", now=100.0)
        self.assertEqual(node._peers.live_peers(now=100.0), [])

    def test_bad_hmac_beacon_ignored(self):
        node = self._node()
        _, wrong = protocol.derive_keys("different")
        beacon = discovery.encode_beacon(wrong, "OTHER", 50506)
        node._handle_beacon(beacon, "10.0.0.5", now=100.0)
        self.assertEqual(node._peers.live_peers(now=100.0), [])

    def test_garbage_beacon_ignored(self):
        node = self._node()
        node._handle_beacon(b"nonsense", "10.0.0.5", now=100.0)
        self.assertEqual(node._peers.live_peers(now=100.0), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_net_discovery -v`
Expected: FAIL — `AttributeError: 'ClipSyncNode' object has no attribute '_handle_beacon'`.

- [ ] **Step 3: Write minimal implementation**

In `clipkit/net.py`, add the three methods to `ClipSyncNode` (place them in a new `# -- UDP discovery threads` section after `_send_frame`):

```python
    # -- UDP discovery ----------------------------------------------------
    def _handle_beacon(self, data, addr_ip, now):
        parsed = discovery.parse_beacon(self._key_mac, data)
        if parsed is None:
            return
        instance_id, tcp_port = parsed
        if instance_id == self._instance_id:
            return                        # our own beacon, bounced back to us
        self._peers.seen(instance_id, addr_ip, tcp_port, now)

    def _udp_beacon_loop(self):
        beacon = discovery.encode_beacon(self._key_mac, self._instance_id,
                                         self._tcp_port)
        while not self._stop.is_set():
            try:
                self._udp_sock.sendto(beacon, ("255.255.255.255", self._udp_port))
            except OSError:
                pass
            self._stop.wait(_BEACON_INTERVAL)

    def _udp_listen_loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self._udp_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                continue
            self._handle_beacon(data, addr[0], time.monotonic())
```

Then, in `start()`, extend the thread list to launch the UDP loops too. Change:

```python
        for target in (self._tcp_accept_loop, self._tx_loop):
```

to:

```python
        for target in (self._tcp_accept_loop, self._tx_loop,
                       self._udp_beacon_loop, self._udp_listen_loop):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_net_discovery tests.test_clip_net -v`
Expected: PASS — 7 tests OK (4 new discovery tests + the 3 Task-4 TCP tests still green after wiring the UDP loops into `start()`).

- [ ] **Step 5: Commit**

```bash
git add clipkit/net.py tests/test_clip_net_discovery.py
git commit -m "feat(clipkit): UDP beacon discovery in ClipSyncNode

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `config.py` — sync defaults

**Files:**
- Modify: `config.py:11-12` (the `clipboard` entry of `DEFAULTS`).
- Test: `tests/test_config.py` (append new tests).

**Interfaces:**
- Consumes: nothing.
- Produces: `config.defaults()["clipboard"]` gains `"sync": False` and `"sync_passphrase": ""`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py` (inside `class TestConfig`, after `test_clipboard_layout_non_string_falls_back`):

```python
    def test_clipboard_sync_defaults(self):
        c = config.defaults()["clipboard"]
        self.assertIs(c["sync"], False)
        self.assertEqual(c["sync_passphrase"], "")

    def test_clipboard_sync_roundtrip(self):
        cfg = config.defaults()
        cfg["clipboard"]["sync"] = True
        cfg["clipboard"]["sync_passphrase"] = "hunter2"
        config.save(self.path, cfg)
        loaded = config.load(self.path)
        self.assertIs(loaded["clipboard"]["sync"], True)
        self.assertEqual(loaded["clipboard"]["sync_passphrase"], "hunter2")

    def test_clipboard_sync_wrong_types_fall_back(self):
        self._write({"clipboard": {"sync": "yes", "sync_passphrase": 123}})
        c = config.load(self.path)["clipboard"]
        self.assertIs(c["sync"], False)          # non-bool rejected
        self.assertEqual(c["sync_passphrase"], "")  # non-str rejected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_config -v`
Expected: FAIL — `KeyError: 'sync'` in `test_clipboard_sync_defaults`.

- [ ] **Step 3: Write minimal implementation**

In `config.py`, change the `clipboard` entry of `DEFAULTS` (lines 11-12) from:

```python
    "clipboard": {"max_items": 30, "hotkey": ["ctrl", "shift", "V"],
                  "x": None, "y": None, "capture": True, "layout": "columns"},
```

to:

```python
    "clipboard": {"max_items": 30, "hotkey": ["ctrl", "shift", "V"],
                  "x": None, "y": None, "capture": True, "layout": "columns",
                  "sync": False, "sync_passphrase": ""},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_config -v`
Expected: PASS — all config tests OK (the `_coerce` logic already handles the new bool/str leaves, which the wrong-types test confirms).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat(config): add clipboard sync + sync_passphrase defaults

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Windows adapter — `clip_sync_win.py` + wire `clipboard.pyw`

**Files:**
- Create: `clip_sync_win.py`
- Modify: `clipboard.pyw` (imports; `ClipboardApp.__init__`; `_poll`; add `_set_clipboard`/`_drain_sync`; `main` teardown + smoke hook).
- Test: `tests/test_clip_sync_win.py`; add a sync-on case to `tests/test_smoke_clipboard.py`.

**Interfaces:**
- Consumes: `clipkit.net.ClipSyncNode`; the toy's `ClipboardApp` (`self.store`, `self.root`, `self.absorb_seq`, `self._last_seq`, `self.cfg`).
- Produces (in `clip_sync_win.py`):
  - `sync_enabled(cfg: dict) -> bool` — True iff `cfg["clipboard"]["sync"]` is truthy AND `sync_passphrase` is non-empty.
  - `make_apply(set_clipboard, store, absorb, now=time.time) -> apply_fn(text)` — set the OS clipboard to a peer's text, advance the sequence baseline (so the poll loop swallows our own write), and record it in history.
  - `build_node(cfg, apply_fn, instance_id=None, udp_port=net.UDP_PORT, tcp_port=net.TCP_PORT) -> ClipSyncNode | None` — build (not started) a node from config, or None if sync is disabled.

The glue lives in a separate importable module so it is unit-testable with fakes (no Tk). `clipboard.pyw` only calls into it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_clip_sync_win.py`:

```python
import unittest

import clip_sync_win


class FakeStore:
    def __init__(self):
        self.added = []

    def add(self, text, ts):
        self.added.append((text, ts))


class TestSyncEnabled(unittest.TestCase):
    def _cfg(self, sync, passphrase):
        return {"clipboard": {"sync": sync, "sync_passphrase": passphrase}}

    def test_enabled_requires_flag_and_passphrase(self):
        self.assertTrue(clip_sync_win.sync_enabled(self._cfg(True, "pw")))

    def test_disabled_when_flag_off(self):
        self.assertFalse(clip_sync_win.sync_enabled(self._cfg(False, "pw")))

    def test_disabled_when_passphrase_empty(self):
        self.assertFalse(clip_sync_win.sync_enabled(self._cfg(True, "")))

    def test_missing_keys_are_safe(self):
        self.assertFalse(clip_sync_win.sync_enabled({"clipboard": {}}))
        self.assertFalse(clip_sync_win.sync_enabled({}))


class TestMakeApply(unittest.TestCase):
    def test_apply_sets_clipboard_absorbs_and_records(self):
        events = []
        store = FakeStore()
        apply = clip_sync_win.make_apply(
            set_clipboard=lambda t: events.append(("set", t)),
            store=store,
            absorb=lambda: events.append(("absorb", None)),
            now=lambda: 42.0)
        apply("from peer")
        # order matters: write the clipboard, THEN absorb the sequence bump
        self.assertEqual(events, [("set", "from peer"), ("absorb", None)])
        self.assertEqual(store.added, [("from peer", 42.0)])

    def test_apply_survives_store_failure(self):
        class Boom:
            def add(self, *a):
                raise RuntimeError("nope")
        events = []
        apply = clip_sync_win.make_apply(
            set_clipboard=lambda t: events.append("set"),
            store=Boom(),
            absorb=lambda: events.append("absorb"),
            now=lambda: 1.0)
        apply("x")                              # must not raise
        self.assertEqual(events, ["set", "absorb"])


class TestBuildNode(unittest.TestCase):
    def test_returns_none_when_disabled(self):
        cfg = {"clipboard": {"sync": False, "sync_passphrase": "pw"}}
        self.assertIsNone(clip_sync_win.build_node(cfg, lambda t: None))

    def test_builds_node_when_enabled(self):
        cfg = {"clipboard": {"sync": True, "sync_passphrase": "pw"}}
        node = clip_sync_win.build_node(cfg, lambda t: None,
                                        instance_id="X", udp_port=55210, tcp_port=55211)
        self.assertIsNotNone(node)
        self.assertEqual(node._instance_id, "X")   # did not start(); no sockets bound
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_sync_win -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clip_sync_win'`.

- [ ] **Step 3: Write minimal implementation**

Create `clip_sync_win.py`:

```python
"""Windows glue connecting the clipboard toy to the clipkit sync node. Kept as a
separate importable module (not inline in clipboard.pyw) so the wiring is
unit-testable with fakes, no Tk required."""
import time
import uuid

from clipkit import net
from clipkit.net import ClipSyncNode


def sync_enabled(cfg):
    c = cfg.get("clipboard", {})
    return bool(c.get("sync")) and bool(c.get("sync_passphrase"))


def make_apply(set_clipboard, store, absorb, now=time.time):
    """Return apply_fn(text): set the local clipboard to a peer's text WITHOUT
    re-broadcasting it. set_clipboard(text) writes the OS clipboard; absorb()
    advances the toy's clipboard-sequence baseline so its poll loop swallows this
    write (no echo); store.add records it in history like any copy."""
    def apply(text):
        set_clipboard(text)
        absorb()
        try:
            store.add(text, now())
        except Exception:
            pass
    return apply


def build_node(cfg, apply_fn, instance_id=None,
               udp_port=net.UDP_PORT, tcp_port=net.TCP_PORT):
    """Build (but do not start) a ClipSyncNode from config, or None if sync off."""
    if not sync_enabled(cfg):
        return None
    return ClipSyncNode(cfg["clipboard"]["sync_passphrase"], apply_fn,
                        instance_id or uuid.uuid4().hex,
                        udp_port=udp_port, tcp_port=tcp_port)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_sync_win -v`
Expected: PASS — 8 tests OK.

- [ ] **Step 5: Commit**

```bash
git add clip_sync_win.py tests/test_clip_sync_win.py
git commit -m "feat(clipboard): Windows sync glue (sync_enabled/make_apply/build_node)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Wire the glue into `clipboard.pyw`**

(a) Add the import near the other local imports (after `import config` on line 23):

```python
import clip_sync_win
```

(b) Add a drain-interval constant next to `CAPTURE_MS` (line 32):

```python
SYNC_DRAIN_MS = 120
```

(c) In `ClipboardApp.__init__`, replace the clipboard-capture block (currently lines 526-534):

```python
        # clipboard capture
        try:
            existing = root.clipboard_get()
            if existing and existing.strip():
                store.add(existing, time.time())
        except tk.TclError:
            pass
        self._last_seq = wkinput.clipboard_sequence()
        self._poll()
```

with:

```python
        # clipboard capture
        try:
            existing = root.clipboard_get()
            if existing and existing.strip():
                store.add(existing, time.time())
        except tk.TclError:
            pass
        self._last_seq = wkinput.clipboard_sequence()
        # clipboard sync (peer-to-peer over the LAN); None unless enabled in config
        self.node = clip_sync_win.build_node(
            cfg, clip_sync_win.make_apply(self._set_clipboard, store, self.absorb_seq))
        if self.node is not None:
            self.node.start()
            self._drain_sync()
        self._poll()
```

(d) Add two methods to `ClipboardApp` (place them right after `absorb_seq`, before `_poll`, around line 626):

```python
    def _set_clipboard(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            pass

    def _drain_sync(self):
        if self.node is None:
            return
        try:
            self.node.poll_incoming()
        finally:
            self.root.after(SYNC_DRAIN_MS, self._drain_sync)
```

(e) Replace `_poll` (currently lines 627-640) with a version that also feeds the sync node and reads the clipboard when sync is on even if history-capture is off:

```python
    def _poll(self):
        try:
            seq = wkinput.clipboard_sequence()
            if seq != self._last_seq:
                self._last_seq = seq
                text = None
                if self.cfg["clipboard"]["capture"] or self.node is not None:
                    try:
                        text = self.root.clipboard_get()
                    except tk.TclError:
                        text = None
                if text:
                    if self.cfg["clipboard"]["capture"]:
                        self.store.add(text, time.time())
                    if self.node is not None:
                        self.node.local_change(text)
        finally:
            self.root.after(CAPTURE_MS, self._poll)
```

(f) In `main()`, add the smoke hook and node teardown. Replace (lines 670-671):

```python
    cfg = config.load(CFG_PATH)
    store = clip_store.ClipStore(cfg["clipboard"]["max_items"], FAV_PATH)
```

with:

```python
    cfg = config.load(CFG_PATH)
    if os.environ.get("TOYBOX_SMOKE_SYNC"):        # exercise the sync path under smoke
        cfg["clipboard"]["sync"] = True
        cfg["clipboard"]["sync_passphrase"] = "smoke-pass"
    store = clip_store.ClipStore(cfg["clipboard"]["max_items"], FAV_PATH)
```

and replace `root.mainloop()` (line 683) with:

```python
    root.mainloop()
    if app.node is not None:
        app.node.stop()
```

- [ ] **Step 7: Write the sync-on smoke test**

Append to `tests/test_smoke_clipboard.py` (inside `class TestSmokeClipboard`):

```python
    def test_sync_enabled_launches_and_exits_clean(self):
        rc, err = run_smoke("clipboard.pyw", 1800,
                            extra_env={"TOYBOX_SMOKE_SYNC": "1"})
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.strip(), "")
```

- [ ] **Step 8: Run the smoke + glue tests**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_sync_win tests.test_smoke_clipboard -v`
Expected: PASS — the glue unit tests and all three smoke cases OK (sync-off launches clean as before; sync-on starts a node, drains, and exits clean with empty stderr).

- [ ] **Step 9: Commit**

```bash
git add clipboard.pyw tests/test_smoke_clipboard.py
git commit -m "feat(clipboard): wire LAN sync node into the clipboard toy

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 10: Restart all toys (config-save code touched)**

Per the Global Constraints, `clipboard.pyw`'s config-consuming code changed. Before any manual verification against the live `config.json`, kill and relaunch all running toys so a stale in-memory copy can't re-clobber shared config. (No manual step is needed for the automated suite; this note is for live testing.)

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -match 'hud\.pyw|clipboard\.pyw|pet\.pyw' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Then relaunch each toy you use with `Start-Process pythonw <toy>.pyw -WorkingDirectory C:/Users/Warren/Toybox`.

---

### Task 8: Mac adapter — `clipsync_mac.py`

**Files:**
- Create: `clipsync_mac.py`
- Test: `tests/test_clipsync_mac.py`

**Interfaces:**
- Consumes: `clipkit.net.ClipSyncNode`.
- Produces:
  - `read_clipboard() -> str` — `pbpaste`, "" on any failure.
  - `write_clipboard(text: str) -> None` — `pbcopy`.
  - `load_passphrase(path: str) -> str` — read `{"passphrase": ...}` JSON, "" if missing/malformed.
  - `poll_once(prev_hash, read_fn, node) -> new_hash` — read the clipboard; on change, `node.local_change(text)`; return the current hash.
  - `main()` — build the node with `write_clipboard` as apply, start it, and loop `poll_incoming` + `poll_once`.
  - Module constant `CONFIG_PATH` (`~/.toybox-clipsync.json`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_clipsync_mac.py`:

```python
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import clipsync_mac


class FakeNode:
    def __init__(self):
        self.changes = []

    def local_change(self, text):
        self.changes.append(text)


class TestClipboardIO(unittest.TestCase):
    def test_read_clipboard_returns_stdout(self):
        fake = mock.Mock(returncode=0, stdout="copied text")
        with mock.patch("clipsync_mac.subprocess.run", return_value=fake) as run:
            self.assertEqual(clipsync_mac.read_clipboard(), "copied text")
        self.assertEqual(run.call_args.args[0][0], "pbpaste")

    def test_read_clipboard_empty_on_failure(self):
        with mock.patch("clipsync_mac.subprocess.run", side_effect=OSError):
            self.assertEqual(clipsync_mac.read_clipboard(), "")

    def test_write_clipboard_pipes_to_pbcopy(self):
        with mock.patch("clipsync_mac.subprocess.run") as run:
            clipsync_mac.write_clipboard("hello mac")
        self.assertEqual(run.call_args.args[0][0], "pbcopy")
        self.assertEqual(run.call_args.kwargs["input"], b"hello mac")

    def test_write_clipboard_survives_failure(self):
        with mock.patch("clipsync_mac.subprocess.run", side_effect=OSError):
            clipsync_mac.write_clipboard("x")     # must not raise


class TestLoadPassphrase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "cfg.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_reads_passphrase(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"passphrase": "secret"}, f)
        self.assertEqual(clipsync_mac.load_passphrase(self.path), "secret")

    def test_missing_file_returns_empty(self):
        self.assertEqual(clipsync_mac.load_passphrase(self.path + ".nope"), "")

    def test_malformed_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(clipsync_mac.load_passphrase(self.path), "")

    def test_non_string_passphrase_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"passphrase": 123}, f)
        self.assertEqual(clipsync_mac.load_passphrase(self.path), "")


class TestPollOnce(unittest.TestCase):
    def test_change_triggers_local_change(self):
        node = FakeNode()
        h1 = clipsync_mac.poll_once(None, lambda: "first", node)
        self.assertEqual(node.changes, ["first"])
        h2 = clipsync_mac.poll_once(h1, lambda: "first", node)   # unchanged
        self.assertEqual(node.changes, ["first"])                # not re-sent
        clipsync_mac.poll_once(h2, lambda: "second", node)       # changed
        self.assertEqual(node.changes, ["first", "second"])

    def test_empty_clipboard_ignored(self):
        node = FakeNode()
        clipsync_mac.poll_once(None, lambda: "", node)
        self.assertEqual(node.changes, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clipsync_mac -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clipsync_mac'`.

- [ ] **Step 3: Write minimal implementation**

Create `clipsync_mac.py`:

```python
"""Standalone macOS clipboard-sync agent. Mirrors the Windows clipboard toy's sync
over the same clipkit core, but reads/writes the clipboard via pbpaste/pbcopy and
runs headless (no Tk). Configure by placing {"passphrase": "..."} in
~/.toybox-clipsync.json with the SAME passphrase as the Windows side, then run:
    python3 clipsync_mac.py
Pure Python 3.12 standard library only."""
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

from clipkit.net import ClipSyncNode

CONFIG_PATH = os.path.expanduser("~/.toybox-clipsync.json")
_POLL_S = 0.3


def read_clipboard():
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        if result.returncode != 0:
            return ""
        return result.stdout
    except OSError:
        return ""


def write_clipboard(text):
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"))
    except OSError:
        pass


def load_passphrase(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        passphrase = data.get("passphrase")
        return passphrase if isinstance(passphrase, str) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def poll_once(prev_hash, read_fn, node):
    """Read the clipboard; if it changed, publish it. Return the current hash."""
    text = read_fn()
    if not text:
        return prev_hash
    h = _hash(text)
    if h != prev_hash:
        node.local_change(text)
    return h


def main():
    passphrase = load_passphrase(CONFIG_PATH)
    if not passphrase:
        print("clipsync: no passphrase in %s; not syncing." % CONFIG_PATH,
              file=sys.stderr)
        return
    node = ClipSyncNode(passphrase, write_clipboard, uuid.uuid4().hex)
    node.start()
    prev = _hash(read_clipboard())
    try:
        while True:
            node.poll_incoming()
            prev = poll_once(prev, read_clipboard, node)
            time.sleep(_POLL_S)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clipsync_mac -v`
Expected: PASS — 10 tests OK. (`pbpaste`/`pbcopy` are never actually invoked; `subprocess.run` is mocked, so these run on the Windows dev machine.)

- [ ] **Step 5: Commit**

```bash
git add clipsync_mac.py tests/test_clipsync_mac.py
git commit -m "feat(clipsync): standalone macOS clipboard-sync agent

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -v`
Expected: PASS — the entire pre-existing suite plus all new clip-sync tests OK, no failures, no errors, clean stderr.

- [ ] **Step 2: Confirm no stray artifacts**

Run: `git status --short`
Expected: clean working tree (everything committed across Tasks 1-8); no `config.json`, `favorites.json`, or `__pycache__` staged.

---

## Self-Review

**1. Spec coverage** (each spec section → task):
- `clipkit/protocol.py` (crypto) → Task 1. ✅
- `clipkit/discovery.py` (beacons + PeerTable) → Task 2. ✅
- `clipkit/engine.py` (state machine + loop guard) → Task 3. ✅
- `clipkit/net.py` (TCP payloads + UDP discovery threads) → Tasks 4 & 5. ✅
- Windows adapter (poll-loop wiring, `absorb_seq` seam, queue drain on `root.after`, history store, threads start/stop) → Task 7. ✅
- Mac adapter (pbpaste/pbcopy, config file, poll loop) → Task 8. ✅
- Config schema (`sync` + `sync_passphrase` in the `clipboard` section) → Task 6. ✅
- Error handling (peer down swallowed, bad HMAC dropped, oversized skipped, clipboard failures caught) → covered across protocol/engine/net/adapters and tested. ✅
- Testing strategy (protocol, discovery, engine, net loopback, Windows smoke, Mac adapter) → Tasks 1-8 tests + Task 9 full-suite. ✅
- Fixed ports 50505/50506 → Task 4 constants; Global Constraints. ✅
- Out-of-scope items (images, internet, >2-peer conflict handling, persistent connections, Mac GUI) → not built. ✅
- Deferred (panel toggle, launchd plist) → not built; noted in spec. ✅

**2. Placeholder scan:** no TBD/TODO/"handle edge cases"/"similar to Task N"; every code and test step contains complete, runnable code. ✅

**3. Type consistency:** function names and signatures are identical across producer and consumer tasks — `derive_keys`→`(bytes,bytes)`; `seal(ke,km,text)`/`unseal(ke,km,frame)` consumed by `net.py`'s Engine lambdas; `encode_beacon`/`parse_beacon`/`PeerTable.seen(id,addr,port,now)`/`live_peers(now)` consumed by `_handle_beacon`/`_tx_loop`; `Engine(seal_fn,open_fn,send_fn,apply_fn,max_bytes)` matches Task 3 and the Task 4 construction; `ClipSyncNode(passphrase,apply_fn,instance_id,udp_port,tcp_port,max_bytes)` matches Tasks 4/5/7/8; `sync_enabled`/`make_apply`/`build_node` match Task 7's test and the `clipboard.pyw` wiring. The spec's `open()` is consistently realized as `unseal()` (noted up front). ✅
