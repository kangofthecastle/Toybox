# tests/test_eyes.py
import math
import unittest
import petkit.eyes as eyes


class TestPupilOffset(unittest.TestCase):
    def test_centered_cursor_no_offset(self):
        self.assertEqual(eyes.pupil_offset(0.0, 0.0), (0.0, 0.0))

    def test_points_toward_cursor(self):
        ox, oy = eyes.pupil_offset(100.0, 0.0)   # far to the right
        self.assertGreater(ox, 0.0)
        self.assertAlmostEqual(oy, 0.0, places=6)

    def test_clamped_to_max_off(self):
        ox, oy = eyes.pupil_offset(10_000.0, 10_000.0, max_off=1.4)
        self.assertLessEqual(math.hypot(ox, oy), 1.4 + 1e-6)

    def test_grows_with_distance_until_reach(self):
        near = math.hypot(*eyes.pupil_offset(10.0, 0.0, reach=55.0, max_off=1.4))
        far = math.hypot(*eyes.pupil_offset(55.0, 0.0, reach=55.0, max_off=1.4))
        self.assertGreater(far, near)

    def test_idle_eye_table_shape(self):
        # Each entry is None (eyes closed -> draw nothing) or a 2-tuple of
        # (x,y) 2x2 top-left corners with valid sprite coords and left x < right x.
        table = eyes.EYES["idle"]
        self.assertEqual(len(table), 10)
        for entry in table:
            if entry is None:
                continue
            self.assertEqual(len(entry), 2)
            (lx, ly), (rx, ry) = entry
            for (x, y) in entry:
                self.assertTrue(0 <= x < 32, f"x={x} out of sprite range")
                self.assertTrue(0 <= y < 32, f"y={y} out of sprite range")
            self.assertLess(lx, rx, f"left x={lx} must be left of right x={rx}")


if __name__ == "__main__":
    unittest.main()
