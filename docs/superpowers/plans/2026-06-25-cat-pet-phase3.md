# Cat Pet — Phase 3 "Assistant" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the cat into a lightweight assistant — a focus/Pomodoro timer, natural-language reminders, activity-gated break nudges, a per-app focus tracker, and clipboard quick-actions — all surfaced through the Phase 2 bubble + right-click menu.

**Architecture:** Five independent, pure, injected-clock logic modules in `petkit/` (TDD'd cross-platform) plus one Win32 foreground-window probe in `winkit/apps.py`, wired into `pet.pyw`'s existing tick loop and right-click menu across two integration tasks. Reminders persist to `reminders.json` (atomic write). Everything is event-driven or low-poll; per-frame cost stays O(1).

**Tech Stack:** Python 3.12 stdlib only — tkinter, ctypes, ast, re, json, time, winsound.

## Global Constraints

- Pure stdlib only; no pip/third-party imports.
- Pure-logic modules take injected clock/now values (monotonic seconds or epoch as noted) — **no `time.monotonic()`/`time.time()`/`datetime.now()` inside them** — so they unit-test deterministically. (Functions of an *injected* `now_epoch` may call `time.localtime(now_epoch)`/`time.mktime` — those are deterministic given the input.)
- Win32 code lives in `winkit/`; pet-feature logic lives in `petkit/`.
- Per-frame work stays O(1). New work is event-driven or low-poll (reminders ≤ ~1/5s, focus-sample ~1/3s, clipboard rides the sequence number).
- Clipboard quick-actions are **read-only** and must reject unsafe input (no `eval`/`exec`/`__import__`; whitelisted `ast` only).
- Test runner: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -p "test_*.py"`.
- Windows-only tests guard with `@unittest.skipUnless(os.name == "nt", "Windows only")`.
- Reuse existing idioms: atomic JSON write = `tempfile.mkstemp` + `os.replace` (see `config.save`); clipboard change = `winkit.input.clipboard_sequence()`; clipboard text = `root.clipboard_get()` (guard `tk.TclError`).

---

### Task 1: Pomodoro / focus timer (petkit/pomodoro.py)

**Files:**
- Create: `petkit/pomodoro.py`
- Test: `tests/test_pomodoro.py`

**Interfaces:**
- Produces: `Pomodoro(focus_s=1500, break_s=300)` with `.start(now)`, `.pause(now)`, `.resume(now)`, `.cancel()`, `.update(now) -> str | None` (returns `"focus_done"` or `"break_done"` exactly on the crossing tick, else `None`), `.remaining(now) -> float` (seconds left in the current phase, 0 when idle), and a `.state` attribute in `{"idle","focus","break","paused"}`.

- [ ] **Step 1: Write failing tests** `tests/test_pomodoro.py`:

```python
import unittest
from petkit.pomodoro import Pomodoro


class TestPomodoro(unittest.TestCase):
    def test_starts_idle(self):
        p = Pomodoro()
        self.assertEqual(p.state, "idle")
        self.assertEqual(p.remaining(now=0.0), 0)

    def test_focus_counts_down_then_enters_break(self):
        p = Pomodoro(focus_s=100, break_s=20)
        p.start(now=0.0)
        self.assertEqual(p.state, "focus")
        self.assertEqual(p.remaining(now=40.0), 60)
        self.assertIsNone(p.update(now=40.0))
        self.assertEqual(p.update(now=100.0), "focus_done")
        self.assertEqual(p.state, "break")
        self.assertEqual(p.remaining(now=100.0), 20)

    def test_break_completes_to_idle(self):
        p = Pomodoro(focus_s=10, break_s=10)
        p.start(now=0.0)
        p.update(now=10.0)                       # -> break
        self.assertEqual(p.update(now=20.0), "break_done")
        self.assertEqual(p.state, "idle")

    def test_pause_freezes_remaining_then_resume(self):
        p = Pomodoro(focus_s=100)
        p.start(now=0.0)
        p.pause(now=30.0)
        self.assertEqual(p.state, "paused")
        self.assertEqual(p.remaining(now=999.0), 70)   # frozen while paused
        p.resume(now=200.0)
        self.assertEqual(p.state, "focus")
        self.assertEqual(p.remaining(now=230.0), 40)
        self.assertEqual(p.update(now=270.0), "focus_done")

    def test_cancel_returns_to_idle(self):
        p = Pomodoro()
        p.start(now=0.0)
        p.cancel()
        self.assertEqual(p.state, "idle")
        self.assertIsNone(p.update(now=9999.0))
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** `petkit/pomodoro.py` using an end-time model:

```python
"""Focus/Pomodoro timer state machine. The clock is injected (monotonic
seconds) so the logic is pure and unit-testable."""


class Pomodoro:
    def __init__(self, focus_s=1500, break_s=300):
        self.focus_s = focus_s
        self.break_s = break_s
        self.state = "idle"
        self._end = 0.0
        self._paused_remaining = 0.0
        self._paused_phase = "idle"

    def start(self, now):
        self.state = "focus"
        self._end = now + self.focus_s

    def pause(self, now):
        if self.state in ("focus", "break"):
            self._paused_remaining = max(0.0, self._end - now)
            self._paused_phase = self.state
            self.state = "paused"

    def resume(self, now):
        if self.state == "paused":
            self.state = self._paused_phase
            self._end = now + self._paused_remaining

    def cancel(self):
        self.state = "idle"

    def update(self, now):
        if self.state == "focus" and now >= self._end:
            self.state = "break"
            self._end = now + self.break_s
            return "focus_done"
        if self.state == "break" and now >= self._end:
            self.state = "idle"
            return "break_done"
        return None

    def remaining(self, now):
        if self.state == "paused":
            return self._paused_remaining
        if self.state in ("focus", "break"):
            return max(0.0, self._end - now)
        return 0
```

- [ ] **Step 4: Run, watch pass. Commit** `feat: add Pomodoro focus-timer state machine`.

---

### Task 2: Reminders — parse + persist (petkit/reminders.py)

**Files:**
- Create: `petkit/reminders.py`
- Test: `tests/test_reminders.py`

**Interfaces:**
- Produces: `parse_reminder(text, now_epoch) -> (message:str, due_epoch:int) | None` (relative `"in 1h30"/"in 20m"/"in 45s"` or absolute `"at 3pm"/"at 15:00"`); and `Reminders(path)` with `.add(text, due_epoch)`, `.pending() -> list[{"text","due"}]` (sorted by due), `.due(now_epoch) -> list[str]` (returns + removes fired ones, persisting), `.cancel(text)`. Missing/corrupt file → empty, never raises.

- [ ] **Step 1: Write failing tests** `tests/test_reminders.py`:

```python
import os
import tempfile
import time
import unittest
from petkit.reminders import parse_reminder, Reminders


class TestParse(unittest.TestCase):
    def test_relative_minutes(self):
        msg, due = parse_reminder("remind me to drink water in 20m", now_epoch=1000)
        self.assertEqual(msg, "drink water")
        self.assertEqual(due, 1000 + 20 * 60)

    def test_relative_hours_minutes(self):
        msg, due = parse_reminder("in 1h30 stretch", now_epoch=0)
        self.assertEqual(due, 90 * 60)

    def test_relative_seconds(self):
        _msg, due = parse_reminder("ping in 45s", now_epoch=10)
        self.assertEqual(due, 55)

    def test_absolute_clock_is_in_the_future_at_that_hour(self):
        now = time.mktime((2026, 6, 25, 9, 0, 0, 0, 0, -1))   # 09:00 local
        msg, due = parse_reminder("call mom at 3pm", now_epoch=now)
        self.assertEqual(msg, "call mom")
        self.assertGreater(due, now)
        self.assertEqual(time.localtime(due).tm_hour, 15)

    def test_absolute_rolls_to_tomorrow_when_past(self):
        now = time.mktime((2026, 6, 25, 18, 0, 0, 0, 0, -1))  # 18:00 local
        _msg, due = parse_reminder("standup at 9am", now_epoch=now)
        self.assertGreater(due, now)
        self.assertEqual(time.localtime(due).tm_hour, 9)

    def test_no_time_phrase_returns_none(self):
        self.assertIsNone(parse_reminder("just some text", now_epoch=0))


class TestStore(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.path)   # start with no file

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_missing_file_is_empty(self):
        self.assertEqual(Reminders(self.path).pending(), [])

    def test_add_persists_and_reloads(self):
        Reminders(self.path).add("water", 5000)
        self.assertEqual(Reminders(self.path).pending(),
                         [{"text": "water", "due": 5000}])

    def test_due_fires_and_removes(self):
        r = Reminders(self.path)
        r.add("a", 100)
        r.add("b", 300)
        self.assertEqual(r.due(now_epoch=200), ["a"])
        self.assertEqual(r.pending(), [{"text": "b", "due": 300}])
        self.assertEqual(Reminders(self.path).pending(),   # persisted
                         [{"text": "b", "due": 300}])

    def test_corrupt_file_is_empty(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(Reminders(self.path).pending(), [])
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** `petkit/reminders.py`:

```python
"""Reminder parsing (relative/absolute natural-language) and an atomic-write
JSON store. Parsing is a pure function of the injected now_epoch."""
import json
import os
import re
import tempfile
import time


def _parse_delay(low):
    m = re.search(r"\bin\s+(\d+)\s*h(?:ours?)?(?:\s*(\d+)\s*m(?:in)?)?\b", low)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2) or 0) * 60
    m = re.search(r"\bin\s+(\d+)\s*m(?:in(?:utes?)?)?\b", low)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r"\bin\s+(\d+)\s*s(?:ec(?:onds?)?)?\b", low)
    if m:
        return int(m.group(1))
    return None


