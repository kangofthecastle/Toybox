# Shared Clipboard (LAN peer-to-peer) — Design

**Date:** 2026-07-03
**Status:** Approved (design phase)
**Topic:** Sync the text clipboard between the Windows Toybox machine and a Mac over the local network.

## Goal

Copy text on either the Windows machine or the Mac and, within about one second,
have it appear on the other machine's clipboard. Same LAN, peer-to-peer, no cloud,
no third-party services. The Windows side folds into the existing clipboard toy;
the Mac side is a standalone background daemon.

## Global Constraints

These bind every component and every task in the implementation plan.

- **Pure Python 3.12 standard library only. No pip, no third-party packages, ever.**
- **Test runner:** `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path>` from the repo root. (A bare `python` is broken on this machine.)
- **Commit trailer, exactly:** `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **TLS / default urllib security is never weakened** (not directly relevant here — this feature uses raw sockets, not urllib — but the no-weakening rule stands).
- **`config.json` is gitignored and holds live secrets** (the GitHub PAT, and now the sync passphrase). Never echo, log, or commit it. All writes go through the scoped `config.update(path, partial)`.
- **After changing any config-save code, restart ALL toys** (hud / clipboard / pet) so a stale in-memory copy can't re-clobber the shared `config.json`.
- **Windows clipboard I/O is via Tkinter** (`root.clipboard_get()` / `clipboard_clear()` / `clipboard_append()`), not raw Win32. Tk must only be touched from the main thread.
- **Ports are fixed code constants** (UDP discovery `50505`, TCP payload `50506`); not configurable (YAGNI).
- **Text only.** Images, files, and rich clipboard formats are out of scope.

## Overview & Architecture

Two symmetric **agents**, one per machine. Each agent both *publishes* its local
clipboard changes to peers and *applies* clipboard changes received from peers.

All non-trivial logic lives in a new pure-stdlib, platform-agnostic package,
`clipkit/`, which performs **no clipboard and no network side effects** and is
therefore fully unit-testable without a network or a real clipboard. Two thin
**platform adapters** (Windows, Mac) perform the actual I/O and drive the core.

```
        Windows  (clipboard.pyw)                     Mac  (clipsync_mac.py)
   Tk poll loop ──local change──┐             ┌──local change── pbpaste poll
   Tk clipboard ◀──apply remote─┤   clipkit   ├─apply remote──▶ pbcopy
                                 │ (pure core) │
        net.py (threads) ◀───────┘             └───────▶ net.py (threads)
                          UDP discovery beacons  +  TCP sealed payloads
