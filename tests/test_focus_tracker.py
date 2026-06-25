import unittest
from petkit.focus_tracker import FocusTally


class TestFocusTally(unittest.TestCase):
    def test_accumulates_dwell_per_app(self):
        t = FocusTally()
        t.sample("code", now=0)
        t.sample("chrome", now=30)      # 30s on code
        t.sample("code", now=40)        # 10s on chrome
        top = dict(t.top(now=60))       # +20s on code in progress
        self.assertEqual(top["code"], 50)
        self.assertEqual(top["chrome"], 10)

    def test_top_is_sorted_and_limited(self):
        t = FocusTally()
        t.sample("a", now=0)
        t.sample("b", now=100)
        t.sample("c", now=110)
        t.sample(None, now=160)         # close out c (50s)
        top = t.top(n=2)
        self.assertEqual([app for app, _ in top], ["a", "c"])

    def test_empty_top_is_empty(self):
        self.assertEqual(FocusTally().top(), [])
