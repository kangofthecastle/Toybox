# tests/test_bubble.py
import unittest
import petkit.bubble as bubble


class TestBubblePosition(unittest.TestCase):
    def test_centered_horizontally_over_window(self):
        x, _ = bubble.bubble_xy(root_x=100, root_y=200, root_w=170,
                                head_offset=48, w=60, h=26)
        # window center 100 + 170//2 = 185; minus half the bubble width (30) -> 155
        self.assertEqual(x, 155)

    def test_sits_just_above_the_head_line(self):
        # head_offset is how far below the window top the cat's head sits; the
        # bubble's bottom must land `gap` px above that line.
        _, y = bubble.bubble_xy(root_x=0, root_y=200, root_w=170,
                                head_offset=48, w=60, h=26, gap=8)
        self.assertEqual(y, 200 + 48 - 26 - 8)   # 214

    def test_zero_head_offset_matches_old_window_top_anchor(self):
        # Backward-compatible default: anchored to the window top.
        _, y = bubble.bubble_xy(root_x=0, root_y=200, root_w=170,
                                head_offset=0, w=60, h=26, gap=8)
        self.assertEqual(y, 200 - 26 - 8)        # 166

    def test_larger_head_offset_lowers_the_bubble(self):
        _, y_small = bubble.bubble_xy(0, 200, 170, 20, 60, 26)
        _, y_big = bubble.bubble_xy(0, 200, 170, 60, 60, 26)
        self.assertGreater(y_big, y_small)       # bigger offset -> closer to the cat


if __name__ == "__main__":
    unittest.main()
