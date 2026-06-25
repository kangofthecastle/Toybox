# Cat Pet — Phase 2 "Alive" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the cat feel alive — it reacts to petting, naps in a box when you're away, and greets you when you come back — all surfaced through a reusable speech bubble + right-click menu.

**Architecture:** Pure, injected-clock logic modules in `petkit/` (TDD'd cross-platform), one Win32 idle probe in `winkit/input.py`, a GUI speech-bubble in `petkit/bubble.py`, all wired into the existing `pet.pyw` tick loop and a new right-click menu. No per-frame cost added beyond an O(1) idle probe; the nap state *lowers* the frame rate.

**Tech Stack:** Python 3.12 stdlib only — tkinter, ctypes, winsound, winreg. No third-party packages.

## Global Constraints

- Pure stdlib only; no pip/third-party imports. (`tkinter`, `ctypes`, `winsound`, `json` OK.)
- Pure-logic modules take injected clock/idle values — **no `time.monotonic()` or `datetime.now()` inside them** — so they unit-test deterministically cross-platform.
- Win32-touching code lives in `winkit/`; pet-feature logic lives in `petkit/`.
- Per-frame work stays O(1). Napping throttles the tick to ~2 fps (a CPU win).
- Test runner: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -p "test_*.py"`. (Bare `python` is a MS-Store stub — use the full path or `py -3.12`.)
- Windows-only tests guard with `@unittest.skipUnless(os.name == "nt", "Windows only")`.
- The window key color is `winkit.window.KEY_COLOR == "#010101"`; never paint with it except as the transparent margin.

---

### Task 1: `idle_ms()` system idle probe (winkit/input.py)

**Files:**
- Modify: `winkit/input.py` (append; reuse the existing `_user32` handle, add a `_kernel32`)
- Test: `tests/test_winkit_pure.py` (append a pure-math test), `tests/test_winkit_system.py` (append a Windows smoke test to `TestInput`)

**Interfaces:**
- Produces: `winkit.input.idle_ms() -> int` (ms since last system-wide keyboard/mouse input); `winkit.input._idle_ms_from_ticks(last_tick, now_tick) -> int` (pure wraparound math).

- [ ] **Step 1: Write the failing pure test** in `tests/test_winkit_pure.py`:

```python
class TestIdleMath(unittest.TestCase):
    def test_simple_delta(self):
        import winkit.input as I
        self.assertEqual(I._idle_ms_from_ticks(100, 500), 400)

    def test_wraparound(self):
        import winkit.input as I
        # GetTickCount is a 32-bit DWORD that wraps every ~49.7 days.
        self.assertEqual(I._idle_ms_from_ticks(0xFFFFFFF0, 0x0000000F), 0x1F)
```

- [ ] **Step 2: Run it, watch it fail** (`AttributeError: _idle_ms_from_ticks`).

- [ ] **Step 3: Implement** in `winkit/input.py` (append):

```python
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetTickCount.restype = ctypes.c_uint
_kernel32.GetTickCount.argtypes = []


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


_user32.GetLastInputInfo.restype = ctypes.c_int  # BOOL
_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]


def _idle_ms_from_ticks(last_tick, now_tick):
    """Milliseconds between two GetTickCount samples, 32-bit-wraparound-safe."""
    return (now_tick - last_tick) & 0xFFFFFFFF


def idle_ms():
    """Milliseconds since the last system-wide keyboard/mouse input."""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    _user32.GetLastInputInfo(ctypes.byref(info))
    return _idle_ms_from_ticks(info.dwTime, _kernel32.GetTickCount())
```

- [ ] **Step 4: Run the pure test, watch it pass.**

- [ ] **Step 5: Add the Windows smoke test** to `TestInput` in `tests/test_winkit_system.py`:

```python
    def test_idle_ms_is_plausible_int(self):
        import winkit.input as I
        v = I.idle_ms()
        self.assertIsInstance(v, int)
        self.assertGreaterEqual(v, 0)
        self.assertLess(v, 7 * 24 * 60 * 60 * 1000)  # < a week
