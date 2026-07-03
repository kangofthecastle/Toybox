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
