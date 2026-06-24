import unittest

from sysmetrics import cpu_percent

# snapshots are (idle, kernel, user) cumulative ticks; kernel includes idle.


class TestCpuPercent(unittest.TestCase):
    def test_no_delta_is_zero(self):
        snap = (100, 200, 50)
        self.assertEqual(cpu_percent(snap, snap), 0.0)

    def test_all_idle_is_zero(self):
        # idle grew 100, kernel grew 100 (all idle), user 0 -> busy 0
        self.assertAlmostEqual(cpu_percent((0, 0, 0), (100, 100, 0)), 0.0)

    def test_half_busy(self):
        # idle 50, total = kernel 100 + user 0 = 100, busy 50 -> 50%
        self.assertAlmostEqual(cpu_percent((0, 0, 0), (50, 100, 0)), 50.0)

    def test_full_busy(self):
        # idle 0, total = 50 + 50 = 100, busy 100 -> 100%
        self.assertAlmostEqual(cpu_percent((0, 0, 0), (0, 50, 50)), 100.0)

    def test_user_time_counts_as_busy(self):
        # idle 20, total = kernel 80 + user 20 = 100, busy 80 -> 80%
        self.assertAlmostEqual(cpu_percent((0, 0, 0), (20, 80, 20)), 80.0)

    def test_zero_total_delta_guarded(self):
        self.assertEqual(cpu_percent((10, 20, 30), (10, 20, 30)), 0.0)

    def test_result_clamped_to_100(self):
        # pathological negative idle delta -> clamp at 100
        self.assertEqual(cpu_percent((100, 0, 0), (0, 100, 0)), 100.0)

    def test_result_clamped_to_0(self):
        # pathological idle delta exceeding total -> clamp at 0
        self.assertEqual(cpu_percent((0, 0, 0), (200, 100, 0)), 0.0)


if __name__ == "__main__":
    unittest.main()