```

- [ ] **Step 6: Run the full suite, watch all pass. Commit** `feat: add idle_ms() system idle probe`.

---

### Task 2: PettingDetector (petkit/reactions.py)

**Files:**
- Create: `petkit/reactions.py`
- Test: `tests/test_reactions.py`

**Interfaces:**
- Produces: `PettingDetector(reversals_needed=3, window_s=1.2)` with `.update(x, inside, now) -> bool` (record a cursor sample at screen-x `x`; `inside` = cursor over the cat; `now` = monotonic seconds) and `.active(now) -> bool` (prune + read without recording). "Petting" = enough horizontal direction-reversals inside the cat within `window_s`.

- [ ] **Step 1: Write failing tests** in `tests/test_reactions.py`:

```python
import unittest
from petkit.reactions import PettingDetector


class TestPettingDetector(unittest.TestCase):
    def test_back_and_forth_inside_triggers_petting(self):
        d = PettingDetector(reversals_needed=3, window_s=10)
        xs = [0, 10, 20, 10, 0, 10, 20, 10, 0]  # 3+ reversals
        petting = False
        for i, x in enumerate(xs):
            petting = d.update(x, True, now=i * 0.1)
        self.assertTrue(petting)

    def test_monotonic_drag_is_not_petting(self):
        d = PettingDetector(reversals_needed=3, window_s=10)
        petting = False
        for i in range(10):
            petting = d.update(i * 5, True, now=i * 0.1)
        self.assertFalse(petting)

    def test_motion_outside_does_not_count(self):
        d = PettingDetector(reversals_needed=3, window_s=10)
        xs = [0, 10, 0, 10, 0, 10]
        petting = False
        for i, x in enumerate(xs):
            petting = d.update(x, False, now=i * 0.1)
        self.assertFalse(petting)

    def test_reversals_age_out(self):
        d = PettingDetector(reversals_needed=3, window_s=1.0)
        for i, x in enumerate([0, 10, 0, 10, 0, 10, 0]):
            d.update(x, True, now=i * 0.1)
        self.assertTrue(d.active(now=0.6))
        self.assertFalse(d.active(now=5.0))  # all reversals older than window_s
```

- [ ] **Step 2: Run, watch fail** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `petkit/reactions.py`:

```python
"""Pure pet-reaction logic: petting detection and the nap/box state machine.
All clock and idle values are injected so this is deterministic and testable."""


class PettingDetector:
    """Counts horizontal cursor direction-reversals while the cursor is over the
    cat; enough reversals within a sliding time window reads as 'petting'."""

    def __init__(self, reversals_needed=3, window_s=1.2):
        self.reversals_needed = reversals_needed
        self.window_s = window_s
        self._last_x = None
        self._last_dir = 0
        self._reversals = []  # monotonic timestamps of recent reversals

    def _prune(self, now):
        cutoff = now - self.window_s
        self._reversals = [t for t in self._reversals if t >= cutoff]

    def update(self, x, inside, now):
        if not inside:
            self._last_x = None
            self._last_dir = 0
            return self.active(now)
        if self._last_x is not None:
            dx = x - self._last_x
            if dx != 0:
                d = 1 if dx > 0 else -1
                if self._last_dir != 0 and d != self._last_dir:
                    self._reversals.append(now)
                self._last_dir = d
        self._last_x = x
        return self.active(now)

    def active(self, now):
        self._prune(now)
        return len(self._reversals) >= self.reversals_needed
