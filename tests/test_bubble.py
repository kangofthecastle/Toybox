import unittest
import petkit.bubble as bubble


class TestBubblePosition(unittest.TestCase):
    def test_right_side_when_it_fits(self):
        x, _ = bubble.bubble_xy(root_x=500, root_y=300, body_left=30,
                                body_right=120, anchor_y=76, w=80, h=30,
                                screen_w=1920, gap=8)
        self.assertEqual(x, 500 + 120 + 8)            # 628

    def test_vertically_centered_on_the_face(self):
        _, y = bubble.bubble_xy(root_x=500, root_y=300, body_left=30,
                                body_right=120, anchor_y=76, w=80, h=30,
                                screen_w=1920, gap=8)
        self.assertEqual(y, 300 + 76 - 15)            # 361

    def test_flips_left_when_right_would_overflow(self):
        # cat near the right screen edge: right placement (1850+120+8=1978, +80
        # -> 2058 > 1920) doesn't fit, so flip to the left of the body.
        x, _ = bubble.bubble_xy(root_x=1850, root_y=300, body_left=30,
                                body_right=120, anchor_y=76, w=80, h=30,
                                screen_w=1920, gap=8)
        self.assertEqual(x, 1850 + 30 - 8 - 80)       # 1792

    def test_default_gap_is_used(self):
        x, _ = bubble.bubble_xy(0, 0, 30, 120, 76, 80, 30, screen_w=1920)
        self.assertEqual(x, 120 + bubble.PAD)

    def test_larger_anchor_lowers_the_bubble(self):
        _, y_small = bubble.bubble_xy(0, 0, 30, 120, 40, 80, 30, 1920)
        _, y_big = bubble.bubble_xy(0, 0, 30, 120, 90, 80, 30, 1920)
        self.assertGreater(y_big, y_small)


if __name__ == "__main__":
    unittest.main()
