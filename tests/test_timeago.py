import unittest

from timeago import format_ago


class TestFormatAgo(unittest.TestCase):
    def test_just_now(self):
        self.assertEqual(format_ago(0), "just now")
        self.assertEqual(format_ago(59), "just now")

    def test_negative_is_just_now(self):
        self.assertEqual(format_ago(-5), "just now")

    def test_minutes(self):
        self.assertEqual(format_ago(60), "1m")
        self.assertEqual(format_ago(3599), "59m")

    def test_hours(self):
        self.assertEqual(format_ago(3600), "1h")
        self.assertEqual(format_ago(86399), "23h")

    def test_days(self):
        self.assertEqual(format_ago(86400), "1d")
        self.assertEqual(format_ago(200000), "2d")

    def test_weeks(self):
        self.assertEqual(format_ago(604800), "1w")      # exactly one week
        self.assertEqual(format_ago(1209600), "2w")     # two weeks
        self.assertEqual(format_ago(3024000), "5w")     # five weeks

    def test_days_to_weeks_boundary(self):
        self.assertEqual(format_ago(604799), "6d")      # just under a week stays days


if __name__ == "__main__":
    unittest.main()
