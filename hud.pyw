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
import winkit.window as window
import winkit.metrics as metrics
import config

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

        self.canvas = tk.Canvas(
            root, width=WIDTH, height=HEIGHT, bg=BG,
            highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

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
        self.menu.add_checkbutton(label="Lock position", variable=self.lock_var,
                                  command=self._toggle_lock)
        self.menu.add_command(label="Close", command=root.destroy)

        self._draw()       # paint something immediately (before first tick)
        self.tick()

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
            return  # a plain click (no drag) must not rewrite config.json
        self._moved = False
        self.cfg["hud"]["x"] = self.root.winfo_x()
        self.cfg["hud"]["y"] = self.root.winfo_y()
        self._save()

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
        try:
            config.save(CFG_PATH, self.cfg)
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

    Hud(root, cfg)

    ms = _smoke_ms()
    if ms:
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
