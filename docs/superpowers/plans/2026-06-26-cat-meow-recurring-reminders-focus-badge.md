# Cat: Meow Chime + Recurring Reminders + Focus Badge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Windows system chime with a real cat meow, make reminders optionally daily-recurring, and float a live focus-timer countdown above the cat.

**Architecture:** Pure logic (reminder recurrence math, badge text formatting) extends/creates `petkit/` modules and is unit-tested with injected clocks. A bundled `assets/meow.wav` (PCM) is played async by `petkit/bubble.py`. A new `petkit/timerbadge.py` mirrors the speech-bubble window technique. `pet.pyw` gains one badge create/update/destroy; `petkit/settings.py` gains a one-time/daily control. Three independent features, each an independently testable increment.

**Tech Stack:** Python 3.12 stdlib only — `tkinter` + `winsound` + `wave` + `json` + `time`. Tests: `unittest`.

## Global Constraints

- **Pure Python 3.12 stdlib only. No third-party / pip packages, ever.** (tkinter, winsound, wave, json, time, os, re.)
- Win32 stays in `winkit/`; pet feature logic + GUI pieces stay in `petkit/` (precedent: `petkit/bubble.py`).
- Pure logic takes injected clock/now values (no `time.*` inside pure functions).
- TDD: write the failing test first, watch it fail, minimal code to pass.
- `assets/meow.wav` MUST be a PCM WAV the stdlib `wave` module opens with `getcomptype() == "NONE"` (otherwise `winsound.PlaySound` is silent).
- Reminder `repeat` is the only new field; values limited to `"none"`/`"daily"`; old `reminders.json` entries load as one-time. **No new `config.json` keys.**
- Test runner — bare `python` is a broken MS-Store stub (exit 49); use the full interpreter path:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`
- Commit after each task. End commit messages with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

**Shorthand:** `PY` = `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`. Run all commands from the repo root `C:/Users/Warren/Toybox`.

## File Structure

```
petkit/reminders.py          # EXTEND: advance_daily() (pure); repeat field in _load/add/due
petkit/timerbadge.py         # NEW: badge_text() (pure) + TimerBadge (GUI, bubble-style)
petkit/bubble.py             # EXTEND: meow via winsound.PlaySound(assets/meow.wav, async)
assets/meow.wav              # NEW: bundled CC0/public-domain PCM meow (real, else synthesized)
pet.pyw                      # WIRE: create/update/destroy the focus badge
petkit/settings.py           # EXTEND: Reminders tab one-time/daily control + list marker
tests/test_reminders.py      # EXTEND: recurrence + back-compat
tests/test_timerbadge.py     # NEW: badge_text unit + TimerBadge GUI smoke (Windows-only)
tests/test_smoke_bubble.py   # EXTEND: meow asset is PCM + chime=True does not raise
tests/test_smoke_pet.py      # EXTEND: focus badge shows during focus
tests/test_smoke_settings.py # EXTEND: daily reminder add + marker render
```

---

### Task 1: Recurring reminders — `repeat` field + daily reschedule

**Files:**
- Modify: `petkit/reminders.py`
- Test: `tests/test_reminders.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `advance_daily(due, now) -> int` — smallest `due + 86400*k` strictly greater than `now` (`k >= 1` when `due <= now`; returns `due` unchanged when already `> now`). Pure.
  - `Reminders.add(text, due_epoch, repeat="none")` — stores `{"text","due","repeat"}`; `repeat` coerced to `"none"` unless exactly `"daily"`.
  - `Reminders._load` — every loaded item carries `repeat` (`"none"` default; non-`"none"`/`"daily"` → `"none"`).
  - `Reminders.due(now_epoch)` — daily items reschedule via `advance_daily` and stay pending; one-time items are removed; returns fired texts sorted by the due that fired.
  - `Reminders.pending()` — dict copies now include `repeat` (no code change needed).

- [ ] **Step 1: Write the failing tests**

In `tests/test_reminders.py`, ensure the imports include `import json` (add it if missing; `os`, `time`, `tempfile`, `shutil`, `unittest`, and `petkit.reminders as reminders` are already there). Append:

