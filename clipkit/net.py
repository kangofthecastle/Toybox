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
        # connect timeout stays under stop()'s 2s per-thread join budget, so a
        # send to a dead peer that is in flight when stop() is called can't
        # outlive the join (a LAN peer connects in milliseconds regardless).
        try:
            with socket.create_connection((addr, port), timeout=1.5) as c:
                c.sendall(struct.pack(">I", len(frame)) + frame)
        except OSError:
            pass
