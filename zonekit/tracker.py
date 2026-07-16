"""Drag-watch state machine: detects a Shift+title-bar drag of a snappable window.

All inputs are injected callables so the machine is pure logic (unit-testable
with synthetic sequences) and the HUD wires in the real winkit functions.
Sampled every ~60 ms from the HUD tick; each sample() returns one event or None:

    ("drag", hwnd, x, y)   a Shift-drag is in progress (every sample, incl. first)
    ("drop", hwnd, x, y)   the button was released mid-drag -> snap here
    ("cancel",)            Shift released mid-drag / window vanished -> no snap

Arming requires the *window rect origin to actually move* while Shift and the
left button are down, so in-app Shift-drags (text selection etc.) never trigger.
"""

IDLE = "idle"
ARMED = "armed"
DRAGGING = "dragging"

#: Minimum window-origin travel (px) between samples to count as a real drag.
MOVE_THRESHOLD = 4


class DragTracker:
    def __init__(self, *, shift_down, button_down, foreground, rect_of,
                 snappable, cursor_pos, move_threshold=MOVE_THRESHOLD):
        self._shift_down = shift_down
        self._button_down = button_down
        self._foreground = foreground
        self._rect_of = rect_of
        self._snappable = snappable
        self._cursor_pos = cursor_pos
        self._threshold = move_threshold
        self._state = IDLE
        self._hwnd = None
        self._origin = None

    @property
    def state(self):
        return self._state

    def reset(self):
        self._state = IDLE
        self._hwnd = None
        self._origin = None

    def sample(self):
        shift = self._shift_down()
        button = self._button_down()

        if self._state == IDLE:
            if shift and button:
                self._try_arm()
            return None

        if self._state == ARMED:
            if not (shift and button):
                self.reset()  # plain click / chord abandoned before any movement
                return None
            hwnd = self._foreground()
            if hwnd != self._hwnd:
                self.reset()
                self._try_arm()
                return None
            rect = self._rect_of(hwnd)
            if rect is None:
                self.reset()
                return None
            if self._moved(rect):
                self._state = DRAGGING
                x, y = self._cursor_pos()
                return ("drag", self._hwnd, x, y)
            return None

        # DRAGGING
        if not button:
            hwnd = self._hwnd
            self.reset()
            x, y = self._cursor_pos()
            return ("drop", hwnd, x, y)
        if not shift or self._rect_of(self._hwnd) is None:
            self.reset()
            return ("cancel",)
        x, y = self._cursor_pos()
        return ("drag", self._hwnd, x, y)

    def _try_arm(self):
        hwnd = self._foreground()
        if not hwnd or not self._snappable(hwnd):
            return
        rect = self._rect_of(hwnd)
        if rect is None:
            return
        self._state = ARMED
        self._hwnd = hwnd
        self._origin = (rect[0], rect[1])

    def _moved(self, rect):
        dx = rect[0] - self._origin[0]
        dy = rect[1] - self._origin[1]
        return abs(dx) >= self._threshold or abs(dy) >= self._threshold