```python
class TestRecurringReminders(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.path = os.path.join(self.dir, "r.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_advance_daily_next_future_slot(self):
        self.assertEqual(reminders.advance_daily(1000, 1000), 1000 + 86400)
        self.assertEqual(reminders.advance_daily(1000, 999), 1000)            # already future
        self.assertEqual(reminders.advance_daily(1000, 1000 + 86400), 1000 + 2 * 86400)

    def test_add_defaults_one_time(self):
        r = reminders.Reminders(self.path)
        r.add("ping", 1000)
        self.assertEqual(r.pending()[0]["repeat"], "none")

    def test_add_daily_stored(self):
        r = reminders.Reminders(self.path)
        r.add("standup", 1000, repeat="daily")
        self.assertEqual(r.pending()[0]["repeat"], "daily")

    def test_add_unknown_repeat_coerced(self):
        r = reminders.Reminders(self.path)
        r.add("x", 1000, repeat="weekly")
        self.assertEqual(r.pending()[0]["repeat"], "none")

    def test_due_one_time_removed(self):
        r = reminders.Reminders(self.path)
        r.add("once", 1000, repeat="none")
        self.assertEqual(r.due(2000), ["once"])
        self.assertEqual(r.pending(), [])

    def test_due_daily_reschedules_and_keeps(self):
        r = reminders.Reminders(self.path)
        r.add("standup", 1000, repeat="daily")
        self.assertEqual(r.due(1000), ["standup"])
        pend = r.pending()
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["due"], 1000 + 86400)
        self.assertEqual(pend[0]["repeat"], "daily")

    def test_due_daily_far_past_fires_once_into_future(self):
        r = reminders.Reminders(self.path)
        r.add("daily", 1000, repeat="daily")
        now = 1000 + 5 * 86400 + 17                       # 5+ days later
        self.assertEqual(r.due(now), ["daily"])           # fires exactly once
        self.assertEqual(len(r.pending()), 1)
        self.assertGreater(r.pending()[0]["due"], now)    # landed in the future

    def test_due_daily_persists_reschedule(self):
        r = reminders.Reminders(self.path)
        r.add("standup", 1000, repeat="daily")
        r.due(1000)
        reloaded = reminders.Reminders(self.path)
        self.assertEqual(reloaded.pending()[0]["due"], 1000 + 86400)
        self.assertEqual(reloaded.pending()[0]["repeat"], "daily")

    def test_load_backcompat_missing_repeat(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([{"text": "old", "due": 1000}], f)   # legacy item, no repeat
        r = reminders.Reminders(self.path)
        self.assertEqual(r.pending()[0]["repeat"], "none")

    def test_load_bad_repeat_coerced(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([{"text": "x", "due": 1000, "repeat": "weekly"}], f)
        r = reminders.Reminders(self.path)
        self.assertEqual(r.pending()[0]["repeat"], "none")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PY -m unittest tests.test_reminders -v`
Expected: FAIL/ERROR — `module 'petkit.reminders' has no attribute 'advance_daily'`; `add()` takes no `repeat`; items have no `repeat` key.

- [ ] **Step 3: Implement**

In `petkit/reminders.py`, add the pure helper after `format_due` (before `class Reminders`):

```python
def advance_daily(due, now):
    """Next daily occurrence strictly after `now`, stepping 24h from `due`. Pure.
    Reschedules a fired daily reminder; if the app was off for days it jumps to
    the next future slot (fires once, not once per missed day)."""
    due, now = int(due), int(now)
    while due <= now:
        due += 86400
    return due
```

In `_load`, replace the append block so each item carries a validated `repeat`:

```python
        for it in data:
            if (isinstance(it, dict) and isinstance(it.get("text"), str)
                    and isinstance(it.get("due"), (int, float))
                    and not isinstance(it.get("due"), bool)):
                repeat = it.get("repeat")
                if repeat not in ("none", "daily"):
                    repeat = "none"
                out.append({"text": it["text"], "due": int(it["due"]),
                            "repeat": repeat})
        return out
```

