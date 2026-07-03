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
