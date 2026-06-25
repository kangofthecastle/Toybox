import unittest
from petkit.reactions import PettingDetector
from petkit.reactions import NapState


class TestPettingDetector(unittest.TestCase):
    def test_back_and_forth_inside_triggers_petting(self):
        d = PettingDetector(reversals_needed=3, window_s=10)
        xs = [0, 10, 20, 10, 0, 10, 20, 10, 0]  # 3+ reversals
        petting = False
        for i, x in enumerate(xs):
            petting = d.update(x, True, now=i * 0.1)
        self.assertTrue(petting)

    def test_monotonic_drag_is_not_petting(self):
        d = PettingDetector(reversals_needed=3, window_s=10)
        petting = False
        for i in range(10):
            petting = d.update(i * 5, True, now=i * 0.1)
        self.assertFalse(petting)

    def test_motion_outside_does_not_count(self):
        d = PettingDetector(reversals_needed=3, window_s=10)
        xs = [0, 10, 0, 10, 0, 10]
        petting = False
        for i, x in enumerate(xs):
            petting = d.update(x, False, now=i * 0.1)
        self.assertFalse(petting)

    def test_reversals_age_out(self):
        d = PettingDetector(reversals_needed=3, window_s=1.0)
        for i, x in enumerate([0, 10, 0, 10, 0, 10, 0]):
            d.update(x, True, now=i * 0.1)
        self.assertTrue(d.active(now=0.6))
        self.assertFalse(d.active(now=5.0))  # all reversals older than window_s


class TestNapState(unittest.TestCase):
    def test_starts_awake(self):
        n = NapState(sleep_after_ms=120000)
        self.assertEqual(n.update(0, now=0.0), "awake")

    def test_naps_after_idle_threshold(self):
        n = NapState(sleep_after_ms=120000)
        self.assertEqual(n.update(130000, now=1.0), "napping")

    def test_activity_during_nap_startles_then_wakes(self):
        n = NapState(sleep_after_ms=120000, startle_s=0.8)
        n.update(130000, now=1.0)               # napping
        self.assertEqual(n.update(5, now=2.0), "startled")
        self.assertEqual(n.update(5, now=2.5), "startled")   # still inside startle_s
        self.assertEqual(n.update(5, now=3.0), "awake")      # startle_s elapsed

    def test_can_renap_after_waking(self):
        n = NapState(sleep_after_ms=120000, startle_s=0.5)
        n.update(130000, now=1.0)               # napping
        n.update(5, now=2.0)                     # startled
        n.update(5, now=2.6)                     # awake
        self.assertEqual(n.update(130000, now=3.0), "napping")