def _parse_clock(low, now_epoch):
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", low)
    if not m:
        return None
    h, mnt, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    lt = list(time.localtime(now_epoch))
    lt[3], lt[4], lt[5] = h, mnt, 0
    due = time.mktime(time.struct_time(tuple(lt)))
    if due <= now_epoch:
        due += 86400
    return due


_TIME_PHRASE = re.compile(
    r"\b(in\s+\d+\s*h(?:ours?)?(?:\s*\d+\s*m(?:in)?)?"
    r"|in\s+\d+\s*m(?:in(?:utes?)?)?|in\s+\d+\s*s(?:ec(?:onds?)?)?"
    r"|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", re.I)


def parse_reminder(text, now_epoch):
    low = text.lower()
    delay = _parse_delay(low)
    due = now_epoch + delay if delay is not None else _parse_clock(low, now_epoch)
    if due is None:
        return None
    msg = re.sub(r"^\s*remind me(?:\s+to)?\s+", "", text, flags=re.I)
    msg = _TIME_PHRASE.sub("", msg).strip(" ,").strip()
    return (msg or "Reminder", int(due))


class Reminders:
    def __init__(self, path):
        self.path = path
        self._items = self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for it in data:
            if (isinstance(it, dict) and isinstance(it.get("text"), str)
                    and isinstance(it.get("due"), (int, float))
                    and not isinstance(it.get("due"), bool)):
                out.append({"text": it["text"], "due": int(it["due"])})
        return out

    def _save(self):
        directory = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._items, f, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def add(self, text, due_epoch):
        self._items.append({"text": text, "due": int(due_epoch)})
        self._save()

    def pending(self):
        return [dict(i) for i in sorted(self._items, key=lambda i: i["due"])]

    def due(self, now_epoch):
        fired = [i for i in self._items if i["due"] <= now_epoch]
        if fired:
            self._items = [i for i in self._items if i["due"] > now_epoch]
            self._save()
        return [i["text"] for i in sorted(fired, key=lambda i: i["due"])]

    def cancel(self, text):
        before = len(self._items)
        self._items = [i for i in self._items if i["text"] != text]
        if len(self._items) != before:
            self._save()
