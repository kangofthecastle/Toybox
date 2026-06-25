import unittest
from petkit.pomodoro import Pomodoro


class TestPomodoro(unittest.TestCase):
    def test_starts_idle(self):
        p = Pomodoro()
        self.assertEqual(p.state, "idle")
        self.assertEqual(p.remaining(now=0.0), 0)

    def test_focus_counts_down_then_enters_break(self):
        p = Pomodoro(focus_s=100, break_s=20)
        p.start(now=0.0)
        self.assertEqual(p.state, "focus")
        self.assertEqual(p.remaining(now=40.0), 60)
        self.assertIsNone(p.update(now=40.0))
        self.assertEqual(p.update(now=100.0), "focus_done")
        self.assertEqual(p.state, "break")
        self.assertEqual(p.remaining(now=100.0), 20)

    def test_break_completes_to_idle(self):
        p = Pomodoro(focus_s=10, break_s=10)
        p.start(now=0.0)
        p.update(now=10.0)                       # -> break
        self.assertEqual(p.update(now=20.0), "break_done")
        self.assertEqual(p.state, "idle")

    def test_pause_freezes_remaining_then_resume(self):
        p = Pomodoro(focus_s=100)
        p.start(now=0.0)
        p.pause(now=30.0)
        self.assertEqual(p.state, "paused")
        self.assertEqual(p.remaining(now=999.0), 70)   # frozen while paused
        p.resume(now=200.0)
        self.assertEqual(p.state, "focus")
        self.assertEqual(p.remaining(now=230.0), 40)
        self.assertEqual(p.update(now=270.0), "focus_done")

    def test_cancel_returns_to_idle(self):
        p = Pomodoro()
        p.start(now=0.0)
        p.cancel()
        self.assertEqual(p.state, "idle")
        self.assertIsNone(p.update(now=9999.0))