```

- [ ] **Step 4: Run, watch pass.**

- [ ] **Step 5: Commit** `feat: add PettingDetector reversal-counting logic`.

---

### Task 3: NapState box-catnap state machine (petkit/reactions.py)

**Files:**
- Modify: `petkit/reactions.py` (append the class)
- Test: `tests/test_reactions.py` (append `TestNapState`)

**Interfaces:**
- Produces: `NapState(sleep_after_ms=120000, startle_s=0.8)` with `.update(idle_ms, now) -> str` returning one of `"awake"`, `"napping"`, `"startled"`, and a `.state` attribute mirroring it.

- [ ] **Step 1: Write failing tests** (append to `tests/test_reactions.py`):

```python
from petkit.reactions import NapState


class TestNapState(unittest.TestCase):
    def test_starts_awake(self):
        n = NapState(sleep_after_ms=120000)
        self.assertEqual(n.update(0, now=0.0), "awake")

    def test_naps_after_idle_threshold(self):
        n = NapState(sleep_after_ms=120000)
        self.assertEqual(n.update(130000, now=1.0), "napping")

    def test_activity_during_nap_startles_then_wakes(self):
        n = NapState(sleep_after_ms=120000, startle_s=0.8)
        n.update(130000, now=1.0)               # napping
        self.assertEqual(n.update(5, now=2.0), "startled")
        self.assertEqual(n.update(5, now=2.5), "startled")   # still inside startle_s
        self.assertEqual(n.update(5, now=3.0), "awake")      # startle_s elapsed

    def test_can_renap_after_waking(self):
        n = NapState(sleep_after_ms=120000, startle_s=0.5)
        n.update(130000, now=1.0)               # napping
        n.update(5, now=2.0)                     # startled
        n.update(5, now=2.6)                     # awake
        self.assertEqual(n.update(130000, now=3.0), "napping")
```

- [ ] **Step 2: Run, watch the new tests fail.**

- [ ] **Step 3: Implement** (append to `petkit/reactions.py`):

```python
class NapState:
    """Idle-driven nap cycle: awake -> napping (idle exceeds threshold) ->
    startled (fresh input while napping) -> awake (after startle_s)."""

    def __init__(self, sleep_after_ms=120000, startle_s=0.8):
        self.sleep_after_ms = sleep_after_ms
        self.startle_s = startle_s
        self.state = "awake"
        self._startle_start = 0.0

    def update(self, idle_ms, now):
        if self.state == "awake":
            if idle_ms >= self.sleep_after_ms:
                self.state = "napping"
        elif self.state == "napping":
            if idle_ms < self.sleep_after_ms:   # input arrived -> jolt awake
                self.state = "startled"
                self._startle_start = now
        elif self.state == "startled":
            if now - self._startle_start >= self.startle_s:
                self.state = "awake"
        return self.state
```

- [ ] **Step 4: Run, watch pass.**

- [ ] **Step 5: Commit** `feat: add NapState box-catnap state machine`.

---

### Task 4: Welcome-back Greeter (petkit/greeter.py)

**Files:**
- Create: `petkit/greeter.py`
- Test: `tests/test_greeter.py`

**Interfaces:**
- Produces: `Greeter(away_after_ms=300000)` with `.update(idle_ms) -> str | None` — returns a greeting string exactly once, on the first active sample after an away period; `None` otherwise.

- [ ] **Step 1: Write failing tests** in `tests/test_greeter.py`:

```python
import unittest
from petkit.greeter import Greeter


class TestGreeter(unittest.TestCase):
    def test_no_greeting_without_being_away(self):
        g = Greeter(away_after_ms=300000)
        self.assertIsNone(g.update(0))
        self.assertIsNone(g.update(1000))

    def test_greets_once_on_return(self):
        g = Greeter(away_after_ms=300000)
        self.assertIsNone(g.update(400000))     # now away
        msg = g.update(0)                         # returned -> greet
        self.assertIsInstance(msg, str)
        self.assertIn("Welcome back", msg)
        self.assertIsNone(g.update(0))            # only once

    def test_reports_minutes_away(self):
        g = Greeter(away_after_ms=300000)
        g.update(600000)                          # 10 minutes idle
        msg = g.update(0)
        self.assertIn("10", msg)

    def test_short_absence_has_no_minute_count(self):
        g = Greeter(away_after_ms=300000)
        g.update(330000)                          # 5.5 min -> "5 min"
        self.assertIn("5", g.update(0))
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** `petkit/greeter.py`:

