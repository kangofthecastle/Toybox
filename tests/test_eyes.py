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


class TestPupilDotOffset(unittest.TestCase):
    # base=8 (2x2 block at zoom 4), dot=4 (1px catchlight), step=2 (snap grid).
    def test_centered_cursor_centers_dot(self):
        # Cursor on the eye center -> no deflection -> dot centered:
        # top-left = (base - dot) / 2 = 2, which is already on the step-2 grid.
        self.assertEqual(eyes.pupil_dot_offset(0.0, 0.0, 8, 4, 2), (2, 2))

    def test_far_right_pins_to_right_edge(self):
        ldx, ldy = eyes.pupil_dot_offset(10_000.0, 0.0, 8, 4, 2)
        self.assertEqual(ldx, 8 - 4)   # clamped + snapped to the right edge
        self.assertEqual(ldy, 2)       # vertically still centered

    def test_snaps_to_step_grid(self):
        for gx in (-200.0, -40.0, -5.0, 5.0, 40.0, 200.0):
            for gy in (-200.0, -5.0, 5.0, 200.0):
                ldx, ldy = eyes.pupil_dot_offset(gx, gy, 8, 4, 2)
                self.assertEqual(ldx % 2, 0, f"ldx={ldx} off grid")
                self.assertEqual(ldy % 2, 0, f"ldy={ldy} off grid")

    def test_stays_inside_block(self):
        for gx in (-9999.0, 0.0, 9999.0):
            for gy in (-9999.0, 0.0, 9999.0):
                ldx, ldy = eyes.pupil_dot_offset(gx, gy, 8, 4, 2)
                self.assertGreaterEqual(ldx, 0)
                self.assertLessEqual(ldx, 8 - 4)
                self.assertGreaterEqual(ldy, 0)
                self.assertLessEqual(ldy, 8 - 4)

    def test_deterministic_identical_inputs(self):
        # The both-eyes-match property: same gaze in -> same dot out.
        a = eyes.pupil_dot_offset(123.0, -45.0, 8, 4, 2)
        b = eyes.pupil_dot_offset(123.0, -45.0, 8, 4, 2)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