```

- [ ] **Step 4: Run, watch pass. Commit** `feat: add reminder parsing + atomic JSON store`.

---

### Task 3: Break / posture nudges (petkit/nudges.py)

**Files:**
- Create: `petkit/nudges.py`
- Test: `tests/test_nudges.py`

**Interfaces:**
- Produces: `NudgeScheduler(interval_s=3000, away_ms=60000)` with `.update(idle_ms, now) -> bool` (True exactly when a nudge is due) and `.snooze(now, secs=300)`. Accumulates only *active* wall-time (when `idle_ms < away_ms`); time spent away does not count and never triggers a nudge on return.

- [ ] **Step 1: Write failing tests** `tests/test_nudges.py`:

```python
import unittest
from petkit.nudges import NudgeScheduler


class TestNudgeScheduler(unittest.TestCase):
    def test_fires_after_active_interval(self):
        n = NudgeScheduler(interval_s=100, away_ms=60000)
        n.update(0, now=0.0)                      # baseline
        self.assertFalse(n.update(0, now=50.0))
        self.assertTrue(n.update(0, now=100.0))   # 100s of active time

    def test_idle_time_does_not_count(self):
        n = NudgeScheduler(interval_s=100, away_ms=60000)
        n.update(0, now=0.0)
        self.assertFalse(n.update(90000, now=80.0))   # away: 80s not counted
        self.assertFalse(n.update(0, now=120.0))      # only 40s active so far
        self.assertTrue(n.update(0, now=180.0))       # now 100s active

    def test_snooze_delays_next(self):
        n = NudgeScheduler(interval_s=100, away_ms=60000)
        n.update(0, now=0.0)
        self.assertTrue(n.update(0, now=100.0))
        n.snooze(now=100.0, secs=200)
        self.assertFalse(n.update(0, now=150.0))
        self.assertTrue(n.update(0, now=300.0))

    def test_only_fires_once_per_interval(self):
        n = NudgeScheduler(interval_s=100, away_ms=60000)
        n.update(0, now=0.0)
        self.assertTrue(n.update(0, now=100.0))
        self.assertFalse(n.update(0, now=120.0))
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** `petkit/nudges.py`:

