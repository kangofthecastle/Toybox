"""System Monitor HUD: a borderless, semi-transparent, always-on-top overlay
showing live CPU%, RAM%, a clock, and scrolling sparklines. Draggable (unless
locked); right-click for opacity presets, lock, and close. Updates at 1 Hz.
Pure Python 3.12 stdlib."""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winkit.startup as startup
startup.guard_streams()  # MUST be the first executable statement (pythonw-at-login safety)

import collections
import threading
import time

import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as tkmsg
import winkit.window as window
import winkit.metrics as metrics
import winkit.media as media
import winkit.nowplaying as nowplaying
import winkit.diskinfo as diskinfo
import config
import webbrowser
import timeago
import feedkit.manager as feedmanager
import feedkit.model as feedmodel
import schedkit.xlsx as schedxlsx
import schedkit.model as schedmodel
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
LOG_PATH = os.path.join(HERE, "toybox.log")

# Layout (logical px). Kept genuinely small per the lightweight requirement.
WIDTH = 220
NOWPLAYING_H = 20      # reserved band under the media row: title line + progress bar
NP_BAR_H = 3           # progress-bar thickness (px)
HEIGHT = 156 + NOWPLAYING_H   # 6 header rows + reserved now-playing band + margin
WIDTH_WIDE = 440       # the "expanded" fixed width (2x narrow; session-only toggle)
PAD = 10
ROW_H = 22
LABEL_X = PAD
SPARK_W = 84            # fixed-width sparkline area
SPARK_RIGHT = WIDTH - PAD
SPARK_LEFT = SPARK_RIGHT - SPARK_W
DISK_MAX_CHARS = 26    # cap for the packed disk-free header row (narrow width)
HISTORY = 60           # ~60 samples in the deque

# Edge-peek dock-to-edge (Feature 6). All session-only, like the width toggle.
DOCK_THRESHOLD = 24    # px from a screen edge (on drop) that triggers docking
DOCK_LIP = 6           # px of the window left peeking when docked and hidden
DOCK_ANIM_MS = 30      # per-frame delay of the slide animation
DOCK_ANIM_STEPS = 4    # frames per slide (reveal or hide)

BG = "#15151a"         # dark translucent background
FG = "#d8d8e0"         # light text
DIM = "#6a6a78"        # clock / faint text
CPU_COLOR = "#33d6ff"  # cyan
RAM_COLOR = "#ff5cc8"  # magenta
GPU_COLOR = "#7ee787"  # green
FONT = ("Consolas", 11)
CLOCK_FONT = ("Consolas", 11, "bold")
EXPAND_FONT = ("Consolas", 15, "bold")   # larger glyph for the width toggle
MEDIA_FONT = ("Segoe UI Symbol", 12)
MEDIA_PREV = "⏮"
MEDIA_PLAY = "⏯"
MEDIA_NEXT = "⏭"
NP_TITLE_FONT = ("Consolas", 9)
NP_TRACK = "#2b2b34"   # progress-bar track (unfilled) colour
NP_POLL_S = 2.5        # background SMTC read interval (seconds)

FEED_FONT = ("Consolas", 9)
FEED_TITLE_FONT = ("Consolas", 9, "bold")
FEED_FG = "#c8c8d4"
FEED_DIM = "#6a6a78"
FEED_LINE_H = 15          # px per feed line
FEED_TITLE_GAP = 4        # px above each feed block
FEED_MAX_CHARS = 30       # truncate any feed text (title or item) to fit 220px
STATE_HEX = {"success": "#3fb950", "failure": "#f85149",
             "pending": "#d29922", "none": "#6a6a78"}
STOCK_UP = "#3fb950"       # green: day change >= 0
STOCK_DOWN = "#f85149"     # red: day change < 0
STOCK_CHART_H = 20         # px per drawn price-chart row
ACCENT = "#33d6ff"         # cyan: active-tab + active range-toggle indicator
HOVER_BG = "#24242e"       # subtle highlight band behind the hovered row/tab
URGENCY_HEX = {"high": STATE_HEX["pending"], "normal": FEED_FG, "low": FEED_DIM}
DISMISS_GLYPH = "✕"   # ✕  per-item mark-read
MARKALL_GLYPH = "✓"   # ✓  header mark-all-read
RELOAD_GLYPH = "⟳"    # ⟳  refresh all feeds (right end of the header)
EXPAND_GLYPH = "↔"    # ↔  toggle narrow(220) <-> wide(440)
ACTION_ZONE_W = 18         # px hit target at the right edge for ✕ / ✓


def _fit(text):
    """Truncate any feed line/title to FEED_MAX_CHARS so a long headline or repo
    name can't overflow the 220px width."""
    return text if len(text) <= FEED_MAX_CHARS else text[:FEED_MAX_CHARS - 1] + "…"


def _stock_points(series, x_left, x_right, top, bottom):
    """Polyline coords for a price series scaled by its own min->max (min at the
    bottom edge, max at the top edge), spread evenly across [x_left, x_right].
    Returns [] for <2 points; a flat series draws a horizontal midline. Unlike
    _update_spark this is min/max-scaled because prices are not 0..100."""
    n = len(series)
    if n < 2:
        return []
    lo, hi = min(series), max(series)
    span = hi - lo
    mid = (top + bottom) / 2.0
    dx = (x_right - x_left) / (n - 1)
    pts = []
    for i, v in enumerate(series):
        x = x_left + i * dx
        y = mid if span <= 0 else bottom - (v - lo) / span * (bottom - top)
        pts.extend((x, y))
    return pts


def edge_for(x, y, w, h, sw, sh, threshold):
    """Which screen edge a window at (x, y) sized (w, h) on an sw x sh screen is
    within `threshold` px of, or None. Ties (a corner) resolve to the nearest,
    scanning left, right, top, bottom so a perfect tie prefers the earlier edge.
    A window dragged partly off-screen (negative gap) still counts as docked."""
    gaps = {
        "left": x,
        "right": sw - (x + w),
        "top": y,
        "bottom": sh - (y + h),
    }
    best = None
    for edge in ("left", "right", "top", "bottom"):
        gap = gaps[edge]
        if gap <= threshold and (best is None or gap < gaps[best]):
            best = edge
    return best


def docked_geometry(edge, x, y, w, h, sw, sh, revealed, lip):
    """Tk geometry string "WxH+X+Y" for a window docked at `edge`. When revealed
    it pins flush to that edge; when hidden it slides off-screen leaving `lip` px
    visible. The cross-axis coordinate is preserved. An unknown edge is a no-op
    (keeps the current x, y). Negative offsets format as +-N, which Tk accepts
    (same convention as the drag handler)."""
    nx, ny = x, y
    if edge == "left":
        nx = 0 if revealed else lip - w
    elif edge == "right":
        nx = sw - w if revealed else sw - lip
    elif edge == "top":
        ny = 0 if revealed else lip - h
    elif edge == "bottom":
        ny = sh - h if revealed else sh - lip
    return "%dx%d+%d+%d" % (w, h, nx, ny)


def _repo_short(full):
    """Bare repo name (drop the owner/), capped so a long owner can't push the
    reason label off the right edge of the 220px tile."""
    name = (full or "").rsplit("/", 1)[-1]
    return name if len(name) <= 12 else name[:11] + "…"


ALPHA_PRESETS = (1.0, 0.85, 0.60)


def _smoke_ms():
    v = os.environ.get("TOYBOX_SMOKE")
    return int(v) if v else None


