# tests/test_glow.py
import unittest
import petkit.glow as glow

HUE = (255, 120, 168)
KEY = (1, 1, 1)


class TestGlowPixel(unittest.TestCase):
    def test_center_full_level_is_hue(self):
        self.assertEqual(glow.glow_pixel(0.0, 70.0, HUE, KEY, 1.0), HUE)

    def test_rim_is_key_color(self):
        self.assertEqual(glow.glow_pixel(70.0, 70.0, HUE, KEY, 1.0), KEY)

    def test_beyond_rim_is_key_color(self):
        self.assertEqual(glow.glow_pixel(200.0, 70.0, HUE, KEY, 1.0), KEY)

    def test_zero_level_is_key_everywhere(self):
        self.assertEqual(glow.glow_pixel(0.0, 70.0, HUE, KEY, 0.0), KEY)

    def test_monotonic_falloff(self):
        near = glow.glow_pixel(10.0, 70.0, HUE, KEY, 1.0)[0]
        far = glow.glow_pixel(50.0, 70.0, HUE, KEY, 1.0)[0]
        self.assertGreaterEqual(near, far)


if __name__ == "__main__":
    unittest.main()