```python
"""Activity-gated break-nudge scheduler. Accumulates only active wall-time
(idle below the away threshold). All time values are injected."""


class NudgeScheduler:
    def __init__(self, interval_s=3000, away_ms=60000):
        self.interval_s = interval_s
        self.away_ms = away_ms
        self._last_now = None
        self._active = 0.0
        self._snooze_until = 0.0

    def update(self, idle_ms, now):
        if self._last_now is None:
            self._last_now = now
            return False
        dt = max(0.0, now - self._last_now)
        self._last_now = now
        if idle_ms < self.away_ms:
            self._active += dt
        if self._active >= self.interval_s and now >= self._snooze_until:
            self._active = 0.0
            return True
        return False

    def snooze(self, now, secs=300):
        self._active = 0.0
        self._snooze_until = now + secs
```

- [ ] **Step 4: Run, watch pass. Commit** `feat: add activity-gated break-nudge scheduler`.

---

### Task 4: Clipboard quick-actions (petkit/clip_actions.py)

**Files:**
- Create: `petkit/clip_actions.py`
- Test: `tests/test_clip_actions.py`

**Interfaces:**
- Produces: `analyze(text) -> dict | None` returning `{"kind":"math","result":str}`, `{"kind":"url","url":str}`, `{"kind":"color","hex":str}`, or `None`. Math uses a whitelisted-`ast` evaluator (numbers, `+ - * / // % **`, unary `+/-`, parentheses only); anything else (names, calls, attributes, division by zero) yields `None`.

- [ ] **Step 1: Write failing tests** `tests/test_clip_actions.py`:

```python
import unittest
from petkit.clip_actions import analyze, safe_eval


class TestSafeEval(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(safe_eval("2+3*4"), 14)
        self.assertEqual(safe_eval("(1+2)/3"), 1.0)
        self.assertEqual(safe_eval("2**10"), 1024)

    def test_rejects_names_and_calls(self):
        self.assertIsNone(safe_eval("__import__('os')"))
        self.assertIsNone(safe_eval("open('x')"))
        self.assertIsNone(safe_eval("a+1"))

    def test_rejects_div_by_zero_and_garbage(self):
        self.assertIsNone(safe_eval("1/0"))
        self.assertIsNone(safe_eval("not an expression"))


class TestAnalyze(unittest.TestCase):
    def test_math(self):
        self.assertEqual(analyze("2 + 2"), {"kind": "math", "result": "4"})

    def test_url(self):
        self.assertEqual(analyze("https://example.com/x"),
                         {"kind": "url", "url": "https://example.com/x"})

    def test_hex_color(self):
        self.assertEqual(analyze("#ff8800"), {"kind": "color", "hex": "#ff8800"})
        self.assertEqual(analyze("aabbcc"), {"kind": "color", "hex": "#aabbcc"})

    def test_plain_text_is_none(self):
        self.assertIsNone(analyze("hello world"))

    def test_blank_is_none(self):
        self.assertIsNone(analyze("   "))
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** `petkit/clip_actions.py`:

```python
"""Read-only clipboard quick-actions: detect a safe arithmetic expression, an
http(s) URL, or a hex color. The math evaluator whitelists ast nodes so no
names/calls/attributes can execute."""
import ast
import re
import operator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_URL_RE = re.compile(r"^https?://\S+$", re.I)
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("non-numeric constant")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    raise ValueError("disallowed expression")


