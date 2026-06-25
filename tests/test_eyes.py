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

    def test_idle_anchor_table_shape(self):
        table = eyes.EYES["idle"]
        self.assertEqual(len(table), 10)
        for left, right in table:
            for (x, y) in (left, right):
                self.assertTrue(0 <= x < 32 and 0 <= y < 32)
            # Anchors must sit on the eye clusters, not the head outline.
            # The left eye lives around col 8, the right around col 13, and both
            # eyes sit on rows 13-14; the old outline drift (right x=18) fails here.
            (lx, ly), (rx, ry) = left, right
            self.assertTrue(6 <= lx <= 10, f"left eye x={lx} off the eye")
            self.assertTrue(11 <= rx <= 15, f"right eye x={rx} off the eye")
            self.assertTrue(11 <= ly <= 15, f"left eye y={ly} off the eye")
            self.assertTrue(11 <= ry <= 15, f"right eye y={ry} off the eye")


if __name__ == "__main__":
    unittest.main()
