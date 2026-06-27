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
import petkit.reactions as reactions
import petkit.greeter as greeter
import petkit.bubble as bubble
import petkit.pomodoro as pomodoro
import petkit.reminders as reminders
import petkit.nudges as nudges
import petkit.pins as pins
import petkit.settings as settings
import winkit.dnd as dnd

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
NAP_FRAME_S = 0.5             # box-catnap animation cadence (~2 fps)
NAP_FPS = 2                   # throttled tick rate while napping (a CPU win)

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

        # Phase 2 "alive": petting -> purr, box catnap, welcome-back greeter,
        # all surfaced through a reusable speech bubble.
        self.nap_sheet = sprites.SpriteSheet(root, os.path.join(ASSETS, "Box3.png"))
        self.petting = reactions.PettingDetector()
        self.nap = reactions.NapState(
            sleep_after_ms=int(pet.get("nap_after_s", 120)) * 1000)
        self.greeter = greeter.Greeter(
            away_after_ms=int(pet.get("away_after_s", 300)) * 1000)
        # Anchor speech bubbles to the cat's head, not the (much taller) window
        # top: the head/ears sit ~6 sprite rows below the sprite cell's top edge
        # (the eyes are at row ~12), so the bubble tucks just over the cat.
        head_y = int(self.base_y - self.sprite_px + 6 * self.zoom)
        self.bubble = bubble.Bubble(root, head_offset=head_y)
        self.nap_state = "awake"
        self.nap_frame_i = 0
        self.nap_frame_t = self.t0
        self._petting_was = False     # squint state, refreshed each tick
        self._purred = False          # one-shot edge for the "purr~" bubble
        self._next_zzz = 0.0

        # Phase 3 "assistant": focus/Pomodoro timer + natural-language reminders.
        self.pomodoro = pomodoro.Pomodoro(focus_s=int(pet.get("focus_min", 25)) * 60,
                                          break_s=int(pet.get("break_min", 5)) * 60)
        self.reminders = reminders.Reminders(os.path.join(HERE, "reminders.json"))
        self._next_reminder_check = 0.0   # low-rate reminder cursor (monotonic)

        # Phase 3 "assistant" (cont.): activity-gated break nudges.
        self.nudger = nudges.NudgeScheduler(interval_s=int(pet.get("nudge_min", 50)) * 60)

        # Phase 4 "power-tools": Pin (right-click the cat to pin the window under
        # it; the cat stays on top) and Catch & Carry (drop files on the cat;
        # click to release as CF_HDROP). Event-driven (menu / WM_DROPFILES).
        self.hwnd = window._hwnd_of(root)
        self.pinset = pins.PinSet(window.set_topmost)
        self._held = []                   # files the cat is currently carrying
        self.drop_target = None
        self._tick_after = None
        self._next_topmost = 0.0          # low-rate cat top-most re-assert cursor
        self.settings = None              # lazily-built Settings window (singleton)
        self._apply_pin_enabled()         # release pins if the feature is off
        self._apply_carry_enabled()       # install the drop target iff enabled

        self._drag_dx = self._drag_dy = 0
        self._moved = False
        canvas.configure(cursor="fleur")
        for w in (root, canvas):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)
            w.bind("<Motion>", self._on_motion)
            w.bind("<ButtonPress-3>", self._on_right_click)

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
            # A plain click (no drag): if the cat is carrying files, release them
            # onto the clipboard. Otherwise nothing to persist.
            if self._held:
                self._release_held()
            return
        self._moved = False
        self.cfg["pet"]["x"] = self.root.winfo_x()
        self.cfg["pet"]["y"] = self.root.winfo_y()
        try:
            config.save(CFG_PATH, self.cfg)
        except Exception:
            pass

    # --- petting (cursor stroking the cat) ------------------------------
    def _on_motion(self, event):
        now = time.monotonic()
        inside = (abs(event.x - self.cx) < self.sprite_px / 2.0
                  and (self.base_y - self.sprite_px) < event.y < self.base_y)
        # Feed the detector here (events only fire on motion); the squint itself
        # is refreshed every tick from petting.active() so it releases when the
        # stroking lapses even if the cursor then holds still (no more <Motion>).
        if self.petting.update(event.x_root, inside, now):
            if not self._purred and self.cfg["pet"].get("petting", True):
                self.bubble.say("purr~", secs=2)
                self._purred = True
        else:
            self._purred = False

    # --- Pin + Catch & Carry (Phase 4) ----------------------------------
    def _apply_pin_enabled(self):
        """Pinning is driven from the right-click menu (the window under the cat),
        so there is no poller to install -- disabling the feature just releases
        whatever the cat is currently holding up."""
        if not self.cfg["pet"].get("pin", True):
            self.pinset.unpin_all()

    def _apply_carry_enabled(self):
        """Install/tear down the WM_DROPFILES target to match the config flag."""
        on = self.cfg["pet"].get("carry", True)
        if on and self.drop_target is None:
            self.drop_target = dnd.FileDropTarget(self.hwnd, self._on_files_dropped)
        elif not on and self.drop_target is not None:
            self.drop_target.close()
            self.drop_target = None
            self._held = []               # stop offering to drop stale files

    def _pin_under_cat(self):
        """Toggle always-on-top on the window directly beneath the cat. On pin,
        re-raise the cat so it stays above the newly-pinned window."""
        if not self.cfg["pet"].get("pin", True):
            return
        hwnd = window.window_below(self.hwnd)
        if not hwnd or hwnd == self.hwnd:
            self.bubble.say("No window here \U0001F431", secs=2)
            return
        on = self.pinset.toggle(hwnd)
        if on:
            window.set_topmost(self.hwnd, True)    # keep the cat above the pin
        self.bubble.say("\U0001F4CC pinned" if on else "unpinned", secs=2)

    def _unpin_all(self):
        self.pinset.unpin_all()
        self.bubble.say("Unpinned all \U0001F431", secs=2)

    def _on_files_dropped(self, paths):
        if not self.cfg["pet"].get("carry", True):
            return
        self._held = list(paths)
        n = len(self._held)
        self.bubble.say("Caught %d file%s \U0001F43E (click to drop)"
                        % (n, "" if n == 1 else "s"), secs=4)

    def _release_held(self):
        if self._held and dnd.set_clipboard_files(self._held):
            self.bubble.say("Ready to paste (Ctrl+V) \U0001F431", secs=4)
        self._held = []

    # --- right-click menu -----------------------------------------------
    def _save_cfg(self):
        try:
            config.save(CFG_PATH, self.cfg)
        except Exception:
            pass

    def _set_cfg_flag(self, key, value):
        """Set a boolean pet flag, run its live side effect, keep any menu var in
        sync, and persist. Used by both the menu and the Settings window."""
        value = bool(value)
        self.cfg["pet"][key] = value
        if getattr(self, "_menu_vars", None) and key in self._menu_vars:
            self._menu_vars[key].set(1 if value else 0)
        if key == "catnap":
            self.nap.reset()
            self.nap_state = "awake"
        elif key == "pin":
            self._apply_pin_enabled()
        elif key == "carry":
            self._apply_carry_enabled()
        self._save_cfg()

    def _toggle_cfg(self, key):
        self._set_cfg_flag(key, not self.cfg["pet"].get(key, True))

    def _set_focus_minutes(self, focus_min, break_min):
        """Apply focus/break durations from the Settings window: persist and push
        them into the live Pomodoro (taking effect on the next Start)."""
        self.cfg["pet"]["focus_min"] = int(focus_min)
        self.cfg["pet"]["break_min"] = int(break_min)
        self.pomodoro.focus_s = int(focus_min) * 60
        self.pomodoro.break_s = int(break_min) * 60
        self._save_cfg()

    def _build_menu(self, now):
        """Build (but do not post) the slim right-click menu. Returned so it is
        unit-testable; _on_right_click posts it. Toggles live in the Settings
        window now -- this menu is actions only."""
        pet = self.cfg["pet"]
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="\U0001F431 Cat", state="disabled")
        m.add_separator()
        st = self.pomodoro.state
        if st == "idle":
            m.add_command(label="▶ Start Focus (%dm)" % int(pet.get("focus_min", 25)),
                          command=self._start_focus)
        else:
            mm, ss = divmod(int(max(0, self.pomodoro.remaining(now))), 60)
            if st == "paused":
                m.add_command(label="▶ Resume (%d:%02d)" % (mm, ss), command=self._resume_focus)
            else:
                m.add_command(label="⏸ Pause (%d:%02d)" % (mm, ss), command=self._pause_focus)
            m.add_command(label="■ Stop focus", command=self._stop_focus)
        m.add_command(label="⏰ Reminders…",
                      command=lambda: self._open_settings("Reminders"))
        if pet.get("pin", True):
            target = window.window_below(self.hwnd)
            pinned = bool(target) and self.pinset.is_pinned(target)
            m.add_command(label="\U0001F4CC Unpin this window" if pinned else "\U0001F4CC Pin this window",
                          command=self._pin_under_cat)
        if self._held:
            m.add_command(label="⤵ Drop %d file(s) → clipboard" % len(self._held),
                          command=self._release_held)
            m.add_command(label="Let go", command=lambda: setattr(self, "_held", []))
        if self.pinset.pinned():
            m.add_command(label="\U0001F4CC Unpin all (%d)" % len(self.pinset.pinned()),
                          command=self._unpin_all)
        m.add_separator()
        m.add_command(label="⚙ Settings…", command=lambda: self._open_settings())
        m.add_command(label="Hide cat", command=self.root.destroy)
        return m

    def _open_settings(self, tab=None):
        if self.settings is None:
            self.settings = settings.SettingsWindow(self)
        self.settings.open(tab)

    def _on_right_click(self, event):
        m = self._build_menu(time.monotonic())
        # The cat window is WS_EX_NOACTIVATE, so it never becomes foreground and a
        # native popup it owns won't dismiss on an outside click (KB135788). Briefly
        # bring it foreground around the (modal, on Windows) popup.
        restore = window.foreground_for_popup(self.hwnd)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()
            restore()

    # --- focus timer + reminders (Phase 3) ------------------------------
    def _start_focus(self):
        self.pomodoro.start(time.monotonic())
        self.bubble.say("Focus on \U0001F43E", secs=2)

    def _pause_focus(self):
        self.pomodoro.pause(time.monotonic())
        self.bubble.say("Paused", secs=2)

    def _resume_focus(self):
        self.pomodoro.resume(time.monotonic())
        self.bubble.say("Resumed \U0001F43E", secs=2)

    def _stop_focus(self):
        self.pomodoro.cancel()

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
        napping = self.nap_state == "napping"
        if napping:
            # Box catnap: slow-cycle the sleeping-in-a-box sheet (~2 fps) and let
            # the sprite's own painted face show -- hide the tracked pixel eyes.
            if now - self.nap_frame_t >= NAP_FRAME_S:
                self.nap_frame_i = (self.nap_frame_i + 1) % self.nap_sheet.frame_count
                self.nap_frame_t = now
            self.canvas.itemconfig(self.cat_item,
                                   image=self.nap_sheet.frame(self.nap_frame_i, self.zoom))
        else:
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

        if napping:                       # box sprite has its own face -> no eyes
            for e in self.eyes:
                self._hide_eye(e)
            return

        # Schedule blinks: when due, shut the eyes for BLINK_DUR_S and pick the
        # next interval. While being petted, hold the eyes shut for a contented
        # squint (reuses the closed-eye render path).
        if now >= self.next_blink:
            self.blink_until = now + BLINK_DUR_S
            self.next_blink = now + random.uniform(BLINK_MIN_S, BLINK_MAX_S)
        if self._petting_was:
            self.blink_until = max(self.blink_until, now + IDLE_FRAME_S)
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
            # Coarsen the gaze: snap the dot to a 2px grid (~3 positions/axis) so it
            # reads pixel-art-steppy rather than continuously sliding.
            step = max(1, z // 2)
            dx = bxi + int(round((dx - bxi) / step)) * step
            dy = byi + int(round((dy - byi) / step)) * step
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

        # Idle-driven nap cycle + welcome-back greeting (one O(1) Win32 probe).
        pet = self.cfg["pet"]
        # Refresh the contented-squint from the live petting state so it relaxes
        # when stroking lapses (reversals age out) even with the cursor at rest.
        self._petting_was = pet.get("petting", True) and self.petting.active(now)
        idle = wkinput.idle_ms()
        prev_nap = self.nap_state
        if pet.get("catnap", True):
            self.nap_state = self.nap.update(idle, now)
        else:
            self.nap_state = "awake"
        if prev_nap == "napping" and self.nap_state == "startled":
            self._on_beat()                       # jolt awake with a hop
        if pet.get("greeter", True):
            g = self.greeter.update(idle)
            if g:
                self.bubble.say(g, secs=4, chime=True)

        napping = self.nap_state == "napping"
        if napping and now >= self._next_zzz:
            self.bubble.say("Zzz", secs=2)
            self._next_zzz = now + 6.0

        # Focus/Pomodoro timer (runs regardless of nap; injected monotonic clock).
        ev = self.pomodoro.update(now)
        if ev == "focus_done":
            self.bubble.say("Break time! \U0001F43E", secs=4, chime=True)
        elif ev == "break_done":
            self.bubble.say("Back to it? \U0001F431", secs=4, chime=True)

        # Reminders, low-rate (<=1/5s); fired reminders use wall-clock epoch.
        if pet.get("reminders", True) and now >= self._next_reminder_check:
            self._next_reminder_check = now + 5.0
            for text in self.reminders.due(time.time()):
                self.bubble.say("⏰ " + text, secs=5, chime=True)

        # Break nudges: reuse the `idle` already probed above for the nap cycle.
        if pet.get("nudges", True) and self.nudger.update(idle, now):
            self.bubble.say("Stretch break? \U0001F431", secs=4, chime=True)

        # Keep the cat above any window it has pinned: a pinned window the user
        # clicks would otherwise rise over it. Gated to when pins exist and
        # rate-limited to ~1/s; SWP_NOACTIVATE -> no focus theft, no flicker.
        if self.pinset.pinned() and now >= self._next_topmost:
            self._next_topmost = now + 1.0
            window.set_topmost(self.hwnd, True)

        try:
            self.draw(now)
        except tk.TclError:
            return

        if napping:
            fps = NAP_FPS                         # throttle the tick -- a CPU win
        else:
            # A running focus timer does NOT pin active fps: pomodoro.update()
            # still runs every idle tick (~8 fps), so the end-of-phase chime
            # lands within ~125 ms -- not worth 30 fps for a 25-min stretch.
            active = ((now - self.last_loud) < IDLE_AFTER_S
                      or self.hop_t is not None
                      or now < self.blink_until
                      or (now - self._last_cursor_move) < CURSOR_ACTIVE_S)
            fps = self.active_fps if active else self.idle_fps
        self._tick_after = self.root.after(max(1, int(round(1000.0 / fps))), self.tick)

    def close(self):
        # Cancel the pending tick so no orphaned after-callback fires post-destroy.
        if self._tick_after is not None:
            try:
                self.root.after_cancel(self._tick_after)
            except Exception:
                pass
            self._tick_after = None
        try:
            self.meter.close()
        except Exception:
            pass
        # Phase 4: tear down native power-tool resources so quitting is clean.
        try:
            if getattr(self, "pinset", None):
                self.pinset.unpin_all()
        except Exception:
            pass
        try:
            if getattr(self, "drop_target", None):
                self.drop_target.close()
        except Exception:
            pass
        try:
            if getattr(self, "settings", None):
                self.settings.close()
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
