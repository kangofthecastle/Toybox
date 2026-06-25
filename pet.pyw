"""Music-Reactive Cat -- a cute pixel-art desktop cat that idles, glows to your
system audio, hops on the beat, tracks your cursor with its eyes, and shifts its
glow by time of day.

A small (~170x170) borderless, transparent, always-on-top window sits near the
bottom-center of the primary screen. Grab the cat to drag it (the position
persists); the transparent margin stays click-through. The cat is drawn as
nearest-neighbor-zoomed pixel-art frames over a soft radial glow that fades to
the window's key color (so the glow rim is transparent -- no fringe). Lightweight:
adaptive frame rate, cached frames/glow, O(1) per-frame work."""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winkit.startup as startup
startup.guard_streams()  # MUST be the first executable statement

import math
import random
import time
import tkinter as tk

import winkit.window as window
import winkit.audio as audio
import winkit.input as wkinput
import winkit.sprites as sprites
import beat_detector
import config
import petkit.persona as persona
import petkit.eyes as eyes
import petkit.glow as glow

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets", "cat")
CFG_PATH = os.path.join(HERE, "config.json")
LOG_PATH = os.path.join(HERE, "toybox.log")

WIN = 170
SILENCE_ENVELOPE = 0.012
IDLE_AFTER_S = 2.0
CURSOR_ACTIVE_S = 1.0
KEY_RGB = (1, 1, 1)            # window.KEY_COLOR "#010101"
IDLE_FRAME_S = 0.09           # idle animation cadence

FUR_COLOR = "#fdd5b5"          # (253,213,181) -- baked sprite fur around the eyes
EYE_REACH = 60.0              # cursor distance (screen px) for full dot deflection
EYE_MAX_OFF = 2.0            # max dot deflection within the 8x8 eye base (screen px)
BLINK_MIN_S = 2.5             # random blink interval bounds
BLINK_MAX_S = 5.5
BLINK_DUR_S = 0.12            # how long an eye stays shut


def _smoke_ms():
    v = os.environ.get("TOYBOX_SMOKE")
    return int(v) if v else None