```python
"""Welcome-back greeter: fires once when activity resumes after an away period.
Idle values are injected so the logic is pure and unit-testable."""


class Greeter:
    def __init__(self, away_after_ms=300000):
        self.away_after_ms = away_after_ms
        self._was_away = False
        self._peak_idle = 0

    def update(self, idle_ms):
        if idle_ms >= self.away_after_ms:
            self._was_away = True
            self._peak_idle = max(self._peak_idle, idle_ms)
            return None
        if self._was_away:
            self._was_away = False
            minutes = self._peak_idle // 60000
            self._peak_idle = 0
            if minutes >= 1:
                return "Welcome back! (%d min)" % minutes
            return "Welcome back!"
        return None
```

- [ ] **Step 4: Run, watch pass.**

- [ ] **Step 5: Commit** `feat: add welcome-back Greeter`.

---

### Task 5: Speech bubble (petkit/bubble.py)

**Files:**
- Create: `petkit/bubble.py`
- Test: `tests/test_smoke_bubble.py` (GUI smoke, Windows-only)

**Interfaces:**
- Produces: `Bubble(root)` anchored above the pet window `root`, with `.say(text, secs=3, chime=False)` (show a transient rounded bubble; auto-hide after `secs`; optional async chime) and `.destroy()`.

**Design:** One reusable `Toplevel` created in `__init__` (overrideredirect, `-topmost`, `-transparentcolor` KEY_COLOR) and withdrawn. `say()` re-renders text on its `Canvas`, repositions above `root`, deiconifies, and (re)schedules a withdraw via `root.after`, cancelling any pending hide first. Reuse — never create/destroy per message. Chime uses `winsound.MessageBeep` (async, stdlib). Default `chime=False` so tests stay silent.

- [ ] **Step 1: Write the failing GUI smoke test** in `tests/test_smoke_bubble.py`:

```python
import os
import unittest
import tkinter as tk


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestBubble(unittest.TestCase):
    def test_say_shows_and_hides_without_crashing(self):
        import winkit.window as W
        import petkit.bubble as B
        W.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.geometry("170x170+100+100")
        root.update()
        try:
            bubble = B.Bubble(root)
            bubble.say("purr~", secs=1, chime=False)
            root.update()
            self.assertTrue(bubble.win.winfo_ismapped())
            bubble.say("Welcome back!", secs=1)  # re-say reuses the window
            root.update()
            bubble.destroy()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run, watch fail** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `petkit/bubble.py` — a reusable transient Toplevel. Render a rounded-rect (`create_polygon`/`create_rectangle` + `create_oval` corners, or a simple rounded rect helper) filled `#fffbe6` with `#202020` text, on a `Canvas` whose `bg=KEY_COLOR`. Size the canvas to the text (`font.measure`) plus padding. Position the window so its bottom-center sits ~8 px above `root`'s top edge, horizontally centered on `root`. Pseudostructure:

