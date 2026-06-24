import unittest

from clip_history import ClipHistory


class TestClipHistory(unittest.TestCase):
    def test_add_then_items_returns_it(self):
        h = ClipHistory()
        self.assertTrue(h.add("hello"))
        self.assertEqual(h.items(), ["hello"])

    def test_newest_first_ordering(self):
        h = ClipHistory()
        h.add("a")
        h.add("b")
        h.add("c")
        self.assertEqual(h.items(), ["c", "b", "a"])

    def test_empty_or_whitespace_only_ignored(self):
        h = ClipHistory()
        self.assertFalse(h.add(""))
        self.assertFalse(h.add("   "))
        self.assertFalse(h.add("\t\n"))
        self.assertEqual(h.items(), [])

    def test_none_ignored(self):
        h = ClipHistory()
        self.assertFalse(h.add(None))
        self.assertEqual(h.items(), [])

    def test_duplicate_of_newest_ignored(self):
        h = ClipHistory()
        h.add("x")
        self.assertFalse(h.add("x"))
        self.assertEqual(h.items(), ["x"])
        self.assertEqual(len(h), 1)

    def test_duplicate_elsewhere_moves_to_front(self):
        h = ClipHistory()
        h.add("a")
        h.add("b")
        h.add("c")  # c, b, a
        self.assertTrue(h.add("a"))
        self.assertEqual(h.items(), ["a", "c", "b"])
        self.assertEqual(len(h), 3)

    def test_cap_evicts_oldest(self):
        h = ClipHistory(max_items=3)
        h.add("a")
        h.add("b")
        h.add("c")
        h.add("d")
        self.assertEqual(h.items(), ["d", "c", "b"])
        self.assertEqual(len(h), 3)

    def test_select_moves_to_front_and_returns(self):
        h = ClipHistory()
        h.add("a")
        h.add("b")
        h.add("c")  # c, b, a  -> index 2 is "a"
        self.assertEqual(h.select(2), "a")
        self.assertEqual(h.items(), ["a", "c", "b"])

    def test_select_index_zero_is_noop_returns_newest(self):
        h = ClipHistory()
        h.add("a")
        h.add("b")  # b, a
        self.assertEqual(h.select(0), "b")
        self.assertEqual(h.items(), ["b", "a"])

    def test_select_out_of_range_returns_none(self):
        h = ClipHistory()
        h.add("a")
        self.assertIsNone(h.select(5))
        self.assertIsNone(h.select(-1))

    def test_preserves_text_with_internal_whitespace(self):
        h = ClipHistory()
        self.assertTrue(h.add("  hi there  "))
        self.assertEqual(h.items(), ["  hi there  "])

    def test_items_returns_copy_not_internal_list(self):
        h = ClipHistory()
        h.add("a")
        got = h.items()
        got.append("tampered")
        self.assertEqual(h.items(), ["a"])


if __name__ == "__main__":
    unittest.main()
