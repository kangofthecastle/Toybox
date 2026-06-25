"""Music-Reactive Pet -- a cute desktop blob that breathes when quiet and
dances to your system audio.

A small (~170x170) borderless, transparent, always-on-top window sits near the
bottom-center of the primary screen. Grab the blob to drag it anywhere (the
position persists); the transparent margin around it stays click-through, so the
pet never blocks the windows beneath. A procedurally drawn blob creature breathes
gently when silent and squashes / hops / warms in color in response to the system
output peak (WASAPI) run through a beat detector.

Lightweight: adaptive frame rate -- ~8 fps idle breathing, ~30 fps active
dancing -- and canvas items are reused (coords/itemconfig) rather than redrawn
from scratch each tick. See docs/superpowers/specs/2026-06-24-native-gotchas.md.
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winkit.startup as startup
startup.guard_streams()  # MUST be the first executable statement (pythonw-at-login safety)

import math
import random
import time
import tkinter as tk

import winkit.window as window
import winkit.audio as audio
import beat_detector
import config

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
LOG_PATH = os.path.join(HERE, "toybox.log")

WIN = 170                 # window edge length (px)
CX = WIN / 2.0            # creature horizontal center
GROUND_Y = WIN - 28       # y of the bottom of the feet / top of the shadow
SILENCE_ENVELOPE = 0.012  # envelope below this counts as "quiet"
IDLE_AFTER_S = 2.0        # seconds of quiet before dropping to idle fps


def _smoke_ms():
    v = os.environ.get("TOYBOX_SMOKE")
    return int(v) if v else None


def _lerp(a, b, t):
    return a + (b - a) * t


def _mix(c0, c1, t):
    """Linearly interpolate two (r, g, b) tuples -> '#rrggbb'. t clamped 0..1."""
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    r = int(round(_lerp(c0[0], c1[0], t)))
    g = int(round(_lerp(c0[1], c1[1], t)))
    b = int(round(_lerp(c0[2], c1[2], t)))
    return "#%02x%02x%02x" % (r, g, b)


# Calm (quiet) -> excited (loud) palettes for the body fill and a lighter belly.
CALM_BODY = (74, 196, 196)     # teal
WARM_BODY = (255, 120, 168)    # warm pink
CALM_BELLY = (158, 232, 232)
WARM_BELLY = (255, 196, 214)
OUTLINE = "#1f3a3a"


class Pet:
    def __init__(self, root, canvas, cfg):
        self.root = root
        self.canvas = canvas
        self.cfg = cfg
        pet = cfg["pet"]

        self.idle_fps = max(1, int(pet.get("idle_fps", 8)))
        self.active_fps = max(1, int(pet.get("active_fps", 30)))
        self.det = beat_detector.BeatDetector(
            pet.get("sensitivity", 1.6), pet.get("floor", 0.02), pet.get("smoothing", 0.4))
        self.meter = audio.AudioPeakMeter()

        # Animation state.
        self.t0 = time.monotonic()
        self.last_loud = -1e9        # monotonic time we last saw non-quiet audio
        self.hop_t = None            # monotonic time a hop started (None = grounded)
        self.hop_dur = 0.45          # seconds for a hop arc
        self.wiggle_phase = 0.0      # extra horizontal sway accumulator
        self.wiggle_amp = 0.0        # current wiggle amplitude (decays)
        self.blink_until = 0.0       # monotonic time blink ends
        self.next_idle_blink = self.t0 + random.uniform(2.0, 5.0)
        self.beat_kind = 0           # cycles hop/wiggle/blink for variety
        self.envelope = 0.0          # smoothed, for color/size

        # Pre-create canvas items once; we only move/recolor them per frame.
        self.shadow = canvas.create_oval(0, 0, 0, 0, fill="#0c2424", outline="")
        self.body = canvas.create_polygon(
            0, 0, 0, 0, fill=OUTLINE, outline=OUTLINE, smooth=True)
        self.belly = canvas.create_oval(0, 0, 0, 0, fill="#9ee8e8", outline="")
        # Eyes: white, pupil, highlight; eyelids are short lines shown when blinking.
        self.eye_l = canvas.create_oval(0, 0, 0, 0, fill="white", outline="")
        self.eye_r = canvas.create_oval(0, 0, 0, 0, fill="white", outline="")
        self.pup_l = canvas.create_oval(0, 0, 0, 0, fill="#16242b", outline="")
        self.pup_r = canvas.create_oval(0, 0, 0, 0, fill="#16242b", outline="")
        self.hi_l = canvas.create_oval(0, 0, 0, 0, fill="white", outline="")
        self.hi_r = canvas.create_oval(0, 0, 0, 0, fill="white", outline="")
        self.lid_l = canvas.create_line(0, 0, 0, 0, fill=OUTLINE, width=3,
                                        capstyle=tk.ROUND, state="hidden")
        self.lid_r = canvas.create_line(0, 0, 0, 0, fill=OUTLINE, width=3,
                                        capstyle=tk.ROUND, state="hidden")

        # Dragging: grab the blob to move the pet. The window is not fully
        # click-through (the transparent margin still is, via the color key),
        # so clicks land only on the creature's pixels. Position persists.
        self._drag_dx = 0
        self._drag_dy = 0
        self._moved = False
        canvas.configure(cursor="fleur")
        for w in (root, canvas):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)

    # --- dragging --------------------------------------------------------
    def _on_press(self, event):
        self._moved = False
        self._drag_dx = event.x_root - self.root.winfo_x()
        self._drag_dy = event.y_root - self.root.winfo_y()

    def _on_drag(self, event):
        self._moved = True
        x = event.x_root - self._drag_dx
        y = event.y_root - self._drag_dy
        self.root.geometry("+%d+%d" % (x, y))

    def _on_release(self, event):
        if not self._moved:
            return  # a plain click (no drag) must not rewrite config.json
        self._moved = False
        self.cfg["pet"]["x"] = self.root.winfo_x()
        self.cfg["pet"]["y"] = self.root.winfo_y()
        try:
            config.save(CFG_PATH, self.cfg)
        except Exception:
            pass

    # --- reactions -------------------------------------------------------
    def _start_hop(self, now):
        if self.hop_t is None:
            self.hop_t = now

    def _start_wiggle(self):
        self.wiggle_amp = min(10.0, self.wiggle_amp + 7.0)

    def _start_blink(self, now, dur=0.13):
        self.blink_until = now + dur

    def _on_beat(self, now, strength):
        # Vary the reaction so the pet feels alive, but bias toward hops.
        self.beat_kind = (self.beat_kind + 1) % 4
        if self.beat_kind == 0 or self.beat_kind == 2:
            self._start_hop(now)
        elif self.beat_kind == 1:
            self._start_wiggle()
        else:
            self._start_blink(now)
        # A strong beat always adds a little hop energy on top.
        if strength > 0.18:
            self._start_hop(now)

    # --- per-frame geometry ---------------------------------------------
    def _hop_offset(self, now):
        if self.hop_t is None:
            return 0.0
        u = (now - self.hop_t) / self.hop_dur
        if u >= 1.0:
            self.hop_t = None
            return 0.0
        # Parabolic arc: 0 -> peak -> 0; eased.
        return -math.sin(math.pi * u) * 26.0

    def draw(self, now):
        env = self.envelope
        # Breathing: slow sine squash; a touch faster/deeper when energetic.
        breathe_speed = 1.1 + env * 2.2
        breath = math.sin((now - self.t0) * breathe_speed)

        # Body size. Width and height counter-squash to conserve "volume".
        base_h = 56.0 + env * 30.0
        squash = 0.05 * breath + env * 0.10
        half_h = base_h * (1.0 - squash) / 2.0
        half_w = (52.0 + env * 14.0) * (1.0 + squash * 0.8) / 2.0

        hop = self._hop_offset(now)

        # Horizontal sway: gentle idle drift + decaying beat wiggle.
        self.wiggle_amp *= 0.85
        sway = math.sin((now - self.t0) * 2.3) * (1.2 + env * 3.0)
        sway += math.sin((now - self.t0) * 11.0) * self.wiggle_amp
        cx = CX + sway

        # Center of the body: feet rest near GROUND_Y, hop lifts everything.
        feet_y = GROUND_Y + hop
        cy = feet_y - half_h

        self._draw_shadow(cx, hop, half_w)
        self._draw_body(cx, cy, half_w, half_h, env)
        self._draw_face(cx, cy, half_w, half_h, env, now)

    def _draw_shadow(self, cx, hop, half_w):
        # Shadow shrinks and fades as the pet rises.
        lift = min(1.0, -hop / 26.0) if hop < 0 else 0.0
        sw = half_w * (1.05 - lift * 0.45)
        sh = 7.0 * (1.0 - lift * 0.5)
        self.canvas.coords(self.shadow, cx - sw, GROUND_Y - sh,
                           cx + sw, GROUND_Y + sh)
        shade = int(round(_lerp(36, 22, lift)))
        self.canvas.itemconfig(self.shadow, fill="#%02x%02x%02x" % (shade // 3, shade, shade))

    def _blob_points(self, cx, cy, hw, hh):
        # An 8-point rounded blob (smoothed polygon) -- slightly egg-shaped,
        # a bit wider at the bottom so it reads as a cute sitting creature.
        bot = hh * 1.04
        return [
            cx,          cy - hh,        # top
            cx + hw * 0.78, cy - hh * 0.62,
            cx + hw,     cy + hh * 0.05,  # right
            cx + hw * 0.86, cy + bot * 0.7,
            cx,          cy + bot,        # bottom
            cx - hw * 0.86, cy + bot * 0.7,
            cx - hw,     cy + hh * 0.05,  # left
            cx - hw * 0.78, cy - hh * 0.62,
        ]

    def _draw_body(self, cx, cy, hw, hh, env):
        self.canvas.coords(self.body, *self._blob_points(cx, cy, hw, hh))
        body_col = _mix(CALM_BODY, WARM_BODY, env * 1.4)
        self.canvas.itemconfig(self.body, fill=body_col, outline=OUTLINE, width=2)
        # Belly: a soft lighter ellipse low on the body.
        bw, bh = hw * 0.62, hh * 0.66
        by = cy + hh * 0.34
        self.canvas.coords(self.belly, cx - bw, by - bh, cx + bw, by + bh)
        self.canvas.itemconfig(self.belly, fill=_mix(CALM_BELLY, WARM_BELLY, env * 1.4))

    def _draw_face(self, cx, cy, hw, hh, env, now):
        # Eyes sit in the upper third; look slightly toward the sway direction.
        eye_dx = hw * 0.42
        eye_y = cy - hh * 0.18
        er = 7.5 + env * 2.0          # eye (white) radius
        look = max(-1.6, min(1.6, (cx - CX) * 0.10))

        # Idle blink scheduling (only when not already blinking).
        if now >= self.next_idle_blink and now >= self.blink_until:
            self._start_blink(now)
            self.next_idle_blink = now + random.uniform(2.2, 5.5)

        blinking = now < self.blink_until
        for eye, pup, hi, lid, sign in (
                (self.eye_l, self.pup_l, self.hi_l, self.lid_l, -1),
                (self.eye_r, self.pup_r, self.hi_r, self.lid_r, +1)):
            ex = cx + sign * eye_dx
            if blinking:
                self.canvas.itemconfig(eye, state="hidden")
                self.canvas.itemconfig(pup, state="hidden")
                self.canvas.itemconfig(hi, state="hidden")
                self.canvas.itemconfig(lid, state="normal")
                self.canvas.coords(lid, ex - er, eye_y, ex + er, eye_y)
            else:
                self.canvas.itemconfig(lid, state="hidden")
                self.canvas.itemconfig(eye, state="normal")
                self.canvas.itemconfig(pup, state="normal")
                self.canvas.itemconfig(hi, state="normal")
                self.canvas.coords(eye, ex - er, eye_y - er, ex + er, eye_y + er)
                pr = er * 0.55
                px, py = ex + look, eye_y + er * 0.12
                self.canvas.coords(pup, px - pr, py - pr, px + pr, py + pr)
                hr = er * 0.22
                hx, hy = ex + look - pr * 0.5, eye_y - er * 0.35
                self.canvas.coords(hi, hx - hr, hy - hr, hx + hr, hy + hr)

    # --- main tick -------------------------------------------------------
    def tick(self):
        now = time.monotonic()
        peak = self.meter.read()
        r = self.det.update(peak, now)
        self.envelope = r["envelope"]

        if self.envelope > SILENCE_ENVELOPE:
            self.last_loud = now
        if r["beat"]:
            self._on_beat(now, self.envelope)

        try:
            self.draw(now)
        except tk.TclError:
            return  # window is being torn down

        # Adaptive frame rate: active while audio is present, idle when quiet.
        active = (now - self.last_loud) < IDLE_AFTER_S or self.hop_t is not None
        fps = self.active_fps if active else self.idle_fps
        delay = max(1, int(round(1000.0 / fps)))
        self.root.after(delay, self.tick)

    def close(self):
        try:
            self.meter.close()
        except Exception:
            pass


def _place(root, cfg):
    pet = cfg["pet"]
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = pet.get("x")
    y = pet.get("y")
    if x is None:
        x = int(sw / 2 - WIN / 2)            # horizontal center
    if y is None:
        y = int(sh - WIN - 70)               # near the bottom, above the taskbar
    # Keep it on-screen even if a stale config points off the visible area.
    x = max(0, min(x, sw - WIN))
    y = max(0, min(y, sh - WIN))
    root.geometry("%dx%d+%d+%d" % (WIN, WIN, x, y))


def main():
    cfg = config.load(CFG_PATH)

    window.enable_dpi_awareness()            # BEFORE Tk()
    root = tk.Tk()
    root.overrideredirect(True)
    root.configure(bg=window.KEY_COLOR)
    root.attributes("-topmost", True)
    root.attributes("-transparentcolor", window.KEY_COLOR)
    _place(root, cfg)

    canvas = tk.Canvas(root, width=WIN, height=WIN, bg=window.KEY_COLOR,
                       highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)

    root.update()                            # realize the HWND before ex-styles
    # Not fully click-through: the color key already passes clicks through the
    # transparent margin, while the blob's pixels stay grabbable for dragging.
    # no_activate keeps the pet from stealing focus when you nudge it.
    window.apply_overlay_styles(root, clickthrough=False, no_activate=True)

    pet = Pet(root, canvas, cfg)
    pet.tick()

    ms = _smoke_ms()
    if ms:
        root.after(ms, root.destroy)         # auto-close in smoke mode

    try:
        root.mainloop()
    finally:
        pet.close()                          # release WASAPI meter after the loop


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
