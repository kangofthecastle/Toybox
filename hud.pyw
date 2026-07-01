"""System Monitor HUD: a borderless, semi-transparent, always-on-top overlay
showing live CPU%, RAM%, a clock, and scrolling sparklines. Draggable (unless
locked); right-click for opacity presets, lock, and close. Updates at 1 Hz.
Pure Python 3.12 stdlib."""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winkit.startup as startup
startup.guard_streams()  # MUST be the first executable statement (pythonw-at-login safety)

import collections
import time

import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as tkmsg
import winkit.window as window
import winkit.metrics as metrics
import winkit.media as media
import config
import webbrowser
import timeago
import feedkit.manager as feedmanager
import feedkit.model as feedmodel

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
LOG_PATH = os.path.join(HERE, "toybox.log")

# Layout (logical px). Kept genuinely small per the lightweight requirement.
WIDTH = 220
HEIGHT = 134          # 5 header rows (CPU/RAM/GPU/clock/media) + margin
PAD = 10
ROW_H = 22
LABEL_X = PAD
SPARK_W = 84            # fixed-width sparkline area
SPARK_RIGHT = WIDTH - PAD
SPARK_LEFT = SPARK_RIGHT - SPARK_W
HISTORY = 60           # ~60 samples in the deque

BG = "#15151a"         # dark translucent background
FG = "#d8d8e0"         # light text
DIM = "#6a6a78"        # clock / faint text
CPU_COLOR = "#33d6ff"  # cyan
RAM_COLOR = "#ff5cc8"  # magenta
GPU_COLOR = "#7ee787"  # green
FONT = ("Consolas", 11)
CLOCK_FONT = ("Consolas", 11, "bold")
MEDIA_FONT = ("Segoe UI Symbol", 12)
MEDIA_PREV = "⏮"
MEDIA_PLAY = "⏯"
MEDIA_NEXT = "⏭"

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
        self.settings = None      # FeedSettingsWindow singleton (Task 11)
        self.active_tab = feedmodel.coerce_default_tab(cfg["hud"].get("default_tab"))
        token = self._github_token()
        self.manager = feedmanager.FeedManager(cfg.get("feeds", []), token=token)

        self.canvas = tk.Canvas(
            root, width=WIDTH, height=HEIGHT, bg=BG,
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
        y3 = PAD + 3 * ROW_H + ROW_H // 2
        self._cpu_text = c.create_text(LABEL_X, y1, anchor="w", text="CPU   0%", fill=FG, font=FONT)
        self._ram_text = c.create_text(LABEL_X, y2, anchor="w", text="RAM   0%", fill=FG, font=FONT)
        self._gpu_text = c.create_text(LABEL_X, ygpu, anchor="w", text="GPU   0%", fill=FG, font=FONT)
        self._clock_text = c.create_text(WIDTH // 2, y3, anchor="center", text="", fill=DIM, font=CLOCK_FONT)
        self._cpu_line = c.create_line(0, 0, 0, 0, fill=CPU_COLOR, width=1, state="hidden")
        self._ram_line = c.create_line(0, 0, 0, 0, fill=RAM_COLOR, width=1, state="hidden")
        self._gpu_line = c.create_line(0, 0, 0, 0, fill=GPU_COLOR, width=1, state="hidden")
        self._cpu_band = (PAD + 1, PAD + ROW_H - 1)
        self._ram_band = (PAD + ROW_H + 1, PAD + 2 * ROW_H - 1)
        self._gpu_band = (PAD + 2 * ROW_H + 1, PAD + 3 * ROW_H - 1)

        ymedia = PAD + 4 * ROW_H + ROW_H // 2
        cx = WIDTH // 2
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

    def _media_at(self, x, y):
        """Return the media-control key at (x, y) among the three fixed glyph
        zones, or None. Boxes are constants (persistent glyphs)."""
        for x0, x1, y0, y1, key in self._media_hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return key
        return None

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
        self._draw()
        self.root.after(1000, self.tick)

    def _draw(self):
        c = self.canvas
        c.itemconfig(self._cpu_text, text=f"CPU {self.cpu:3.0f}%")
        c.itemconfig(self._ram_text, text=f"RAM {self.ram:3.0f}%")
        if self.gpu is None:
            c.itemconfig(self._gpu_text, text="GPU  --%", fill=DIM)
        else:
            c.itemconfig(self._gpu_text, text=f"GPU {self.gpu:3.0f}%", fill=FG)
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
        x0 = SPARK_RIGHT - (n - 1) * step  # newest sample sits at the right edge
        pts = []
        for i, v in enumerate(hist):
            frac = max(0.0, min(1.0, v / 100.0))
            pts.extend((x0 + i * step, bottom - frac * height))
        self.canvas.coords(line_id, *pts)
        self.canvas.itemconfig(line_id, state="normal")

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
        for idx, result in self.manager.drain():
            self.feed_state[idx] = result
        try:
            self._draw_feeds()
        except tk.TclError:
            return                                  # window gone; stop the loop
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
        if len(tile) == 2:                       # ("stocks", payload)
            return self._draw_stock_tile(idx, tile[1], y)
        title, title_url, color, lines, header_action = tile
        c = self.canvas
        y += FEED_TITLE_GAP
        tid = c.create_text(PAD, y, anchor="w", text=self._fit_px(title, PAD), fill=color, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        self._register_hit(y, title_url)
        if header_action is not None:
            mk = c.create_text(WIDTH - PAD, y, anchor="e", text=MARKALL_GLYPH,
                               fill=FEED_DIM, font=FEED_TITLE_FONT)
            self._feed_items.append(mk)
            self._register_action(y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, header_action)
        y += FEED_LINE_H
        for row in lines:
            if len(row) == 3:
                text, url, dim = row
                lid = c.create_text(PAD + 6, y, anchor="w", text=self._fit_px(text, PAD + 6),
                                    fill=(FEED_DIM if dim else FEED_FG), font=FEED_FONT)
                self._feed_items.append(lid)
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
                    aid = c.create_text(WIDTH - PAD - reserve, y, anchor="e", text=age,
                                        fill=FEED_DIM, font=FEED_FONT)
                    self._feed_items.append(aid)
                if dismiss is not None:
                    xg = c.create_text(WIDTH - PAD, y, anchor="e", text=DISMISS_GLYPH,
                                       fill=FEED_DIM, font=FEED_FONT)
                    self._feed_items.append(xg)
                    self._register_action(y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, dismiss)
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
        a clickable feed row highlights the full content width. Refresh/dismiss
        glyph zones are intentionally not highlighted."""
        for y0, y1, x0, x1, action in self._action_hits:
            if y0 <= y <= y1 and x0 <= x <= x1 and action[0] in ("tab", "range"):
                return (x0 - 3, y0, x1 + 3, y1)
        for y0, y1, _url in self._hit:
            if y0 <= y <= y1:
                return (PAD, y0, WIDTH - PAD, y1)
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

    def _on_motion(self, event):
        self._hover_xy = (event.x, event.y)
        self._apply_hover()

    def _on_leave(self, event):
        self._hover_xy = None
        self._apply_hover()

    def _fit_px(self, text, x_start):
        """Trim text with an ellipsis so it fits from x_start to the right margin
        at FEED_FONT width (pixel-accurate, unlike the char-count _fit)."""
        m = self._feed_font_measure.measure
        budget = WIDTH - PAD - x_start
        if m(text) <= budget:
            return text
        while text and m(text + "…") > budget:
            text = text[:-1]
        return text + "…"

    def _fit_line1(self, text, age, reserve=0):
        """Truncate line 1 by measured pixel width so it never collides with the
        right-aligned age (and the ✕ glyph when present, via reserve px)."""
        m = self._feed_font_measure.measure
        budget = WIDTH - 2 * PAD - m(age) - 8 - reserve
        if m(text) <= budget:
            return text
        while text and m(text + "…") > budget:
            text = text[:-1]
        return text + "…"

    def _draw_feeds(self):
        c = self.canvas
        for item_id in self._feed_items:
            c.delete(item_id)
        self._feed_items = []
        self._hit = []
        self._action_hits = []
        if self._hover_item is not None:
            c.delete(self._hover_item)
            self._hover_item = None
        self._hover_rect = None
        y = PAD + 5 * ROW_H + 4                   # below the 5-row header (CPU/RAM/GPU/clock/media)
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
        rid = c.create_text(WIDTH - PAD, row_y, anchor="e", text=RELOAD_GLYPH,
                            fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(rid)
        self._register_action(row_y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, ("refresh", "news"))
        return y + FEED_LINE_H + FEED_TITLE_GAP

    def _draw_github_header(self, y):
        c = self.canvas
        dv = c.create_line(PAD, y + 1, WIDTH - PAD, y + 1, fill=FEED_DIM, width=1)
        self._feed_items.append(dv)
        row_y = y + FEED_LINE_H // 2
        tid = c.create_text(PAD, row_y, anchor="w", text="GitHub", fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        rid = c.create_text(WIDTH - PAD, row_y, anchor="e", text=RELOAD_GLYPH,
                            fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(rid)
        self._register_action(row_y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, ("refresh", "github"))
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
            pts = _stock_points(q.series, PAD + 6, WIDTH - PAD, y + 2, y + STOCK_CHART_H - 2)
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
        x = WIDTH - PAD
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

    def _resize(self, wanted_h):
        sh = self.root.winfo_screenheight()
        new_h = max(HEIGHT, min(int(wanted_h), sh - self.root.winfo_y()))
        if new_h != self.root.winfo_height():
            self.canvas.config(height=new_h)
            self.root.geometry("%dx%d" % (WIDTH, new_h))

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
        try:
            self.manager.stop()
        except Exception:
            pass
        if getattr(self, "settings", None) is not None:
            self.settings.close()

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
