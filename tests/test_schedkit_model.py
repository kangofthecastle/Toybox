import datetime
import unittest

from schedkit.model import parse_schedule


def _sched(rows, sheet="S"):
    return parse_schedule({sheet: rows})


def _find_weekday(month, day, weekday):
    """A real date on the given month/day whose weekday matches (weekday: Mon=0)."""
    for y in range(2020, 2040):
        d = datetime.date(y, month, day)
        if d.weekday() == weekday:
            return d
    raise AssertionError("no matching date")


class TestParseSchedule(unittest.TestCase):
    def test_now_slot_matches_text_column(self):
        sched = _sched([["Time", "Jun 29"], ["9:00-10:00", "Standup"]])
        slot = sched.at(datetime.datetime(2026, 6, 29, 9, 30))
        self.assertEqual(slot.kind, "now")
        self.assertEqual(slot.task, "Standup")
        self.assertEqual(slot.start.hour, 9)
        self.assertEqual(slot.end.hour, 10)

    def test_next_slot_during_gap(self):
        sched = _sched([["Time", "Jun 29"],
                        ["9:00-10:00", "Morning"],
                        ["1:00-2:00", "Afternoon"]])   # 1:00 infers to 13:00
        slot = sched.at(datetime.datetime(2026, 6, 29, 11, 0))
        self.assertEqual(slot.kind, "next")
        self.assertEqual(slot.task, "Afternoon")
        self.assertEqual(slot.start.hour, 13)

    def test_none_after_last_block(self):
        sched = _sched([["Time", "Jun 29"], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(2026, 6, 29, 20, 0)).kind, "none")

    def test_noon_wrap_infers_pm(self):
        sched = _sched([["Time", "Jun 29"],
                        ["11:00-12:00", "A"],
                        ["12:00-1:00", "B"],
                        ["1:00-3:00", "C"]])
        slot = sched.at(datetime.datetime(2026, 6, 29, 12, 30))
        self.assertEqual(slot.kind, "now")
        self.assertEqual(slot.task, "B")
        self.assertEqual(slot.start.hour, 12)   # noon, not midnight
        self.assertEqual(slot.end.hour, 13)     # 1:00 -> 13:00

    def test_serial_date_column_and_year_disambiguation(self):
        serial = (datetime.date(2026, 6, 29) - datetime.date(1899, 12, 30)).days
        sched = _sched([["Time", serial], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(2026, 6, 29, 9, 30)).task, "Work")
        # same month/day, different year -> serial carries the year -> no match
        self.assertEqual(sched.at(datetime.datetime(2025, 6, 29, 9, 30)).kind, "none")

    def test_weekday_agreement_required(self):
        mon = _find_weekday(6, 29, 0)             # a year where Jun 29 is Monday
        sched = _sched([["Time", "Mon Jun 29"], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(mon.year, 6, 29, 9, 30)).kind, "now")
        other = next(datetime.date(y, 6, 29) for y in range(2020, 2040)
                     if datetime.date(y, 6, 29).weekday() != 0)
        self.assertEqual(sched.at(datetime.datetime(other.year, 6, 29, 9, 30)).kind, "none")

    def test_placeholder_task_skipped(self):
        sched = _sched([["Time", "Jun 29"],
                        ["9:00-10:00", "—"],   # em-dash placeholder
                        ["10:00-11:00", "Real"]])
        slot = sched.at(datetime.datetime(2026, 6, 29, 9, 30))
        self.assertEqual(slot.kind, "next")
        self.assertEqual(slot.task, "Real")

    def test_header_below_title_row_detected(self):
        sched = _sched([["My Week"], ["Time", "Jun 29"], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(2026, 6, 29, 9, 30)).task, "Work")

    def test_no_matching_column_returns_none(self):
        sched = _sched([["Time", "Jun 30"], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(2026, 6, 29, 9, 30)).kind, "none")

    def test_bad_or_empty_workbook_returns_none_slot(self):
        now = datetime.datetime(2026, 6, 29, 9, 30)
        self.assertEqual(parse_schedule({}).at(now).kind, "none")
        self.assertEqual(parse_schedule(None).at(now).kind, "none")
        self.assertEqual(parse_schedule({"S": []}).at(now).kind, "none")


if __name__ == "__main__":
    unittest.main()
