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

        # z-order: glow (back) -> cat -> pupils (front)
        self.glow_item = canvas.create_image(0, 0, anchor="center",
                                              image=self.glow.get(self.hue, 0.0))
        self.cat_item = canvas.create_image(0, 0, anchor="s",
                                            image=self.sheet.frame(0, self.zoom))
        pr = max(2, int(round(1.3 * self.zoom)))
        self.pr = pr
        self.pup_l = canvas.create_oval(0, 0, 0, 0, fill="#241a1a", outline="")
        self.pup_r = canvas.create_oval(0, 0, 0, 0, fill="#241a1a", outline="")

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
        self._draw_pupils(cx, feet_y)

    def _draw_pupils(self, cx, feet_y):
        z = self.zoom
        left_px = cx - self.sprite_px / 2.0          # sprite left edge (window space)
        top_px = feet_y - self.sprite_px             # sprite top edge
        rootx, rooty = self.root.winfo_rootx(), self.root.winfo_rooty()
        gx, gy = self._cursor
        anchors = eyes.EYES["idle"][self.frame_i % len(eyes.EYES["idle"])]
        for item, (ax, ay) in zip((self.pup_l, self.pup_r), anchors):
            ex = left_px + ax * z
            ey = top_px + ay * z
            ox, oy = eyes.pupil_offset(gx - (rootx + ex), gy - (rooty + ey))
            px = ex + ox * z
            py = ey + oy * z
            self.canvas.coords(item, px - self.pr, py - self.pr, px + self.pr, py + self.pr)

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
