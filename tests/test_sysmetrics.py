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


from sysmetrics import gpu_percent


class TestGpuPercent(unittest.TestCase):
    # instance names mimic PDH: "..._eng_N_engtype_<Type>"
    def _n(self, engtype, eng=0):
        return "pid_100_luid_0x0_0x1_phys_0_eng_%d_engtype_%s" % (eng, engtype)

    def test_single_engine(self):
        self.assertAlmostEqual(gpu_percent([(self._n("3D"), 40.0)]), 40.0)

    def test_sums_within_a_type(self):
        # two Copy engines: 30 + 25 = 55
        pairs = [(self._n("Copy", 13), 30.0), (self._n("Copy", 14), 25.0)]
        self.assertAlmostEqual(gpu_percent(pairs), 55.0)

    def test_max_across_types_wins(self):
        pairs = [(self._n("3D"), 40.0),
                 (self._n("Copy", 13), 30.0), (self._n("Copy", 14), 25.0)]  # Copy=55 > 3D=40
        self.assertAlmostEqual(gpu_percent(pairs), 55.0)

    def test_clamped_to_100(self):
        pairs = [(self._n("3D", 0), 60.0), (self._n("3D", 1), 60.0)]  # 120 -> 100
        self.assertAlmostEqual(gpu_percent(pairs), 100.0)

    def test_empty_is_none(self):
        self.assertIsNone(gpu_percent([]))

    def test_instances_without_engtype_are_ignored(self):
        self.assertIsNone(gpu_percent([("pid_1_luid_no_marker", 99.0)]))

    def test_mixed_ignores_non_engtype(self):
        pairs = [("no_marker_here", 99.0), (self._n("3D"), 10.0)]
        self.assertAlmostEqual(gpu_percent(pairs), 10.0)


if __name__ == "__main__":
    unittest.main()
