import unittest

import clip_view


class TestFlattenLine(unittest.TestCase):
    def test_plain_text_unchanged(self):
        self.assertEqual(clip_view.flatten_line("hello world"), "hello world")

    def test_newline_becomes_return_glyph(self):
        self.assertEqual(clip_view.flatten_line("a\nb"), "a ⏎ b")

    def test_crlf_becomes_space(self):
        self.assertEqual(clip_view.flatten_line("a\r\nb"), "a b")

    def test_carriage_return_becomes_space(self):
        self.assertEqual(clip_view.flatten_line("a\rb"), "a b")

    def test_tab_becomes_space(self):
        self.assertEqual(clip_view.flatten_line("a\tb"), "a b")

    def test_whitespace_only_returns_glyph(self):
        self.assertEqual(clip_view.flatten_line("   "), "⏎")
        self.assertEqual(clip_view.flatten_line(""), "⏎")

    def test_long_text_not_truncated(self):
        s = "x" * 500
        self.assertEqual(clip_view.flatten_line(s), s)
        self.assertEqual(len(clip_view.flatten_line(s)), 500)


class TestLayoutHelpers(unittest.TestCase):
    def test_normalize_keeps_known(self):
        self.assertEqual(clip_view.normalize_layout("columns"), "columns")
        self.assertEqual(clip_view.normalize_layout("stacked"), "stacked")

    def test_normalize_unknown_to_columns(self):
        self.assertEqual(clip_view.normalize_layout("weird"), "columns")
        self.assertEqual(clip_view.normalize_layout(""), "columns")

    def test_next_layout_toggles(self):
        self.assertEqual(clip_view.next_layout("columns"), "stacked")
        self.assertEqual(clip_view.next_layout("stacked"), "columns")

    def test_next_layout_unknown_to_stacked(self):
        self.assertEqual(clip_view.next_layout("weird"), "stacked")

    def test_panel_size_known(self):
        self.assertEqual(clip_view.panel_size("columns"), (632, 420))
        # Stacked keeps the columns width (only the height grows) so toggling
        # never narrows the panel.
        self.assertEqual(clip_view.panel_size("stacked"), (632, 620))

    def test_stacked_keeps_columns_width(self):
        self.assertEqual(clip_view.panel_size("stacked")[0],
                         clip_view.panel_size("columns")[0])

    def test_panel_size_unknown_falls_back_to_columns(self):
        self.assertEqual(clip_view.panel_size("weird"), (632, 420))


if __name__ == "__main__":
    unittest.main()
