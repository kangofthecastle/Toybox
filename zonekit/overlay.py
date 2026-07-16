"""Translucent zone overlays: the drag-time snap overlay and the divider editor.

Both are borderless, topmost, uniformly translucent toplevels covering one
monitor's work area. The snap overlay is fully click-through + no-activate so
it can never interfere with the drag in progress; the divider editor is
interactive (it takes focus so Esc works) and lives only until commit/cancel.
Ex-styles follow docs/superpowers/specs/2026-06-24-native-gotchas.md section 1:
realize the HWND first, style, then show.
"""
import tkinter as tk

import winkit.window as window
from zonekit import geometry

BG = "#15151a"          # matches the HUD
ZONE_FILL = "#23232e"
HOVER_FILL = "#123c4d"  # hovered zone: dark cyan wash
ACCENT = "#33d6ff"
EDGE = "#4a4a58"
HINT_FG = "#d8d8e0"
HINT_FONT = ("Consolas", 11)
ALPHA_SNAP = 0.40
ALPHA_EDIT = 0.45
DIVIDER_HALF = 3        # divider handle half-thickness (px)


class _Overlay:
    """Base: a translucent toplevel covering `work` ((l, t, r, b) screen px)."""

    def __init__(self, root, work, alpha, *, clickthrough, no_activate):
        self.work = work
        left, top, right, bottom = work
        self.top = tk.Toplevel(root)
        try:
            self.top.withdraw()           # style before first show: no flash
            self.top.overrideredirect(True)
            self.top.attributes("-topmost", True)
            self.top.attributes("-alpha", alpha)
            self.top.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
            self.canvas = tk.Canvas(self.top, bg=BG, highlightthickness=0, bd=0)
            self.canvas.pack(fill="both", expand=True)
            self.top.update()             # realize the HWND before ex-styles
            window.apply_overlay_styles(
                self.top, clickthrough=clickthrough, no_activate=no_activate)
            self.top.deiconify()
        except Exception:
            self.destroy()                # never leak a screen-covering toplevel
            raise

    def _local(self, rect):
        """Screen rect -> canvas-local rect (the canvas origin is work's l, t)."""
        left, top = self.work[0], self.work[1]
        return (rect[0] - left, rect[1] - top, rect[2] - left, rect[3] - top)

    @property
    def _local_work(self):
        left, top, right, bottom = self.work
        return (0, 0, right - left, bottom - top)

    def destroy(self):
        try:
            self.top.destroy()
        except tk.TclError:
            pass


class SnapOverlay(_Overlay):
    """The two drop targets shown while a Shift-drag is in progress."""

    def __init__(self, root, monitor, layout, ratio):
        super().__init__(root, monitor["work"], ALPHA_SNAP,
                         clickthrough=True, no_activate=True)
        self.device = monitor["device"]
        self.layout = layout
        self.ratio = ratio
        self._hover = None
        self._items = [
            self.canvas.create_rectangle(*self._local(rect), fill=ZONE_FILL,
                                         outline=EDGE, width=2)
            for rect in geometry.zone_rects(monitor["work"], layout, ratio)
        ]

    def highlight(self, index):
        """Tint zone `index` (0/1) as the drop target; None clears both."""
        if index == self._hover:
            return
        self._hover = index
        for i, item in enumerate(self._items):
            active = (i == index)
            self.canvas.itemconfig(
                item, fill=(HOVER_FILL if active else ZONE_FILL),
                outline=(ACCENT if active else EDGE))


class DividerEditor(_Overlay):
    """Interactive ratio editor: drag the divider, release to commit, Esc/right-
    click to cancel. Exactly one of on_commit(ratio) / on_cancel() fires."""

    def __init__(self, root, monitor, layout, ratio, on_commit, on_cancel):
        super().__init__(root, monitor["work"], ALPHA_EDIT,
                         clickthrough=False, no_activate=False)
        self.layout = layout
        self.ratio = geometry.clamp_ratio(ratio)
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        self._done = False
        self._z0 = self.canvas.create_rectangle(0, 0, 0, 0, fill=ZONE_FILL, outline="")
        self._z1 = self.canvas.create_rectangle(0, 0, 0, 0, fill=ZONE_FILL, outline="")
        self._div = self.canvas.create_rectangle(0, 0, 0, 0, fill=ACCENT, outline="")
        w = self._local_work
        self._hint = self.canvas.create_text(
            w[2] // 2, min(60, w[3] // 8),
            text="drag the divider  •  release to set  •  Esc cancels",
            fill=HINT_FG, font=HINT_FONT)
        self._redraw()
        self.canvas.bind("<Button-1>", self._drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._commit)
        self.canvas.bind("<Button-3>", self._cancel)
        self.top.bind("<Escape>", self._cancel)
        self.top.focus_force()            # so Esc reaches us

    def _redraw(self):
        z0, z1 = geometry.zone_rects(self._local_work, self.layout, self.ratio)
        self.canvas.coords(self._z0, *z0)
        self.canvas.coords(self._z1, *z1)
        pos = geometry.divider_pos(self._local_work, self.layout, self.ratio)
        w = self._local_work
        if self.layout == "v":
            self.canvas.coords(self._div, pos - DIVIDER_HALF, 0, pos + DIVIDER_HALF, w[3])
        else:
            self.canvas.coords(self._div, 0, pos - DIVIDER_HALF, w[2], pos + DIVIDER_HALF)
        self.canvas.tag_raise(self._hint)

    def _drag(self, event):
        self.ratio = geometry.ratio_from_point(self._local_work, self.layout,
                                               event.x, event.y)
        self._redraw()

    def _commit(self, _event):
        if self._done:
            return
        self._done = True
        self.destroy()
        self._on_commit(self.ratio)

    def _cancel(self, _event=None):
        if self._done:
            return
        self._done = True
        self.destroy()
        self._on_cancel()
