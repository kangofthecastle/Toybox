import unittest

import hud


class TestMediaLayout(unittest.TestCase):
    def test_audio_off_keeps_transport_centered(self):
        lay = hud.media_layout(220, audio_on=False)
        self.assertEqual(lay["play"], 110)
        self.assertEqual(lay["prev"], 110 - hud.MEDIA_GAP)
        self.assertEqual(lay["next"], 110 + hud.MEDIA_GAP)
        self.assertIsNone(lay["speaker"])
        self.assertIsNone(lay["headphone"])

    def test_audio_on_group_is_centered_narrow(self):
        w = 220
        lay = hud.media_layout(w, audio_on=True)
        mid = (lay["prev"] + lay["headphone"]) / 2
        self.assertAlmostEqual(mid, w // 2, delta=1)

    def test_audio_on_group_is_centered_wide(self):
        w = hud.WIDTH_WIDE
        lay = hud.media_layout(w, audio_on=True)
        mid = (lay["prev"] + lay["headphone"]) / 2
        self.assertAlmostEqual(mid, w // 2, delta=1)

    def test_ordering_and_spacing(self):
        lay = hud.media_layout(220, audio_on=True)
        xs = [lay["prev"], lay["play"], lay["next"], lay["speaker"], lay["headphone"]]
        self.assertEqual(xs, sorted(xs))                       # left-to-right
        self.assertEqual(lay["play"] - lay["prev"], hud.MEDIA_GAP)
        self.assertEqual(lay["next"] - lay["play"], hud.MEDIA_GAP)
        self.assertEqual(lay["speaker"] - lay["next"], hud.AUDIO_GAP)
        self.assertEqual(lay["headphone"] - lay["speaker"], hud.AUDIO_SP)

    def test_cluster_fits_within_narrow_width(self):
        lay = hud.media_layout(220, audio_on=True)
        left = lay["prev"] - hud.MEDIA_HALF
        right = lay["headphone"] + hud.AUDIO_HALF
        self.assertGreaterEqual(left, 8)      # within ~PAD of the left edge
        self.assertLessEqual(right, 212)      # within ~PAD of the right edge


if __name__ == "__main__":
    unittest.main()
