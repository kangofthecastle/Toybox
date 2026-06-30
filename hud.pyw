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
HEIGHT = 96
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
FONT = ("Consolas", 11)
CLOCK_FONT = ("Consolas", 11, "bold")

FEED_FONT = ("Consolas", 9)
FEED_TITLE_FONT = ("Consolas", 9, "bold")
FEED_FG = "#c8c8d4"
FEED_DIM = "#6a6a78"
FEED_LINE_H = 15          # px per feed line
FEED_TITLE_GAP = 4        # px above each feed block
FEED_MAX_CHARS = 30       # truncate any feed text (title or item) to fit 220px
STATE_HEX = {"success": "#3fb950", "failure": "#f85149",
             "pending": "#d29922", "none": "#6a6a78"}
URGENCY_HEX = {"high": STATE_HEX["pending"], "normal": FEED_FG, "low": FEED_DIM}
DISMISS_GLYPH = "✕"   # ✕  per-item mark-read
MARKALL_GLYPH = "✓"   # ✓  header mark-all-read
ACTION_ZONE_W = 18         # px hit target at the right edge for ✕ / ✓


def _fit(text):
    """Truncate any feed line/title to FEED_MAX_CHARS so a long headline or repo
    name can't overflow the 220px width."""
    return text if len(text) <= FEED_MAX_CHARS else text[:FEED_MAX_CHARS - 1] + "…"


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
        self._drag_dx = 0
        self._drag_dy = 0
        self._moved = False
        self.lock_var = tk.BooleanVar(value=bool(cfg["hud"]["locked"]))
        self.CFG_PATH = CFG_PATH  # exposed for the settings window's config.save
        self.feed_state = {}      # idx -> feedmanager.FeedResult
        self._hit = []            # [(y0, y1, url)] for click-to-open (http/https only)
        self._action_hits = []    # [(y0,y1,x0,x1,action)] x-aware dismiss/mark-all zones
        self._feed_items = []     # canvas item ids to clear on each feed redraw
        self._drain_after = None  # pending after() id so close() can cancel it
        self.settings = None      # FeedSettingsWindow singleton (Task 11)
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
        y3 = PAD + 2 * ROW_H + ROW_H // 2
        self._cpu_text = c.create_text(LABEL_X, y1, anchor="w", text="CPU   0%", fill=FG, font=FONT)
        self._ram_text = c.create_text(LABEL_X, y2, anchor="w", text="RAM   0%", fill=FG, font=FONT)
        self._clock_text = c.create_text(WIDTH // 2, y3, anchor="center", text="", fill=DIM, font=CLOCK_FONT)
        self._cpu_line = c.create_line(0, 0, 0, 0, fill=CPU_COLOR, width=1, state="hidden")
        self._ram_line = c.create_line(0, 0, 0, 0, fill=RAM_COLOR, width=1, state="hidden")
        self._cpu_band = (PAD + 1, PAD + ROW_H - 1)
        self._ram_band = (PAD + ROW_H + 1, PAD + 2 * ROW_H - 1)

        # Dragging moves the whole window (it is borderless / overrideredirect).
        for w in (root, self.canvas):
            w.bind("<Button-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)
            w.bind("<Button-3>", self._on_menu)

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
        self._drain_feeds()

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
            action = self._action_at(event.x, event.y)   # dismiss/mark-all zone wins over open
            if action is not None:
                self._do_dismiss(action)
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
        self._draw()
        self.root.after(1000, self.tick)

    def _draw(self):
        c = self.canvas
        c.itemconfig(self._cpu_text, text=f"CPU {self.cpu:3.0f}%")
        c.itemconfig(self._ram_text, text=f"RAM {self.ram:3.0f}%")
        c.itemconfig(self._clock_text, text=time.strftime("%H:%M:%S"))
        self._update_spark(self._cpu_line, self.cpu_hist, self._cpu_band)
        self._update_spark(self._ram_line, self.ram_hist, self._ram_band)

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

    def _drain_feeds(self):
        self._drain_after = None
        for idx, result in self.manager.drain():
            self.feed_state[idx] = result
        try:
            self._draw_feeds()
        except tk.TclError:
            return                                  # window gone; stop the loop
        self._drain_after = self.root.after(250, self._drain_feeds)

    def _feed_tiles(self):
        """Yield (title, title_url, color, lines, header_action) per configured feed.
        title_url is the click target for the title line (None for non-github feeds);
        lines is a list of (text, url, dim) 3-tuples or (line1, url, color, subtitle,
        age, dismiss) 6-tuples for notifications items. Pulls live results from
        feed_state, falling back to a 'loading'/error placeholder. A github tile
        surfaces result.error even when CI itself returned ok (e.g. a bad notifications
        token)."""
        for idx, feed in enumerate(self.manager.feeds):
            title = feed.get("title") or "feed"
            if not feed.get("valid"):
                yield (title, None, FEED_DIM, [("! " + (feed.get("error") or "invalid"), None, True)], None)
                continue
            result = self.feed_state.get(idx)
            if result is None:
                yield (title, None, FEED_FG, [("loading…", None, True)], None)
                continue
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
                yield (header, "https://github.com/notifications", FEED_FG, lines, header_action)
                continue
            if result.status is not None:                 # github tile
                color = STATE_HEX.get(result.status.state, FEED_DIM)
                lines = [("! " + result.error, None, True)] if result.error else []
                yield (result.status.text, result.status.url, color, lines, None)
                continue
            dim = result.state in ("stale", "error")
            lines = [(it.text, it.url, dim) for it in result.items]
            if result.error:
                lines = [("! " + result.error, None, True)] + lines
            if not lines:
                lines = [("(empty)", None, True)]
            yield (title, None, FEED_FG, lines, None)

    def _register_hit(self, y, url):
        """Record a clickable region for the line centered at y -- but ONLY for
        http/https URLs, so attacker-controlled feed content can't launch
        file://, javascript:, data:, or custom-scheme URLs."""
        if url and feedmodel.is_web_url(url):
            self._hit.append((y - FEED_LINE_H // 2, y + FEED_LINE_H // 2, url))

    def _register_action(self, y, x0, x1, action):
        """Record an x-aware click zone that fires a manager action (mark-read),
        NOT a browser open. Checked before the open-URL hits, so the narrow
        right-edge zone never opens the thread."""
        self._action_hits.append((y - FEED_LINE_H // 2, y + FEED_LINE_H // 2, x0, x1, action))

    def _action_at(self, x, y):
        for y0, y1, x0, x1, action in self._action_hits:
            if y0 <= y <= y1 and x0 <= x <= x1:
                return action
        return None

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
        y = PAD + 3 * ROW_H + 4
        for title, title_url, color, lines, header_action in self._feed_tiles():
            y += FEED_TITLE_GAP
            tid = c.create_text(PAD, y, anchor="w", text=_fit(title),
                                fill=color, font=FEED_TITLE_FONT)
            self._feed_items.append(tid)
            self._register_hit(y, title_url)            # github/notifications header is clickable
            if header_action is not None:               # notifications: ✓ marks all read
                mk = c.create_text(WIDTH - PAD, y, anchor="e", text=MARKALL_GLYPH,
                                   fill=FEED_DIM, font=FEED_TITLE_FONT)
                self._feed_items.append(mk)
                self._register_action(y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, header_action)
            y += FEED_LINE_H
            for row in lines:
                if len(row) == 3:                      # existing single-line path, unchanged
                    text, url, dim = row
                    lid = c.create_text(PAD + 6, y, anchor="w", text=_fit(text),
                                        fill=(FEED_DIM if dim else FEED_FG), font=FEED_FONT)
                    self._feed_items.append(lid)
                    self._register_hit(y, url)
                    y += FEED_LINE_H
                else:                                  # len == 6: notifications 2-line item
                    line1, url, color, subtitle, age, dismiss = row
                    reserve = ACTION_ZONE_W if dismiss else 0
                    l1 = c.create_text(PAD + 6, y, anchor="w",
                                       text=self._fit_line1(line1, age, reserve),
                                       fill=color, font=FEED_FONT)
                    self._feed_items.append(l1)
                    if age:
                        age_x = WIDTH - PAD - reserve
                        aid = c.create_text(age_x, y, anchor="e", text=age,
                                            fill=FEED_DIM, font=FEED_FONT)
                        self._feed_items.append(aid)
                    if dismiss is not None:
                        xg = c.create_text(WIDTH - PAD, y, anchor="e", text=DISMISS_GLYPH,
                                           fill=FEED_DIM, font=FEED_FONT)
                        self._feed_items.append(xg)
                        self._register_action(y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, dismiss)
                    self._register_hit(y, url)
                    y += FEED_LINE_H
                    l2 = c.create_text(PAD + 12, y, anchor="w", text=_fit(subtitle),
                                       fill=FEED_DIM, font=FEED_FONT)
                    self._feed_items.append(l2)
                    self._register_hit(y, url)         # second band -> whole item opens the thread
                    y += FEED_LINE_H
        self._resize(y + PAD)

    def _resize(self, wanted_h):
        sh = self.root.winfo_screenheight()
        new_h = max(HEIGHT, min(int(wanted_h), sh - self.root.winfo_y()))
        if new_h != self.root.winfo_height():
            self.canvas.config(height=new_h)
            self.root.geometry("%dx%d" % (WIDTH, new_h))

    def _feed_has_text(self, needle):
        for item_id in self._feed_items:
            if needle in self.canvas.itemcget(item_id, "text"):
                return True
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