Replace `add`:

```python
    def add(self, text, due_epoch, repeat="none"):
        if repeat != "daily":
            repeat = "none"
        self._items.append({"text": text, "due": int(due_epoch),
                            "repeat": repeat})
        self._save()
```

Replace `due`:

```python
    def due(self, now_epoch):
        fired = sorted((i for i in self._items if i["due"] <= now_epoch),
                       key=lambda i: i["due"])
        if not fired:
            return []
        texts = [i["text"] for i in fired]            # capture order before mutating
        kept = []
        for i in self._items:
            if i["due"] > now_epoch:
                kept.append(i)
            elif i.get("repeat") == "daily":
                i["due"] = advance_daily(i["due"], now_epoch)
                kept.append(i)
            # else: one-time fired -> dropped
        self._items = kept
        self._save()
        return texts
```

(`pending()` already returns `dict(i)` copies, so `repeat` flows through unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `PY -m unittest tests.test_reminders -v`
Expected: PASS (new recurrence tests + all pre-existing reminder tests).

- [ ] **Step 5: Commit**

```bash
git add petkit/reminders.py tests/test_reminders.py
git commit -m "Add daily-recurring reminders (repeat field + advance_daily)"
```

---

### Task 2: Meow chime — bundle `assets/meow.wav`, play it async

**Files:**
- Create: `assets/meow.wav`
- Modify: `petkit/bubble.py`
- Test: `tests/test_smoke_bubble.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `petkit.bubble._MEOW` (absolute path to the bundled WAV); `bubble.say(..., chime=True)` now plays the meow async (silent if the file is missing).

- [ ] **Step 1: Obtain `assets/meow.wav` (real CC0 meow preferred; synthesized fallback)**

Goal: a short cat **meow** at `assets/meow.wav` that is a PCM WAV (`getcomptype() == "NONE"`).

1. **Preferred — a real, freely-licensed meow.** Find a CC0 / public-domain short cat "meow" available as a PCM WAV (e.g. search Wikimedia Commons for "cat meow" and filter for `.wav`, or a CC0 sound library). Download it:
   `curl -L -o assets/meow.wav "<DIRECT_WAV_URL>"`
   Then validate:
   `PY -c "import wave;w=wave.open('assets/meow.wav','rb');print(w.getcomptype(),w.getnchannels(),w.getframerate(),w.getnframes())"`
   Accept only if `getcomptype()` prints `NONE` and `getnframes()` > 0. If the license requires attribution, add a line to `README.md`. (CC0 needs none.)
2. **Fallback — synthesize a meow-like WAV** (guaranteed valid PCM; use this only if no suitable real WAV is obtained). Run:
   ```bash
   PY - <<'PYEOF'
   import math, struct, wave
   RATE = 22050; DUR = 0.45
   def s(t):
       x = t / DUR
       base = 600 + 250 * math.sin(math.pi * x)        # arched pitch 600->850->600 Hz
       vib = 1 + 0.03 * math.sin(2*math.pi*6*t)        # gentle vibrato
       env = math.sin(math.pi * x) ** 0.6              # smooth attack/decay
       y = math.sin(2*math.pi*base*vib*t) + 0.4*math.sin(2*math.pi*2*base*vib*t)
       return max(-1.0, min(1.0, env * y / 1.4))
   frames = bytearray()
   for n in range(int(RATE*DUR)):
       frames += struct.pack("<h", int(s(n/RATE) * 30000))
   with wave.open("assets/meow.wav", "wb") as w:
       w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
       w.writeframes(bytes(frames))
   print("wrote assets/meow.wav")
   PYEOF
   ```
   Validate the same way (must print `NONE`).

Record in your report which path was taken and (for the real file) the source URL + license.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_smoke_bubble.py`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestMeowChime(unittest.TestCase):
    def test_meow_asset_is_pcm_wav(self):
        import wave
        import petkit.bubble as B
        with wave.open(B._MEOW, "rb") as w:
            self.assertEqual(w.getcomptype(), "NONE")   # PCM -> winsound-playable
            self.assertGreater(w.getnframes(), 0)

    def test_chime_true_meows_without_raising(self):
        import winkit.window as W
        import petkit.bubble as B
        W.enable_dpi_awareness()
        root = tk.Tk(); root.overrideredirect(True)
        root.geometry("170x170+100+100"); root.update()
        try:
            bubble = B.Bubble(root)
            bubble.say("meow", secs=1, chime=True)       # plays the async meow once
            root.update()
            bubble.destroy()
        finally:
            root.destroy()
```

(`test_chime_true_meows_without_raising` emits one short meow when run — that is the real behavior under test.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `PY -m unittest tests.test_smoke_bubble -v`
Expected: FAIL/ERROR — `petkit.bubble` has no attribute `_MEOW`.

- [ ] **Step 4: Implement the meow chime in `petkit/bubble.py`**

Add `import os` to the import block (it currently imports `tkinter as tk`, `tkinter.font as tkfont`, `winsound`, `winkit.window as window`). Add the path constant next to the other module constants (`PAD`/`BUBBLE_FILL`/`TEXT_FILL`):

```python
_MEOW = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "assets", "meow.wav"))
```

Replace the chime block in `say` (currently `winsound.MessageBeep(winsound.MB_ICONASTERISK)`):

```python
        if chime:
            try:
                winsound.PlaySound(
                    _MEOW,
                    winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except Exception:
                pass
```

- [ ] **Step 5: Run tests to verify they pass; then the full suite**

Run: `PY -m unittest tests.test_smoke_bubble -v`  → PASS.
Run: `PY -m unittest discover -s tests -p "test_*.py"` → ends in `OK`.

- [ ] **Step 6: Commit**

```bash
git add assets/meow.wav petkit/bubble.py tests/test_smoke_bubble.py
git commit -m "Replace the Windows chime with a real meow (async PlaySound)"
```

---

### Task 3: Focus badge module — `petkit/timerbadge.py`

**Files:**
- Create: `petkit/timerbadge.py`
- Test: `tests/test_timerbadge.py`

**Interfaces:**
- Consumes: `petkit.bubble.bubble_xy` (placement), `winkit.window.KEY_COLOR`.
- Produces:
  - `badge_text(state, remaining_s) -> str` — `"focus"`→`"🎯 M:SS"`, `"break"`→`"☕ M:SS"`, `"paused"`→`"⏸ M:SS"`, else `""`. `remaining_s` clamped to `>= 0`. Pure.
  - `class TimerBadge(root, head_offset=0)` with `show(text)` (empty `text` → hide), `hide()`, `destroy()`. Singleton withdrawn Toplevel; lifts only on the hidden→shown transition (so transient bubbles posted later stay above it); all Tk calls guarded against `tk.TclError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_timerbadge.py`:

```python
import os
import unittest

import petkit.timerbadge as timerbadge


class TestBadgeText(unittest.TestCase):
    def test_focus(self):
        self.assertEqual(timerbadge.badge_text("focus", 125), "\U0001F3AF 2:05")

    def test_break(self):
        self.assertEqual(timerbadge.badge_text("break", 5), "☕ 0:05")

    def test_paused(self):
        self.assertEqual(timerbadge.badge_text("paused", 1500), "⏸ 25:00")

    def test_idle_is_empty(self):
        self.assertEqual(timerbadge.badge_text("idle", 0), "")

    def test_negative_clamped(self):
        self.assertEqual(timerbadge.badge_text("focus", -3), "\U0001F3AF 0:00")


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestTimerBadgeWidget(unittest.TestCase):
    def test_show_update_hide_destroy(self):
        import tkinter as tk
        import winkit.window as window
        root = tk.Tk(); root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("80x80+140+140"); root.update()
        try:
            b = timerbadge.TimerBadge(root, head_offset=10)
            b.show(timerbadge.badge_text("focus", 1500)); root.update()
            self.assertTrue(b._shown)
            b.show(timerbadge.badge_text("focus", 1499)); root.update()   # update path
            b.show("")                         # empty text -> hide
            self.assertFalse(b._shown)
            b.hide()
            b.destroy()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PY -m unittest tests.test_timerbadge -v`
Expected: FAIL/ERROR — `No module named 'petkit.timerbadge'`.

- [ ] **Step 3: Implement `petkit/timerbadge.py`**

```python
"""Persistent focus-timer badge: a small always-on-top countdown that floats
just above the cat while a Pomodoro focus/break/pause is running. Mirrors the
speech-bubble window technique (transparent overrideredirect Toplevel, rounded
rect + text on a Canvas) and reuses bubble.bubble_xy for placement. The label
(badge_text) is a pure function and is unit-tested; the rest is GUI glue guarded
against TclError like bubble.py. Stdlib only."""
import tkinter as tk
import tkinter.font as tkfont

import petkit.bubble as bubble
import winkit.window as window

PAD = 6
BADGE_FILL = "#222831"
TEXT_FILL = "#f5f5f5"

_ICON = {"focus": "\U0001F3AF", "break": "☕", "paused": "⏸"}


def badge_text(state, remaining_s):
    """Pure label for the focus badge. 'focus'->'🎯 M:SS', 'break'->'☕ M:SS',
    'paused'->'⏸ M:SS'; any other state (e.g. 'idle') -> '' (badge hidden).
    remaining_s is clamped at 0."""
    icon = _ICON.get(state)
    if icon is None:
        return ""
    rem = int(remaining_s)
    if rem < 0:
        rem = 0
    m, s = divmod(rem, 60)
    return "%s %d:%02d" % (icon, m, s)


class TimerBadge:
    def __init__(self, root, head_offset=0):
        self.root = root
        self.head_offset = head_offset
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg=window.KEY_COLOR)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", window.KEY_COLOR)
        self.canvas = tk.Canvas(self.win, highlightthickness=0, bd=0,
                                bg=window.KEY_COLOR)
        self.canvas.pack()
        self.font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._shown = False
        self.win.withdraw()

    def show(self, text):
        if not text:
            self.hide()
            return
        tw = self.font.measure(text)
        th = self.font.metrics("linespace")
        w, h = tw + 2 * PAD, th + 2 * PAD
        try:
            self.canvas.configure(width=w, height=h)
            self.canvas.delete("all")
            self._round_rect(0, 0, w, h, 7, fill=BADGE_FILL)
            self.canvas.create_text(w / 2, h / 2, text=text, fill=TEXT_FILL,
                                    font=self.font)
            self.root.update_idletasks()
            rx, ry = bubble.bubble_xy(self.root.winfo_rootx(),
                                      self.root.winfo_rooty(),
                                      self.root.winfo_width(),
                                      self.head_offset, w, h)
            self.win.geometry("%dx%d+%d+%d" % (w, h, rx, ry))
            if not self._shown:
                self.win.deiconify()
                self.win.lift()                 # lift once; later bubbles stay above
                self._shown = True
        except tk.TclError:
            pass

    def hide(self):
        if not self._shown:
            return
        self._shown = False
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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PY -m unittest tests.test_timerbadge -v`
Expected: PASS (5 pure + 1 GUI smoke).

- [ ] **Step 5: Commit**

```bash
git add petkit/timerbadge.py tests/test_timerbadge.py
git commit -m "Add the focus-timer badge widget (badge_text + TimerBadge)"
```

---

### Task 4: Wire the focus badge into `pet.pyw`

**Files:**
- Modify: `pet.pyw`
- Test: `tests/test_smoke_pet.py`

**Interfaces:**
- Consumes: `petkit.timerbadge.TimerBadge`/`badge_text` (Task 3); `self.pomodoro` (`state`, `remaining(now)`); the existing `head_y` and `self.bubble` wiring.
- Produces: `Cat.timerbadge` (a `TimerBadge`), updated each `tick`, destroyed in `close`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_smoke_pet.py` (reuse the established `_make_cat` pattern in a new class):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPetFocusBadge(unittest.TestCase):
    def _make_cat(self):
        import tkinter as tk
        import winkit.window as window
        import config
        import pet as petmod
        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("%dx%d+100+100" % (petmod.WIN, petmod.WIN))
        canvas = tk.Canvas(root, width=petmod.WIN, height=petmod.WIN,
                           bg=window.KEY_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        root.update()
        return root, petmod.Cat(root, canvas, config.defaults())

    def test_badge_shows_during_focus_and_hides_when_idle(self):
        root, cat = self._make_cat()
        try:
            self.assertTrue(hasattr(cat, "timerbadge"))
            cat._start_focus()
            self.assertEqual(cat.pomodoro.state, "focus")
            cat.tick()                              # one tick with focus running
            self.assertTrue(cat.timerbadge._shown)  # badge became visible
            cat._stop_focus()
            cat.tick()                              # idle tick hides it
            self.assertFalse(cat.timerbadge._shown)
            cat.close()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PY -m unittest tests.test_smoke_pet.TestPetFocusBadge -v`
Expected: FAIL/ERROR — `Cat` has no `timerbadge`.

- [ ] **Step 3a: Import the module**

In `pet.pyw`, add to the import block (next to the other `import petkit.* as ...` lines, e.g. by `import petkit.bubble as bubble`):

```python
import petkit.timerbadge as timerbadge
```

- [ ] **Step 3b: Create the badge in `__init__`**

Immediately after the bubble is created (`self.bubble = bubble.Bubble(root, head_offset=head_y)`), add:

```python
        self.timerbadge = timerbadge.TimerBadge(root, head_offset=head_y)
```

- [ ] **Step 3c: Update the badge each tick**

In `tick`, right after the Pomodoro done-event block (currently):

```python
        ev = self.pomodoro.update(now)
        if ev == "focus_done":
            self.bubble.say("Break time! \U0001F43E", secs=4, chime=True)
        elif ev == "break_done":
            self.bubble.say("Back to it? \U0001F431", secs=4, chime=True)
```

insert:

```python
        st = self.pomodoro.state
        if st in ("focus", "break", "paused"):
            self.timerbadge.show(timerbadge.badge_text(st, self.pomodoro.remaining(now)))
        else:
            self.timerbadge.hide()
```

- [ ] **Step 3d: Destroy the badge in `close`**

In `Cat.close`, after the `settings` teardown block, add:

```python
        try:
            if getattr(self, "timerbadge", None):
                self.timerbadge.destroy()
        except Exception:
            pass
```

- [ ] **Step 4: Run the targeted test, then the full suite**

Run: `PY -m unittest tests.test_smoke_pet.TestPetFocusBadge -v` → PASS.
Run: `PY -m unittest discover -s tests -p "test_*.py"` → ends in `OK`.

- [ ] **Step 5: Commit**

```bash
git add pet.pyw tests/test_smoke_pet.py
git commit -m "Float a live focus-timer badge above the cat while a timer runs"
```

---

### Task 5: Settings — one-time/daily control on the Reminders tab

**Files:**
- Modify: `petkit/settings.py`
- Test: `tests/test_smoke_settings.py`

**Interfaces:**
- Consumes: `Reminders.add(text, due, repeat)` and the `repeat` field in `pending()` (Task 1).
- Produces: `SettingsWindow._repeat_var` (a `tk.IntVar`); the Reminders tab adds with the chosen `repeat` and marks recurring rows.

- [ ] **Step 1: Write the failing test**

Add a method to the existing `TestSettingsWindow` class in `tests/test_smoke_settings.py`:

```python
    def test_daily_reminder_add_and_marker(self):
        import petkit.settings as settings
        root, cat = self._make_cat()
        try:
            win = settings.SettingsWindow(cat)
            win.open("Reminders")
            win._mode_var.set("at"); win._hh_var.set("9"); win._mm_var.set("0")
            win._repeat_var.set(1)
            win._msg_var.set("standup"); win._on_add_reminder()
            pend = cat.reminders.pending()
            self.assertTrue(any(i["text"] == "standup" and i["repeat"] == "daily"
                                for i in pend))
            win._refresh_reminders()        # daily-marker render path, must not raise
            win.close()
            cat.close()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PY -m unittest tests.test_smoke_settings.TestSettingsWindow.test_daily_reminder_add_and_marker -v`
Expected: FAIL/ERROR — `SettingsWindow` has no `_repeat_var`.

- [ ] **Step 3a: Add the daily checkbutton (in `_build_reminders_tab`)**

In `petkit/settings.py`, replace the Add-button line in the `atrow` block:

```python
        tk.Button(atrow, text="Add", command=self._on_add_reminder).pack(side="left", padx=8)
```

with:

```python
        self._repeat_var = tk.IntVar(value=0)
        tk.Checkbutton(atrow, text="daily", variable=self._repeat_var).pack(side="left", padx=(8, 0))
        tk.Button(atrow, text="Add", command=self._on_add_reminder).pack(side="left", padx=8)
```

- [ ] **Step 3b: Pass `repeat` on add (in `_on_add_reminder`)**

Replace:

```python
        self.cat.reminders.add(self._msg_var.get().strip() or "Reminder", due)
```

with:

```python
        repeat = "daily" if self._repeat_var.get() else "none"
        self.cat.reminders.add(self._msg_var.get().strip() or "Reminder", due, repeat)
```

- [ ] **Step 3c: Mark recurring rows (in `_refresh_reminders`)**

Replace the two label lines:

```python
            tk.Label(row, text=reminders.format_due(item["due"], now), fg="#666").pack(side="right", padx=6)
            tk.Label(row, text="• " + item["text"], anchor="w").pack(side="left")
```

with:

```python
            daily = item.get("repeat") == "daily"
            when = ("daily " if daily else "") + reminders.format_due(item["due"], now)
            tk.Label(row, text=when, fg="#666").pack(side="right", padx=6)
            tk.Label(row, text=("↻ " if daily else "• ") + item["text"], anchor="w").pack(side="left")
```

- [ ] **Step 4: Run the targeted test, then the full suite**

Run: `PY -m unittest tests.test_smoke_settings -v` → PASS.
Run: `PY -m unittest discover -s tests -p "test_*.py"` → ends in `OK`.

- [ ] **Step 5: Commit**

```bash
git add petkit/settings.py tests/test_smoke_settings.py
git commit -m "Settings: one-time/daily choice on the Reminders tab"
```

---

## Self-Review

**1. Spec coverage** (against `docs/superpowers/specs/2026-06-26-cat-meow-recurring-reminders-focus-badge-design.md`):
- Meow chime (bundled PCM `assets/meow.wav`, async `PlaySound`, `SND_NODEFAULT`, all 5 alerts) → Task 2. ✓
- Recurring reminders (`repeat` none/daily, daily reschedule via `advance_daily`, fire-once-when-late, back-compat load, no new config keys) → Task 1. ✓
- Reminders UI (one-time/daily control + recurring marker) → Task 5. ✓
- Focus badge (pure `badge_text`, `TimerBadge` bubble-style window, show/hide/destroy, wired into `tick`/`close`, fps unchanged) → Tasks 3 + 4. ✓
- Testing strategy (pure unit for recurrence + badge_text; Windows GUI smoke for badge/bubble/pet/settings; meow asset validated as PCM) → Tasks 1–5. ✓

**2. Placeholder scan:** No TBD/TODO. The meow asset has concrete acquisition + validation + a complete synth fallback script (not a placeholder). Every code step shows full code; commands use the explicit `PY` path. ✓

**3. Type consistency:** `advance_daily(due, now)` is called inside `due()` with matching args; `Reminders.add(text, due, repeat="none")` matches the Settings call in Task 5 and the default keeps every existing one-arg/two-arg caller one-time; `badge_text(state, remaining_s)` is called with `(st, self.pomodoro.remaining(now))` in Task 4 and `(state, secs)` in tests; `TimerBadge.show/hide/destroy` and `_shown` match the tests; `bubble.bubble_xy(root_x, root_y, root_w, head_offset, w, h)` matches its definition; `_MEOW` is referenced by the bubble chime and the asset test. ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-26-cat-meow-recurring-reminders-focus-badge.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints.
