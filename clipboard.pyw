"""Floating Clipboard manager.

A small, static, draggable clipboard icon (drawn in the pet's teal art style)
floats on screen. Right-click it (or press Ctrl+Shift+V) to open a two-column
panel: ALL (recent copies, in-memory) and FAVORITES (kept items, persisted to
favorites.json). Click a row's text to copy it and close. Star moves an item
between columns. Check rows in ALL (shift-click for ranges) to bulk-remove.
Left-drag the icon to move it. The panel header holds the capture toggle,
search, and a ≡ menu (clear history, run at login, hide, quit). Pure stdlib.
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winkit.startup as startup
startup.guard_streams()  # MUST be the first executable statement (pythonw-at-login safety)

import time
import tkinter as tk

import winkit.window as window
import winkit.input as wkinput
import clip_store
import clip_view
import config
import timeago
from selection import shift_range

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
LOG_PATH = os.path.join(HERE, "toybox.log")
FAV_PATH = os.path.join(HERE, "favorites.json")

CAPTURE_MS = 250
DRAG_THRESHOLD = 4

ICON = 44
KEY = window.KEY_COLOR

# Icon palette (teal clipboard, matching the pet).
IC_BODY = "#4ac4c4"
IC_BODY_DK = "#36a0a0"
IC_PAPER = "#eef7f7"
IC_LINE = "#9fc9c9"
IC_CLIP = "#2f8f8f"
IC_OUTLINE = "#1f3a3a"

# Panel theme (dark).
PANEL_BG = "#1e1f22"
COL_BG = "#212429"
ROW_HOVER = "#2a2e36"
SEL_BG = "#314059"
FG = "#e8e8e8"
DIM = "#8a8d92"
BORDER = "#3a3d42"
ENTRY_BG = "#2b2d31"
TEAL = "#4ac4c4"
STAR_ON = "#ffce4d"
STAR_OFF = "#70747a"
DEL_HOVER = "#e0695f"
CURRENT_BG = "#243b3b"   # teal-tinted row bg for the live-clipboard entry
CURRENT_BAR = TEAL       # left accent bar for the live-clipboard entry

COL_W = 300


def _smoke_ms():
    v = os.environ.get("TOYBOX_SMOKE")
    return int(v) if v else None


def _round_rect(canvas, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ---------------------------------------------------------------------------
class ClipPanel:
    """The two-column clipboard panel (a Toplevel built fresh on each open)."""

    def __init__(self, app):
        self.app = app
        self.store = app.store
        self._selected = set()   # texts checked in ALL
        self._anchor = None      # index in the current ALL view (for shift-select)
        self._all_texts = []     # texts currently shown in ALL (view order)
        self._suppress_close = False  # set while the options menu is open
        self._current = None     # text of the live system clipboard (for highlight)
        self.layout = clip_view.normalize_layout(app.cfg["clipboard"]["layout"])
        self.panel_w, self.panel_h = clip_view.panel_size(self.layout)

        win = tk.Toplevel(app.root)
        self.win = win
        win.overrideredirect(True)
        win.configure(bg=BORDER)
        win.attributes("-topmost", True)

        self.outer = tk.Frame(win, bg=PANEL_BG)
        self.outer.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_header(self.outer)

        self.footer = tk.Frame(self.outer, bg=PANEL_BG, height=34)
        self.footer.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        self.remove_btn = tk.Label(
            self.footer, text="", bg="#4a2b2b", fg="#ffd9d4",
            font=("Segoe UI", 9, "bold"), padx=10, pady=4, cursor="hand2")
        self.remove_btn.bind("<Button-1>", lambda e: self._remove_selected())

        self._build_body()

        win.bind("<Escape>", lambda e: self.close())
        win.bind("<FocusOut>", self._on_focus_out)
        self._place()
        win.deiconify()
        win.lift()
        win.focus_force()
        self.refresh()
        self.search.focus_set()

    # -- chrome -----------------------------------------------------------
    def _build_header(self, parent):
        hdr = tk.Frame(parent, bg=PANEL_BG)
        hdr.pack(fill="x", padx=8, pady=(8, 6))

        self.cap_lbl = tk.Label(hdr, bg=PANEL_BG, font=("Segoe UI", 10),
                                cursor="hand2")
        self.cap_lbl.pack(side="left")
        self.cap_lbl.bind("<Button-1>", lambda e: self._toggle_capture())
        self._render_capture()

        close = tk.Label(hdr, text="✕", bg=PANEL_BG, fg=DIM,
                         font=("Segoe UI", 11), cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.close())
        close.bind("<Enter>", lambda e: close.config(fg=DEL_HOVER))
        close.bind("<Leave>", lambda e: close.config(fg=DIM))

        burger = tk.Label(hdr, text="≡", bg=PANEL_BG, fg=DIM,
                          font=("Segoe UI", 13), cursor="hand2")
        burger.pack(side="right", padx=(0, 8))
        burger.bind("<Button-1>", lambda e: self._open_options(burger))
        burger.bind("<Enter>", lambda e: burger.config(fg=FG))
        burger.bind("<Leave>", lambda e: burger.config(fg=DIM))

        self.layout_btn = tk.Label(hdr, bg=PANEL_BG, fg=DIM,
                                   font=("Segoe UI", 12), cursor="hand2")
        self.layout_btn.pack(side="right", padx=(0, 8))
        self.layout_btn.bind("<Button-1>", lambda e: self._toggle_layout())
        self.layout_btn.bind("<Enter>", lambda e: self.layout_btn.config(fg=FG))
        self.layout_btn.bind("<Leave>", lambda e: self.layout_btn.config(fg=DIM))
        self._render_layout_btn()

        self.search_var = tk.StringVar()
        self.search = tk.Entry(hdr, textvariable=self.search_var, bg=ENTRY_BG,
                               fg=FG, insertbackground=FG, relief="flat",
                               font=("Segoe UI", 10), highlightthickness=1,
                               highlightbackground=BORDER, highlightcolor=TEAL)
        self.search.pack(side="right", padx=8, ipady=3, fill="x", expand=True)
        self.search_var.trace_add("write", lambda *_: self.refresh())

    def _build_body(self):
        self.body = tk.Frame(self.outer, bg=PANEL_BG)
        self.body.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        if self.layout == "stacked":
            self.all_inner, self.all_canvas = self._build_column(
                self.body, "ALL", "top", False)
            self.fav_inner, self.fav_canvas = self._build_column(
                self.body, "FAVORITES", "bottom", False)
        else:
            self.all_inner, self.all_canvas = self._build_column(
                self.body, "ALL", "left", True)
            self.fav_inner, self.fav_canvas = self._build_column(
                self.body, "FAVORITES", "right", True)

    def _render_layout_btn(self):
        # Glyph reflects the CURRENT layout: stacked rows vs. side-by-side columns.
        self.layout_btn.config(text="▤" if self.layout == "stacked" else "▥")

    def _rebuild_body(self):
        try:
            self.win.unbind_all("<MouseWheel>")
            self.win.unbind_all("<Shift-MouseWheel>")
        except tk.TclError:
            pass
        try:
            self.body.destroy()
        except tk.TclError:
            pass
        self._build_body()
        self.refresh()

    def _toggle_layout(self):
        self.layout = clip_view.next_layout(self.layout)
        self.app.cfg["clipboard"]["layout"] = self.layout
        self.app.save_cfg()
        self.panel_w, self.panel_h = clip_view.panel_size(self.layout)
        self._place()
        self._rebuild_body()
        self._render_layout_btn()

    def _build_column(self, parent, title, side, fixed_width):
        col = tk.Frame(parent, bg=COL_BG)
        if fixed_width:
            col.configure(width=COL_W)
            col.pack(side=side, fill="both", expand=True,
                     padx=(0, 6) if side == "left" else (6, 0))
            col.pack_propagate(False)
        else:
            col.pack(side=side, fill="both", expand=True,
                     pady=(0, 6) if side == "top" else (6, 0))
        tk.Label(col, text=title, bg=COL_BG, fg=DIM, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=8, pady=(6, 2))

        wrap = tk.Frame(col, bg=COL_BG)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=COL_BG, highlightthickness=0)
        vsb = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        hsb = tk.Scrollbar(wrap, orient="horizontal", command=canvas.xview)
        inner = tk.Frame(canvas, bg=COL_BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        def _sync(_e=None):
            # Stretch the inner frame to fill the viewport when its content is
            # smaller, so the scrollregion never drops below the canvas size and
            # the scrollbars stay inert until content actually overflows.
            vw, vh = canvas.winfo_width(), canvas.winfo_height()
            w = max(inner.winfo_reqwidth(), vw)
            h = max(inner.winfo_reqheight(), vh)
            canvas.itemconfigure(win_id, width=w, height=h)
            canvas.configure(scrollregion=(0, 0, w, h))

        inner.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        def vwheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")

        def hwheel(e):
            canvas.xview_scroll(int(-e.delta / 120), "units")

        def on_enter(e, c=canvas, v=vwheel, h=hwheel):
            c.bind_all("<MouseWheel>", v)
            c.bind_all("<Shift-MouseWheel>", h)

        def on_leave(e, c=canvas):
            c.unbind_all("<MouseWheel>")
            c.unbind_all("<Shift-MouseWheel>")

        for w in (canvas, inner):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
        return inner, canvas

    def _place(self):
        self.win.update_idletasks()
        ix, iy = self.app.root.winfo_x(), self.app.root.winfo_y()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = ix + ICON + 8
        if x + self.panel_w > sw:
            x = ix - self.panel_w - 8
        x = max(8, min(x, sw - self.panel_w - 8))
        y = max(8, min(iy, sh - self.panel_h - 8))
        self.win.geometry("%dx%d+%d+%d" % (self.panel_w, self.panel_h, x, y))

    # -- rendering --------------------------------------------------------
    def refresh(self):
        needle = self.search_var.get().lower()
        self._current = self._current_clip()
        for inner in (self.all_inner, self.fav_inner):
            for child in inner.winfo_children():
                child.destroy()

        recent = [e for e in self.store.recent() if needle in e["text"].lower()]
        favs = [e for e in self.store.favorites() if needle in e["text"].lower()]
        self._all_texts = [e["text"] for e in recent]
        self._selected &= set(self._all_texts)

        if not recent:
            self._empty(self.all_inner, "nothing copied yet" if not needle else "no matches")
        for i, e in enumerate(recent):
            self._all_row(i, e)
        if not favs:
            self._empty(self.fav_inner, "star items to keep them" if not needle else "no matches")
        for e in favs:
            self._fav_row(e)
        self._render_remove()
        for c in (self.all_canvas, self.fav_canvas):
            try:
                c.xview_moveto(0)
            except tk.TclError:
                pass

    def _empty(self, parent, msg):
        tk.Label(parent, text="  " + msg, bg=COL_BG, fg=DIM,
                 anchor="w", font=("Segoe UI", 9, "italic")).pack(fill="x", pady=6)

    def _base_bg(self, text, is_current):
        if text in self._selected:
            return SEL_BG
        if is_current:
            return CURRENT_BG
        return COL_BG

    def _row_frame(self, parent, text, is_current):
        bg = self._base_bg(text, is_current)
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=1)
        accent = tk.Frame(row, bg=(CURRENT_BAR if is_current else bg), width=3)
        accent.pack(side="left", fill="y")

        def hover(on):
            b = ROW_HOVER if on else self._base_bg(text, is_current)
            row.config(bg=b)
            for c in row.winfo_children():
                if isinstance(c, tk.Label):
                    c.config(bg=b)
            accent.config(bg=(CURRENT_BAR if is_current else b))
        row.bind("<Enter>", lambda e: hover(True))
        row.bind("<Leave>", lambda e: hover(False))
        return row, bg

    def _icon_btn(self, row, glyph, color, bg, cmd, side="left"):
        b = tk.Label(row, text=glyph, bg=bg, fg=color, width=2,
                     font=("Segoe UI", 10), cursor="hand2")
        b.pack(side=side)
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def _time_lbl(self, row, entry, bg):
        ago = timeago.format_ago(time.time() - entry["time"])
        tk.Label(row, text=ago, bg=bg, fg=DIM, width=8, anchor="w",
                 font=("Segoe UI", 8)).pack(side="left")

    def _len_lbl(self, row, entry, bg):
        tk.Label(row, text=str(len(entry["text"])), bg=bg, fg=DIM, width=5,
                 anchor="w", font=("Segoe UI", 8)).pack(side="left")

    def _text_lbl(self, row, entry, bg):
        txt = tk.Label(row, text=clip_view.flatten_line(entry["text"]), bg=bg,
                       fg=FG, anchor="w", font=("Consolas", 9), cursor="hand2")
        txt.pack(side="left")
        txt.bind("<Button-1>", lambda e, t=entry["text"]: self._copy_and_close(t))
        return txt

    def _all_row(self, index, entry):
        text = entry["text"]
        is_current = (text == self._current)
        row, bg = self._row_frame(self.all_inner, text, is_current)
        chk = tk.Label(row, text="☑" if text in self._selected else "☐", bg=bg,
                       fg=TEAL if text in self._selected else STAR_OFF,
                       font=("Segoe UI", 10), cursor="hand2")
        chk.pack(side="left", padx=(2, 0))
        chk.bind("<Button-1>", lambda e, i=index, t=text: self._on_check(i, t, e))
        star = tk.Label(row, text="☆", bg=bg, fg=STAR_OFF, width=2,
                        font=("Segoe UI", 10), cursor="hand2")
        star.pack(side="left")
        star.bind("<Button-1>", lambda e, t=text: self._favorite(t))
        self._icon_btn(row, "✕", DIM, bg, lambda t=text: self._delete(t))
        self._time_lbl(row, entry, bg)
        self._len_lbl(row, entry, bg)
        self._text_lbl(row, entry, bg)

    def _fav_row(self, entry):
        text = entry["text"]
        is_current = (text == self._current)
        row, bg = self._row_frame(self.fav_inner, text, is_current)
        self._icon_btn(row, "★", STAR_ON, bg, lambda t=text: self._unfavorite(t))
        self._icon_btn(row, "✕", DIM, bg, lambda t=text: self._delete(t))
        self._time_lbl(row, entry, bg)
        self._len_lbl(row, entry, bg)
        self._text_lbl(row, entry, bg)

    def _render_remove(self):
        n = len(self._selected)
        if n:
            self.remove_btn.config(text="Remove selected (%d)" % n)
            self.remove_btn.pack(side="left")
        else:
            self.remove_btn.pack_forget()

    def _render_capture(self):
        on = bool(self.app.cfg["clipboard"]["capture"])
        self.cap_lbl.config(text=("⏻ capture on" if on else "⏻ capture off"),
                            fg=(TEAL if on else DIM))

    # -- actions ----------------------------------------------------------
    def _current_clip(self):
        try:
            t = self.app.root.clipboard_get()
        except tk.TclError:
            return None
        return t if t and t.strip() else None

    def _copy_and_close(self, text):
        try:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(text)
            self.app.absorb_seq()
        except tk.TclError:
            pass
        self.close()

    def _favorite(self, text):
        self.store.favorite(text)
        self.refresh()

    def _unfavorite(self, text):
        self.store.unfavorite(text)
        self.refresh()

    def _delete(self, text):
        self.store.delete(text)
        self._selected.discard(text)
        self.refresh()

    def _on_check(self, index, text, event):
        if event.state & 0x0001 and self._anchor is not None:  # Shift
            for j in shift_range(self._anchor, index):
                if 0 <= j < len(self._all_texts):
                    self._selected.add(self._all_texts[j])
        else:
            if text in self._selected:
                self._selected.discard(text)
            else:
                self._selected.add(text)
            self._anchor = index
        self.refresh()

    def _remove_selected(self):
        if not self._selected:
            return
        self.store.delete_many(list(self._selected))
        self._selected.clear()
        self._anchor = None
        self.refresh()

    def _toggle_capture(self):
        self.app.cfg["clipboard"]["capture"] = not self.app.cfg["clipboard"]["capture"]
        self.app.save_cfg()
        self._render_capture()

    def _open_options(self, widget):
        app = self.app
        self._suppress_close = True
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label="Clear history (All)", command=app._clear_history)
        m.add_separator()
        enabled = startup.is_run_at_startup("Toybox_clipboard")
        m.add_command(label="✓ Run at login" if enabled else "Run at login",
                      command=app._toggle_startup)
        m.add_separator()
        if app.icon_visible:
            m.add_command(label="Hide icon", command=lambda: (self.close(), app.hide_icon()))
        else:
            m.add_command(label="Show icon", command=app.show_icon)
        m.add_command(label="Quit", command=app.root.destroy)
        try:
            m.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())
        finally:
            try:
                m.grab_release()
                if self.win.winfo_exists():
                    self.win.after(200, lambda: setattr(self, "_suppress_close", False))
            except tk.TclError:
                pass

    def _on_focus_out(self, event):
        if self._suppress_close:
            return
        try:
            if self.win.focus_get() is None:
                self.close()
        except (KeyError, tk.TclError):
            pass

    def close(self):
        self.app.panel = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
class ClipboardApp:
    def __init__(self, root, store, cfg):
        self.root = root
        self.store = store
        self.cfg = cfg
        self.panel = None
        self.icon_visible = True

        root.overrideredirect(True)
        root.configure(bg=KEY)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", KEY)
        self._place_icon()

        self.canvas = tk.Canvas(root, width=ICON, height=ICON, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._draw_icon()

        root.update()
        self._apply_styles()

        self._moved = False
        self._dx = self._dy = 0
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", lambda e: self.open_panel())  # right-click opens panel
        self.canvas.configure(cursor="hand2")

        # clipboard capture
        try:
            existing = root.clipboard_get()
            if existing and existing.strip():
                store.add(existing, time.time())
        except tk.TclError:
            pass
        self._last_seq = wkinput.clipboard_sequence()
        self._poll()

        try:
            self.hotkey = wkinput.HotkeyPoller(root, cfg["clipboard"]["hotkey"],
                                               self.open_panel, 66)
        except (ValueError, TypeError):
            self.hotkey = wkinput.HotkeyPoller(root, config.DEFAULTS["clipboard"]["hotkey"],
                                               self.open_panel, 66)

    # -- icon -------------------------------------------------------------
    def _place_icon(self):
        c = self.cfg["clipboard"]
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = c["x"] if c["x"] is not None else sw - ICON - 24
        y = c["y"] if c["y"] is not None else sh - ICON - 80
        x = max(0, min(int(x), sw - ICON))
        y = max(0, min(int(y), sh - ICON))
        self.root.geometry("%dx%d+%d+%d" % (ICON, ICON, x, y))

    def _apply_styles(self):
        window.apply_overlay_styles(self.root, clickthrough=False, no_activate=True)

    def hide_icon(self):
        self.icon_visible = False
        self.root.withdraw()

    def show_icon(self):
        self.icon_visible = True
        self.root.deiconify()
        self.root.update_idletasks()
        self._apply_styles()  # re-assert ex-styles after re-showing

    def _draw_icon(self):
        c = self.canvas
        _round_rect(c, 7, 9, 37, 41, 5, fill=IC_BODY, outline=IC_OUTLINE, width=2)
        _round_rect(c, 11, 13, 33, 37, 3, fill=IC_PAPER, outline="")
        for i in range(3):
            y = 19 + i * 5
            c.create_line(15, y, 29, y, fill=IC_LINE, width=2)
        _round_rect(c, 16, 5, 28, 14, 3, fill=IC_CLIP, outline=IC_OUTLINE, width=2)

    def _press(self, e):
        self._moved = False
        self._dx = e.x_root - self.root.winfo_x()
        self._dy = e.y_root - self.root.winfo_y()
        self._sx, self._sy = e.x_root, e.y_root

    def _drag(self, e):
        if abs(e.x_root - self._sx) + abs(e.y_root - self._sy) > DRAG_THRESHOLD:
            self._moved = True
        if self._moved:
            self.root.geometry("+%d+%d" % (e.x_root - self._dx, e.y_root - self._dy))

    def _release(self, e):
        if self._moved:
            self.cfg["clipboard"]["x"] = self.root.winfo_x()
            self.cfg["clipboard"]["y"] = self.root.winfo_y()
            self.save_cfg()
        # a plain left-click does nothing; right-click opens the panel

    # -- panel ------------------------------------------------------------
    def toggle_panel(self):
        if self.panel is not None and self.panel.win.winfo_exists():
            self.panel.close()
        else:
            self.open_panel()

    def open_panel(self):
        if self.panel is not None and self.panel.win.winfo_exists():
            self.panel.close()
        self.panel = ClipPanel(self)

    # -- utility actions (invoked from the panel's menu) ------------------
    def _toggle_capture(self):
        self.cfg["clipboard"]["capture"] = not self.cfg["clipboard"]["capture"]
        self.save_cfg()
        if self.panel is not None and self.panel.win.winfo_exists():
            self.panel._render_capture()

    def _clear_history(self):
        self.store.clear_recent()
        if self.panel is not None and self.panel.win.winfo_exists():
            self.panel.refresh()

    def _toggle_startup(self):
        enabled = startup.is_run_at_startup("Toybox_clipboard")
        startup.set_run_at_startup("Toybox_clipboard", os.path.abspath(__file__), not enabled)

    # -- capture loop -----------------------------------------------------
    def absorb_seq(self):
        self._last_seq = wkinput.clipboard_sequence()

    def _poll(self):
        try:
            seq = wkinput.clipboard_sequence()
            if seq != self._last_seq:
                self._last_seq = seq
                if self.cfg["clipboard"]["capture"]:
                    try:
                        text = self.root.clipboard_get()
                    except tk.TclError:
                        text = None
                    if text:
                        self.store.add(text, time.time())
        finally:
            self.root.after(CAPTURE_MS, self._poll)

    def save_cfg(self):
        try:
            config.save(CFG_PATH, self.cfg)
        except Exception:
            pass


def _smoke_exercise(app):
    """Seed a long entry, point the live clipboard at it (highlight path), open
    the panel and toggle its layout, so both layouts' build paths execute."""
    long_text = "lorem ipsum dolor sit amet " * 8  # ~216 chars, one line
    app.store.add(long_text, time.time())
    try:
        app.root.clipboard_clear()
        app.root.clipboard_append(long_text)
    except tk.TclError:
        pass
    app.open_panel()
    panel = app.panel
    if panel is not None:
        app.root.after(300, panel._toggle_layout)


def main():
    if not _smoke_ms() and not startup.acquire_single_instance("Toybox_clipboard"):
        return
    cfg = config.load(CFG_PATH)
    store = clip_store.ClipStore(cfg["clipboard"]["max_items"], FAV_PATH)

    window.enable_dpi_awareness()
    root = tk.Tk()
    app = ClipboardApp(root, store, cfg)
    startup.watch_for_quit("Toybox_clipboard", root.after, root.destroy)

    ms = _smoke_ms()
    if ms:
        if os.environ.get("TOYBOX_SMOKE_PANEL"):
            _smoke_exercise(app)
        root.after(ms, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        raise
