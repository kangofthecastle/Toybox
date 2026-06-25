import os
import tempfile
import time
import unittest
from petkit.reminders import parse_reminder, Reminders


class TestParse(unittest.TestCase):
    def test_relative_minutes(self):
        msg, due = parse_reminder("remind me to drink water in 20m", now_epoch=1000)
        self.assertEqual(msg, "drink water")
        self.assertEqual(due, 1000 + 20 * 60)

    def test_relative_hours_minutes(self):
        msg, due = parse_reminder("in 1h30 stretch", now_epoch=0)
        self.assertEqual(due, 90 * 60)

    def test_relative_seconds(self):
        _msg, due = parse_reminder("ping in 45s", now_epoch=10)
        self.assertEqual(due, 55)

    def test_absolute_clock_is_in_the_future_at_that_hour(self):
        now = time.mktime((2026, 6, 25, 9, 0, 0, 0, 0, -1))   # 09:00 local
        msg, due = parse_reminder("call mom at 3pm", now_epoch=now)
        self.assertEqual(msg, "call mom")
        self.assertGreater(due, now)
        self.assertEqual(time.localtime(due).tm_hour, 15)

    def test_absolute_rolls_to_tomorrow_when_past(self):
        now = time.mktime((2026, 6, 25, 18, 0, 0, 0, 0, -1))  # 18:00 local
        _msg, due = parse_reminder("standup at 9am", now_epoch=now)
        self.assertGreater(due, now)
        self.assertEqual(time.localtime(due).tm_hour, 9)

    def test_no_time_phrase_returns_none(self):
        self.assertIsNone(parse_reminder("just some text", now_epoch=0))


class TestStore(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.path)   # start with no file

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_missing_file_is_empty(self):
        self.assertEqual(Reminders(self.path).pending(), [])

    def test_add_persists_and_reloads(self):
        Reminders(self.path).add("water", 5000)
        self.assertEqual(Reminders(self.path).pending(),
                         [{"text": "water", "due": 5000}])

    def test_due_fires_and_removes(self):
        r = Reminders(self.path)
        r.add("a", 100)
        r.add("b", 300)
        self.assertEqual(r.due(now_epoch=200), ["a"])
        self.assertEqual(r.pending(), [{"text": "b", "due": 300}])
        self.assertEqual(Reminders(self.path).pending(),   # persisted
                         [{"text": "b", "due": 300}])

    def test_corrupt_file_is_empty(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(Reminders(self.path).pending(), [])
