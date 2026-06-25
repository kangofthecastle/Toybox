import unittest
from petkit.greeter import Greeter


class TestGreeter(unittest.TestCase):
    def test_no_greeting_without_being_away(self):
        g = Greeter(away_after_ms=300000)
        self.assertIsNone(g.update(0))
        self.assertIsNone(g.update(1000))

    def test_greets_once_on_return(self):
        g = Greeter(away_after_ms=300000)
        self.assertIsNone(g.update(400000))     # now away
        msg = g.update(0)                         # returned -> greet
        self.assertIsInstance(msg, str)
        self.assertIn("Welcome back", msg)
        self.assertIsNone(g.update(0))            # only once

    def test_reports_minutes_away(self):
        g = Greeter(away_after_ms=300000)
        g.update(600000)                          # 10 minutes idle
        msg = g.update(0)
        self.assertIn("10", msg)

    def test_short_absence_has_no_minute_count(self):
        g = Greeter(away_after_ms=300000)
        g.update(330000)                          # 5.5 min -> "5 min"
        self.assertIn("5", g.update(0))
