# tests/test_glow.py
import unittest
import petkit.glow as glow


class TestGlowCoverage(unittest.TestCase):
    def test_center_full_level_is_dense(self):
        self.assertEqual(glow.glow_coverage(0.0, 70.0, 1.0), 1.0)

    def test_rim_is_zero(self):
        self.assertEqual(glow.glow_coverage(70.0, 70.0, 1.0), 0.0)

    def test_beyond_rim_is_zero(self):
        self.assertEqual(glow.glow_coverage(200.0, 70.0, 1.0), 0.0)

    def test_zero_level_is_zero_everywhere(self):
        self.assertEqual(glow.glow_coverage(0.0, 70.0, 0.0), 0.0)

    def test_monotonic_falloff(self):
        near = glow.glow_coverage(10.0, 70.0, 1.0)
        far = glow.glow_coverage(50.0, 70.0, 1.0)
        self.assertGreaterEqual(near, far)

    def test_coverage_in_unit_range(self):
        for d in (0.0, 5.0, 30.0, 69.0, 70.0, 100.0):
            c = glow.glow_coverage(d, 70.0, 0.7)
            self.assertGreaterEqual(c, 0.0)
            self.assertLessEqual(c, 1.0)


class TestDither(unittest.TestCase):
    def test_full_coverage_lights_every_cell(self):
        self.assertTrue(all(glow._lit(x, y, 1.0) for x in range(4) for y in range(4)))

    def test_zero_coverage_lights_nothing(self):
        self.assertFalse(any(glow._lit(x, y, 0.0) for x in range(4) for y in range(4)))

    def test_partial_coverage_is_a_proper_subset(self):
        # Ordered dithering is stable: every cell lit at a lower coverage stays
        # lit at a higher one (so the aura grows smoothly as the music swells).
        lo = {(x, y) for x in range(4) for y in range(4) if glow._lit(x, y, 0.3)}
        hi = {(x, y) for x in range(4) for y in range(4) if glow._lit(x, y, 0.6)}
        self.assertTrue(lo.issubset(hi))
        self.assertGreater(len(hi), len(lo))


if __name__ == "__main__":
    unittest.main()
