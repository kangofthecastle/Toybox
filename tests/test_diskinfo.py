import unittest
import winkit.diskinfo as diskinfo


class TestHumanBytes(unittest.TestCase):
    def test_gigabytes_integer(self):
        self.assertEqual(diskinfo.human_bytes(312 * 1024**3), "312G")

    def test_terabytes_one_decimal(self):
        self.assertEqual(diskinfo.human_bytes(int(1.1 * 1024**4)), "1.1T")

    def test_small_gigabytes_one_decimal(self):
        self.assertEqual(diskinfo.human_bytes(5 * 1024**3), "5.0G")

    def test_megabytes_integer(self):
        self.assertEqual(diskinfo.human_bytes(999 * 1024**2), "999M")

    def test_zero_and_negative_are_zero(self):
        self.assertEqual(diskinfo.human_bytes(0), "0")
        self.assertEqual(diskinfo.human_bytes(-10), "0")

    def test_non_numeric_is_safe(self):
        self.assertEqual(diskinfo.human_bytes(None), "0")
        self.assertEqual(diskinfo.human_bytes("x"), "0")

    def test_switches_unit_below_1000_boundary(self):
        # 1023.6 GiB must roll into T, never render a 5-char "1024G".
        self.assertEqual(diskinfo.human_bytes(int(1023.6 * 1024**3)), "1.0T")

    def test_output_never_exceeds_four_chars(self):
        for n in (0, 1, 999, 1023, 1024, 999 * 1024**2, 1023 * 1024**3,
                  int(9.96 * 1024**3), int(1.1 * 1024**4), 5 * 1024**4,
                  900 * 1024**4):
            self.assertLessEqual(len(diskinfo.human_bytes(n)), 4, n)


class TestFormatDiskRow(unittest.TestCase):
    def test_packs_drives_with_letters(self):
        usages = [("C:", 312 * 1024**3, 0), ("D:", int(1.1 * 1024**4), 0)]
        self.assertEqual(diskinfo.format_disk_row(usages, 30), "C 312G  D 1.1T")

    def test_strips_colon_from_letter(self):
        self.assertEqual(diskinfo.format_disk_row([("C:", 5 * 1024**3, 0)], 30),
                         "C 5.0G")

    def test_empty_is_empty_string(self):
        self.assertEqual(diskinfo.format_disk_row([], 30), "")

    def test_no_cap_when_max_chars_none(self):
        usages = [("C:", 312 * 1024**3, 0), ("D:", int(1.1 * 1024**4), 0)]
        self.assertEqual(diskinfo.format_disk_row(usages, None), "C 312G  D 1.1T")

    def test_truncates_with_ellipsis_when_too_wide(self):
        usages = [("C:", 312 * 1024**3, 0), ("D:", 1 * 1024**4, 0),
                  ("E:", 2 * 1024**4, 0), ("F:", 3 * 1024**4, 0)]
        out = diskinfo.format_disk_row(usages, 10)
        self.assertEqual(len(out), 10)
        self.assertTrue(out.endswith("…"))


if __name__ == "__main__":
    unittest.main()
