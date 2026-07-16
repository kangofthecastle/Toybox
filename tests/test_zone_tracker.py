"""Unit tests for zonekit.tracker — synthetic input sequences, no Tk/ctypes."""
import unittest

from zonekit.tracker import DragTracker, IDLE, ARMED, DRAGGING


class Rig:
    """Scriptable fake inputs for DragTracker."""

    def __init__(self):
        self.shift = False
        self.button = False
        self.fg = 0
        self.rects = {}  # hwnd -> (l, t, r, b) or None
        self.snappable = set()
        self.cursor = (0, 0)
        self.tracker = DragTracker(
            shift_down=lambda: self.shift,
            button_down=lambda: self.button,
            foreground=lambda: self.fg,
            rect_of=lambda h: self.rects.get(h),
            snappable=lambda h: h in self.snappable,
            cursor_pos=lambda: self.cursor,
        )

    def window(self, hwnd, rect, snappable=True):
        self.rects[hwnd] = rect
        if snappable:
            self.snappable.add(hwnd)
        self.fg = hwnd

    def move_window(self, hwnd, dx, dy):
        l, t, r, b = self.rects[hwnd]
        self.rects[hwnd] = (l + dx, t + dy, r + dx, b + dy)


class HappyPath(unittest.TestCase):
    def test_arm_drag_drop(self):
        rig = Rig()
        rig.window(101, (100, 100, 500, 400))
        rig.shift = rig.button = True
        rig.cursor = (300, 120)

        self.assertIsNone(rig.tracker.sample())  # arms, no event yet
        self.assertEqual(rig.tracker.state, ARMED)

        rig.move_window(101, 30, 5)
        rig.cursor = (330, 125)
        self.assertEqual(rig.tracker.sample(), ("drag", 101, 330, 125))
        self.assertEqual(rig.tracker.state, DRAGGING)

        rig.cursor = (700, 900)
        self.assertEqual(rig.tracker.sample(), ("drag", 101, 700, 900))

        rig.button = False
        self.assertEqual(rig.tracker.sample(), ("drop", 101, 700, 900))
        self.assertEqual(rig.tracker.state, IDLE)

    def test_drop_even_if_shift_released_same_sample(self):
        # Simultaneous release of both keys within one poll = intent to drop.
        rig = Rig()
        rig.window(101, (0, 0, 400, 300))
        rig.shift = rig.button = True
        rig.tracker.sample()
        rig.move_window(101, 50, 0)
        rig.tracker.sample()
        rig.shift = rig.button = False
        rig.cursor = (200, 200)
        self.assertEqual(rig.tracker.sample(), ("drop", 101, 200, 200))


class Cancels(unittest.TestCase):
    def test_shift_release_mid_drag_cancels(self):
        rig = Rig()
        rig.window(101, (0, 0, 400, 300))
        rig.shift = rig.button = True
        rig.tracker.sample()
        rig.move_window(101, 50, 0)
        rig.tracker.sample()
        rig.shift = False  # button still down: user bailed out
        self.assertEqual(rig.tracker.sample(), ("cancel",))
        self.assertEqual(rig.tracker.state, IDLE)

    def test_window_vanishing_mid_drag_cancels(self):
        rig = Rig()
        rig.window(101, (0, 0, 400, 300))
        rig.shift = rig.button = True
        rig.tracker.sample()
        rig.move_window(101, 50, 0)
        rig.tracker.sample()
        rig.rects[101] = None
        self.assertEqual(rig.tracker.sample(), ("cancel",))

    def test_plain_click_never_drags(self):
        rig = Rig()
        rig.window(101, (0, 0, 400, 300))
        rig.shift = rig.button = True
        rig.tracker.sample()  # arms
        rig.button = False    # released without any movement
        self.assertIsNone(rig.tracker.sample())
        self.assertEqual(rig.tracker.state, IDLE)


class NeverArms(unittest.TestCase):
    def test_non_snappable_window(self):
        rig = Rig()
        rig.window(101, (0, 0, 400, 300), snappable=False)
        rig.shift = rig.button = True
        self.assertIsNone(rig.tracker.sample())
        self.assertEqual(rig.tracker.state, IDLE)

    def test_no_foreground_window(self):
        rig = Rig()
        rig.shift = rig.button = True
        self.assertIsNone(rig.tracker.sample())
        self.assertEqual(rig.tracker.state, IDLE)

    def test_jitter_below_threshold_stays_armed(self):
        rig = Rig()
        rig.window(101, (100, 100, 500, 400))
        rig.shift = rig.button = True
        rig.tracker.sample()
        rig.move_window(101, 2, 2)  # below the 4 px threshold
        self.assertIsNone(rig.tracker.sample())
        self.assertEqual(rig.tracker.state, ARMED)

    def test_in_app_shift_drag_never_triggers(self):
        # Shift+drag selecting text: chord held, window rect never moves.
        rig = Rig()
        rig.window(101, (100, 100, 500, 400))
        rig.shift = rig.button = True
        for _ in range(20):
            self.assertIsNone(rig.tracker.sample())
        self.assertEqual(rig.tracker.state, ARMED)  # armed but never DRAGGING


class Reset(unittest.TestCase):
    def test_reset_mid_drag_suppresses_stale_drop(self):
        # The HUD resets the tracker whenever the watch pauses (editor open,
        # all layouts off): a DRAGGING state frozen across the pause must not
        # replay as a drop at the stale hwnd once sampling resumes.
        rig = Rig()
        rig.window(101, (0, 0, 400, 300))
        rig.shift = rig.button = True
        rig.tracker.sample()
        rig.move_window(101, 50, 0)
        rig.tracker.sample()
        self.assertEqual(rig.tracker.state, DRAGGING)
        rig.tracker.reset()                    # pause
        rig.shift = rig.button = False         # user finished while paused
        self.assertIsNone(rig.tracker.sample())  # resume: no bogus drop
        self.assertEqual(rig.tracker.state, IDLE)


class Rearm(unittest.TestCase):
    def test_foreground_change_while_armed_rearms(self):
        rig = Rig()
        rig.window(101, (0, 0, 400, 300))
        rig.shift = rig.button = True
        rig.tracker.sample()
        rig.window(202, (500, 500, 900, 800))  # focus jumped to another window
        self.assertIsNone(rig.tracker.sample())
        rig.move_window(202, 10, 0)
        event = rig.tracker.sample()
        self.assertEqual(event[:2], ("drag", 202))


if __name__ == "__main__":
    unittest.main()
