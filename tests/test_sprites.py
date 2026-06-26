# tests/test_sprites.py
import os
import tkinter as tk
import unittest

import winkit.sprites as sprites

ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets", "cat")


class TestSpriteSheet(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as e:
            self.skipTest("no Tk/display: %s" % e)

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_idle_has_ten_frames(self):
        s = sprites.SpriteSheet(self.root, os.path.join(ASSETS, "Idle.png"))
        self.assertEqual(s.frame_count, 10)

    def test_frame_is_nearest_neighbor_zoomed(self):
        s = sprites.SpriteSheet(self.root, os.path.join(ASSETS, "Idle.png"))
        f = s.frame(0, zoom=4)
        self.assertEqual((f.width(), f.height()), (128, 128))

    def test_frame_is_cached(self):
        s = sprites.SpriteSheet(self.root, os.path.join(ASSETS, "Idle.png"))
        self.assertIs(s.frame(2, 4), s.frame(2, 4))

    def test_index_wraps(self):
        s = sprites.SpriteSheet(self.root, os.path.join(ASSETS, "Idle.png"))
        self.assertIs(s.frame(12, 4), s.frame(2, 4))  # 12 % 10 == 2


class TestOpaqueBbox(unittest.TestCase):
    def test_bbox_of_a_rectangle(self):
        opq = lambda x, y: 2 <= x <= 5 and 3 <= y <= 7
        self.assertEqual(sprites.opaque_bbox(10, 10, opq), (2, 3, 5, 7))

    def test_bbox_single_pixel(self):
        opq = lambda x, y: (x, y) == (4, 4)
        self.assertEqual(sprites.opaque_bbox(8, 8, opq), (4, 4, 4, 4))

    def test_bbox_none_when_fully_transparent(self):
        self.assertIsNone(sprites.opaque_bbox(8, 8, lambda x, y: False))


if __name__ == "__main__":
    unittest.main()