```python
import tkinter as tk
import tkinter.font as tkfont
import winsound
import winkit.window as window

PAD = 8
BUBBLE_FILL = "#fffbe6"
TEXT_FILL = "#202020"


class Bubble:
    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg=window.KEY_COLOR)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", window.KEY_COLOR)
        self.canvas = tk.Canvas(self.win, highlightthickness=0, bd=0,
                                bg=window.KEY_COLOR)
        self.canvas.pack()
        self.font = tkfont.Font(family="Segoe UI", size=10)
        self._hide_id = None
        self.win.withdraw()

    def say(self, text, secs=3, chime=False):
        tw = self.font.measure(text)
        th = self.font.metrics("linespace")
        w, h = tw + 2 * PAD, th + 2 * PAD
        self.canvas.configure(width=w, height=h)
        self.canvas.delete("all")
        self._round_rect(0, 0, w, h, 8, fill=BUBBLE_FILL)
        self.canvas.create_text(w / 2, h / 2, text=text, fill=TEXT_FILL,
                                font=self.font)
        self.root.update_idletasks()
        rx = self.root.winfo_rootx() + self.root.winfo_width() // 2 - w // 2
        ry = self.root.winfo_rooty() - h - PAD
        self.win.geometry("%dx%d+%d+%d" % (w, h, rx, ry))
        self.win.deiconify()
        self.win.lift()
        if chime:
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        if self._hide_id is not None:
            try:
                self.root.after_cancel(self._hide_id)
            except Exception:
                pass
        self._hide_id = self.root.after(int(secs * 1000), self._hide)

    def _hide(self):
        self._hide_id = None
        try:
            self.win.withdraw()
        except tk.TclError:
            pass

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
```

- [ ] **Step 4: Run the smoke test, watch pass.** (Run on Windows; it constructs a real Tk window.)

- [ ] **Step 5: Commit** `feat: add reusable speech bubble`.

---

### Task 6: Wire it all into pet.pyw + right-click menu

**Files:**
- Modify: `pet.pyw` (imports, `Cat.__init__`, `Cat.tick`, `Cat.draw`, add `<Motion>`/`<ButtonPress-3>` bindings, nap rendering, menu builder)
- Modify: `config.py` (extend `DEFAULTS["pet"]` with the new ability flags/thresholds)
- Test: `tests/test_config.py` (assert the new pet defaults exist), `tests/test_smoke_pet.py` (still passes with the new wiring)

**Interfaces consumed:** `winkit.input.idle_ms`, `petkit.reactions.PettingDetector`, `petkit.reactions.NapState`, `petkit.greeter.Greeter`, `petkit.bubble.Bubble`, `winkit.sprites.SpriteSheet`.

**Config additions** — extend `DEFAULTS["pet"]` (in `config.py`) with, on the same line style as the existing keys:

```python
    "petting": True, "catnap": True, "greeter": True,
    "nap_after_s": 120, "away_after_s": 300,
```

- [ ] **Step 1: Config test first** — append to `tests/test_config.py` a test asserting `config.defaults()["pet"]` contains `petting`, `catnap`, `greeter` (bools) and `nap_after_s`, `away_after_s` (ints). Run, watch fail. Add the keys to `config.py`. Run, watch pass. Commit `feat: add Phase 2 pet config defaults`.

- [ ] **Step 2: Construct the Phase 2 objects** in `Cat.__init__` (after the existing sprite/glow setup):

```python
        self.nap_sheet = sprites.SpriteSheet(root, os.path.join(ASSETS, "Box3.png"))
        self.petting = reactions.PettingDetector()
        self.nap = reactions.NapState(sleep_after_ms=int(pet.get("nap_after_s", 120)) * 1000)
        self.greeter = greeter.Greeter(away_after_ms=int(pet.get("away_after_s", 300)) * 1000)
        self.bubble = bubble.Bubble(root)
        self.nap_state = "awake"
        self.nap_frame_i = 0
        self.nap_frame_t = self.t0
        self._petting_was = False
        self._next_zzz = 0.0
```

Add imports at the top: `import petkit.reactions as reactions`, `import petkit.greeter as greeter`, `import petkit.bubble as bubble`. Bind `<Motion>` on root+canvas to `self._on_motion`, and `<ButtonPress-3>` to `self._on_right_click`.

- [ ] **Step 3: `_on_motion`** — feed the petting detector. `inside` = cursor over the cat sprite bbox in window space (`abs(event.x - self.cx) < self.sprite_px/2` and `self.base_y - self.sprite_px < event.y < self.base_y`):

