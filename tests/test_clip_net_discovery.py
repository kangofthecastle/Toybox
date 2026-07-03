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
