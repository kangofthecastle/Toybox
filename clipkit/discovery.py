"""LAN peer discovery for clipboard sync. Agents UDP-broadcast a small,
HMAC-authenticated beacon carrying only their instance id and TCP payload port
(never clipboard content); each agent tracks the peers it hears from and expires
stale ones. Authenticating with the shared passphrase's key_mac means an agent
discovers only its own peers, and a stray beacon cannot point it at a rogue
endpoint."""
import hmac
import struct
import threading

_BEACON_MAGIC = b"TBCB"               # Toy Box Clip Beacon
_TAG_LEN = 32
_MIN_LEN = len(_BEACON_MAGIC) + 2 + 1 + _TAG_LEN   # magic + port + id_len + tag


def encode_beacon(key_mac, instance_id, tcp_port):
    """body = magic(4) | tcp_port(2, big-endian) | id_len(1) | instance_id;
    frame = body | HMAC-SHA256(body)."""
    # cap at 255 bytes without splitting a multibyte char (decode/ignore drops any
    # partial trailing char, so the id always stays valid UTF-8 and re-parseable)
    idb = instance_id.encode("utf-8")[:255].decode("utf-8", "ignore").encode("utf-8")
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
        self._lock = threading.Lock()

    def seen(self, instance_id, addr, tcp_port, now):
        with self._lock:
            self._peers[instance_id] = (addr, tcp_port, now)

    def live_peers(self, now):
        with self._lock:
            return [(addr, port) for (addr, port, ts) in self._peers.values()
                    if now - ts <= self.ttl]

    def expire(self, now):
        with self._lock:
            self._peers = {k: v for k, v in self._peers.items()
                           if now - v[2] <= self.ttl}
