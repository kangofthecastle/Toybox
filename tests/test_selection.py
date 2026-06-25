import unittest

from selection import shift_range


class TestShiftRange(unittest.TestCase):
    def test_forward_range(self):
        self.assertEqual(shift_range(2, 5), {2, 3, 4, 5})

    def test_backward_range(self):
        self.assertEqual(shift_range(5, 2), {2, 3, 4, 5})

    def test_single(self):
        self.assertEqual(shift_range(3, 3), {3})

    def test_no_anchor(self):
        self.assertEqual(shift_range(None, 4), {4})


if __name__ == "__main__":
    unittest.main()