```

Design principle: keep the pure decision logic (`protocol`, `discovery`,
`engine`) free of sockets and clipboards so it can be tested exhaustively; isolate
all side effects in `net.py` (sockets) and the platform adapters (clipboards).

## Components

### `clipkit/protocol.py` — wire frame + crypto

**Responsibility:** turn a plaintext string into an encrypted, authenticated byte
frame and back, using only stdlib primitives.

**Interface:**
- `derive_keys(passphrase: str) -> (key_enc: bytes, key_mac: bytes)`
- `seal(key_enc, key_mac, text: str) -> bytes`
- `open(key_enc, key_mac, frame: bytes) -> str | None` — returns `None` on any auth
  failure, tamper, or malformed input (never raises on bad input).

**Construction (encrypt-then-MAC, all stdlib):**
- **Key derivation, once at startup:**
  `master = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), b"toybox-clipsync-v1", 200_000, dklen=64)`,
  then `key_enc = master[:32]`, `key_mac = master[32:]`. The salt is a fixed
  application label (its job is domain separation, not secrecy), so both machines
  derive identical keys from the shared passphrase and we pay the PBKDF2 cost only
  once per process, not per message.
- **Per message:** `nonce = os.urandom(16)`. Keystream in counter mode:
  block *i* = `hmac.new(key_enc, nonce + i.to_bytes(8, "big"), "sha256").digest()`,
  concatenated and truncated to the plaintext length, XORed with the UTF-8
  plaintext to produce the ciphertext.
- **Authentication:** `tag = hmac.new(key_mac, nonce + ciphertext, "sha256").digest()`.
- **Frame layout:** `MAGIC(4) ‖ nonce(16) ‖ tag(32) ‖ ciphertext(N)`.
- **open():** length/magic check → recompute tag over `nonce + ciphertext` →
  `hmac.compare_digest` (constant time); on mismatch return `None`; otherwise
  decrypt (same keystream XOR) and UTF-8 decode. Any exception → `None`.

**Rationale:** this is a standard encrypt-then-MAC with an HMAC-SHA256 CTR
keystream. It is "rolling our own" only in the sense of composing well-understood
stdlib primitives; the pure-TLS alternative would require X.509 certificate
generation, which the stdlib cannot do without shipping a cert or shelling out to
openssl. For a personal LAN clipboard this construction is appropriate, and it is
the most heavily tested unit in the feature.

**Dependencies:** `hashlib`, `hmac`, `os` (stdlib only).

### `clipkit/discovery.py` — peer discovery

**Responsibility:** let the two agents find each other on the LAN with no
configured IP addresses, and keep an up-to-date set of live peers.

**Interface:**
- `encode_beacon(key_mac, instance_id: str, tcp_port: int) -> bytes`
- `parse_beacon(key_mac, data: bytes) -> (instance_id, tcp_port) | None` — rejects
  any beacon whose HMAC does not verify.
- `class PeerTable`: `seen(instance_id, addr, tcp_port, now)`, `live_peers(now) -> list[(addr, tcp_port)]`,
  with TTL-based expiry.

**Behavior:** each agent periodically UDP-broadcasts an authenticated beacon
carrying `{instance_id, tcp_port}` — **never** clipboard content. Beacons are
HMAC-authenticated with the same passphrase-derived `key_mac`, so an agent
discovers only *its own* peers and a foreign/stray beacon cannot point it at a
rogue endpoint. An agent filters out beacons carrying its own `instance_id` (so it
never peers with itself). Peers not heard from within the TTL are expired from the
table.

**Dependencies:** `hmac`, `time` (pure logic); actual UDP sockets live in `net.py`.

### `clipkit/engine.py` — sync state machine

**Responsibility:** decide what to send and what to apply, and prevent echo loops.

**Interface (constructed with injected callbacks — no direct I/O):**
- `Engine(seal_fn, open_fn, send_fn, apply_fn, max_bytes=1_000_000)`
- `on_local_change(text: str)` — if `text` differs from the last value we sent or
  applied, and it is within `max_bytes`, seal it and hand the frame to `send_fn`
  (which delivers to every live peer). Records the value's hash.
- `on_remote_frame(frame: bytes)` — `open_fn` the frame; if it verifies and the
  text differs from the last value we sent or applied, call `apply_fn(text)` to set
  the local clipboard, and record the hash so the resulting local-change event does
  not echo back.

**Loop guard:** a single `_last_value_hash` records the last value the engine
either sent or applied. A local change equal to it (the echo of our own apply) is
suppressed; a remote value equal to it (the echo of our own send) is suppressed.
This is what prevents the two machines from ping-ponging a value forever.

**Dependencies:** `hashlib` for the value hash; everything else injected. No
sockets, no clipboard — fully unit-testable with fakes.

### `clipkit/net.py` — socket plumbing (the only networked module)

**Responsibility:** run the UDP discovery loop and the TCP payload server/client on
background daemon threads, driving `discovery` and `engine`.

**Behavior:**
- UDP: bind the discovery port, broadcast our beacon on an interval, and feed
  received beacons to the `PeerTable`.
- TCP: a small server accepts a connection, reads one length-prefixed frame, and
  hands it to `engine.on_remote_frame` (marshalled to the adapter's main thread —
  see adapters). Sending: on a local change, connect to each live peer, write one
  length-prefixed sealed frame, close.
- All network errors (refused, timeout, reset) are swallowed; a failed send is
  retried on the next change, and discovery re-freshens the peer set.

**Dependencies:** `socket`, `threading`, `struct` (length prefix), `queue`.
Lightly tested via loopback; the pure modules carry the correctness weight.

### Windows adapter — modifications to `clipboard.pyw`

Reuses seams that already exist in the toy:
- The existing `_poll()` already detects a new local copy via
  `wkinput.clipboard_sequence()`. On a genuine change, in addition to
  `store.add(...)`, call `engine.on_local_change(text)` (only when sync is enabled).
- **Applying a remote value:** `root.clipboard_clear()` + `root.clipboard_append(text)`,
  then call the existing **`absorb_seq()`** so the poll loop swallows our own write
  instead of re-broadcasting it. This is the loop-prevention seam already present in
  the code. The applied text is also passed to `store.add(...)` so synced items
  appear in the history panel like any copy.
- **Threading:** `net.py` runs on background daemon threads. Received frames cross
  to the Tk main thread through a `queue.Queue` drained by `root.after(...)` — the
  same worker→queue→main-thread pattern used by feedkit's manager. Tk is never
  touched off the main thread.
- **Lifecycle:** the discovery/TCP threads start when sync is enabled and are torn
  down (bounded) on `close()`.

### Mac adapter — `clipsync_mac.py` (standalone entry, no Tk)

- **Read:** `subprocess.run(["pbpaste"], capture_output=True)`, polled about every
  300 ms, hashed to detect a change → `engine.on_local_change(text)`.
- **Write:** `subprocess.run(["pbcopy"], input=text.encode())`.
- Builds the same `clipkit` core (protocol + discovery + engine + net) with a
  pbpaste/pbcopy adapter and runs the poll loop. Runs as a plain background
  process. An optional launchd/login-item plist is documented, not required.

## Data Flow (example: copy on Mac → appears on Windows)

1. User copies text on the Mac. The pbpaste poll loop sees the change →
   `engine.on_local_change(text)`.
2. The engine records the hash, `seal`s the frame with the passphrase keys, and
   `send_fn` delivers a TCP frame to each live peer (the Windows box, discovered via
   UDP beacons).
3. The Windows TCP server thread receives the frame and puts it on the queue.
4. The Windows Tk `root.after` drain pops it → `engine.on_remote_frame` → `open`
   verifies → new text → adapter sets the Tk clipboard, calls `absorb_seq()`, records
   the last-applied hash, and adds it to the history store.
5. The Windows `_poll()` sees the sequence number bumped, but `absorb_seq()` already
   advanced `_last_seq`, so nothing is re-broadcast. No echo.

## Configuration

**Windows** — new keys in the existing `clipboard` section of `config.json`,
written via scoped `config.update` so nothing clobbers other toys:

```jsonc
"clipboard": {
    // ...existing keys...
    "sync": false,          // master switch, OFF by default — zero behavior change until opted in
    "sync_passphrase": ""   // shared secret; empty ⇒ sync stays off even if "sync" is true
}
```

The passphrase sits in `config.json` in plaintext — the same trust model as the
GitHub PAT already stored there (gitignored, local-only). Sync only activates when
`sync` is true **and** `sync_passphrase` is non-empty.

**Mac** — a small `~/.toybox-clipsync.json` `{"passphrase": "..."}` (or a
`--passphrase` flag). Must hold the same secret as the Windows side.

**Enabling on Windows is via editing `config.json`** (set `sync: true` + passphrase),
mirroring how the PAT is configured. A panel on/off toggle next to the existing
"capture" toggle is a deliberately deferred nicety (see Deferred, below).

## Error Handling

Never crash the toy. Specifically:
- Peer down / connection refused / timeout → swallow; retry on the next change.
  Discovery re-freshens the peer set, so a peer that went away is expired.
- Bad HMAC (wrong passphrase, foreign traffic) or malformed frame → `open`/`parse`
  return `None`; the frame is dropped silently.
- Clipboard read/write failure (`tk.TclError`, `pbpaste`/`pbcopy` nonzero exit) →
  caught and skipped.
- Payload larger than `max_bytes` (~1 MB) → not synced (prevents flooding the LAN
  with a giant copy).
- Non-text clipboard content (images, files) → ignored.

## Testing Strategy

Pure-stdlib `unittest`, mirroring the existing `tests/` layout.

- **`tests/test_clip_protocol.py`** — seal/open round-trip; wrong passphrase →
  `None`; tampered ciphertext → `None`; tampered tag → `None`; truncated/short frame
  → `None`; bad magic → `None`; a fresh nonce each call (two seals of the same text
  differ).
- **`tests/test_clip_discovery.py`** — beacon encode/parse round-trip; beacon with
  bad HMAC rejected; self-beacon filtered; `PeerTable` expiry after TTL; multiple
  peers tracked.
- **`tests/test_clip_engine.py`** — with a fake adapter (records `apply` calls) and a
  fake sender (records sends): a local change sends a sealed frame; a valid remote
  frame applies exactly once; **an applied remote value is never re-broadcast**
  (loop guard); a duplicate local value is not resent; an oversized value is skipped;
  a bad frame is ignored.
- **Windows smoke** — extend the existing clipboard smoke test (fake engine, no real
  network) to verify the poll loop calls `on_local_change` and the queue drain routes
  a frame to `on_remote_frame` and applies via the Tk seam.
- **Mac adapter** — unit-test the pbpaste/pbcopy wrappers with `subprocess`
  monkeypatched (no real `pbcopy` on the Windows dev/test machine); the
  change-detection loop tested with a fake reader/clock.
- **`net.py`** — a light loopback test (two engines on `127.0.0.1`) exercising a real
  send/receive round-trip; kept minimal since the pure modules carry correctness.

## File / Package Layout

New package (matches the `winkit` / `petkit` / `feedkit` convention):

- `clipkit/__init__.py`
- `clipkit/protocol.py` — key derivation, `seal`, `open`
- `clipkit/discovery.py` — beacon encode/parse, `PeerTable`
- `clipkit/engine.py` — sync state machine + loop guard
- `clipkit/net.py` — UDP/TCP plumbing on daemon threads

Modified:
- `clipboard.pyw` — wire the engine to the poll loop, drain the queue on
  `root.after`, apply remote values through the `absorb_seq()` seam, start/stop the
  net threads with sync.
- `config.py` — add `sync` and `sync_passphrase` to the `clipboard` DEFAULTS.

New standalone:
- `clipsync_mac.py` — the Mac agent (pbpaste/pbcopy adapter + clipkit core).

Tests: `tests/test_clip_protocol.py`, `tests/test_clip_discovery.py`,
`tests/test_clip_engine.py`, a Windows smoke extension, a Mac-adapter test, and a
`net.py` loopback test.

## Out of Scope (YAGNI)

- Images, files, and rich clipboard formats — text only.
- Internet / cross-network operation (the shared-cloud-file transport that was the
  alternative approach). This feature is same-LAN only.
- More than two peers: the broadcast-to-all-live-peers design supports it and gives
  last-writer-wins for free, but multi-peer conflict resolution is not a goal.
- Persistent connections, delivery ACKs, compression.
- A Mac GUI.

## Deferred (easy follow-ups, intentionally not in v1)

- A panel on/off toggle for sync on the Windows side, next to the existing "capture"
  toggle. Cheap to add; left out to keep v1 scope tight (enable via `config.json`).
- A launchd plist / login item to auto-start the Mac agent (documented, not shipped).