class Cat:
    def __init__(self, root, canvas, cfg):
        self.root = root
        self.canvas = canvas
        self.cfg = cfg
        pet = cfg["pet"]
        self.zoom = max(1, int(pet.get("zoom", 4)))
        self.sprite_px = 32 * self.zoom
        self.cx = WIN / 2.0
        self.base_y = WIN - 18                      # feet line

        self.idle_fps = max(1, int(pet.get("idle_fps", 8)))
        self.active_fps = max(1, int(pet.get("active_fps", 30)))
        self.det = beat_detector.BeatDetector(
            pet.get("sensitivity", 1.6), pet.get("floor", 0.02), pet.get("smoothing", 0.4))
        self.meter = audio.AudioPeakMeter()

        self.sheet = sprites.SpriteSheet(root, os.path.join(ASSETS, "Idle.png"))
        self.glow = glow.GlowCache(root, KEY_RGB, size=int(self.sprite_px * 1.25))
        self.hue = persona.glow_rgb(time.localtime().tm_hour)

        self.t0 = time.monotonic()
        self.last_loud = -1e9
        self.frame_i = 0
        self.frame_t = self.t0
        self.hop_t = None
        self.hop_dur = 0.45
        self.wiggle_amp = 0.0
        self.envelope = 0.0
        self._cursor = wkinput.cursor_pos()
        self._last_cursor = self._cursor
        self._last_cursor_move = -1e9

        # z-order: glow (back) -> cat -> eyes (front)
        self.glow_item = canvas.create_image(0, 0, anchor="center",
                                              image=self.glow.get(self.hue, 0.0))
        self.cat_item = canvas.create_image(0, 0, anchor="s",
                                            image=self.sheet.frame(0, self.zoom))

        # Pixel eyes: per eye we pre-create a black 2x2 base + a white dot (open
        # state) and a fur-colored 2x2 cell + black dash (closed/blink state).
        # Per frame we only move/recolor and toggle visibility -- never recreate.
        self.eyes = [self._make_eye(), self._make_eye()]

        # Blink: brief shut-eye on a random interval (timed off draw()'s clock).
        self.blink_until = 0.0
        self.next_blink = self.t0 + random.uniform(BLINK_MIN_S, BLINK_MAX_S)

        self._drag_dx = self._drag_dy = 0
        self._moved = False
        canvas.configure(cursor="fleur")
        for w in (root, canvas):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)

    # --- dragging (unchanged behavior) ----------------------------------
    def _on_press(self, event):
        self._moved = False
        self._drag_dx = event.x_root - self.root.winfo_x()
        self._drag_dy = event.y_root - self.root.winfo_y()

    def _on_drag(self, event):
        self._moved = True
        self.root.geometry("+%d+%d" % (event.x_root - self._drag_dx,
                                       event.y_root - self._drag_dy))

    def _on_release(self, event):
        if not self._moved:
            return
        self._moved = False
        self.cfg["pet"]["x"] = self.root.winfo_x()
        self.cfg["pet"]["y"] = self.root.winfo_y()
        try:
            config.save(CFG_PATH, self.cfg)
        except Exception:
            pass

    # --- per-frame ------------------------------------------------------
    def _hop_offset(self, now):
        if self.hop_t is None:
            return 0.0
        u = (now - self.hop_t) / self.hop_dur
        if u >= 1.0:
            self.hop_t = None
            return 0.0
        return -math.sin(math.pi * u) * 22.0

    def _on_beat(self):
        if self.hop_t is None:
            self.hop_t = time.monotonic()
        self.wiggle_amp = min(8.0, self.wiggle_amp + 6.0)

    def draw(self, now):
        env = self.envelope
        # advance the idle animation
        if now - self.frame_t >= IDLE_FRAME_S:
            self.frame_i = (self.frame_i + 1) % self.sheet.frame_count
            self.frame_t = now
            self.canvas.itemconfig(self.cat_item, image=self.sheet.frame(self.frame_i, self.zoom))

        self.wiggle_amp *= 0.85
        sway = math.sin((now - self.t0) * 2.3) * (0.6 + env * 2.0)
        sway += math.sin((now - self.t0) * 11.0) * self.wiggle_amp
        hop = self._hop_offset(now)
        cx = self.cx + sway
        feet_y = self.base_y + hop

        self.canvas.coords(self.cat_item, cx, feet_y)
        self.canvas.coords(self.glow_item, cx, feet_y - self.sprite_px / 2.0)
        self.canvas.itemconfig(self.glow_item, image=self.glow.get(self.hue, min(1.0, env * 1.6)))

        # Schedule blinks: when due, shut the eyes for BLINK_DUR_S and pick the
        # next interval.
        if now >= self.next_blink:
            self.blink_until = now + BLINK_DUR_S
            self.next_blink = now + random.uniform(BLINK_MIN_S, BLINK_MAX_S)
        self._draw_eyes(cx, feet_y, now)

    def _make_eye(self):
        """Pre-create the canvas items for one eye (open: black base + white dot;
        closed: fur cell + black dash). Hidden until placed each frame."""
        c = self.canvas
        return {
            "base": c.create_rectangle(0, 0, 0, 0, fill="#000000", outline=""),
            "dot":  c.create_rectangle(0, 0, 0, 0, fill="#ffffff", outline=""),
            "lid":  c.create_rectangle(0, 0, 0, 0, fill=FUR_COLOR, outline=""),
            "dash": c.create_rectangle(0, 0, 0, 0, fill="#000000", outline=""),
        }

    def _hide_eye(self, e):
        for item in e.values():
            self.canvas.itemconfig(item, state="hidden")

    def _draw_eyes(self, cx, feet_y, now):
        z = self.zoom
        left_px = cx - self.sprite_px / 2.0          # sprite left edge (window space)
        top_px = feet_y - self.sprite_px             # sprite top edge
        rootx, rooty = self.root.winfo_rootx(), self.root.winfo_rooty()
        gx, gy = self._cursor

        table = eyes.EYES["idle"]
        anchors = table[self.frame_i % len(table)]
        if anchors is None:                          # closed-eye frame: no eyes
            for e in self.eyes:
                self._hide_eye(e)
            return

        blinking = now < self.blink_until
        for e, (ax, ay) in zip(self.eyes, anchors):
            bx = left_px + ax * z                    # 2x2 base top-left (window space)
            by = top_px + ay * z
            base = 2 * z                             # 8x8 px black base over the eye
            if blinking:
                # Closed eye: fur-fill the 2x2, draw a 2px-wide x 1px-tall dash
                # across its vertical middle; hide the open-eye items.
                self.canvas.coords(e["lid"], bx, by, bx + base, by + base)
                dash_x0 = bx
                dash_x1 = bx + 2 * z                  # 2 sprite px wide
                dash_y0 = by + z / 2.0                # 1 sprite px tall, centered on
                dash_y1 = by + z * 1.5               # the 2px cell's vertical middle
                self.canvas.coords(e["dash"], dash_x0, dash_y0, dash_x1, dash_y1)
                self.canvas.itemconfig(e["lid"], state="normal")
                self.canvas.itemconfig(e["dash"], state="normal")
                self.canvas.itemconfig(e["base"], state="hidden")
                self.canvas.itemconfig(e["dot"], state="hidden")
                continue

            # Open eye: black 2x2 base, white 1px dot floated toward the cursor.
            self.canvas.coords(e["base"], bx, by, bx + base, by + base)
            ecx = bx + base / 2.0                     # base center (window space)
            ecy = by + base / 2.0
            ox, oy = eyes.pupil_offset(gx - (rootx + ecx), gy - (rooty + ecy),
                                       reach=EYE_REACH, max_off=EYE_MAX_OFF)
            # Float the dot CENTER toward the cursor (base_center + off), so its
            # top-left is offset back by half the dot. Snap to int px and clamp so
            # the 4x4 dot stays fully inside the 8x8 base.
            bxi, byi = int(round(bx)), int(round(by))
            dx = int(round(ecx + ox - z / 2.0))
            dy = int(round(ecy + oy - z / 2.0))
            dx = min(max(dx, bxi), bxi + base - z)
            dy = min(max(dy, byi), byi + base - z)
            self.canvas.coords(e["dot"], dx, dy, dx + z, dy + z)
            self.canvas.itemconfig(e["base"], state="normal")
            self.canvas.itemconfig(e["dot"], state="normal")
            self.canvas.itemconfig(e["lid"], state="hidden")
            self.canvas.itemconfig(e["dash"], state="hidden")

    def tick(self):
        now = time.monotonic()
        r = self.det.update(self.meter.read(), now)
        self.envelope = r["envelope"]

        cur = wkinput.cursor_pos()
        if cur != self._last_cursor:
            self._last_cursor = cur
            self._last_cursor_move = now
        self._cursor = cur

        if self.envelope > SILENCE_ENVELOPE:
            self.last_loud = now
        if r["beat"]:
            self._on_beat()

        try:
            self.draw(now)
        except tk.TclError:
            return

        active = ((now - self.last_loud) < IDLE_AFTER_S
                  or self.hop_t is not None
                  or now < self.blink_until
                  or (now - self._last_cursor_move) < CURSOR_ACTIVE_S)
        fps = self.active_fps if active else self.idle_fps
        self.root.after(max(1, int(round(1000.0 / fps))), self.tick)

    def close(self):
        try:
            self.meter.close()
        except Exception:
            pass


