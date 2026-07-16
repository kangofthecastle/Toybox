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
import winkit.audiovolume as audiovolume
import winkit.diskinfo as diskinfo
import winkit.audio as audio
import winkit.monitors as monitors
import winkit.input as wkinput
import zonekit.geometry as zgeom
import zonekit.overlay as zoverlay
import zonekit.tracker as ztracker
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
NOWPLAYING_H = 32      # reserved band under the media row: title + bar + time labels
NP_BAR_H = 3           # progress-bar thickness (px)
NP_TIME_W = 34         # inset each side of the bar for the M:SS elapsed/total labels
VOLUME_H = 24          # reserved band under the now-playing band: mute glyph + slider
VOL_BAR_H = 4          # slider track thickness (px)
VOL_KNOB_R = 6         # slider knob radius (px)
VOL_GLYPH_W = 22       # left inset reserved for the mute/speaker glyph
VOL_PCT_W = 34         # right inset reserved for the "100%" readout
ZONES_H = 24           # reserved band under the volume band: monitor partition glyphs
HEIGHT = 156 + NOWPLAYING_H + VOLUME_H + ZONES_H   # header rows + np + volume + zones bands + margin
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
MEDIA_FONT = ("Segoe UI Symbol", 14)
MEDIA_PREV = "⏮"
MEDIA_PLAY = "⏯"
MEDIA_NEXT = "⏭"
MEDIA_GAP = 54                     # spacing between transport glyphs
MEDIA_HALF, MEDIA_VHALF = 20, 13   # transport tap-target half-extents
AUDIO_FONT = ("Segoe MDL2 Assets", 12)   # monochrome icon font (recolours via fill)
AUDIO_SPEAKER = ""           # MDL2 Volume glyph    -> HD-audio speakers
AUDIO_HEADPHONE = ""         # MDL2 Headphone glyph -> ARCAM headphones
AUDIO_GAP = 32                     # gap from 'next' to speaker (>MEDIA_HALF+AUDIO_HALF so hit-zones never touch)
AUDIO_SP = 22                      # gap between the speaker and headphone icons
AUDIO_HALF = 10                    # audio tap-target half-extent
NP_TITLE_FONT = ("Consolas", 9)
NP_TIME_FONT = ("Consolas", 8)   # elapsed / total M:SS labels flanking the bar
VOL_GLYPH_FONT = ("Segoe UI Symbol", 12)
VOL_LOUD = "\U0001F50A"    # speaker with sound waves
VOL_MUTED = "\U0001F507"   # muted speaker
ZONE_GLYPH_FONT = ("Segoe UI Symbol", 12)
ZONE_GLYPHS = {"off": "▯", "v": "◫", "h": "⊟"}   # per-monitor partition state
ZONE_GLYPH_SP = 26     # spacing between per-monitor partition glyphs
ZONE_HALF = 11         # partition glyph tap-target half-extent
ZONES_POLL_MS = 60     # Shift-drag watch sample interval (~16 Hz, like HotkeyPoller)
ZONES_MON_S = 5.0      # monitor-list refresh interval (plug/unplug pickup)
VK_LBUTTON = 0x01      # GetAsyncKeyState vk for the (physical) left mouse button
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
WEATHER_GLYPH_FONT = ("Segoe UI Symbol", 14)   # condition glyph (☀ ☁ ☔ ❄ ⛈)
WEATHER_HEAD_H = 20        # px for the glyph + current-temp lead row
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


def media_layout(width, audio_on):
    """x-centres for the transport controls (+ the audio output pair when
    audio_on). With audio shown, the transport+audio group is group-centred so
    both fit at the narrow 220px width; without audio the transport is plainly
    centred (unchanged behaviour). Returns keys prev/play/next/speaker/headphone
    (the audio keys are None when audio_on is False)."""
    cx = width // 2
    if not audio_on:
        return {"prev": cx - MEDIA_GAP, "play": cx, "next": cx + MEDIA_GAP,
                "speaker": None, "headphone": None}
    extent = 2 * MEDIA_GAP + AUDIO_GAP + AUDIO_SP
    prev = cx - extent // 2
    nxt = prev + 2 * MEDIA_GAP
    return {"prev": prev, "play": prev + MEDIA_GAP, "next": nxt,
            "speaker": nxt + AUDIO_GAP, "headphone": nxt + AUDIO_GAP + AUDIO_SP}


def zone_state_for(zones, device):
    """(layout, ratio) for a monitor device from the hud.zones list. Unknown
    devices and malformed entries read as ("off", 0.5); layout/ratio are
    coerced so a hand-edited config can't crash the zones engine."""
    for ent in zones or []:
        if isinstance(ent, dict) and ent.get("device") == device:
            layout = ent.get("layout")
            if layout not in zgeom.LAYOUTS:
                layout = "off"
            return layout, zgeom.clamp_ratio(ent.get("ratio", 0.5))
    return "off", 0.5


