import unittest
from petkit.reactions import PettingDetector


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