def _place(root, cfg):
    pet = cfg["pet"]
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    x = pet.get("x")
    y = pet.get("y")
    if x is None:
        x = int(sw / 2 - WIN / 2)
    if y is None:
        y = int(sh - WIN - 70)
    x = max(0, min(x, sw - WIN))
    y = max(0, min(y, sh - WIN))
    root.geometry("%dx%d+%d+%d" % (WIN, WIN, x, y))


def main():
    if not _smoke_ms() and not startup.acquire_single_instance("Toybox_pet"):
        return
    cfg = config.load(CFG_PATH)

    window.enable_dpi_awareness()
    root = tk.Tk()
    root.overrideredirect(True)
    root.configure(bg=window.KEY_COLOR)
    root.attributes("-topmost", True)
    root.attributes("-transparentcolor", window.KEY_COLOR)
    _place(root, cfg)

    canvas = tk.Canvas(root, width=WIN, height=WIN, bg=window.KEY_COLOR,
                       highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)

    root.update()
    window.apply_overlay_styles(root, clickthrough=False, no_activate=True)

    cat = Cat(root, canvas, cfg)
    cat.tick()
    startup.watch_for_quit("Toybox_pet", root.after, root.destroy)

    ms = _smoke_ms()
    if ms:
        root.after(ms, root.destroy)

    try:
        root.mainloop()
    finally:
        cat.close()


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
