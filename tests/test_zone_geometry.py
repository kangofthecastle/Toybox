"""Unit tests for zonekit.geometry — pure math, no Tk, no ctypes."""
import unittest

from zonekit import geometry as g

WORK = (0, 0, 1920, 1040)  # typical 1080p work area minus taskbar
NEG = (-2560, -400, 0, 1040)  # secondary monitor left of (and above) primary


class ClampRatio(unittest.TestCase):
    def test_passthrough_in_range(self):
        self.assertEqual(g.clamp_ratio(0.5), 0.5)
        self.assertEqual(g.clamp_ratio(0.15), 0.15)
        self.assertEqual(g.clamp_ratio(0.85), 0.85)

    def test_clamps_extremes(self):
        self.assertEqual(g.clamp_ratio(0.0), g.RATIO_MIN)
        self.assertEqual(g.clamp_ratio(1.0), g.RATIO_MAX)
        self.assertEqual(g.clamp_ratio(-3), g.RATIO_MIN)

    def test_bad_input_resets(self):
        self.assertEqual(g.clamp_ratio(None), 0.5)
        self.assertEqual(g.clamp_ratio("junk"), 0.5)
        self.assertEqual(g.clamp_ratio(float("nan")), 0.5)


class ZoneRects(unittest.TestCase):
    def test_vertical_half(self):
        z0, z1 = g.zone_rects(WORK, "v", 0.5)
        self.assertEqual(z0, (0, 0, 960, 1040))
        self.assertEqual(z1, (960, 0, 1920, 1040))

    def test_horizontal_half(self):
        z0, z1 = g.zone_rects(WORK, "h", 0.5)
        self.assertEqual(z0, (0, 0, 1920, 520))
        self.assertEqual(z1, (0, 520, 1920, 1040))

    def test_exact_tiling_odd_sizes(self):
        # Odd widths/ratios must tile exactly: no gap, no overlap.
        for work in (WORK, (0, 0, 1919, 1039), NEG):
            for layout in ("v", "h"):
                for ratio in (0.15, 0.333, 0.5, 0.618, 0.85):
                    z0, z1 = g.zone_rects(work, layout, ratio)
                    if layout == "v":
                        self.assertEqual(z0[2], z1[0])
                        self.assertEqual((z0[0], z1[2]), (work[0], work[2]))
                    else:
                        self.assertEqual(z0[3], z1[1])
                        self.assertEqual((z0[1], z1[3]), (work[1], work[3]))

    def test_negative_origin_monitor(self):
        z0, z1 = g.zone_rects(NEG, "v", 0.5)
        self.assertEqual(z0, (-2560, -400, -1280, 1040))
        self.assertEqual(z1, (-1280, -400, 0, 1040))

    def test_ratio_clamped(self):
        z0, _ = g.zone_rects(WORK, "v", 0.01)
        self.assertEqual(z0[2], round(1920 * g.RATIO_MIN))

    def test_off_layout_raises(self):
        with self.assertRaises(ValueError):
            g.zone_rects(WORK, "off", 0.5)


class ZoneAt(unittest.TestCase):
    def test_vertical_sides(self):
        self.assertEqual(g.zone_at(WORK, "v", 0.5, 100, 500), 0)
        self.assertEqual(g.zone_at(WORK, "v", 0.5, 1800, 500), 1)
        self.assertEqual(g.zone_at(WORK, "v", 0.5, 959, 500), 0)
        self.assertEqual(g.zone_at(WORK, "v", 0.5, 960, 500), 1)

    def test_horizontal_sides(self):
        self.assertEqual(g.zone_at(WORK, "h", 0.5, 100, 100), 0)
        self.assertEqual(g.zone_at(WORK, "h", 0.5, 100, 900), 1)

    def test_outside_work_is_none(self):
        self.assertIsNone(g.zone_at(WORK, "v", 0.5, -5, 500))
        self.assertIsNone(g.zone_at(WORK, "v", 0.5, 1920, 500))
        self.assertIsNone(g.zone_at(WORK, "v", 0.5, 100, 1040))

    def test_off_layout_is_none(self):
        self.assertIsNone(g.zone_at(WORK, "off", 0.5, 100, 100))

    def test_negative_origin(self):
        self.assertEqual(g.zone_at(NEG, "v", 0.5, -2000, 0), 0)
        self.assertEqual(g.zone_at(NEG, "v", 0.5, -100, 0), 1)


class Divider(unittest.TestCase):
    def test_positions(self):
        self.assertEqual(g.divider_pos(WORK, "v", 0.5), 960)
        self.assertEqual(g.divider_pos(WORK, "h", 0.5), 520)
        self.assertEqual(g.divider_pos(NEG, "v", 0.5), -1280)

    def test_ratio_round_trip(self):
        for layout in ("v", "h"):
            for ratio in (0.2, 0.5, 0.7):
                pos = g.divider_pos(WORK, layout, ratio)
                point = (pos, 500) if layout == "v" else (500, pos)
                back = g.ratio_from_point(WORK, layout, *point)
                self.assertAlmostEqual(back, ratio, places=2)

    def test_ratio_from_point_clamps(self):
        self.assertEqual(g.ratio_from_point(WORK, "v", -500, 0), g.RATIO_MIN)
        self.assertEqual(g.ratio_from_point(WORK, "v", 5000, 0), g.RATIO_MAX)

    def test_degenerate_work_area(self):
        self.assertEqual(g.ratio_from_point((0, 0, 0, 0), "v", 10, 10), 0.5)


class NextLayout(unittest.TestCase):
    def test_cycle(self):
        self.assertEqual(g.next_layout("off"), "v")
        self.assertEqual(g.next_layout("v"), "h")
        self.assertEqual(g.next_layout("h"), "off")

    def test_unknown_resets(self):
        self.assertEqual(g.next_layout("banana"), "off")


if __name__ == "__main__":
    unittest.main()
