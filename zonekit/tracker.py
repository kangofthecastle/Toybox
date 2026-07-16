"""Drag-watch state machine: detects a title-bar drag of a snappable window.

Zones activate on a PLAIN drag (no modifier); holding Shift while dragging is
the opt-out that suppresses snapping so a window can be placed freely
(FancyZones' "activate on drag" behavior). Releasing Shift mid-drag resumes.

All inputs are injected callables so the machine is pure logic (unit-testable
with synthetic sequences) and the HUD wires in the real winkit functions.
Sampled every ~60 ms from the HUD tick; each sample() returns one event or None:

    ("drag", hwnd, x, y)   a drag is in progress (every sample, incl. first)
    ("drop", hwnd, x, y)   the button was released mid-drag -> snap here
    ("cancel",)            suppressed (Shift) / window vanished -> hide overlay

Arming requires the *window rect origin to actually move* while the primary
button is down, so clicks and in-app drags (text selection, scrollbars, canvas
tools) never trigger.
"""

IDLE = "idle"
ARMED = "armed"
DRAGGING = "dragging"
SUPPRESSED = "suppressed"

#: Minimum window-origin travel (px) between samples to count as a real drag.
MOVE_THRESHOLD = 4


class DragTracker:
    def __init__(self, *, suppress_down, button_down, foreground, rect_of,
                 snappable, cursor_pos, move_threshold=MOVE_THRESHOLD):
        self._suppress_down = suppress_down
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
        button = self._button_down()

        if self._state == IDLE:
            if button:
                self._try_arm()
            return None

        if not button:
            # Button released: only a live (unsuppressed) drag becomes a drop.
            dragging, hwnd = (self._state == DRAGGING), self._hwnd
            self.reset()
            if dragging:
                x, y = self._cursor_pos()
                return ("drop", hwnd, x, y)
            return None

        if self._state == ARMED:
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
                if self._suppress_down():
                    self._state = SUPPRESSED
                    return None
                self._state = DRAGGING
                x, y = self._cursor_pos()
                return ("drag", self._hwnd, x, y)
            return None

        if self._state == DRAGGING:
            if self._rect_of(self._hwnd) is None:
                self.reset()
                return ("cancel",)
            if self._suppress_down():          # Shift pressed mid-drag: opt out
                self._state = SUPPRESSED
                return ("cancel",)
            x, y = self._cursor_pos()
            return ("drag", self._hwnd, x, y)

        # SUPPRESSED: still dragging, snapping opted out; Shift release resumes.
        if self._rect_of(self._hwnd) is None:
            self.reset()
            return None
        if not self._suppress_down():
            self._state = DRAGGING
            x, y = self._cursor_pos()
            return ("drag", self._hwnd, x, y)
        return None

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
