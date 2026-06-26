# tests/test_bubble.py
import unittest
import petkit.bubble as bubble


class TestBubblePosition(unittest.TestCase):
    def test_placed_to_the_right_of_the_cat(self):
        # left edge sits `gap` px past the cat's right edge
        x, _ = bubble.bubble_xy(root_x=100, root_y=200, cat_right=149,
                                anchor_y=72, w=60, h=26, gap=8)
        self.assertEqual(x, 100 + 149 + 8)        # 257

    def test_vertically_centered_on_the_face(self):
        _, y = bubble.bubble_xy(root_x=0, root_y=200, cat_right=149,
                                anchor_y=72, w=60, h=26, gap=8)
        self.assertEqual(y, 200 + 72 - 13)        # center on anchor_y -> 259

    def test_default_gap_is_used(self):
        x, _ = bubble.bubble_xy(root_x=0, root_y=0, cat_right=149,
                                anchor_y=72, w=60, h=26)
        self.assertEqual(x, 149 + bubble.PAD)

    def test_larger_anchor_lowers_the_bubble(self):
        _, y_small = bubble.bubble_xy(0, 200, 149, 40, 60, 26)
        _, y_big = bubble.bubble_xy(0, 200, 149, 90, 60, 26)
        self.assertGreater(y_big, y_small)


if __name__ == "__main__":
    unittest.main()
