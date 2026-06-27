import os
import unittest

import petkit.timerbadge as timerbadge


class TestBadgeText(unittest.TestCase):
    def test_focus(self):
        self.assertEqual(timerbadge.badge_text("focus", 125), "\U0001F3AF 2:05")

    def test_break(self):
        self.assertEqual(timerbadge.badge_text("break", 5), "☕ 0:05")

    def test_paused(self):
        self.assertEqual(timerbadge.badge_text("paused", 1500), "⏸ 25:00")

    def test_idle_is_empty(self):
        self.assertEqual(timerbadge.badge_text("idle", 0), "")

    def test_negative_clamped(self):
        self.assertEqual(timerbadge.badge_text("focus", -3), "\U0001F3AF 0:00")


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestTimerBadgeWidget(unittest.TestCase):
    def test_show_update_hide_destroy(self):
        import tkinter as tk
        import winkit.window as window
        root = tk.Tk(); root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("80x80+140+140"); root.update()
        try:
            b = timerbadge.TimerBadge(root, head_offset=10)
            b.show(timerbadge.badge_text("focus", 1500)); root.update()
            self.assertTrue(b._shown)
            b.show(timerbadge.badge_text("focus", 1499)); root.update()   # update path
            b.show("")                         # empty text -> hide
            self.assertFalse(b._shown)
            b.hide()
            b.destroy()
        finally:
            root.destroy()
