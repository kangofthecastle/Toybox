"""Reusable transient speech bubble for the pet.

One :class:`Toplevel` is created once and reused for every message: ``say``
re-renders the text on its canvas, repositions the window above the pet, and
(re)schedules an auto-hide. The bubble is never created/destroyed per message.
Stdlib only (tkinter + winsound)."""

import tkinter as tk
import tkinter.font as tkfont
import winsound
import winkit.window as window

PAD = 8
BUBBLE_FILL = "#fffbe6"
TEXT_FILL = "#202020"


def bubble_xy(root_x, root_y, root_w, head_offset, w, h, gap=PAD):
    """Top-left (x, y) for a ``w`` x ``h`` bubble: centered horizontally over the
    pet window and resting ``gap`` px above the cat's head.

    ``head_offset`` is the distance in px from the window's top edge down to the
    cat's head line. The window is much taller than the sprite (it holds the glow
    aura padding), so anchoring to the window top floats the bubble far above the
    cat; offsetting by the head line keeps it tucked just over the cat's head.
    ``head_offset=0`` reproduces the old window-top anchor."""
    x = root_x + root_w // 2 - w // 2
    y = root_y + head_offset - h - gap
    return x, y


class Bubble:
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
        self.font = tkfont.Font(family="Segoe UI", size=10)
        self._hide_id = None
        self.win.withdraw()

    def say(self, text, secs=3, chime=False):
        tw = self.font.measure(text)
        th = self.font.metrics("linespace")
        w, h = tw + 2 * PAD, th + 2 * PAD
        self.canvas.configure(width=w, height=h)
        self.canvas.delete("all")
        self._round_rect(0, 0, w, h, 8, fill=BUBBLE_FILL)
        self.canvas.create_text(w / 2, h / 2, text=text, fill=TEXT_FILL,
                                font=self.font)
        self.root.update_idletasks()
        rx, ry = bubble_xy(self.root.winfo_rootx(), self.root.winfo_rooty(),
                           self.root.winfo_width(), self.head_offset, w, h)
        self.win.geometry("%dx%d+%d+%d" % (w, h, rx, ry))
        self.win.deiconify()
        self.win.lift()
        if chime:
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        if self._hide_id is not None:
            try:
                self.root.after_cancel(self._hide_id)
            except Exception:
                pass
        self._hide_id = self.root.after(int(secs * 1000), self._hide)

    def _hide(self):
        self._hide_id = None
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
