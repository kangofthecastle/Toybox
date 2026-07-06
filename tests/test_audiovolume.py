import os
import unittest
import unittest.mock as mock

import winkit.audiovolume as av


class TestClamp01(unittest.TestCase):
    def test_mid(self):
        self.assertAlmostEqual(av.clamp01(0.4), 0.4)

    def test_below_zero(self):
        self.assertEqual(av.clamp01(-3.0), 0.0)

    def test_above_one(self):
        self.assertEqual(av.clamp01(5.0), 1.0)

    def test_bad_input(self):
        self.assertEqual(av.clamp01(None), 0.0)


class TestLevelFromX(unittest.TestCase):
    def test_left_edge_is_zero(self):
        self.assertEqual(av.level_from_x(10, 10, 210), 0.0)

    def test_right_edge_is_one(self):
        self.assertEqual(av.level_from_x(210, 10, 210), 1.0)

    def test_quarter(self):
        self.assertAlmostEqual(av.level_from_x(60, 10, 210), 0.25)

    def test_left_of_track_clamps_zero(self):
        self.assertEqual(av.level_from_x(-99, 10, 210), 0.0)

    def test_right_of_track_clamps_one(self):
        self.assertEqual(av.level_from_x(9999, 10, 210), 1.0)

    def test_degenerate_track_is_zero(self):
        self.assertEqual(av.level_from_x(50, 10, 10), 0.0)

    def test_bad_input(self):
        self.assertEqual(av.level_from_x(None, None, None), 0.0)


class TestXFromLevel(unittest.TestCase):
    def test_zero_at_left(self):
        self.assertEqual(av.x_from_level(0.0, 10, 210), 10)

    def test_one_at_right(self):
        self.assertEqual(av.x_from_level(1.0, 10, 210), 210)

    def test_half_midpoint(self):
        self.assertEqual(av.x_from_level(0.5, 10, 210), 110)

    def test_clamps_over_one(self):
        self.assertEqual(av.x_from_level(2.0, 10, 210), 210)


class TestFormatPct(unittest.TestCase):
    def test_none(self):
        self.assertEqual(av.format_pct(None), "")

    def test_rounds(self):
        self.assertEqual(av.format_pct(0.633), "63%")

    def test_full(self):
        self.assertEqual(av.format_pct(1.0), "100%")

    def test_zero(self):
        self.assertEqual(av.format_pct(0.0), "0%")


class TestStepLevel(unittest.TestCase):
    def test_up(self):
        self.assertAlmostEqual(av.step_level(0.5, 0.02), 0.52)

    def test_down(self):
        self.assertAlmostEqual(av.step_level(0.5, -0.02), 0.48)

    def test_clamps_high(self):
        self.assertEqual(av.step_level(0.99, 0.02), 1.0)

    def test_clamps_low(self):
        self.assertEqual(av.step_level(0.01, -0.05), 0.0)


if __name__ == "__main__":
    unittest.main()