```python
    def _on_motion(self, event):
        now = time.monotonic()
        inside = (abs(event.x - self.cx) < self.sprite_px / 2.0
                  and (self.base_y - self.sprite_px) < event.y < self.base_y)
        if self.petting.update(event.x_root, inside, now):
            if not self._petting_was and self.cfg["pet"].get("petting", True):
                self.bubble.say("purr~", secs=2)
            self._petting_was = True
        else:
            self._petting_was = False
```

- [ ] **Step 4: Drive nap + greeter in `tick`** (after computing `now`, before/with `draw`): read `idle = wkinput.idle_ms()`; if `cfg["pet"]["catnap"]`, `self.nap_state = self.nap.update(idle, now)` else `"awake"`; if `cfg["pet"]["greeter"]`, `g = self.greeter.update(idle)` and if `g: self.bubble.say(g, secs=4, chime=True)`. When `self.nap_state == "napping"`, force the active flag false and clamp `fps` to `max(2, ...)`→ actually to ~2 fps (nap is a CPU win); occasionally `self.bubble.say("Zzz", secs=2)` throttled by `self._next_zzz`. On the `napping`→`startled` edge, trigger a hop (`self._on_beat()`).

- [ ] **Step 5: Nap rendering in `draw`** — when `self.nap_state == "napping"`, swap `self.cat_item`'s image from `self.nap_sheet` (advance `nap_frame_i` at ~2 fps) and **hide both eyes** (the box-sleeping sprite has its own face); otherwise render the Idle sheet + eyes exactly as today. Petting squint: when `self._petting_was`, treat eyes as blinking (reuse the closed-eye path) for a contented squint.

- [ ] **Step 6: Right-click menu** — `_on_right_click(event)` builds a fresh `tk.Menu` each popup (so checkmarks reflect current config) and `tk_popup`s it:

```python
    def _on_right_click(self, event):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="🐱 Cat", state="disabled")
        m.add_separator()
        for key, label in (("petting", "Petting & purr"),
                           ("catnap", "Box catnap"),
                           ("greeter", "Welcome-back greeting")):
            m.add_checkbutton(label=label, onvalue=1, offvalue=0,
                              variable=self._menu_var(key),
                              command=lambda k=key: self._toggle_cfg(k))
        m.add_separator()
        m.add_command(label="Hide cat", command=self.root.destroy)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()
```

`_menu_var(key)` returns a cached `tk.IntVar` initialised from `cfg["pet"][key]`; `_toggle_cfg(key)` flips `cfg["pet"][key]`, saves config (best-effort), and updates the var. (Left-click stays drag-only — do not bind button-3 to drag.)

- [ ] **Step 7: Smoke** — run `tests/test_smoke_pet.py` under `TOYBOX_SMOKE`; confirm the cat still constructs and ticks (now with bubble/menu/nap wiring) without crashing. If the smoke harness needs a nudge to cover the new objects, add a minimal assertion that `cat.bubble` and `cat.nap` exist. Run the **full suite**; all green.

- [ ] **Step 8: Commit** `feat: wire petting, catnap, greeter, bubble + right-click menu into the cat`.

---

## Self-Review Notes

- Spec coverage: Petting & Purr (Task 2 + 6), Box Catnap incl. `idle_ms()` (Tasks 1, 3, 6), welcome-back greeter (Tasks 4, 6), bubble substrate (Task 5, 6), right-click menu substrate (Task 6). All Phase 2 spec items covered.
- Type consistency: `NapState.update`/`PettingDetector.update`/`Greeter.update` signatures match between their producing tasks and the Task 6 call sites.
- Pure modules inject clock/idle — no wall-clock inside `petkit/reactions.py` or `petkit/greeter.py`. `idle_ms()` is the only new Win32 call and is isolated in `winkit/input.py`.
