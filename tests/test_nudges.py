import unittest
from petkit.nudges import NudgeScheduler


class TestNudgeScheduler(unittest.TestCase):
    def test_fires_after_active_interval(self):
        n = NudgeScheduler(interval_s=100, away_ms=60000)
        n.update(0, now=0.0)                      # baseline
        self.assertFalse(n.update(0, now=50.0))
        self.assertTrue(n.update(0, now=100.0))   # 100s of active time

    def test_idle_time_does_not_count(self):
        n = NudgeScheduler(interval_s=100, away_ms=60000)
        n.update(0, now=0.0)
        self.assertFalse(n.update(90000, now=80.0))   # away: 80s not counted
        self.assertFalse(n.update(0, now=120.0))      # only 40s active so far
        self.assertTrue(n.update(0, now=180.0))       # now 100s active

    def test_snooze_delays_next(self):
        n = NudgeScheduler(interval_s=100, away_ms=60000)
        n.update(0, now=0.0)
        self.assertTrue(n.update(0, now=100.0))
        n.snooze(now=100.0, secs=200)
        self.assertFalse(n.update(0, now=150.0))
        self.assertTrue(n.update(0, now=300.0))

    def test_only_fires_once_per_interval(self):
        n = NudgeScheduler(interval_s=100, away_ms=60000)
        n.update(0, now=0.0)
        self.assertTrue(n.update(0, now=100.0))
        self.assertFalse(n.update(0, now=120.0))