def zones_with_state(zones, device, layout=None, ratio=None):
    """A sanitized copy of the hud.zones list with `device`'s entry updated
    (created if new); only the fields passed change. Non-dict entries drop."""
    out = [dict(e) for e in (zones or []) if isinstance(e, dict)]
    for ent in out:
        if ent.get("device") == device:
            break
    else:
        ent = {"device": device, "layout": "off", "ratio": 0.5}
        out.append(ent)
    if layout is not None:
        ent["layout"] = layout
    if ratio is not None:
        ent["ratio"] = zgeom.clamp_ratio(ratio)
    return out


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
        # config.json feed-reload watcher: baseline the mtime now, BEFORE the first
        # tick() (called at the end of __init__), so tick never sees a spurious
        # change on startup.
        self._cfg_mtime = self._config_mtime()
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
        self._weather_glyph_font = tkfont.Font(root=root, family=WEATHER_GLYPH_FONT[0],
                                               size=WEATHER_GLYPH_FONT[1])

        # Persistent canvas items: created once, updated in place each tick
        # (no per-frame create/destroy churn -- matches the lightweight pattern).
        c = self.canvas
        y1 = PAD + ROW_H // 2
        y2 = PAD + ROW_H + ROW_H // 2
        ygpu = PAD + 2 * ROW_H + ROW_H // 2
        ydisk = PAD + 3 * ROW_H + ROW_H // 2     # disk row: row 4 (after GPU)
        y3 = PAD + 5 * ROW_H + ROW_H // 2 + NOWPLAYING_H + VOLUME_H + ZONES_H   # clock + expand, below the np/volume/zones bands
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
        self._ymedia = ymedia
        self._resolve_audio()          # -> self._spk_id / _hp_id / _audio_on
        lay = media_layout(self.width, self._audio_on)
        self._media_prev = c.create_text(lay["prev"], ymedia, text=MEDIA_PREV, fill=FG, font=MEDIA_FONT)
        self._media_play = c.create_text(lay["play"], ymedia, text=MEDIA_PLAY, fill=FG, font=MEDIA_FONT)
        self._media_next = c.create_text(lay["next"], ymedia, text=MEDIA_NEXT, fill=FG, font=MEDIA_FONT)
        self._media_hover = None   # which media glyph is currently hover-highlighted
        # Output-switch icons: speaker -> HD-audio, headphone -> ARCAM. Monochrome
        # MDL2 glyphs so the active one can be tinted ACCENT. Hidden when the two
        # configured devices don't both resolve (feature simply absent then).
        st = "normal" if self._audio_on else "hidden"
        self._audio_speaker = c.create_text(lay["speaker"] or 0, ymedia, text=AUDIO_SPEAKER,
                                            fill=DIM, font=AUDIO_FONT, state=st)
        self._audio_headphone = c.create_text(lay["headphone"] or 0, ymedia, text=AUDIO_HEADPHONE,
                                              fill=DIM, font=AUDIO_FONT, state=st)
        self._audio_hover = None
        self._audio_active = None
        self._audio_at_s = 0.0         # last default-endpoint poll (monotonic)
        self._relayout_media_hits(lay)
        self._refresh_audio_active()   # initial highlight

        # Now-playing band: reserved directly below the media row so the header
        # never jumps when playback starts/stops. Two rows: the title, then the
        # progress bar flanked by elapsed/total M:SS time labels.
        np_top = ymedia + ROW_H // 2                 # bottom edge of the media row band
        self._np_row_y = np_top + NOWPLAYING_H - 8   # baseline of the bar + time labels
        self._np_bar_y = self._np_row_y - NP_BAR_H // 2
        b_left, b_right = self._np_bar_bounds()
        self._np_title = c.create_text(self.width // 2, np_top + 8, anchor="center",
                                       text="", fill=DIM, font=NP_TITLE_FONT)
        self._np_bar_bg = c.create_rectangle(b_left, self._np_bar_y, b_right,
                                             self._np_bar_y + NP_BAR_H,
                                             fill=NP_TRACK, outline="")
        self._np_bar = c.create_rectangle(b_left, self._np_bar_y, b_left,
                                          self._np_bar_y + NP_BAR_H,
                                          fill=ACCENT, outline="")
        self._np_elapsed = c.create_text(b_left - 5, self._np_row_y, anchor="e",
                                         text="", fill=DIM, font=NP_TIME_FONT)
        self._np_total = c.create_text(b_right + 5, self._np_row_y, anchor="w",
                                       text="", fill=DIM, font=NP_TIME_FONT)
        self._np_lock = threading.Lock()
        self._np_latest = None                       # NowPlaying or None (poll thread writes)
        self._np_stop = threading.Event()
        self._np_thread = None
        self._np_scroll = None            # now-playing title ticker state, or None (fits/blank)
        self._np_marquee_after = None     # pending after() id for the ticker loop
        self._np_seekable = False         # True only while a timeline is present (click-to-seek armed)
        self._np_bar_span = (b_left, b_right)   # last drawn bar span, for seek hit-testing
        self._np_duration = 0.0           # last drawn track duration (s), for seek target math

        # Volume band: reserved directly below the now-playing band. A mute glyph,
        # a draggable slider (track + fill + knob), and a right-aligned percent.
        vy = (ymedia + ROW_H // 2) + NOWPLAYING_H + VOLUME_H // 2   # under the np band
        self._vol_row_y = vy
        v_left, v_right = self._vol_bar_bounds()
        self._vol_bar_span = (v_left, v_right)
        self._vol_glyph = c.create_text(PAD, vy, anchor="w", text=VOL_LOUD,
                                        fill=FG, font=VOL_GLYPH_FONT)
        self._vol_bar_bg = c.create_rectangle(v_left, vy - VOL_BAR_H // 2, v_right,
                                              vy + VOL_BAR_H // 2, fill=NP_TRACK, outline="")
        self._vol_bar = c.create_rectangle(v_left, vy - VOL_BAR_H // 2, v_left,
                                           vy + VOL_BAR_H // 2, fill=ACCENT, outline="")
        self._vol_knob = c.create_oval(v_left - VOL_KNOB_R, vy - VOL_KNOB_R,
                                       v_left + VOL_KNOB_R, vy + VOL_KNOB_R,
                                       fill=FG, outline="")
        self._vol_pct = c.create_text(self.width - PAD, vy, anchor="e", text="",
                                      fill=DIM, font=NP_TIME_FONT)
        self._vol_level = None       # 0..1, or None until first read
        self._vol_muted = False
        self._vol_dragging = False
        self._vol_press_glyph = False
        self._vol_apply_at = 0.0     # monotonic time of last COM write (drag throttle)

        # Partitions (zones) band: one glyph per monitor under the volume band.
        # Left-click cycles off/vertical/horizontal, right-click opens the
        # divider editor. Snapped-window memory is session-only; the per-monitor
        # layout+ratio persist in cfg["hud"]["zones"] (a list, like feeds).
        zy = (ymedia + ROW_H // 2) + NOWPLAYING_H + VOLUME_H + ZONES_H // 2
        self._zone_row_y = zy
        self._zone_label = c.create_text(PAD, zy, anchor="w", text="SPLIT",
                                         fill=DIM, font=NP_TIME_FONT)
        self._zone_items = []      # [(canvas id, device)], parallel to hits
        self._zone_hits = []       # (x0, x1, y0, y1, device) tap zones
        self._zone_hover = None    # device currently hover-highlighted, or None
        self._monitors = []        # cached winkit.monitors.list_monitors()
        self._mon_at = 0.0         # last monitor refresh (monotonic)
        self._zone_windows = {}    # hwnd -> (device, zone idx); session-only
        self._zone_overlay = None  # SnapOverlay while a Shift-drag is live
        self._zone_editor = None   # DividerEditor while editing a ratio
        self._zones_after = None   # pending after() id of the zones tick
        self._zone_tracker = ztracker.DragTracker(
            shift_down=lambda: wkinput.key_down(wkinput.vk_for("shift")),
            button_down=lambda: wkinput.key_down(VK_LBUTTON),
            foreground=window.foreground_window,
            rect_of=window.window_rect,
            snappable=window.is_snappable,
            cursor_pos=wkinput.cursor_pos)
        self._refresh_monitors(force=True)

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
            w.bind("<MouseWheel>", self._on_wheel)
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
        self._tick_after = None
        self.tick()
        self._zones_tick()
        self._drain_after = self.root.after(250, self._drain_feeds)

    # --- dragging ---------------------------------------------------------
    def _on_press(self, event):
        self._moved = False
        self._vol_dragging = False
        self._vol_press_glyph = self._vol_glyph_hit(event.x, event.y)
        self._drag_dx = event.x_root - self.root.winfo_x()
        self._drag_dy = event.y_root - self.root.winfo_y()
        if not self._vol_press_glyph and self._vol_hit(event.x, event.y):
            self._vol_dragging = True                 # slider grab: adjust volume, don't move window
            self._vol_set_from_x(event.x)

    def _on_drag(self, event):
        if self._vol_dragging:
            self._vol_set_from_x(event.x)             # adjust volume; window stays put
            return
        if self.lock_var.get():
            return  # position is locked
        self._moved = True
        x = event.x_root - self._drag_dx
        y = event.y_root - self._drag_dy
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, event):
        if self._vol_dragging:
            self._vol_dragging = False
            try:
                audiovolume.set_level(audiovolume.clamp01(self._vol_level))  # final position sticks
            except Exception:
                pass
            return
        if self._vol_press_glyph:
            self._vol_press_glyph = False
            if not self._moved and self._vol_glyph_hit(event.x, event.y):
                self._toggle_mute()
                return
        if not self._moved:
            if self._in_expand(event.x, event.y):
                self._toggle_width()
                return
            key = self._media_at(event.x, event.y)        # persistent media glyph zones (unchanged)
            if key is not None:
                self._do_media(key)
                return
            slot = self._audio_at(event.x, event.y)        # speaker/headphone output switch
            if slot is not None:
                self._do_audio(slot)
                return
            dev = self._zone_glyph_at(event.x, event.y)    # partition glyph: cycle layout
            if dev is not None:
                self._cycle_zone_layout(dev)
                return
            if self._np_seek_at(event.x, event.y):        # click on the progress bar -> seek
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

    # --- audio output switch ---------------------------------------------
    def _resolve_audio(self):
        """Resolve the two configured output endpoints to live device ids. Sets
        self._spk_id / _hp_id (or None) and self._audio_on (both present). Skips
        all COM work when neither slot is configured (keeps default tests light)."""
        acfg = (self.cfg.get("hud", {}) or {}).get("audio", {}) or {}
        spk = acfg.get("speaker", {}) or {}
        hp = acfg.get("headphone", {}) or {}
        self._spk_id = self._hp_id = None
        if not (spk.get("id") or spk.get("name") or hp.get("id") or hp.get("name")):
            self._audio_on = False
            return
        try:
            devs = audio.list_render_devices()
        except Exception:
            devs = []
        self._spk_id = audio.match_device(devs, spk.get("id", ""), spk.get("name", ""))
        self._hp_id = audio.match_device(devs, hp.get("id", ""), hp.get("name", ""))
        self._audio_on = bool(self._spk_id and self._hp_id)

    def _relayout_media_hits(self, lay):
        """Rebuild the transport (+ audio) tap zones for the given layout."""
        y, mh, mv = self._ymedia, MEDIA_HALF, MEDIA_VHALF
        self._media_hits = [
            (lay["prev"] - mh, lay["prev"] + mh, y - mv, y + mv, "prev"),
            (lay["play"] - mh, lay["play"] + mh, y - mv, y + mv, "playpause"),
            (lay["next"] - mh, lay["next"] + mh, y - mv, y + mv, "next"),
        ]
        self._audio_hits = []
        if self._audio_on:
            ah = AUDIO_HALF
            self._audio_hits = [
                (lay["speaker"] - ah, lay["speaker"] + ah, y - mv, y + mv, "speaker"),
                (lay["headphone"] - ah, lay["headphone"] + ah, y - mv, y + mv, "headphone"),
            ]

    def _audio_at(self, x, y):
        """Return 'speaker'/'headphone' if (x, y) hits an output icon, else None."""
        for x0, x1, y0, y1, slot in self._audio_hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return slot
        return None

    def _set_audio_hover(self, slot):
        if slot == self._audio_hover:
            return
        self._audio_hover = slot
        self._recolor_audio()

    def _recolor_audio(self):
        """Active output icon -> ACCENT; a hovered inactive one -> FG; else DIM."""
        for slot, item in (("speaker", getattr(self, "_audio_speaker", None)),
                           ("headphone", getattr(self, "_audio_headphone", None))):
            if item is None:
                continue
            if slot == self._audio_active:
                fill = ACCENT
            elif slot == self._audio_hover:
                fill = FG
            else:
                fill = DIM
            try:
                self.canvas.itemconfig(item, fill=fill)
            except tk.TclError:
                pass

    def _do_audio(self, slot):
        """Switch the default output device to the clicked slot's endpoint."""
        dev = self._spk_id if slot == "speaker" else self._hp_id
        if dev and audio.set_default_render(dev):
            self._audio_active = slot
            self._recolor_audio()

    def _refresh_audio_active(self):
        """Light the icon matching the OS default output -- reflects our own
        switches and any change made elsewhere in Windows. No-op when off."""
        if not self._audio_on:
            return
        try:
            cur = audio.default_render_id()
        except Exception:
            return
        new = audio.active_slot(cur, self._spk_id, self._hp_id)
        if new != self._audio_active:
            self._audio_active = new
            self._recolor_audio()

    # --- monitor partitions (zones) ----------------------------------------
    def _refresh_monitors(self, force=False):
        """Cache the monitor list, refreshing at most every ZONES_MON_S so
        plug/unplug is picked up without an enumeration per 60ms sample."""
        now = time.monotonic()
        if not force and now - self._mon_at < ZONES_MON_S:
            return
        self._mon_at = now
        try:
            mons = monitors.list_monitors()
        except Exception:
            mons = []
        changed = [m["device"] for m in mons] != [m["device"] for m in self._monitors]
        self._monitors = mons
        if changed:
            self._draw_zone_glyphs()

    def _monitor_by_device(self, device):
        for m in self._monitors:
            if m["device"] == device:
                return m
        return None

    def _zone_state(self, device):
        return zone_state_for(self.cfg["hud"].get("zones", []), device)

    def _set_zone_state(self, device, layout=None, ratio=None):
        self.cfg["hud"]["zones"] = zones_with_state(
            self.cfg["hud"].get("zones", []), device, layout=layout, ratio=ratio)
        try:
            # Scoped write: the zones list is wholly HUD-owned, so replacing it
            # is safe and everything else in config.json survives untouched.
            config.update(CFG_PATH, {"hud": {"zones": self.cfg["hud"]["zones"]}})
        except Exception:
            pass
        self._recolor_zone_glyphs()
        self._resnap_zone_windows(device)

    def _cycle_zone_layout(self, device):
        layout, _ = self._zone_state(device)
        self._set_zone_state(device, layout=zgeom.next_layout(layout))

    def _any_zone_active(self):
        return any(self._zone_state(m["device"])[0] != "off" for m in self._monitors)

    def _draw_zone_glyphs(self):
        """(Re)create the per-monitor partition glyphs, right-aligned in the
        zones band (primary monitor leftmost). Rebuilds the tap zones."""
        c = self.canvas
        for item, _dev in self._zone_items:
            c.delete(item)
        self._zone_items = []
        self._zone_hits = []
        y = self._zone_row_y
        x = self.width - PAD - ZONE_HALF
        for m in reversed(self._monitors):
            dev = m["device"]
            item = c.create_text(x, y, anchor="center", text="", font=ZONE_GLYPH_FONT)
            self._zone_items.append((item, dev))
            self._zone_hits.append((x - ZONE_HALF, x + ZONE_HALF,
                                    y - ZONE_HALF, y + ZONE_HALF, dev))
            x -= ZONE_GLYPH_SP
        self._recolor_zone_glyphs()

    def _recolor_zone_glyphs(self):
        """Glyph shows the layout; active layout -> ACCENT, hovered -> FG, else DIM."""
        for item, dev in self._zone_items:
            layout, _ = self._zone_state(dev)
            if layout != "off":
                fill = ACCENT
            elif dev == self._zone_hover:
                fill = FG
            else:
                fill = DIM
            try:
                self.canvas.itemconfig(item, text=ZONE_GLYPHS[layout], fill=fill)
            except tk.TclError:
                pass

    def _zone_glyph_at(self, x, y):
        """The device whose partition glyph is at (x, y), else None."""
        for x0, x1, y0, y1, dev in self._zone_hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return dev
        return None

    def _set_zone_hover(self, dev):
        if dev == self._zone_hover:
            return
        self._zone_hover = dev
        self._recolor_zone_glyphs()

    def _zones_tick(self):
        """~16 Hz Shift-drag watch (the zone-snap engine). Cheap when idle:
        three GetAsyncKeyState reads gated behind _any_zone_active(). A sample
        failure never kills the loop (HotkeyPoller pattern)."""
        self._zones_after = None
        try:
            self._refresh_monitors()
            if self._zone_editor is not None:
                pass                          # ratio editing pauses the watch
            elif self._any_zone_active():
                event = self._zone_tracker.sample()
                if event is not None:
                    self._zone_event(event)
            elif self._zone_overlay is not None:
                self._hide_zone_overlay()
        except Exception:
            pass
        finally:
            self._zones_after = self.root.after(ZONES_POLL_MS, self._zones_tick)

    def _zone_event(self, event):
        kind = event[0]
        if kind == "drag":
            _, _hwnd, x, y = event
            self._zone_drag_at(x, y)
        elif kind == "drop":
            _, hwnd, x, y = event
            self._hide_zone_overlay()
            self._zone_drop(hwnd, x, y)
        else:  # cancel
            self._hide_zone_overlay()

    def _zone_drag_at(self, x, y):
        """Show/refresh the snap overlay on the monitor under the cursor and
        highlight the zone that a drop would fill."""
        try:
            m = monitors.monitor_at(x, y)
        except Exception:
            m = None
        if m is None:
            self._hide_zone_overlay()
            return
        layout, ratio = self._zone_state(m["device"])
        if layout == "off":
            self._hide_zone_overlay()
            return
        ov = self._zone_overlay
        if ov is None or (ov.device, ov.layout, ov.ratio) != (m["device"], layout, ratio):
            self._hide_zone_overlay()
            try:
                self._zone_overlay = zoverlay.SnapOverlay(self.root, m, layout, ratio)
            except Exception:
                self._zone_overlay = None
                return
        self._zone_overlay.highlight(zgeom.zone_at(m["work"], layout, ratio, x, y))

    def _zone_drop(self, hwnd, x, y):
        try:
            m = monitors.monitor_at(x, y)
        except Exception:
            return
        if m is None:
            return
        layout, ratio = self._zone_state(m["device"])
        if layout == "off":
            return
        zone = zgeom.zone_at(m["work"], layout, ratio, x, y)
        if zone is None:
            return
        rect = zgeom.zone_rects(m["work"], layout, ratio)[zone]
        if window.move_window(hwnd, *rect):
            self._zone_windows[hwnd] = (m["device"], zone)

    def _resnap_zone_windows(self, device):
        """Re-fit this session's snapped windows on `device` after a layout or
        ratio change; prune entries whose window is gone or refuses to move."""
        m = self._monitor_by_device(device)
        layout, ratio = self._zone_state(device)
        for hwnd, (dev, zone) in list(self._zone_windows.items()):
            if dev != device:
                continue
            if m is None or layout == "off" or not window.is_window(hwnd):
                self._zone_windows.pop(hwnd, None)
                continue
            rect = zgeom.zone_rects(m["work"], layout, ratio)[zone]
            if not window.move_window(hwnd, *rect):
                self._zone_windows.pop(hwnd, None)

    def _hide_zone_overlay(self):
        if self._zone_overlay is not None:
            self._zone_overlay.destroy()
            self._zone_overlay = None

    def _open_zone_editor(self, device):
        layout, ratio = self._zone_state(device)
        m = self._monitor_by_device(device)
        if m is None or layout == "off":
            return                      # nothing to edit while the split is off
        self._close_zone_editor()
        self._hide_zone_overlay()
        try:
            self._zone_editor = zoverlay.DividerEditor(
                self.root, m, layout, ratio,
                on_commit=lambda r, d=device: self._zone_ratio_committed(d, r),
                on_cancel=self._zone_editor_closed)
        except Exception:
            self._zone_editor = None

    def _zone_ratio_committed(self, device, ratio):
        self._zone_editor = None
        self._set_zone_state(device, ratio=ratio)

    def _zone_editor_closed(self):
        self._zone_editor = None

    def _close_zone_editor(self):
        if self._zone_editor is not None:
            self._zone_editor.destroy()
            self._zone_editor = None

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
        dev = self._zone_glyph_at(event.x, event.y)
        if dev is not None:                   # right-click a partition glyph:
            self._open_zone_editor(dev)       # divider editor, not the menu
            return
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
        if now - self._audio_at_s >= 2:          # reflect default-output changes made elsewhere
            self._refresh_audio_active()
            self._audio_at_s = now
        self._reload_feeds_if_config_changed()   # live-pick-up of edited feeds/token
        self._draw()
        self._draw_nowplaying()
        self._refresh_volume()
        self._draw_volume()
        self._tick_after = self.root.after(1000, self.tick)

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

    def _np_bar_bounds(self):
        """Horizontal span (x_left, x_right) of the progress bar, inset on both
        sides to leave room for the elapsed/total M:SS time labels."""
        return PAD + NP_TIME_W, self.width - PAD - NP_TIME_W

    def _vol_bar_bounds(self):
        """(x_left, x_right) of the slider track, inset for the glyph and percent."""
        return PAD + VOL_GLYPH_W, self.width - PAD - VOL_PCT_W

    def _refresh_volume(self):
        """Pull the live system level/mute (main-thread; the call is fast). Skipped
        while the user is dragging so the optimistic drag value is not clobbered."""
        if self._vol_dragging:
            return
        v = audiovolume.get()
        if v is not None:
            self._vol_level, self._vol_muted = v

    def _draw_volume(self):
        """Render the slider fill, knob, mute glyph and percent from _vol_level /
        _vol_muted. Muted greys the fill and swaps the glyph (the knob stays put so
        unmuting restores the level). Blank until the first read. Never raises."""
        c = self.canvas
        vy = self._vol_row_y
        v_left, v_right = self._vol_bar_span
        try:
            if self._vol_level is None:
                c.itemconfig(self._vol_pct, text="")
                c.coords(self._vol_bar, v_left, vy - VOL_BAR_H // 2, v_left,
                         vy + VOL_BAR_H // 2)
                return
            frac = audiovolume.clamp01(self._vol_level)
            kx = v_left + int((v_right - v_left) * frac)
            c.coords(self._vol_bar, v_left, vy - VOL_BAR_H // 2, kx, vy + VOL_BAR_H // 2)
            c.itemconfig(self._vol_bar, fill=(DIM if self._vol_muted else ACCENT))
            c.coords(self._vol_knob, kx - VOL_KNOB_R, vy - VOL_KNOB_R,
                     kx + VOL_KNOB_R, vy + VOL_KNOB_R)
            c.itemconfig(self._vol_glyph, text=(VOL_MUTED if self._vol_muted else VOL_LOUD))
            c.itemconfig(self._vol_pct, text=audiovolume.format_pct(frac))
        except tk.TclError:
            pass

    def _vol_hit(self, x, y):
        """True if (x, y) is on the slider track (a generous vertical band)."""
        v_left, v_right = self._vol_bar_span
        return (v_left - 8 <= x <= v_right + 8 and
                self._vol_row_y - (VOL_KNOB_R + 5) <= y <= self._vol_row_y + (VOL_KNOB_R + 5))

    def _vol_glyph_hit(self, x, y):
        """True if (x, y) is on the mute/speaker glyph at the row's left."""
        return (PAD - 2 <= x <= PAD + VOL_GLYPH_W - 2 and
                self._vol_row_y - 10 <= y <= self._vol_row_y + 10)

    def _vol_set_from_x(self, x):
        """Set the level from a click/drag x: update the shown value immediately,
        unmute if muted (matches Windows), and write to the device (throttled to
        ~30 ms so a fast drag doesn't hammer COM)."""
        v_left, v_right = self._vol_bar_span
        frac = audiovolume.level_from_x(x, v_left, v_right)
        self._vol_level = frac
        if self._vol_muted:
            self._vol_muted = False
            audiovolume.set_mute(False)
        self._draw_volume()
        now = time.monotonic()
        if now - self._vol_apply_at >= 0.03:
            audiovolume.set_level(frac)
            self._vol_apply_at = now

    def _toggle_mute(self):
        """Flip mute (the speaker glyph); reflect it immediately."""
        self._vol_muted = not self._vol_muted
        audiovolume.set_mute(self._vol_muted)
        self._draw_volume()

    def _on_wheel(self, event):
        """Mouse wheel over the track nudges the level +/-2% per notch; ignored
        elsewhere. A nudge up also unmutes."""
        if not self._vol_hit(event.x, event.y):
            return
        step = 0.02 if getattr(event, "delta", 0) > 0 else -0.02
        base = self._vol_level if self._vol_level is not None else 0.0
        self._vol_level = audiovolume.step_level(base, step)
        if self._vol_muted and step > 0:
            self._vol_muted = False
            audiovolume.set_mute(False)
        audiovolume.set_level(self._vol_level)
        self._draw_volume()

    def _draw_nowplaying(self):
        """Update the title line, progress bar and elapsed/total time labels from
        the latest SMTC sample. The bar advances with wall-clock so it moves
        smoothly between reads. A title that fits renders static and centered; a
        title that overflows auto-scrolls (music-player ticker: scroll left to
        reveal the end, then jump back to the start -- never bouncing). Blank when
        nothing is playing; bar + times hidden when the source has no timeline.
        Never raises."""
        c = self.canvas
        with self._np_lock:
            s = self._np_latest
        t_left, t_right = PAD, self.width - PAD           # title budget: full width
        b_left, b_right = self._np_bar_bounds()           # bar span: inset for time labels
        y0, y1 = self._np_bar_y, self._np_bar_y + NP_BAR_H
        try:
            # np items are persistent (created once, never deleted), so coords()
            # always returns a populated list here -- [1] is safe.
            title_y = self.canvas.coords(self._np_title)[1]
            if s is None or s.status == "stopped":
                self._np_scroll = None                       # nothing playing -> no ticker
                self._np_seekable = False
                c.itemconfig(self._np_title, text="", anchor="center")
                c.coords(self._np_title, self.width // 2, title_y)
                c.coords(self._np_bar, b_left, y0, b_left, y1)   # zero width => blank
                for it in (self._np_bar_bg, self._np_elapsed, self._np_total):
                    c.itemconfig(it, state="hidden")
                return
            text = nowplaying.format_track(s.title, s.artist)
            pos = nowplaying.advance(s.position_s, time.monotonic() - s.sampled_at,
                                     s.status)
            frac = nowplaying.progress_fraction(pos, s.duration_s)
            if s.duration_s > 0:                             # timeline present -> bar + times + seek
                self._np_seekable = True
                self._np_bar_span = (b_left, b_right)
                self._np_duration = s.duration_s
                for it in (self._np_bar_bg, self._np_bar, self._np_elapsed, self._np_total):
                    c.itemconfig(it, state="normal")
                c.coords(self._np_bar, b_left, y0, b_left + int((b_right - b_left) * frac), y1)
                c.itemconfig(self._np_elapsed, text=nowplaying.format_clock(pos))
                c.itemconfig(self._np_total, text=nowplaying.format_clock(s.duration_s))
            else:                                            # no timeline (e.g. foobar2000) -> hide, no seek
                self._np_seekable = False
                for it in (self._np_bar_bg, self._np_bar, self._np_elapsed, self._np_total):
                    c.itemconfig(it, state="hidden")
            c.itemconfig(self._np_title, text=text)          # FULL text; the widget edge clips overflow
            max_off = nowplaying.marquee_scroll_max(
                self._feed_font_measure.measure(text), t_right - t_left)
            if max_off <= 0:
                self._np_scroll = None                       # fits => static, centered
                c.itemconfig(self._np_title, anchor="center")
                c.coords(self._np_title, self.width // 2, title_y)
            else:
                if self._np_scroll is None or self._np_scroll.get("text") != text:
                    self._np_scroll = {"text": text, "offset": 0, "pause": 0}
                self._np_scroll["max"] = max_off
                self._np_scroll["base_x"] = t_left
                c.itemconfig(self._np_title, anchor="w")
                c.coords(self._np_title, t_left - self._np_scroll["offset"], title_y)
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
            # _np_title is persistent (never deleted), so coords() is always
            # populated here -- [1] is safe.
            y = self.canvas.coords(self._np_title)[1]
            self.canvas.coords(self._np_title, m["base_x"] - m["offset"], y)
        except tk.TclError:
            self._np_marquee_after = None
            return
        self._np_marquee_after = self.root.after(33, self._np_marquee_step)

    def _np_seek_at(self, x, y):
        """If (x, y) falls on the now-playing progress bar and a seekable timeline
        is present, seek there -- optimistically jumping the local sample so the
        bar moves at once -- and return True; otherwise return False. The real
        SMTC seek runs off the UI thread (it can block ~1s)."""
        if not self._np_seekable:
            return False
        b_left, b_right = self._np_bar_span
        if not (b_left - 4 <= x <= b_right + 4 and
                self._np_row_y - 8 <= y <= self._np_row_y + 8):
            return False
        target = nowplaying.seek_target_seconds(x, b_left, b_right, self._np_duration)
        self._dispatch_seek(target)
        with self._np_lock:                              # optimistic: reflect the seek now
            s = self._np_latest
            if s is not None:
                self._np_latest = s._replace(position_s=target,
                                             sampled_at=time.monotonic())
        self._draw_nowplaying()
        return True

    def _dispatch_seek(self, position_s):
        """Issue the SMTC seek off the UI thread (a test seam; the WinRT call can
        block up to ~1s while it drives the async to completion)."""
        threading.Thread(target=nowplaying.seek, args=(position_s,),
                         name="np-seek", daemon=True).start()

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

    def _weather_indices(self):
        """Indices of weather feeds -- always shown in their own section above the
        tabs, never tab-scoped."""
        return [i for i, f in enumerate(self.manager.feeds)
                if f.get("type") == "weather"]

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
        self._set_audio_hover(self._audio_at(event.x, event.y))
        self._set_zone_hover(self._zone_glyph_at(event.x, event.y))
        rec = self._scroll_line_at(event.x, event.y)
        if rec is not None:
            self._start_marquee(rec)
        else:
            self._stop_marquee()

    def _on_leave(self, event):
        self._hover_xy = None
        self._apply_hover()
        self._set_media_hover(None)
        self._set_audio_hover(None)
        self._set_zone_hover(None)
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
        y = PAD + 6 * ROW_H + 4 + NOWPLAYING_H + VOLUME_H + ZONES_H    # below header rows + np/volume/zones bands
        y = self._draw_schedule_tile(y)   # pinned "now" tile, above the tab bar
        for idx in self._weather_indices():   # weather: always shown, own tile (not tab-scoped)
            y = self._draw_tile(idx, self.manager.feeds[idx], y)
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
        fg = FEED_DIM if stale else FEED_FG
        color = FEED_DIM if stale else ACCENT
        # Lead row: condition glyph + current temperature + condition word.
        cx = PAD + 6
        glyph = feedmodel.weather_glyph(w.code)
        if glyph:
            gid = c.create_text(cx, y + WEATHER_HEAD_H // 2, anchor="w", text=glyph,
                                fill=color, font=WEATHER_GLYPH_FONT)
            self._feed_items.append(gid)
            cx += self._weather_glyph_font.measure(glyph) + 4
        curid = c.create_text(cx, y + WEATHER_HEAD_H // 2, anchor="w",
                              text=_fit(feedmodel.format_weather_current(w)),
                              fill=fg, font=FEED_TITLE_FONT)
        self._feed_items.append(curid)
        y += WEATHER_HEAD_H
        # Row: hi / lo (+ feels-like when known).
        hlid = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                             text=_fit(feedmodel.format_weather_hilo(w)),
                             fill=fg, font=FEED_FONT)
        self._feed_items.append(hlid)
        y += FEED_LINE_H
        # Row: humidity / wind / rain chance -- only when at least one is known.
        detail = feedmodel.format_weather_detail(w)
        if detail:
            did = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                                text=_fit(detail), fill=FEED_DIM, font=FEED_FONT)
            self._feed_items.append(did)
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
        if self._tick_after is not None:
            try:
                self.root.after_cancel(self._tick_after)
            except Exception:
                pass
            self._tick_after = None
        if self._zones_after is not None:
            try:
                self.root.after_cancel(self._zones_after)
            except Exception:
                pass
            self._zones_after = None
        self._hide_zone_overlay()
        self._close_zone_editor()
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
        self._draw_nowplaying()  # re-fill bar + reposition time labels at the new width
        self._draw_volume()      # reposition slider fill/knob at the new width
        self._draw_feeds()    # reflow feeds + resize the window (via _resize)

    def _relayout_header(self):
        """Move the width-dependent persistent header items to the current width:
        the centered clock and the media glyphs (+ their hit zones). Sparklines
        re-right-align on the next _update_spark, which reads self.width."""
        c = self.canvas
        cx = self.width // 2
        c.coords(self._clock_text, cx, self.canvas.coords(self._clock_text)[1])
        c.coords(self._np_title, cx, self.canvas.coords(self._np_title)[1])
        b_left, b_right = self._np_bar_bounds()
        c.coords(self._np_bar_bg, b_left, self._np_bar_y, b_right, self._np_bar_y + NP_BAR_H)
        c.coords(self._np_elapsed, b_left - 5, self._np_row_y)
        c.coords(self._np_total, b_right + 5, self._np_row_y)
        self._np_bar_span = (b_left, b_right)
        v_left, v_right = self._vol_bar_bounds()
        self._vol_bar_span = (v_left, v_right)
        c.coords(self._vol_glyph, PAD, self._vol_row_y)
        c.coords(self._vol_bar_bg, v_left, self._vol_row_y - VOL_BAR_H // 2,
                 v_right, self._vol_row_y + VOL_BAR_H // 2)
        c.coords(self._vol_pct, self.width - PAD, self._vol_row_y)
        ymedia = PAD + 4 * ROW_H + ROW_H // 2    # media row 5 (above clock)
        lay = media_layout(self.width, self._audio_on)
        c.coords(self._media_prev, lay["prev"], ymedia)
        c.coords(self._media_play, lay["play"], ymedia)
        c.coords(self._media_next, lay["next"], ymedia)
        if self._audio_on:
            c.coords(self._audio_speaker, lay["speaker"], ymedia)
            c.coords(self._audio_headphone, lay["headphone"], ymedia)
        self._relayout_media_hits(lay)
        y3 = PAD + 5 * ROW_H + ROW_H // 2 + NOWPLAYING_H + VOLUME_H + ZONES_H   # clock + expand, below the np/volume/zones bands
        c.coords(self._expand_text, self.width - PAD, y3)
        self._expand_box = (self.width - PAD - ACTION_ZONE_W, y3 - 10, self.width, y3 + 10)
        c.coords(self._zone_label, PAD, self._zone_row_y)
        self._draw_zone_glyphs()      # glyphs are right-aligned: x depends on width

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

    def _reload_feeds(self, reloaded=None):
        if reloaded is None:
            reloaded = config.load(self.CFG_PATH)
        self.cfg["feeds"] = reloaded.get("feeds", [])
        self.cfg["hud"]["github_token"] = reloaded["hud"].get("github_token", "")
        self.feed_state = {}
        self.manager.set_token(self._github_token())
        self.manager.set_feeds(self.cfg["feeds"])
        self._draw_feeds()

    def _config_mtime(self):
        """config.json's mtime, or None if it can't be stat'd. Cheap (one syscall)."""
        try:
            return os.stat(self.CFG_PATH).st_mtime
        except OSError:
            return None

    def _reload_feeds_if_config_changed(self):
        """Live-reload feeds when config.json changes on disk. mtime-gated, so the
        common case is a single os.stat per tick. Only reloads when the feeds or
        github_token actually differ from what's loaded -- so the HUD's own window-
        position/opacity saves (and any other toy's writes to its own section)
        change the mtime but never trigger a disruptive feed refetch. Runs on the
        main thread (called from tick()), so touching Tk in _reload_feeds is safe.
        Never raises."""
        try:
            mtime = self._config_mtime()
            if mtime is None or mtime == self._cfg_mtime:
                return
            self._cfg_mtime = mtime
            reloaded = config.load(self.CFG_PATH)
            if (reloaded.get("feeds", []) == self.cfg["feeds"]
                    and reloaded["hud"].get("github_token", "")
                    == self.cfg["hud"].get("github_token", "")):
                return                            # nothing feed-relevant changed
            self._reload_feeds(reloaded)
        except Exception:
            pass


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
