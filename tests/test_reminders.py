import os
import shutil
import tempfile
import time
import unittest
import petkit.reminders as reminders
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

    def test_absolute_clock_tiny_epoch_does_not_raise(self):
        # mktime can overflow for a pre-1970 local time (Windows); the documented
        # "never raises" contract must hold -- return None instead.
        try:
            parse_reminder("call mom at 3pm", now_epoch=0)
        except Exception as exc:                       # noqa: BLE001
            self.fail("parse_reminder raised %r" % exc)


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


class TestDueFromFields(unittest.TestCase):
    def test_in_minutes(self):
        self.assertEqual(reminders.due_from_fields("in", 20, "min", 0, 0, 1000), 1000 + 1200)

    def test_in_hours(self):
        self.assertEqual(reminders.due_from_fields("in", 2, "hours", 0, 0, 1000), 1000 + 7200)

    def test_in_string_amount_coerced(self):
        self.assertEqual(reminders.due_from_fields("in", "15", "min", 0, 0, 0), 900)

    def test_in_negative_is_none(self):
        self.assertIsNone(reminders.due_from_fields("in", -5, "min", 0, 0, 0))

    def test_in_bad_unit_is_none(self):
        self.assertIsNone(reminders.due_from_fields("in", 5, "weeks", 0, 0, 0))

    def test_at_later_today(self):
        base = list(time.localtime()); base[3], base[4], base[5] = 8, 0, 0
        now = time.mktime(time.struct_time(tuple(base)))   # 8:00 local today
        due = reminders.due_from_fields("at", 0, "min", 23, 30, now)
        self.assertGreater(due, now)
        self.assertLessEqual(due - now, 24 * 3600)
        lt = time.localtime(due)
        self.assertEqual((lt.tm_hour, lt.tm_min), (23, 30))

    def test_at_already_past_rolls_to_tomorrow(self):
        base = list(time.localtime()); base[3], base[4], base[5] = 23, 0, 0
        now = time.mktime(time.struct_time(tuple(base)))   # 23:00 local today
        due = reminders.due_from_fields("at", 0, "min", 9, 0, now)   # 9am already passed
        self.assertGreater(due - now, 3600)
        self.assertLessEqual(due - now, 24 * 3600)

    def test_at_invalid_hour_is_none(self):
        self.assertIsNone(reminders.due_from_fields("at", 0, "min", 99, 0, 1000))

    def test_unknown_mode_is_none(self):
        self.assertIsNone(reminders.due_from_fields("nope", 0, "min", 0, 0, 1000))


class TestFormatDue(unittest.TestCase):
    def _at(self, h, m):
        base = list(time.localtime()); base[3], base[4], base[5] = h, m, 0
        return time.mktime(time.struct_time(tuple(base)))

    def test_same_day_pm(self):
        now = self._at(16, 12)
        self.assertEqual(reminders.format_due(now, now - 60), "4:12pm")

    def test_midnight_is_12am(self):
        now = self._at(0, 5)
        self.assertEqual(reminders.format_due(now, now - 60), "12:05am")

    def test_noon_is_12pm(self):
        now = self._at(12, 0)
        self.assertEqual(reminders.format_due(now, now - 60), "12:00pm")

    def test_next_day_is_prefixed(self):
        now = self._at(9, 0)
        s = reminders.format_due(now + 24 * 3600, now)
        self.assertTrue(s.startswith("tomorrow ") or s[:3].isalpha())  # not a bare clock


class TestReminderRemove(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.path = os.path.join(self.dir, "r.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_remove_one_of_same_text(self):
        r = reminders.Reminders(self.path)
        r.add("ping", 1000); r.add("ping", 2000)
        r.remove("ping", 1000)
        self.assertEqual([(i["text"], i["due"]) for i in r.pending()], [("ping", 2000)])

    def test_remove_persists(self):
        r = reminders.Reminders(self.path)
        r.add("ping", 1000); r.add("ping", 2000)
        r.remove("ping", 1000)
        self.assertEqual(len(reminders.Reminders(self.path).pending()), 1)  # reloaded from disk

    def test_remove_absent_is_noop(self):
        r = reminders.Reminders(self.path)
        r.add("ping", 1000)
        r.remove("ping", 9999)
        self.assertEqual(len(r.pending()), 1)
