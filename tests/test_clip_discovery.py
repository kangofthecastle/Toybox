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

    def test_long_unicode_id_truncates_but_still_parses(self):
        # a >255-byte multibyte id must be truncated WITHOUT splitting a char,
        # so the beacon stays valid UTF-8 and authenticates
        beacon = discovery.encode_beacon(self.km, "é" * 200, 50506)   # 400 bytes
        parsed = discovery.parse_beacon(self.km, beacon)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[1], 50506)


class TestPeerTable(unittest.TestCase):
    def test_seen_then_live(self):
        pt = discovery.PeerTable(ttl=10.0)
        pt.seen("A", "10.0.0.2", 50506, now=100.0)
        self.assertEqual(pt.live_peers(now=105.0), [("10.0.0.2", 50506)])

    def test_expiry_after_ttl(self):
        pt = discovery.PeerTable(ttl=10.0)
        pt.seen("A", "10.0.0.2", 50506, now=100.0)
        self.assertEqual(pt.live_peers(now=111.0), [])   # 11s > 10s ttl

    def test_exact_ttl_boundary_is_live(self):
        pt = discovery.PeerTable(ttl=10.0)
        pt.seen("A", "10.0.0.2", 50506, now=100.0)
        self.assertEqual(pt.live_peers(now=110.0), [("10.0.0.2", 50506)])  # exactly ttl => live

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

    def test_concurrent_seen_and_live_peers_is_safe(self):
        import sys
        import threading
        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-9)   # maximise thread interleaving to expose the race
        try:
            pt = discovery.PeerTable(ttl=1e9)
            errors = []
            def writer():
                try:
                    for i in range(10000):
                        pt.seen("id%d" % i, "10.0.0.2", 50506, now=float(i))
                except Exception as e:  # pragma: no cover - failure path
                    errors.append(e)
            def reader():
                try:
                    for _ in range(10000):
                        pt.live_peers(now=1e9)
                except Exception as e:
                    errors.append(e)
            threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
            for t in threads: t.start()
            for t in threads: t.join()
        finally:
            sys.setswitchinterval(old_interval)
        self.assertEqual(errors, [])
