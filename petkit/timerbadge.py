"""Persistent focus-timer badge: a small always-on-top countdown that floats
just above the cat while a Pomodoro focus/break/pause is running. Mirrors the
speech-bubble window technique (transparent overrideredirect Toplevel, rounded
rect + text on a Canvas) and reuses bubble.bubble_xy for placement. The label
(badge_text) is a pure function and is unit-tested; the rest is GUI glue guarded
against TclError like bubble.py. Stdlib only."""
import tkinter as tk
import tkinter.font as tkfont

import petkit.bubble as bubble
import winkit.window as window

PAD = 6
BADGE_FILL = "#222831"
TEXT_FILL = "#f5f5f5"

_ICON = {"focus": "\U0001F3AF", "break": "☕", "paused": "⏸"}


def badge_text(state, remaining_s):
    """Pure label for the focus badge. 'focus'->'🎯 M:SS', 'break'->'☕ M:SS',
    'paused'->'⏸ M:SS'; any other state (e.g. 'idle') -> '' (badge hidden).
    remaining_s is clamped at 0."""
    icon = _ICON.get(state)
    if icon is None:
        return ""
    rem = int(remaining_s)
    if rem < 0:
        rem = 0
    m, s = divmod(rem, 60)
    return "%s %d:%02d" % (icon, m, s)


class TimerBadge:
    def __init__(self, root, head_offset=0):
        self.root = root
        self.head_offset = head_offset
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg=window.KEY_COLOR)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", window.KEY_COLOR)
        self.canvas = tk.Canvas(self.win, highlightthickness=0, bd=0,
                                bg=window.KEY_COLOR)
        self.canvas.pack()
        self.font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._shown = False
        self.win.withdraw()

    def show(self, text):
        if not text:
            self.hide()
            return
        tw = self.font.measure(text)
        th = self.font.metrics("linespace")
        w, h = tw + 2 * PAD, th + 2 * PAD
        try:
            self.canvas.configure(width=w, height=h)
            self.canvas.delete("all")
            self._round_rect(0, 0, w, h, 7, fill=BADGE_FILL)
            self.canvas.create_text(w / 2, h / 2, text=text, fill=TEXT_FILL,
                                    font=self.font)
            self.root.update_idletasks()
            rx, ry = bubble.bubble_xy(self.root.winfo_rootx(),
                                      self.root.winfo_rooty(),
                                      self.root.winfo_width(),
                                      self.head_offset, w, h)
            self.win.geometry("%dx%d+%d+%d" % (w, h, rx, ry))
            if not self._shown:
                self.win.deiconify()
                self.win.lift()                 # lift once; later bubbles stay above
                self._shown = True
        except tk.TclError:
            pass

    def hide(self):
        if not self._shown:
            return
        self._shown = False
        try:
            self.win.withdraw()
        except tk.TclError:
            pass

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