class Hud:
    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        self.sampler = metrics.CpuSampler()
        self.cpu_hist = collections.deque(maxlen=HISTORY)
        self.ram_hist = collections.deque(maxlen=HISTORY)
        self.cpu = 0.0
        self.ram = 0.0
        self.gpu_sampler = metrics.GpuSampler()
        self.gpu_hist = collections.deque(maxlen=HISTORY)
        self.gpu = None
        self.disk = []           # latest diskinfo.usage() list
        self._disk_at = 0.0      # monotonic time of last disk sample (interval-gated)
        self._drag_dx = 0
        self._drag_dy = 0
        self._moved = False
        self.lock_var = tk.BooleanVar(value=bool(cfg["hud"]["locked"]))
        self.CFG_PATH = CFG_PATH  # exposed for the settings window's config.save
        self.feed_state = {}      # idx -> feedmanager.FeedResult
        self._hit = []            # [(y0, y1, url)] for click-to-open (http/https only)
        self._action_hits = []    # [(y0,y1,x0,x1,action)] x-aware dismiss/mark-all zones
        self._feed_items = []     # canvas item ids to clear on each feed redraw
        self._hover_xy = None      # last cursor (x, y) over the canvas, or None
        self._hover_item = None    # the highlight rectangle canvas id, or None
        self._hover_rect = None    # the (x0,y0,x1,y1) currently highlighted, or None
        self._drain_after = None  # pending after() id so close() can cancel it
        self._scroll_lines = []    # [{item, full, x_start, y0, y1}] truncated feed lines
        self._marquee = None       # active marquee dict, or None
        self._marquee_after = None # pending after() id
        self.settings = None      # FeedSettingsWindow singleton (Task 11)
        self.active_tab = feedmodel.coerce_default_tab(cfg["hud"].get("default_tab"))
        token = self._github_token()
        self.manager = feedmanager.FeedManager(cfg.get("feeds", []), token=token)
        # Schedule tile state. self.schedule starts empty (tile hidden) and is
        # replaced under the lock by the mtime-gated poller thread. Guarded by the
        # smoke check so a smoke launch starts no thread.
        self.schedule = schedmodel.Schedule([])
        self._sched_lock = threading.Lock()
        self._sched_path = self._schedule_path()
        self._sched_mtime = None
        self._sched_stop = threading.Event()
        self._sched_thread = None
        if not _smoke_ms():
            self._start_schedule_poller()
        self.width = WIDTH        # session-only; resets narrow each launch
        self._dock_edge = None    # None|'left'|'right'|'top'|'bottom'; session-only
        self._dock_after = None   # pending dock-slide after() id (cancelled on close)
        self._dock_target = None  # (w, h, x, y) the slide animates toward, or None
        self._dock_steps = 0      # frames left in the current slide

        self.canvas = tk.Canvas(
            root, width=self.width, height=HEIGHT, bg=BG,
            highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        # Pixel-width measurer for line 1 (emoji glyphs are double-width, so
        # char-count truncation under-budgets and collides with the age).
        self._feed_font_measure = tkfont.Font(root=root, family=FEED_FONT[0], size=FEED_FONT[1])

        # Persistent canvas items: created once, updated in place each tick
        # (no per-frame create/destroy churn -- matches the lightweight pattern).
        c = self.canvas
        y1 = PAD + ROW_H // 2
        y2 = PAD + ROW_H + ROW_H // 2
        ygpu = PAD + 2 * ROW_H + ROW_H // 2
        ydisk = PAD + 3 * ROW_H + ROW_H // 2     # disk row: row 4 (after GPU)
        y3 = PAD + 5 * ROW_H + ROW_H // 2 + NOWPLAYING_H   # clock + expand, shifted below the now-playing band
        self._cpu_text = c.create_text(LABEL_X, y1, anchor="w", text="CPU   0%", fill=FG, font=FONT)
        self._ram_text = c.create_text(LABEL_X, y2, anchor="w", text="RAM   0%", fill=FG, font=FONT)
        self._gpu_text = c.create_text(LABEL_X, ygpu, anchor="w", text="GPU   0%", fill=FG, font=FONT)
        self._disk_text = c.create_text(LABEL_X, ydisk, anchor="w", text="", fill=FG, font=FONT)
        self._clock_text = c.create_text(self.width // 2, y3, anchor="center", text="", fill=DIM, font=CLOCK_FONT)
        self._expand_text = c.create_text(self.width - PAD, y3, anchor="e",
                                          text=EXPAND_GLYPH, fill=FG, font=EXPAND_FONT)
        self._expand_box = (self.width - PAD - ACTION_ZONE_W, y3 - 10, self.width, y3 + 10)
        self._cpu_line = c.create_line(0, 0, 0, 0, fill=CPU_COLOR, width=1, state="hidden")
        self._ram_line = c.create_line(0, 0, 0, 0, fill=RAM_COLOR, width=1, state="hidden")
        self._gpu_line = c.create_line(0, 0, 0, 0, fill=GPU_COLOR, width=1, state="hidden")
        self._cpu_band = (PAD + 1, PAD + ROW_H - 1)
        self._ram_band = (PAD + ROW_H + 1, PAD + 2 * ROW_H - 1)
        self._gpu_band = (PAD + 2 * ROW_H + 1, PAD + 3 * ROW_H - 1)

        ymedia = PAD + 4 * ROW_H + ROW_H // 2    # media controls: row 5 (above the clock)
        cx = self.width // 2
        gap = 44
        self._media_prev = c.create_text(cx - gap, ymedia, text=MEDIA_PREV, fill=FG, font=MEDIA_FONT)
        self._media_play = c.create_text(cx, ymedia, text=MEDIA_PLAY, fill=FG, font=MEDIA_FONT)
        self._media_next = c.create_text(cx + gap, ymedia, text=MEDIA_NEXT, fill=FG, font=MEDIA_FONT)
        half = ACTION_ZONE_W
        self._media_hits = [
            (cx - gap - half, cx - gap + half, ymedia - 11, ymedia + 11, "prev"),
            (cx - half,       cx + half,       ymedia - 11, ymedia + 11, "playpause"),
            (cx + gap - half, cx + gap + half, ymedia - 11, ymedia + 11, "next"),
        ]
        self._media_hover = None   # which media glyph is currently hover-highlighted

        # Now-playing band: reserved directly below the media row so the header
        # never jumps when playback starts/stops.
        np_top = ymedia + ROW_H // 2                 # bottom edge of the media row band
        self._np_bar_y = np_top + NOWPLAYING_H - NP_BAR_H - 1
        self._np_title = c.create_text(self.width // 2, np_top + 6, anchor="center",
                                       text="", fill=DIM, font=NP_TITLE_FONT)
        self._np_bar_bg = c.create_rectangle(PAD, self._np_bar_y, self.width - PAD,
                                             self._np_bar_y + NP_BAR_H,
                                             fill=NP_TRACK, outline="")
        self._np_bar = c.create_rectangle(PAD, self._np_bar_y, PAD,
                                          self._np_bar_y + NP_BAR_H,
                                          fill=ACCENT, outline="")
        self._np_lock = threading.Lock()
        self._np_latest = None                       # NowPlaying or None (poll thread writes)
        self._np_stop = threading.Event()
        self._np_thread = None
        self._np_scroll = None            # now-playing title ticker state, or None (fits/blank)
        self._np_marquee_after = None     # pending after() id for the ticker loop

        # Dragging moves the whole window (it is borderless / overrideredirect).
        # Bind on the canvas ONLY -- it is packed fill=both/expand so it covers the
        # whole window, and a canvas's bindtags already include its toplevel. Binding
        # on both root and the canvas would fire each handler twice for one click
        # (e.g. opening a feed link in two browser tabs).
        for w in (self.canvas,):
            w.bind("<Button-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)
            w.bind("<Button-3>", self._on_menu)
            w.bind("<Motion>", self._on_motion)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Enter>", self._on_dock_enter, add="+")
            w.bind("<Leave>", self._on_dock_leave, add="+")

        self.menu = tk.Menu(root, tearoff=0)
        for preset in ALPHA_PRESETS:
            self.menu.add_command(
                label=f"Opacity {int(round(preset * 100))}%",
                command=lambda p=preset: self._set_alpha(p),
            )
        self.menu.add_separator()
        self.menu.add_command(label="Feeds…", command=self._open_feed_settings)
        self.menu.add_command(label="Reload feeds", command=self._reload_feeds)
        self.menu.add_separator()
        self.menu.add_checkbutton(label="Lock position", variable=self.lock_var,
                                  command=self._toggle_lock)
        self.menu.add_command(label="Close", command=root.destroy)   # mainloop's finally runs hud.close()

        self._draw()       # paint something immediately (before first tick)
        self._draw_feeds()
        if not _smoke_ms():
            self.manager.start()   # no worker / no network under smoke launches
            self._start_nowplaying()
        self.tick()
        self._drain_after = self.root.after(250, self._drain_feeds)

    # --- dragging ---------------------------------------------------------
    def _on_press(self, event):
        self._moved = False
        self._drag_dx = event.x_root - self.root.winfo_x()
        self._drag_dy = event.y_root - self.root.winfo_y()

    def _on_drag(self, event):
        if self.lock_var.get():
            return  # position is locked
        self._moved = True
        x = event.x_root - self._drag_dx
        y = event.y_root - self._drag_dy
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, event):
        if not self._moved:
            if self._in_expand(event.x, event.y):
                self._toggle_width()
                return
            key = self._media_at(event.x, event.y)        # persistent media glyph zones (unchanged)
            if key is not None:
                self._do_media(key)
                return
            action = self._action_at(event.x, event.y)   # tab/refresh/range/dismiss zones
            if action is not None:
                self._dispatch_action(action)
                return
            url = self._open_at(event.x, event.y)
            if url:
                try:
                    webbrowser.open(url, new=2)
                except Exception:
                    pass
            return  # a plain click (no drag) must not rewrite config.json
        self._moved = False
        self.cfg["hud"]["x"] = self.root.winfo_x()
        self.cfg["hud"]["y"] = self.root.winfo_y()
        self._save()
        self._maybe_dock()

    def _dispatch_action(self, action):
        kind = action[0]
        if kind == "tab":
            self._set_active_tab(action[1])
        elif kind == "refresh":
            (self._refresh_news if action[1] == "news" else self._refresh_github)()
        elif kind == "range":
            self._set_stock_range(action[1], action[2])
        else:
            self._do_dismiss(action)

    def _in_expand(self, x, y):
        """True if (x, y) is within the fixed expand/collapse control on the clock
        row (a constant box, like the old _reload_box)."""
        x0, y0, x1, y1 = self._expand_box
        return x0 <= x <= x1 and y0 <= y <= y1

    def _media_at(self, x, y):
        """Return the media-control key at (x, y) among the three fixed glyph
        zones, or None. Boxes are constants (persistent glyphs)."""
        for x0, x1, y0, y1, key in self._media_hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return key
        return None

    def _set_media_hover(self, key):
        """Brighten the hovered media glyph with the accent colour; revert the
        others to FG. Cheap on <Motion> -- a no-op unless the glyph changes."""
        if key == self._media_hover:
            return
        self._media_hover = key
        for k, item in (("prev", self._media_prev),
                        ("playpause", self._media_play),
                        ("next", self._media_next)):
            try:
                self.canvas.itemconfig(item, fill=(ACCENT if k == key else FG))
            except tk.TclError:
                pass

    def _do_media(self, key):
        """Dispatch a media-control click to winkit.media (looked up as a module
        attribute so tests can monkeypatch it)."""
        if key == "prev":
            media.prev_track()
        elif key == "playpause":
            media.play_pause()
        elif key == "next":
            media.next_track()

    def _do_dismiss(self, action):
        """Optimistically apply a mark-read action to the rendered tile, then hand
        it to the worker. The worker's reconcile (success) or restore (failure)
        result overwrites this optimistic state on the next 250ms drain."""
        kind, idx = action[0], action[1]
        result = self.feed_state.get(idx)
        if kind == "one":
            thread_url = action[2]
            if result is not None:
                remaining = [it for it in result.items if it.thread_url != thread_url]
                self.feed_state[idx] = result._replace(
                    items=remaining, badge=max(0, (result.badge or 0) - 1))
                self._draw_feeds()
            self.manager.mark_read(idx, thread_url)
        elif kind == "all":
            if not tkmsg.askyesno("Mark all read?",
                                  "Mark all notifications as read?", parent=self.root):
                return
            if result is not None:
                self.feed_state[idx] = result._replace(items=[], badge=0)
                self._draw_feeds()
            self.manager.mark_all_read(idx)

    # --- menu -------------------------------------------------------------
    def _on_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _set_alpha(self, alpha):
        self.root.attributes("-alpha", alpha)
        self.cfg["hud"]["alpha"] = alpha
        self._save()

    def _toggle_lock(self):
        self.cfg["hud"]["locked"] = bool(self.lock_var.get())
        self._save()

    def _save(self):
        # Persist ONLY the HUD's own window keys via a scoped read-modify-write,
        # so a drag / opacity / lock save can never clobber feeds, github_token,
        # or another toy's section (config.update merges over the latest on-disk
        # state instead of overwriting the whole file with our in-memory copy).
        h = self.cfg["hud"]
        try:
            config.update(CFG_PATH, {"hud": {"x": h["x"], "y": h["y"],
                                             "alpha": h["alpha"], "locked": h["locked"]}})
        except Exception:
            pass  # a transient write failure must never crash the HUD

    # --- update loop ------------------------------------------------------
    def tick(self):
        self.cpu = self.sampler.sample()
        self.ram = metrics.ram_percent()
        self.cpu_hist.append(self.cpu)
        self.ram_hist.append(self.ram)
        self.gpu = self.gpu_sampler.sample()
        if self.gpu is not None:
            self.gpu_hist.append(self.gpu)
        now = time.monotonic()
        if now - self._disk_at >= 15:            # disk-free changes slowly; refresh ~15s
            self.disk = diskinfo.usage()
            self._disk_at = now
        self._draw()
        self._draw_nowplaying()
        self.root.after(1000, self.tick)

    def _draw(self):
        c = self.canvas
        c.itemconfig(self._cpu_text, text=f"CPU {self.cpu:3.0f}%")
        c.itemconfig(self._ram_text, text=f"RAM {self.ram:3.0f}%")
        if self.gpu is None:
            c.itemconfig(self._gpu_text, text="GPU  --%", fill=DIM)
        else:
            c.itemconfig(self._gpu_text, text=f"GPU {self.gpu:3.0f}%", fill=FG)
        c.itemconfig(self._disk_text, text=diskinfo.format_disk_row(self.disk, DISK_MAX_CHARS))
        c.itemconfig(self._clock_text, text=time.strftime("%H:%M:%S"))
        self._update_spark(self._cpu_line, self.cpu_hist, self._cpu_band)
        self._update_spark(self._ram_line, self.ram_hist, self._ram_band)
        self._update_spark(self._gpu_line, self.gpu_hist, self._gpu_band)

    def _update_spark(self, line_id, hist, band):
        """Update a scrolling polyline of the last HISTORY samples (each 0..100),
        right-aligned in a fixed-width band. Reuses the existing line item."""
        n = len(hist)
        if n < 2:
            self.canvas.itemconfig(line_id, state="hidden")
            return
        top, bottom = band
        height = bottom - top
        step = SPARK_W / (HISTORY - 1)
        x0 = (self.width - PAD) - (n - 1) * step  # newest sample sits at the right edge
        pts = []
        for i, v in enumerate(hist):
            frac = max(0.0, min(1.0, v / 100.0))
            pts.extend((x0 + i * step, bottom - frac * height))
        self.canvas.coords(line_id, *pts)
        self.canvas.itemconfig(line_id, state="normal")

    # --- now playing ------------------------------------------------------
    def _start_nowplaying(self):
        """Spawn the daemon that polls SMTC every NP_POLL_S and stores the latest
        sample under a lock. It waits one interval before the first read so a
        just-constructed HUD (and the tests) see a stable None until then."""
        def _loop():
            while not self._np_stop.wait(NP_POLL_S):
                try:
                    s = nowplaying.read()
                except Exception:
                    s = None
                with self._np_lock:
                    self._np_latest = s
        self._np_thread = threading.Thread(target=_loop, name="nowplaying",
                                            daemon=True)
        self._np_thread.start()

    def _draw_nowplaying(self):
        """Update the title line + progress bar from the latest SMTC sample. The
        bar advances with wall-clock so it moves smoothly between reads. A title
        that fits renders static and centered; a title that overflows the tile
        auto-scrolls (music-player ticker: scroll left to reveal the end, then
        jump back to the start -- never bouncing). Blank when nothing is playing.
        Never raises."""
        c = self.canvas
        with self._np_lock:
            s = self._np_latest
        left = PAD
        right = self.width - PAD
        y0, y1 = self._np_bar_y, self._np_bar_y + NP_BAR_H
        try:
            title_y = self.canvas.coords(self._np_title)[1]
            if s is None or s.status == "stopped":
                self._np_scroll = None                       # nothing playing -> no ticker
                c.itemconfig(self._np_title, text="", anchor="center")
                c.coords(self._np_title, self.width // 2, title_y)
                c.coords(self._np_bar, left, y0, left, y1)   # zero width => blank
                c.itemconfig(self._np_bar_bg, state="hidden")
                return
            text = nowplaying.format_track(s.title, s.artist)
            pos = nowplaying.advance(s.position_s, time.monotonic() - s.sampled_at,
                                     s.status)
            frac = nowplaying.progress_fraction(pos, s.duration_s)
            if s.duration_s > 0:                             # source publishes a timeline -> show bar
                c.itemconfig(self._np_bar_bg, state="normal")
                c.itemconfig(self._np_bar, state="normal")
                c.coords(self._np_bar, left, y0, left + int((right - left) * frac), y1)
            else:                                            # no timeline (e.g. foobar2000) -> hide bar
                c.itemconfig(self._np_bar_bg, state="hidden")
                c.itemconfig(self._np_bar, state="hidden")
            c.itemconfig(self._np_title, text=text)          # FULL text; the widget edge clips overflow
            max_off = nowplaying.marquee_scroll_max(
                self._feed_font_measure.measure(text), right - left)
            if max_off <= 0:
                self._np_scroll = None                       # fits => static, centered
                c.itemconfig(self._np_title, anchor="center")
                c.coords(self._np_title, self.width // 2, title_y)
            else:
                if self._np_scroll is None or self._np_scroll.get("text") != text:
                    self._np_scroll = {"text": text, "offset": 0, "pause": 0}
                self._np_scroll["max"] = max_off
                self._np_scroll["base_x"] = left
                c.itemconfig(self._np_title, anchor="w")
                c.coords(self._np_title, left - self._np_scroll["offset"], title_y)
                self._np_marquee_ensure()                    # kick the ticker loop if idle
        except tk.TclError:
            pass

    def _np_marquee_ensure(self):
        """Start the now-playing ticker loop if it is not already scheduled. The
        loop self-stops when _np_scroll goes None (title fits or nothing plays)."""
        if self._np_marquee_after is None:
            self._np_marquee_after = self.root.after(33, self._np_marquee_step)

    def _np_marquee_step(self):
        """Advance the persistent now-playing title one pixel-motion tick using the
        SAME wrap math as the feed marquee (nowplaying.marquee_step). Runs only
        while a long title overflows; stops itself otherwise. Never raises."""
        m = self._np_scroll
        if m is None:
            self._np_marquee_after = None                    # nothing to scroll -> stop the loop
            return
        try:
            m["offset"], m["pause"] = nowplaying.marquee_step(
                m["offset"], m["max"], m["pause"])
            y = self.canvas.coords(self._np_title)[1]
            self.canvas.coords(self._np_title, m["base_x"] - m["offset"], y)
        except tk.TclError:
            self._np_marquee_after = None
            return
        self._np_marquee_after = self.root.after(33, self._np_marquee_step)

    # --- feeds ------------------------------------------------------------
    def _github_token(self):
        return os.environ.get("TOYBOX_GITHUB_TOKEN") or self.cfg["hud"].get("github_token", "")

    def _news_indices(self):
        """Indices of news-family feeds (rss/json/text/stocks), config order."""
        return [i for i, f in enumerate(self.manager.feeds)
                if feedmodel.is_news_type(f.get("type"))]

    def _github_indices(self):
        """Indices of pinned GitHub-family feeds (github/notifications/search)."""
        return [i for i, f in enumerate(self.manager.feeds)
                if feedmodel.is_pinned_type(f.get("type"))]

    def _drain_feeds(self):
        self._drain_after = None
        changed = False
        for idx, result in self.manager.drain():
            self.feed_state[idx] = result
            changed = True
        if changed:
            try:
                self._draw_feeds()
            except tk.TclError:
                return
        self._drain_after = self.root.after(250, self._drain_feeds)

    def _tile_for(self, idx, feed):
        """Return one tile tuple for a feed: a 5-tuple (title, title_url, color,
        lines, header_action). (Task 9 adds a ('stocks', payload) 2-tuple.)"""
        title = feed.get("title") or "feed"
        if not feed.get("valid"):
            return (title, None, FEED_DIM, [("! " + (feed.get("error") or "invalid"), None, True)], None)
        if feed.get("valid") and feed["type"] == "stocks":
            result = self.feed_state.get(idx)
            payload = {"title": feed.get("title") or "Markets", "range": feed["range"],
                       "quotes": list(result.items) if result else [],
                       "state": result.state if result else "loading",
                       "error": result.error if result else None}
            return ("stocks", payload)
        if feed.get("valid") and feed["type"] == "weather":
            result = self.feed_state.get(idx)
            payload = {"title": feed.get("title") or feed.get("city") or "Weather",
                       "range": feed["range"],
                       "weather": (result.items[0] if result and result.items else None),
                       "state": result.state if result else "loading",
                       "error": result.error if result else None}
            return ("weather", payload)
        result = self.feed_state.get(idx)
        if result is None:
            return (title, None, FEED_FG, [("loading…", None, True)], None)
        if feed["type"] == "notifications":
            badge = result.badge or 0          # badge may be None; None>=50 would crash the drain loop
            header = title + ("  \U0001f514 %s" % ("50+" if badge >= 50 else badge))
            lines = []
            if result.error == "no github_token":
                lines.append(("! set GitHub token in Settings", None, True))
            elif result.error == "dismiss failed":
                lines.append(("! dismiss failed", None, True))
            elif result.error and not result.items:
                lines.append(("! " + result.error, None, True))
            elif result.state == "ok" and not result.items:
                lines.append(("inbox zero", None, True))
            stale = result.state != "ok"
            for it in result.items:
                color = FEED_DIM if stale else URGENCY_HEX.get(it.urgency, FEED_FG)
                age = "" if it.updated_at <= 0 else timeago.format_ago(time.time() - it.updated_at)
                num = (" " + it.number) if it.number else ""
                line1 = "%s %s%s · %s" % (it.glyph, _repo_short(it.repo), num, it.reason_label)
                dismiss = ("one", idx, it.thread_url) if it.thread_url else None
                lines.append((line1, it.url, color, it.title, age, dismiss))
            extra = badge - len(result.items)
            if extra > 0:
                lines.append(("… %d more" % extra, "https://github.com/notifications", True))
            header_action = ("all", idx) if (result.state == "ok" and result.items) else None
            return (header, "https://github.com/notifications", FEED_FG, lines, header_action)
        if feed["type"] == "search":
            badge = result.badge or 0           # badge may be None
            header = title + ("  (%d)" % badge)
            web = feedmodel.github_search_web_url(feed["query"])
            lines = []
            if result.error == "no github_token":
                lines.append(("! set GitHub token in Settings", None, True))
            elif result.error and not result.items:
                lines.append(("! " + result.error, None, True))
            elif result.state == "ok" and not result.items:
                lines.append(("none open", None, True))
            stale = result.state != "ok"
            for it in result.items:
                color = FEED_DIM if stale else URGENCY_HEX.get(it.urgency, FEED_FG)
                age = "" if it.updated_at <= 0 else timeago.format_ago(time.time() - it.updated_at)
                num = (" " + it.number) if it.number else ""
                line1 = "%s %s%s · %s" % (it.glyph, _repo_short(it.repo), num, it.reason_label)
                lines.append((line1, it.url, color, it.title, age, None))
            extra = badge - len(result.items)
            if extra > 0:
                lines.append(("… %d more" % extra, web, True))
            return (header, web, FEED_FG, lines, None)
        if result.status is not None:                 # github tile
            color = STATE_HEX.get(result.status.state, FEED_DIM)
            lines = [("! " + result.error, None, True)] if result.error else []
            return (result.status.text, result.status.url, color, lines, None)
        dim = result.state in ("stale", "error")
        lines = [(it.text, it.url, dim) for it in result.items]
        if result.error:
            lines = [("! " + result.error, None, True)] + lines
        if not lines:
            lines = [("(empty)", None, True)]
        return (title, None, FEED_FG, lines, None)

    def _draw_tile(self, idx, feed, y):
        tile = self._tile_for(idx, feed)
        if len(tile) == 2:                       # ("stocks"/"weather", payload)
            if tile[0] == "weather":
                return self._draw_weather_tile(idx, tile[1], y)
            return self._draw_stock_tile(idx, tile[1], y)
        title, title_url, color, lines, header_action = tile
        c = self.canvas
        y += FEED_TITLE_GAP
        tid = c.create_text(PAD, y, anchor="w", text=self._fit_px(title, PAD), fill=color, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        self._register_hit(y, title_url)
        if header_action is not None:
            mk = c.create_text(self.width - PAD, y, anchor="e", text=MARKALL_GLYPH,
                               fill=FEED_DIM, font=FEED_TITLE_FONT)
            self._feed_items.append(mk)
            self._register_action(y, self.width - PAD - ACTION_ZONE_W, self.width, header_action)
        y += FEED_LINE_H
        for row in lines:
            if len(row) == 3:
                text, url, dim = row
                fitted = self._fit_px(text, PAD + 6)
                lid = c.create_text(PAD + 6, y, anchor="w", text=fitted,
                                    fill=(FEED_DIM if dim else FEED_FG), font=FEED_FONT)
                self._feed_items.append(lid)
                if fitted != text:
                    self._scroll_lines.append({"item": lid, "full": text, "x_start": PAD + 6,
                                               "y0": y - FEED_LINE_H // 2, "y1": y + FEED_LINE_H // 2})
                self._register_hit(y, url)
                y += FEED_LINE_H
            else:
                line1, url, color, subtitle, age, dismiss = row
                reserve = ACTION_ZONE_W if dismiss else 0
                l1 = c.create_text(PAD + 6, y, anchor="w",
                                   text=self._fit_line1(line1, age, reserve),
                                   fill=color, font=FEED_FONT)
                self._feed_items.append(l1)
                if age:
                    aid = c.create_text(self.width - PAD - reserve, y, anchor="e", text=age,
                                        fill=FEED_DIM, font=FEED_FONT)
                    self._feed_items.append(aid)
                if dismiss is not None:
                    xg = c.create_text(self.width - PAD, y, anchor="e", text=DISMISS_GLYPH,
                                       fill=FEED_DIM, font=FEED_FONT)
                    self._feed_items.append(xg)
                    self._register_action(y, self.width - PAD - ACTION_ZONE_W, self.width, dismiss)
                self._register_hit(y, url)
                y += FEED_LINE_H
                l2 = c.create_text(PAD + 12, y, anchor="w", text=self._fit_px(subtitle, PAD + 12),
                                   fill=FEED_DIM, font=FEED_FONT)
                self._feed_items.append(l2)
                self._register_hit(y, url)
                y += FEED_LINE_H
        return y

    def _register_hit(self, y, url):
        """Record a clickable region for the line centered at y -- but ONLY for
        http/https URLs, so attacker-controlled feed content can't launch
        file://, javascript:, data:, or custom-scheme URLs."""
        if url and feedmodel.is_web_url(url):
            self._hit.append((y - FEED_LINE_H // 2, y + FEED_LINE_H // 2, url))

    def _register_action(self, y, x0, x1, action):
        """Record an x-aware action zone (dismiss/mark-all AND tab/refresh/range),
        NOT a browser open. Checked before the open-URL hits, so the narrow
        right-edge zone never opens the thread."""
        self._action_hits.append((y - FEED_LINE_H // 2, y + FEED_LINE_H // 2, x0, x1, action))

    def _action_at(self, x, y):
        for y0, y1, x0, x1, action in self._action_hits:
            if y0 <= y <= y1 and x0 <= x <= x1:
                return action
        return None

    def _hover_zone_at(self, x, y):
        """Rectangle (x0,y0,x1,y1) to highlight for the clickable thing under the
        cursor, or None. A tab/range action highlights its own segment (a pill);
        any other clickable feed row highlights the full content width. Refresh
        glyphs get no highlight (their rows register no _hit); a dismiss glyph
        shares its row's full-width band rather than getting its own pill."""
        for y0, y1, x0, x1, action in self._action_hits:
            if y0 <= y <= y1 and x0 <= x <= x1 and action[0] in ("tab", "range"):
                return (x0 - 3, y0, x1 + 3, y1)
        for y0, y1, _url in self._hit:
            if y0 <= y <= y1:
                return (PAD, y0, self.width - PAD, y1)
        return None

    def _apply_hover(self):
        """Reconcile the highlight rectangle with the current cursor position.
        No-op when the target band is unchanged (avoids per-motion churn)."""
        rect = self._hover_zone_at(*self._hover_xy) if self._hover_xy else None
        if rect == self._hover_rect:
            return
        self._hover_rect = rect
        if self._hover_item is not None:
            self.canvas.delete(self._hover_item)
            self._hover_item = None
        if rect is not None:
            self._hover_item = self.canvas.create_rectangle(*rect, fill=HOVER_BG, outline="")
            self.canvas.tag_lower(self._hover_item)     # behind text/lines/charts

    def _scroll_line_at(self, x, y):
        """The scrollable (truncated) line record under (x, y), or None."""
        for rec in self._scroll_lines:
            if rec["y0"] <= y <= rec["y1"]:
                return rec
        return None

    def _start_marquee(self, rec):
        if self._marquee is not None and self._marquee["item"] == rec["item"]:
            return
        self._stop_marquee()
        self.canvas.itemconfig(rec["item"], text=rec["full"])   # full text; window clips overflow
        budget = self.width - PAD - rec["x_start"]
        full_w = self._feed_font_measure.measure(rec["full"])
        self._marquee = {"item": rec["item"], "base_x": rec["x_start"],
                         "max": max(0, full_w - budget), "offset": 0, "pause": 0}
        self._marquee_after = self.root.after(400, self._marquee_step)   # brief pause, then scroll

    def _marquee_step(self):
        m = self._marquee
        if m is None:
            return
        try:
            m["offset"], m["pause"] = nowplaying.marquee_step(
                m["offset"], m["max"], m["pause"])   # shared wrap math (0->max->0, no bounce)
            y = self.canvas.coords(m["item"])[1]
            self.canvas.coords(m["item"], m["base_x"] - m["offset"], y)
        except tk.TclError:
            self._stop_marquee(); return
        self._marquee_after = self.root.after(33, self._marquee_step)

    def _stop_marquee(self):
        if self._marquee_after is not None:
            try:
                self.root.after_cancel(self._marquee_after)
            except Exception:
                pass
            self._marquee_after = None
        if self._marquee is not None:
            rec = next((r for r in self._scroll_lines if r["item"] == self._marquee["item"]), None)
            if rec is not None:
                try:
                    xy = self.canvas.coords(rec["item"])
                    if xy:  # empty list means item was already deleted (e.g. by _draw_feeds)
                        self.canvas.coords(rec["item"], rec["x_start"], xy[1])
                        self.canvas.itemconfig(rec["item"], text=self._fit_px(rec["full"], rec["x_start"]))
                except tk.TclError:
                    pass
            self._marquee = None

    def _on_motion(self, event):
        self._hover_xy = (event.x, event.y)
        self._apply_hover()
        self._set_media_hover(self._media_at(event.x, event.y))
        rec = self._scroll_line_at(event.x, event.y)
        if rec is not None:
            self._start_marquee(rec)
        else:
            self._stop_marquee()

    def _on_leave(self, event):
        self._hover_xy = None
        self._apply_hover()
        self._set_media_hover(None)
        self._stop_marquee()

    def _fit_px(self, text, x_start):
        """Trim text with an ellipsis so it fits from x_start to the right margin
        at FEED_FONT width (pixel-accurate, unlike the char-count _fit)."""
        m = self._feed_font_measure.measure
        budget = self.width - PAD - x_start
        if m(text) <= budget:
            return text
        while text and m(text + "…") > budget:
            text = text[:-1]
        return text + "…"

    def _fit_line1(self, text, age, reserve=0):
        """Truncate line 1 by measured pixel width so it never collides with the
        right-aligned age (and the ✕ glyph when present, via reserve px)."""
        m = self._feed_font_measure.measure
        budget = self.width - 2 * PAD - m(age) - 8 - reserve
        if m(text) <= budget:
            return text
        while text and m(text + "…") > budget:
            text = text[:-1]
        return text + "…"

    def _schedule_path(self):
        """Absolute .xlsx path from config (hud.schedule.path), or "" when unset
        or malformed -> the tile stays hidden."""
        sched = self.cfg["hud"].get("schedule") or {}
        if not isinstance(sched, dict):
            return ""
        path = sched.get("path") or ""
        return path if isinstance(path, str) else ""

    def _schedule_now(self):
        """Injectable clock for the schedule tile (tests override this)."""
        return datetime.datetime.now()

    def _start_schedule_poller(self):
        """Start the daemon mtime poller (no-op without a configured path)."""
        if not self._sched_path:
            return
        self._sched_thread = threading.Thread(
            target=self._schedule_loop, name="schedpoller", daemon=True)
        self._sched_thread.start()

    def _schedule_loop(self):
        """Every ~30s: re-read the file if its mtime changed. Never touches Tk."""
        while not self._sched_stop.is_set():
            try:
                self._reload_schedule_if_changed()
            except Exception:
                pass
            self._sched_stop.wait(30)

    def _reload_schedule_if_changed(self):
        """mtime-gated re-read + re-parse. A missing/locked file or a {} read
        retains the last-good schedule (and retries next poll); only a non-empty
        workbook replaces self.schedule."""
        path = self._sched_path
        if not path:
            return
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return
        if mtime == self._sched_mtime:
            return
        workbook = schedxlsx.read_workbook(path)
        if not workbook:
            return
        schedule = schedmodel.parse_schedule(workbook)
        with self._sched_lock:
            self.schedule = schedule
            self._sched_mtime = mtime

    def _draw_schedule_tile(self, y):
        """Pinned "now" tile above the tab bar. kind 'now' -> "▸ task";
        'next' -> "→ HH:MM  task"; 'none' -> hidden (y unchanged). Reuses the
        pixel-fit ellipsis and registers a marquee record for a truncated line.
        Not clickable (no URL)."""
        with self._sched_lock:
            schedule = self.schedule
        slot = schedule.at(self._schedule_now())
        if slot.kind == "none":
            return y
        if slot.kind == "now":
            text = "▸ " + slot.task
        else:
            text = "→ %s  %s" % (slot.start.strftime("%H:%M"), slot.task)
        c = self.canvas
        y += FEED_TITLE_GAP
        row_y = y + FEED_LINE_H // 2
        fitted = self._fit_px(text, PAD)
        tid = c.create_text(PAD, row_y, anchor="w", text=fitted,
                            fill=ACCENT, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        if fitted != text:
            self._scroll_lines.append({"item": tid, "full": text, "x_start": PAD,
                                       "y0": row_y - FEED_LINE_H // 2,
                                       "y1": row_y + FEED_LINE_H // 2})
        return y + FEED_LINE_H + FEED_TITLE_GAP

    def _draw_feeds(self):
        c = self.canvas
        for item_id in self._feed_items:
            c.delete(item_id)
        self._feed_items = []
        self._hit = []
        self._action_hits = []
        self._stop_marquee()
        self._scroll_lines = []
        if self._hover_item is not None:
            c.delete(self._hover_item)
            self._hover_item = None
        self._hover_rect = None
        y = PAD + 6 * ROW_H + 4 + NOWPLAYING_H    # below the header rows + reserved now-playing band
        y = self._draw_schedule_tile(y)   # pinned "now" tile, above the tab bar
        y = self._draw_tab_bar(y)
        news = [i for i in self._news_indices()
                if self.manager.feeds[i].get("tab") == self.active_tab]
        for idx in news:
            y = self._draw_tile(idx, self.manager.feeds[idx], y)
        if not news:
            pid = c.create_text(PAD + 6, y + FEED_TITLE_GAP + FEED_LINE_H // 2, anchor="w",
                                text="no feeds", fill=FEED_DIM, font=FEED_FONT)
            self._feed_items.append(pid)
            y += FEED_TITLE_GAP + FEED_LINE_H
        y = self._draw_github_header(y)
        for idx in self._github_indices():
            y = self._draw_tile(idx, self.manager.feeds[idx], y)
        self._resize(y + PAD)
        self._apply_hover()

    def _draw_tab_bar(self, y):
        c = self.canvas
        row_y = y + FEED_LINE_H // 2
        x = PAD
        for key, label in feedmodel.NEWS_TABS:
            active = (key == self.active_tab)
            tid = c.create_text(x, row_y, anchor="w", text=label,
                                fill=(FEED_FG if active else FEED_DIM),
                                font=(FEED_TITLE_FONT if active else FEED_FONT))
            self._feed_items.append(tid)
            w = self._feed_font_measure.measure(label)
            self._register_action(row_y, x, x + w, ("tab", key))
            if active:
                uy = row_y + FEED_LINE_H // 2 - 1
                ul = c.create_rectangle(x, uy, x + w, uy + 2, fill=ACCENT, outline="")
                self._feed_items.append(ul)
            x += w + 6
        rid = c.create_text(self.width - PAD, row_y, anchor="e", text=RELOAD_GLYPH,
                            fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(rid)
        self._register_action(row_y, self.width - PAD - ACTION_ZONE_W, self.width, ("refresh", "news"))
        return y + FEED_LINE_H + FEED_TITLE_GAP

    def _draw_github_header(self, y):
        c = self.canvas
        dv = c.create_line(PAD, y + 1, self.width - PAD, y + 1, fill=FEED_DIM, width=1)
        self._feed_items.append(dv)
        row_y = y + FEED_LINE_H // 2
        tid = c.create_text(PAD, row_y, anchor="w", text="GitHub", fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        rid = c.create_text(self.width - PAD, row_y, anchor="e", text=RELOAD_GLYPH,
                            fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(rid)
        self._register_action(row_y, self.width - PAD - ACTION_ZONE_W, self.width, ("refresh", "github"))
        return y + FEED_LINE_H + FEED_TITLE_GAP

    def _draw_stock_tile(self, idx, payload, y):
        c = self.canvas
        y += FEED_TITLE_GAP
        row_y = y + FEED_LINE_H // 2
        tid = c.create_text(PAD, row_y, anchor="w", text=_fit(payload["title"]),
                            fill=FEED_FG, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        self._draw_range_toggle(idx, payload["range"], row_y)
        y += FEED_LINE_H
        quotes = payload["quotes"]
        if not quotes:
            msg = ("! " + payload["error"]) if (payload["state"] != "loading" and payload["error"]) else "loading…"
            lid = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                                text=_fit(msg), fill=FEED_DIM, font=FEED_FONT)
            self._feed_items.append(lid)
            return y + FEED_LINE_H
        stale = payload["state"] in ("stale", "error")
        for q in quotes:
            color = FEED_DIM if stale else (STOCK_UP if q.change_pct >= 0 else STOCK_DOWN)
            url = feedmodel.yahoo_quote_web_url(q.symbol)
            lid = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                                text=_fit(feedmodel.format_quote_line(q)),
                                fill=color, font=FEED_FONT)
            self._feed_items.append(lid)
            self._register_hit(y + FEED_LINE_H // 2, url)
            y += FEED_LINE_H
            pts = _stock_points(q.series, PAD + 6, self.width - PAD, y + 2, y + STOCK_CHART_H - 2)
            if pts:
                bottom = y + STOCK_CHART_H - 2
                poly = c.create_polygon(*(pts + [pts[-2], bottom, pts[0], bottom]),
                                        fill=color, stipple="gray25", outline="")
                self._feed_items.append(poly)
                ln = c.create_line(*pts, fill=color, width=1)
                self._feed_items.append(ln)
            self._register_hit(y + STOCK_CHART_H // 2, url)
            y += STOCK_CHART_H
        return y

    def _draw_range_toggle(self, idx, current, row_y):
        c = self.canvas
        x = self.width - PAD
        for code in reversed(feedmodel.STOCK_RANGE_ORDER):        # draw right->left; 3M rightmost
            label = feedmodel.STOCK_RANGE_LABELS[code]
            active = (code == current)
            tid = c.create_text(x, row_y, anchor="e", text=label,
                                fill=(FEED_FG if active else FEED_DIM), font=FEED_FONT)
            self._feed_items.append(tid)
            w = self._feed_font_measure.measure(label)
            self._register_action(row_y, x - w, x, ("range", idx, code))
            if active:
                uy = row_y + FEED_LINE_H // 2 - 1
                ul = c.create_rectangle(x - w, uy, x, uy + 2, fill=ACCENT, outline="")
                self._feed_items.append(ul)
            x -= w + 6

    def _draw_weather_tile(self, idx, payload, y):
        c = self.canvas
        y += FEED_TITLE_GAP
        row_y = y + FEED_LINE_H // 2
        tid = c.create_text(PAD, row_y, anchor="w", text=_fit(payload["title"]),
                            fill=FEED_FG, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        self._draw_weather_range_toggle(idx, payload["range"], row_y)
        y += FEED_LINE_H
        w = payload["weather"]
        if w is None:
            msg = ("! " + payload["error"]) if (payload["state"] != "loading" and payload["error"]) else "loading…"
            lid = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                                text=_fit(msg), fill=FEED_DIM, font=FEED_FONT)
            self._feed_items.append(lid)
            return y + FEED_LINE_H
        stale = payload["state"] in ("stale", "error")
        color = FEED_DIM if stale else ACCENT
        lid = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                            text=_fit(feedmodel.format_weather_line(w)),
                            fill=(FEED_DIM if stale else FEED_FG), font=FEED_FONT)
        self._feed_items.append(lid)
        y += FEED_LINE_H
        pts = _stock_points(w.series, PAD + 6, self.width - PAD, y + 2, y + STOCK_CHART_H - 2)
        if pts:
            bottom = y + STOCK_CHART_H - 2
            poly = c.create_polygon(*(pts + [pts[-2], bottom, pts[0], bottom]),
                                    fill=color, stipple="gray25", outline="")
            self._feed_items.append(poly)
            ln = c.create_line(*pts, fill=color, width=1)
            self._feed_items.append(ln)
        y += STOCK_CHART_H
        return y

    def _draw_weather_range_toggle(self, idx, current, row_y):
        c = self.canvas
        x = self.width - PAD
        for code in reversed(feedmodel.WEATHER_RANGE_ORDER):     # draw right->left; 7D rightmost
            label = feedmodel.WEATHER_RANGE_LABELS[code]
            active = (code == current)
            tid = c.create_text(x, row_y, anchor="e", text=label,
                                fill=(FEED_FG if active else FEED_DIM), font=FEED_FONT)
            self._feed_items.append(tid)
            w = self._feed_font_measure.measure(label)
            self._register_action(row_y, x - w, x, ("range", idx, code))
            if active:
                uy = row_y + FEED_LINE_H // 2 - 1
                ul = c.create_rectangle(x - w, uy, x, uy + 2, fill=ACCENT, outline="")
                self._feed_items.append(ul)
            x -= w + 6

    def _resize(self, wanted_h):
        sh = self.root.winfo_screenheight()
        new_h = max(HEIGHT, min(int(wanted_h), sh - self.root.winfo_y()))
        if new_h != self.root.winfo_height() or self.width != self.root.winfo_width():
            self.canvas.config(width=self.width, height=new_h)
            self.root.geometry("%dx%d" % (self.width, new_h))

    def _feed_has_text(self, needle):
        for item_id in self._feed_items:
            try:
                if needle in self.canvas.itemcget(item_id, "text"):
                    return True
            except Exception:
                pass
        return False

    def close(self):
        # Cleanup only -- never destroys the root (mirrors petkit Cat.close). The
        # single root.destroy() is the quit path in main(); close() runs after it
        # (in main's finally) and the tests call close() then destroy() themselves.
        if self._drain_after is not None:
            try:
                self.root.after_cancel(self._drain_after)
            except Exception:
                pass
            self._drain_after = None
        if self._dock_after is not None:
            try:
                self.root.after_cancel(self._dock_after)
            except Exception:
                pass
            self._dock_after = None
        self._stop_marquee()
        self._np_stop.set()
        if self._np_marquee_after is not None:
            try:
                self.root.after_cancel(self._np_marquee_after)
            except Exception:
                pass
            self._np_marquee_after = None
        try:
            self.manager.stop()
        except Exception:
            pass
        if self._sched_thread is not None:
            self._sched_stop.set()
            try:
                self._sched_thread.join(timeout=2)
            except Exception:
                pass
        if getattr(self, "settings", None) is not None:
            self.settings.close()

    def _on_dock_enter(self, event):
        """Pointer entered the window: if docked, slide fully into view."""
        if self._dock_edge:
            self._dock_animate(revealed=True)

    def _on_dock_leave(self, event):
        """Pointer left the window: if docked, slide back out to the peeking lip."""
        if self._dock_edge:
            self._dock_animate(revealed=False)

    def _maybe_dock(self):
        """On drag-release, snap to a screen edge if within DOCK_THRESHOLD (and
        slide to the hidden lip), else undock. Session-only; never persisted."""
        try:
            x = self.root.winfo_x(); y = self.root.winfo_y()
            w = self.root.winfo_width(); h = self.root.winfo_height()
            sw = self.root.winfo_screenwidth(); sh = self.root.winfo_screenheight()
        except Exception:
            return
        self._dock_edge = edge_for(x, y, w, h, sw, sh, DOCK_THRESHOLD)
        if self._dock_edge:
            self._dock_animate(revealed=False)   # slide out to the peeking lip

    def _target_from(self, edge, revealed):
        """Parse docked_geometry(edge, ...) into (w, h, x, y) ints for the slide
        animator. Uses the live window size so it composes with the width toggle."""
        w = self.root.winfo_width(); h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth(); sh = self.root.winfo_screenheight()
        x = self.root.winfo_x(); y = self.root.winfo_y()
        geo = docked_geometry(edge, x, y, w, h, sw, sh, revealed, DOCK_LIP)
        size, _, rest = geo.partition("+")       # "WxH", "+", "X+Y" (X may be -N)
        gw, gh = size.split("x")
        gx, gy = rest.split("+")
        return int(gw), int(gh), int(gx), int(gy)

    def _dock_animate(self, revealed):
        """Start (or restart) the chained-after slide toward the docked target for
        the current edge. No-op when not docked. Guarded so a bad geometry never
        crashes the HUD."""
        if not self._dock_edge:
            return
        if self._dock_after is not None:
            try:
                self.root.after_cancel(self._dock_after)
            except Exception:
                pass
            self._dock_after = None
        try:
            self._dock_target = self._target_from(self._dock_edge, revealed)
        except Exception:
            self._dock_target = None
            return
        self._dock_steps = DOCK_ANIM_STEPS
        self._dock_step()

    def _dock_step(self):
        """One frame of the dock slide: move a fraction toward _dock_target and, if
        frames remain, reschedule. The final frame snaps exactly and clears state."""
        if self._dock_target is None:
            return
        w, h, tx, ty = self._dock_target
        try:
            cx = self.root.winfo_x(); cy = self.root.winfo_y()
        except Exception:
            self._dock_target = None
            self._dock_after = None
            return
        if self._dock_steps <= 1:
            nx, ny = tx, ty
        else:
            nx = cx + (tx - cx) // self._dock_steps
            ny = cy + (ty - cy) // self._dock_steps
        try:
            self.root.geometry("%dx%d+%d+%d" % (w, h, nx, ny))
        except Exception:
            pass
        self._dock_steps -= 1
        if self._dock_steps <= 0:
            self._dock_target = None
            self._dock_after = None
        else:
            self._dock_after = self.root.after(DOCK_ANIM_MS, self._dock_step)

    def _open_at(self, x, y):
        for y0, y1, url in self._hit:
            if y0 <= y <= y1:
                return url if feedmodel.is_web_url(url) else None
        return None

    def _open_feed_settings(self):
        import feedkit.settings as feedsettings
        if getattr(self, "settings", None) is None:
            self.settings = feedsettings.FeedSettingsWindow(self)
        self.settings.open()

    def _toggle_width(self):
        """Session-only toggle between narrow (WIDTH) and wide (WIDTH_WIDE). No
        config write. Repositions the persistent header, resizes the window, and
        redraws the feeds at the new width."""
        self.width = WIDTH_WIDE if self.width == WIDTH else WIDTH
        self._relayout_header()
        self._draw()          # repaint header (clock/media/sparklines) at the new width
        self._draw_feeds()    # reflow feeds + resize the window (via _resize)

    def _relayout_header(self):
        """Move the width-dependent persistent header items to the current width:
        the centered clock and the media glyphs (+ their hit zones). Sparklines
        re-right-align on the next _update_spark, which reads self.width."""
        c = self.canvas
        cx = self.width // 2
        c.coords(self._clock_text, cx, self.canvas.coords(self._clock_text)[1])
        c.coords(self._np_title, cx, self.canvas.coords(self._np_title)[1])
        c.coords(self._np_bar_bg, PAD, self._np_bar_y, self.width - PAD, self._np_bar_y + NP_BAR_H)
        ymedia = PAD + 4 * ROW_H + ROW_H // 2    # media row 5 (above clock)
        gap = 44
        c.coords(self._media_prev, cx - gap, ymedia)
        c.coords(self._media_play, cx, ymedia)
        c.coords(self._media_next, cx + gap, ymedia)
        half = ACTION_ZONE_W
        self._media_hits = [
            (cx - gap - half, cx - gap + half, ymedia - 11, ymedia + 11, "prev"),
            (cx - half,       cx + half,       ymedia - 11, ymedia + 11, "playpause"),
            (cx + gap - half, cx + gap + half, ymedia - 11, ymedia + 11, "next"),
        ]
        y3 = PAD + 5 * ROW_H + ROW_H // 2 + NOWPLAYING_H   # clock + expand, below the now-playing band
        c.coords(self._expand_text, self.width - PAD, y3)
        self._expand_box = (self.width - PAD - ACTION_ZONE_W, y3 - 10, self.width, y3 + 10)

    def _set_active_tab(self, key):
        self.active_tab = feedmodel.coerce_tab(key)
        self._draw_feeds()

    def _refresh_news(self):
        idxs = self._news_indices()
        for i in idxs:
            self.feed_state.pop(i, None)
        self.manager.refresh(idxs)
        self._draw_feeds()

    def _refresh_github(self):
        reloaded = config.load(self.CFG_PATH)
        self.cfg["hud"]["github_token"] = reloaded["hud"].get("github_token", "")
        self.manager.set_token(self._github_token())
        idxs = self._github_indices()
        for i in idxs:
            self.feed_state.pop(i, None)
        self.manager.refresh(idxs)
        self._draw_feeds()

    def _set_stock_range(self, idx, code):
        feeds = self.manager.feeds
        ftype = feeds[idx].get("type") if 0 <= idx < len(feeds) else None
        if ftype == "weather":
            self.manager.set_weather_range(idx, code)
        else:
            self.manager.set_stock_range(idx, code)
        self.feed_state.pop(idx, None)
        self._draw_feeds()

    def _reload_feeds(self):
        reloaded = config.load(self.CFG_PATH)
        self.cfg["feeds"] = reloaded.get("feeds", [])
        self.cfg["hud"]["github_token"] = reloaded["hud"].get("github_token", "")
        self.feed_state = {}
        self.manager.set_token(self._github_token())
        self.manager.set_feeds(self.cfg["feeds"])
        self._draw_feeds()


def main():
    if not _smoke_ms() and not startup.acquire_single_instance("Toybox_hud"):
        return  # another HUD is already running
    cfg = config.load(CFG_PATH)
    hud_cfg = cfg["hud"]

    window.enable_dpi_awareness()  # before tk.Tk()

    root = tk.Tk()
    root.title("Toybox HUD")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", float(hud_cfg["alpha"]))
    except (tk.TclError, TypeError, ValueError):
        root.attributes("-alpha", 0.85)

    # Clamp the restored position into the visible primary work area so a stale
    # off-screen coordinate (e.g. a now-disconnected monitor) can't orphan this
    # borderless, title-bar-less window where it can't be dragged back.
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, min(int(hud_cfg["x"]), sw - WIDTH))
    y = max(0, min(int(hud_cfg["y"]), sh - HEIGHT))
    root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")
    root.configure(bg=BG)

    root.update()  # realize the HWND before touching ex-styles
    window.apply_overlay_styles(root, clickthrough=False, tool_window=True)

    hud = Hud(root, cfg)
    startup.watch_for_quit("Toybox_hud", root.after, root.destroy)

    ms = _smoke_ms()
    if ms:
        root.after(ms, root.destroy)
    try:
        root.mainloop()
    finally:
        hud.close()        # cleanup after the single root.destroy() (stops the worker)


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