def safe_eval(text):
    try:
        tree = ast.parse(text.strip(), mode="eval")
        return _eval(tree)
    except Exception:
        return None


def _fmt(n):
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n)


def analyze(text):
    s = (text or "").strip()
    if not s:
        return None
    if _URL_RE.match(s):
        return {"kind": "url", "url": s}
    m = _HEX_RE.match(s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return {"kind": "color", "hex": "#" + h.lower()}
    val = safe_eval(s)
    if val is not None and re.search(r"[-+*/%()]|\*\*", s):
        return {"kind": "math", "result": _fmt(val)}
    return None
```

(Note: the `re.search` guard means a bare number like `"42"` is *not* treated as math — an operator must be present — so copying a plain integer doesn't pop a useless bubble.)

- [ ] **Step 4: Run, watch pass. Commit** `feat: add clipboard quick-action analyzer (safe math/url/color)`.

---

### Task 5: Foreground-app probe + focus tally (winkit/apps.py, petkit/focus_tracker.py)

**Files:**
- Create: `winkit/apps.py` (Win32 probe), `petkit/focus_tracker.py` (pure tally)
- Test: `tests/test_focus_tracker.py` (pure), `tests/test_winkit_system.py` (append a Windows smoke test)

**Interfaces:**
- Produces: `winkit.apps.foreground_app_name() -> str` (basename of the foreground window's process, e.g. `"chrome"`, fallback to the window title, `""` if none); `petkit.focus_tracker.FocusTally()` with `.sample(app, now)` (accrue dwell to the previous app, switch current) and `.top(n=3, now=None) -> list[(app, seconds)]` (descending; includes the current app's in-progress dwell when `now` is given).

- [ ] **Step 1: Write failing pure tests** `tests/test_focus_tracker.py`:

```python
import unittest
from petkit.focus_tracker import FocusTally


class TestFocusTally(unittest.TestCase):
    def test_accumulates_dwell_per_app(self):
        t = FocusTally()
        t.sample("code", now=0)
        t.sample("chrome", now=30)      # 30s on code
        t.sample("code", now=40)        # 10s on chrome
        top = dict(t.top(now=60))       # +20s on code in progress
        self.assertEqual(top["code"], 50)
        self.assertEqual(top["chrome"], 10)

    def test_top_is_sorted_and_limited(self):
        t = FocusTally()
        t.sample("a", now=0)
        t.sample("b", now=100)
        t.sample("c", now=110)
        t.sample(None, now=160)         # close out c (50s)
        top = t.top(n=2)
        self.assertEqual([app for app, _ in top], ["a", "c"])

    def test_empty_top_is_empty(self):
        self.assertEqual(FocusTally().top(), [])
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** `petkit/focus_tracker.py`:

```python
"""Pure per-app foreground-dwell tally. Sample (app, now) snapshots; dwell time
is accrued to whichever app was foreground between consecutive samples."""


class FocusTally:
    def __init__(self):
        self._totals = {}
        self._cur = None
        self._since = None

    def _accrue(self, now):
        if self._cur and self._since is not None:
            self._totals[self._cur] = self._totals.get(self._cur, 0) + max(0, now - self._since)

    def sample(self, app, now):
        self._accrue(now)
        self._cur = app
        self._since = now

    def top(self, n=3, now=None):
        totals = dict(self._totals)
        if now is not None and self._cur and self._since is not None:
            totals[self._cur] = totals.get(self._cur, 0) + max(0, now - self._since)
        return sorted(totals.items(), key=lambda kv: -kv[1])[:n]
```

- [ ] **Step 4: Implement** `winkit/apps.py` (Win32 — follow the `winkit/input.py` ctypes idiom):

```python
"""Foreground-window app-name probe (Win32). Returns a short, stable app name
for the currently-focused window, for the pet's focus tracker."""
import ctypes
import os
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _process_name(pid):
    h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.splitext(os.path.basename(buf.value))[0]
        return ""
    finally:
        _kernel32.CloseHandle(h)


def foreground_app_name():
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = _process_name(pid.value) if pid.value else ""
    if name:
        return name
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value
```

- [ ] **Step 5: Add the Windows smoke test** to `tests/test_winkit_system.py` (new class):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestApps(unittest.TestCase):
    def test_foreground_app_name_is_str(self):
        import winkit.apps as A
        name = A.foreground_app_name()
        self.assertIsInstance(name, str)
```

- [ ] **Step 6: Run the full suite, watch pass. Commit** `feat: add foreground-app probe + pure focus tally`.

---

### Task 6: Wire focus timer + reminders into pet.pyw

**Files:**
- Modify: `pet.pyw` (imports, `Cat.__init__`, `tick`, menu builder; add a reminder entry dialog), `config.py` (`DEFAULTS["pet"]`)
- Test: `tests/test_config.py` (new pet defaults present), `tests/test_smoke_pet.py` (still green)

**Config additions** — extend `DEFAULTS["pet"]`:

```python
    "focus_min": 25, "break_min": 5,
    "reminders": True,
```

- [ ] **Step 1: Config test first** — assert `config.defaults()["pet"]` has `focus_min`/`break_min` (ints) and `reminders` (bool). Run→fail, add keys, run→pass. Commit `feat: add focus/reminder pet config defaults`.

- [ ] **Step 2: Construct objects** in `Cat.__init__`: `import petkit.pomodoro as pomodoro`, `import petkit.reminders as reminders`. Build `self.pomodoro = pomodoro.Pomodoro(focus_s=pet["focus_min"]*60, break_s=pet["break_min"]*60)`, `self.reminders = reminders.Reminders(os.path.join(HERE, "reminders.json"))`, and a low-rate reminder cursor `self._next_reminder_check = 0.0`.

- [ ] **Step 3: Tick integration** (in `tick`, after the nap/greeter block, all guarded by `not napping` where it makes sense for visuals but timers run regardless):
  - `ev = self.pomodoro.update(now)`; if `ev == "focus_done"`: `self.bubble.say("Break time! 🐾", secs=4, chime=True)`; if `ev == "break_done"`: `self.bubble.say("Back to it? 🐱", secs=4, chime=True)`.
  - Reminders, low-rate: `if pet.get("reminders", True) and now >= self._next_reminder_check: self._next_reminder_check = now + 5.0; for text in self.reminders.due(time.time()): self.bubble.say("⏰ " + text, secs=5, chime=True)`.
  - Keep the cat "active" (so it doesn't drop to idle fps) while a focus timer is running, so the bubble/chime fire promptly: add `or self.pomodoro.state in ("focus", "break")` to the `active` predicate.

- [ ] **Step 4: Menu additions** — in `_on_right_click`, above the ability toggles, add a focus section:
  - `m.add_command(label="Focus %d min" % pet["focus_min"], command=self._start_focus)` where `_start_focus` calls `self.pomodoro.start(time.monotonic())` and `self.bubble.say("Focus on 🐾", secs=2)`.
  - When `self.pomodoro.state != "idle"`, instead show `m.add_command(label="Stop focus (%d:%02d left)" % divmod(int(self.pomodoro.remaining(time.monotonic())), 60), command=self._stop_focus)` (`_stop_focus` → `self.pomodoro.cancel()`).
  - `m.add_command(label="Add reminder…", command=self._add_reminder_dialog)`.
  - keep `reminders` as a checkbutton in the toggle loop too (extend the existing tuple with `("reminders", "Reminders")`).

- [ ] **Step 5: Reminder dialog** — `_add_reminder_dialog` opens a tiny `Toplevel` (not click-through) with a `tk.Entry` and an OK button; on submit, `parsed = reminders.parse_reminder(entry_text, time.time())`; if `parsed`: `self.reminders.add(*parsed)` and `self.bubble.say("Reminder set 🐾", secs=2)`; else `self.bubble.say("Couldn't read a time 😿", secs=3)`. Destroy the dialog on submit/escape. (Bind `<Return>` to submit, `<Escape>` to cancel; place it near the cat.)

- [ ] **Step 6: Smoke** — run `tests/test_smoke_pet.py` (constructs the Cat, now with pomodoro/reminders) and the full suite. Green. Ensure `reminders.json` is gitignored (add to `.gitignore`).

- [ ] **Step 7: Commit** `feat: wire focus timer + reminders (menu, dialog, low-rate timer) into the cat`.

---

### Task 7: Wire nudges + clip-actions + focus-tracker into pet.pyw

**Files:**
- Modify: `pet.pyw` (imports, `Cat.__init__`, `tick`, menu), `config.py` (`DEFAULTS["pet"]`)
- Test: `tests/test_config.py`, `tests/test_smoke_pet.py`

**Config additions** — extend `DEFAULTS["pet"]`:

```python
    "nudges": True, "nudge_min": 50,
    "clip_actions": True, "focus_tracker": True,
```

- [ ] **Step 1: Config test first** — assert the four new keys exist with correct types. Run→fail, add, run→pass. Commit `feat: add nudge/clip/focus-tracker config defaults`.

- [ ] **Step 2: Construct objects** in `Cat.__init__`: `import petkit.nudges as nudges`, `import petkit.clip_actions as clip_actions`, `import petkit.focus_tracker as focus_tracker`, `import winkit.apps as apps`. Build `self.nudger = nudges.NudgeScheduler(interval_s=pet["nudge_min"]*60)`, `self.tally = focus_tracker.FocusTally()`, `self._clip_seq = wkinput.clipboard_sequence()`, `self._next_focus_sample = 0.0`. (Import `apps`/`clip_actions`/`focus_tracker` lazily-safe: top-level import is fine, they're stdlib-only.)

- [ ] **Step 3: Tick integration:**
  - Nudges: `if pet.get("nudges", True) and self.nudger.update(idle, now): self.bubble.say("Stretch break? 🐱", secs=4, chime=True)` (reuse the `idle` already probed for the nap cycle — no second `idle_ms()` call).
  - Clipboard quick-actions: `if pet.get("clip_actions", True): seq = wkinput.clipboard_sequence(); if seq != self._clip_seq: self._clip_seq = seq; try: txt = self.root.clipboard_get() except tk.TclError: txt = ""; act = clip_actions.analyze(txt); if act: self._show_clip_action(act)`. `_show_clip_action` bubbles `"= result"`, `"open link?"`, or `"🎨 hex"` accordingly (math/url/color). (Keep it a passive bubble; no auto-open.)
  - Focus tracker, low-rate: `if pet.get("focus_tracker", True) and now >= self._next_focus_sample: self._next_focus_sample = now + 3.0; self.tally.sample(apps.foreground_app_name(), now)`.

- [ ] **Step 4: Menu additions** — extend the toggle tuple with `("nudges","Break nudges")`, `("clip_actions","Clipboard helper")`, `("focus_tracker","Track app focus")`. Add `m.add_command(label="Today's apps…", command=self._show_top_apps)` where `_show_top_apps` bubbles the top 3 from `self.tally.top(3, now=time.monotonic())` (e.g. `"code 42m · chrome 18m"`), or `"No app data yet"` if empty.

- [ ] **Step 5: Smoke + full suite** — run `tests/test_smoke_pet.py` and the whole suite; all green.

- [ ] **Step 6: Commit** `feat: wire break nudges, clipboard helper, app-focus tracker into the cat`.

---

## Self-Review Notes

- Spec coverage: Pomodoro (T1, T6), Reminders (T2, T6), Nudges (T3, T7), Clipboard quick-actions (T4, T7), App-focus tracker (T5, T7). All Phase 3 spec items covered.
- Type consistency: `Pomodoro.update/remaining/start/pause/resume`, `Reminders.due/add/pending`, `NudgeScheduler.update/snooze`, `clip_actions.analyze`, `FocusTally.sample/top`, `apps.foreground_app_name` — signatures match between producing tasks (T1–T5) and the wiring call sites (T6–T7).
- Purity: `petkit/pomodoro.py`, `petkit/nudges.py`, `petkit/focus_tracker.py`, `petkit/clip_actions.py` and `parse_reminder` take injected values / are pure functions; the only wall-clock reads are in `pet.pyw` (the wiring layer). The only new Win32 calls are isolated in `winkit/apps.py`.
- Lightweight: reminders poll ≤1/5s, focus sample ~1/3s, clipboard rides the sequence number (zero cost when idle); per-frame cost unchanged.
- `reminders.json` is runtime state → gitignore it (Task 6 Step 6).
