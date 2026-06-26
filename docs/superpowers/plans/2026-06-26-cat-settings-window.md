# Cat Settings Window + Menu Declutter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slim the cat's right-click menu down to actions, move all on/off toggles into a dedicated `ttk.Notebook` Settings window (Focus / Reminders / Pin / More), give the focus timer + reminders + window-pin real GUI/config, and make pinning cat-driven (pin the window under the cat) while keeping the cat above pinned windows.

**Architecture:** Pure logic (reminder field→epoch math, due formatting, precise removal) extends `petkit/reminders.py` and is unit-tested. Win32 glue (`window_below`, `window_title`) extends `winkit/window.py`. The Settings window is a new `petkit/settings.py` GUI module (one Toplevel, one Notebook, four tab-builders) wired to the existing `Cat` via small support methods. `pet.pyw` loses the hotkey-driven pin path and the in-menu checkbuttons; the menu is rebuilt slim.

**Tech Stack:** Python 3.12 stdlib only — `tkinter` + `tkinter.ttk` + `ctypes` + `winsound`. Tests: `unittest`.

## Global Constraints

- **Pure stdlib only. No third-party / pip packages, ever.**
- Win32 lives in `winkit/`; pet feature logic + its GUI pieces live in `petkit/` (precedent: `petkit/bubble.py`).
- Pure logic takes injected clock/now values (no `time.monotonic()`/`time.time()` *inside* pure functions) so it is deterministic and cross-platform testable.
- TDD: write the failing test first, watch it fail, minimal code to pass.
- Test runner (bare `python` is a MS-Store stub → exit 49); use the full interpreter path:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`
- `ttk.Notebook` is allowed (it is part of stdlib `tkinter.ttk`); the rest of the window uses plain `tk` widgets to match the codebase.
- No new `config.json` keys. **Remove** the now-unused `pin_hotkey` key. Reuse `focus_min`, `break_min`, `reminders`, `pin`, `petting`, `catnap`, `greeter`, `nudges`, `carry`.
- Commit after each task. End commit messages with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

**Shorthand used below:** `PY` = `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`. Run all commands from the repo root `C:/Users/Warren/Toybox`.

## File Structure

```
petkit/reminders.py    # EXTEND: due_from_fields(), format_due() (pure); Reminders.remove()
winkit/window.py       # EXTEND: window_below(hwnd), window_title(hwnd)
pet.pyw                # Cat support methods (_save_cfg/_set_cfg_flag/_set_focus_minutes/
                       #   _pin_under_cat), pin redesign (no hotkey, cat-stays-on-top),
                       #   then (Task 5) slim _build_menu + Settings wiring
petkit/settings.py     # NEW: SettingsWindow (Toplevel + ttk.Notebook; 4 tab builders)
config.py              # remove "pin_hotkey"
tests/test_reminders.py     # EXTEND: due_from_fields / format_due / remove
tests/test_winkit_system.py # EXTEND: window_below / window_title smoke (Windows-only)
tests/test_config.py        # update phase4 defaults test (pin_hotkey gone)
tests/test_smoke_pet.py     # update pin/carry wiring test; add slim-menu structure test
tests/test_smoke_settings.py# NEW: GUI smoke for SettingsWindow (Windows-only)
```

---

### Task 1: Reminders — structured-field math, due formatting, precise remove

**Files:**
- Modify: `petkit/reminders.py`
- Test: `tests/test_reminders.py`

**Interfaces:**
- Consumes: nothing new (extends an existing module).
- Produces:
  - `due_from_fields(mode, amount, unit, hh, mm, now_epoch) -> int | None` — `mode="in"`: `int(now_epoch) + amount * {"sec":1,"min":60,"hours":3600}[unit]` (amount coerced via `int`, must be ≥ 0, unit must be known). `mode="at"`: today at `hh:mm` (24h, validated `0≤hh≤23`, `0≤mm≤59`), rolled +86400 if already ≤ now. Anything else → `None`.
  - `format_due(due_epoch, now_epoch) -> str` — e.g. `"4:12pm"`, `"12:05am"`; `"tomorrow 4:12pm"` when due is the next calendar day; `"<Wkday> 4:12pm"` otherwise.
  - `Reminders.remove(text, due) -> None` — deletes the single pending item matching both `text` and `int(due)`; atomic save; no-op if absent.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_reminders.py`. Ensure the imports at the top of the file include `import os`, `import time`, `import tempfile`, `import shutil`, `import unittest`, `import petkit.reminders as reminders` (add any that are missing). Append these classes:

```python
class TestDueFromFields(unittest.TestCase):
    def test_in_minutes(self):
        self.assertEqual(reminders.due_from_fields("in", 20, "min", 0, 0, 1000), 1000 + 1200)

    def test_in_hours(self):
        self.assertEqual(reminders.due_from_fields("in", 2, "hours", 0, 0, 1000), 1000 + 7200)

    def test_in_string_amount_coerced(self):
        self.assertEqual(reminders.due_from_fields("in", "15", "min", 0, 0, 0), 900)

    def test_in_negative_is_none(self):
        self.assertIsNone(reminders.due_from_fields("in", -5, "min", 0, 0, 0))

    def test_in_bad_unit_is_none(self):
        self.assertIsNone(reminders.due_from_fields("in", 5, "weeks", 0, 0, 0))

    def test_at_later_today(self):
        base = list(time.localtime()); base[3], base[4], base[5] = 8, 0, 0
        now = time.mktime(time.struct_time(tuple(base)))   # 8:00 local today
        due = reminders.due_from_fields("at", 0, "min", 23, 30, now)
        self.assertGreater(due, now)
        self.assertLessEqual(due - now, 24 * 3600)
        lt = time.localtime(due)
        self.assertEqual((lt.tm_hour, lt.tm_min), (23, 30))

    def test_at_already_past_rolls_to_tomorrow(self):
        base = list(time.localtime()); base[3], base[4], base[5] = 23, 0, 0
        now = time.mktime(time.struct_time(tuple(base)))   # 23:00 local today
        due = reminders.due_from_fields("at", 0, "min", 9, 0, now)   # 9am already passed
        self.assertGreater(due - now, 3600)
        self.assertLessEqual(due - now, 24 * 3600)

    def test_at_invalid_hour_is_none(self):
        self.assertIsNone(reminders.due_from_fields("at", 0, "min", 99, 0, 1000))

    def test_unknown_mode_is_none(self):
        self.assertIsNone(reminders.due_from_fields("nope", 0, "min", 0, 0, 1000))


class TestFormatDue(unittest.TestCase):
    def _at(self, h, m):
        base = list(time.localtime()); base[3], base[4], base[5] = h, m, 0
        return time.mktime(time.struct_time(tuple(base)))

    def test_same_day_pm(self):
        now = self._at(16, 12)
        self.assertEqual(reminders.format_due(now, now - 60), "4:12pm")

    def test_midnight_is_12am(self):
        now = self._at(0, 5)
        self.assertEqual(reminders.format_due(now, now - 60), "12:05am")

    def test_noon_is_12pm(self):
        now = self._at(12, 0)
        self.assertEqual(reminders.format_due(now, now - 60), "12:00pm")

    def test_next_day_is_prefixed(self):
        now = self._at(9, 0)
        s = reminders.format_due(now + 24 * 3600, now)
        self.assertTrue(s.startswith("tomorrow ") or s[:3].isalpha())  # not a bare clock


class TestReminderRemove(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.path = os.path.join(self.dir, "r.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_remove_one_of_same_text(self):
        r = reminders.Reminders(self.path)
        r.add("ping", 1000); r.add("ping", 2000)
        r.remove("ping", 1000)
        self.assertEqual([(i["text"], i["due"]) for i in r.pending()], [("ping", 2000)])

    def test_remove_persists(self):
        r = reminders.Reminders(self.path)
        r.add("ping", 1000); r.add("ping", 2000)
        r.remove("ping", 1000)
        self.assertEqual(len(reminders.Reminders(self.path).pending()), 1)  # reloaded from disk

    def test_remove_absent_is_noop(self):
        r = reminders.Reminders(self.path)
        r.add("ping", 1000)
        r.remove("ping", 9999)
        self.assertEqual(len(r.pending()), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PY -m unittest tests.test_reminders -v`
Expected: FAIL/ERROR — `module 'petkit.reminders' has no attribute 'due_from_fields'` (and `format_due`), `Reminders` object has no attribute `remove`.

- [ ] **Step 3: Implement the helpers**

In `petkit/reminders.py`, add the module-level constant + functions (place after `parse_reminder`, before `class Reminders`):

```python
_UNIT_SECONDS = {"sec": 1, "min": 60, "hours": 3600}


def due_from_fields(mode, amount, unit, hh, mm, now_epoch):
    """Compute a reminder due-epoch from the Settings tab's structured fields. Pure.

    mode="in": now_epoch + amount * unit-seconds (unit in 'sec'|'min'|'hours'); amount >= 0.
    mode="at": today at hh:mm (24h), rolled to tomorrow if already <= now_epoch.
    Returns an int epoch, or None on invalid input."""
    if mode == "in":
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return None
        if amount < 0 or unit not in _UNIT_SECONDS:
            return None
        return int(now_epoch) + amount * _UNIT_SECONDS[unit]
    if mode == "at":
        try:
            hh, mm = int(hh), int(mm)
        except (TypeError, ValueError):
            return None
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        lt = list(time.localtime(now_epoch))
        lt[3], lt[4], lt[5] = hh, mm, 0
        try:
            due = time.mktime(time.struct_time(tuple(lt)))
        except (OverflowError, ValueError):
            return None
        if due <= now_epoch:
            due += 86400
        return int(due)
    return None


def format_due(due_epoch, now_epoch):
    """Human-friendly fire time, e.g. '4:12pm'. Prefixes 'tomorrow ' for the next
    calendar day and the weekday abbrev for any later day. Pure (localtime of an
    injected epoch)."""
    due = time.localtime(int(due_epoch))
    h = due.tm_hour % 12 or 12
    ap = "am" if due.tm_hour < 12 else "pm"
    clock = "%d:%02d%s" % (h, due.tm_min, ap)
    now = time.localtime(int(now_epoch))
    if (due.tm_year, due.tm_yday) == (now.tm_year, now.tm_yday):
        return clock
    nxt = time.localtime(int(now_epoch) + 86400)
    if (due.tm_year, due.tm_yday) == (nxt.tm_year, nxt.tm_yday):
        return "tomorrow " + clock
    return time.strftime("%a", due) + " " + clock
```

And add this method to `class Reminders` (next to `cancel`):

```python
    def remove(self, text, due):
        """Remove the single pending item matching both text and due epoch."""
        due = int(due)
        for i, it in enumerate(self._items):
            if it["text"] == text and int(it["due"]) == due:
                del self._items[i]
                self._save()
                return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PY -m unittest tests.test_reminders -v`
Expected: PASS (all new tests green; existing reminder tests still pass).

- [ ] **Step 5: Commit**

```bash
git add petkit/reminders.py tests/test_reminders.py
git commit -m "Add structured reminder helpers (due_from_fields/format_due) + precise remove"
```

---

### Task 2: Win32 helpers — window under the cat, window title

**Files:**
- Modify: `winkit/window.py`
- Test: `tests/test_winkit_system.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `window_below(hwnd) -> int` — root window directly beneath `hwnd` at its center; `0` for none/desktop/itself. Briefly sets `WS_EX_TRANSPARENT` on `hwnd` so `WindowFromPoint` passes through, restoring the style in a `finally`.
  - `window_title(hwnd) -> str` — `GetWindowTextW`, `""` on failure/empty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_winkit_system.py` (it already has `import os`, `import unittest`):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestWindowHelpers(unittest.TestCase):
    def test_window_title_is_str(self):
        import ctypes
        import winkit.window as W
        fg = ctypes.windll.user32.GetForegroundWindow()
        self.assertIsInstance(W.window_title(fg), str)

    def test_window_below_returns_int_and_restores_transparent(self):
        import tkinter as tk
        import winkit.window as W
        root = tk.Tk(); root.withdraw()
        root.geometry("80x80+150+150"); root.update()
        hwnd = W._hwnd_of(root)
        try:
            res = W.window_below(hwnd)
            self.assertIsInstance(res, int)
            style = int(W._get(hwnd, W.GWL_EXSTYLE) or 0)
            self.assertFalse(style & W.WS_EX_TRANSPARENT)   # probe restored the ex-style
        finally:
            root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PY -m unittest tests.test_winkit_system.TestWindowHelpers -v`
Expected: FAIL/ERROR — `module 'winkit.window' has no attribute 'window_title'` / `window_below`.

- [ ] **Step 3: Implement the helpers**

In `winkit/window.py`, add the ctypes prototypes (place right after the `GetAncestor` argtypes block, before the `WM_NULL = 0x0000` line — anywhere in the prototype section is fine):

```python
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetDesktopWindow.restype = wintypes.HWND
_user32.GetDesktopWindow.argtypes = []
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
```

Then add the two functions (place after `root_window_at`):

```python
def window_below(hwnd):
    """The root window directly beneath `hwnd` at its center point, or 0 if there
    is none, it resolves to the desktop, or it resolves back to `hwnd` itself.

    `hwnd` (e.g. the cat) is a hit-testable top-most overlay, so a plain
    WindowFromPoint at its center returns `hwnd`. Temporarily OR in
    WS_EX_TRANSPARENT so hit-testing passes through it, read what's underneath,
    then restore the original ex-style in a finally (never leave the cat
    click-through). Does not move or hide the window."""
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return 0
    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2
    style = int(_get(hwnd, GWL_EXSTYLE) or 0)
    had_transparent = bool(style & WS_EX_TRANSPARENT)
    if not had_transparent:
        _set(hwnd, GWL_EXSTYLE, ctypes.c_void_p(style | WS_EX_TRANSPARENT))
    try:
        found = _user32.WindowFromPoint(wintypes.POINT(cx, cy))
        if not found:
            return 0
        root = int(_user32.GetAncestor(found, GA_ROOT) or found)
    finally:
        if not had_transparent:
            cur = int(_get(hwnd, GWL_EXSTYLE) or 0)
            _set(hwnd, GWL_EXSTYLE, ctypes.c_void_p(cur & ~WS_EX_TRANSPARENT))
    if root == int(hwnd) or root == int(_user32.GetDesktopWindow() or 0):
        return 0
    return root


def window_title(hwnd):
    """The window's title text (GetWindowTextW), or '' on failure/empty."""
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    got = _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value if got else ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PY -m unittest tests.test_winkit_system.TestWindowHelpers -v`
Expected: PASS (both tests; this is Windows, so they run, not skip).

- [ ] **Step 5: Commit**

```bash
git add winkit/window.py tests/test_winkit_system.py
git commit -m "Add window_below() (window under the cat) and window_title()"
```

---

### Task 3: Cat support methods + Pin redesign (cat-driven, stays on top) + drop pin_hotkey

**Files:**
- Modify: `pet.pyw`
- Modify: `config.py`
- Test: `tests/test_config.py`, `tests/test_smoke_pet.py`

**Interfaces:**
- Consumes: `winkit.window.window_below` (Task 2), `winkit.window.set_topmost` (existing), `petkit.pins.PinSet.toggle/pinned/is_pinned/unpin_all` (existing), `petkit.pomodoro.Pomodoro.focus_s/break_s` (existing attrs).
- Produces (new `Cat` methods later tasks rely on):
  - `Cat._save_cfg() -> None` — `config.save(CFG_PATH, self.cfg)` swallowing exceptions.
  - `Cat._set_cfg_flag(key, value) -> None` — set a bool pet flag, run its side effect (`catnap`→`nap.reset()`+awake; `pin`→`_apply_pin_enabled()`; `carry`→`_apply_carry_enabled()`), keep any menu var in sync, then `_save_cfg()`.
  - `Cat._set_focus_minutes(focus_min, break_min) -> None` — write `focus_min`/`break_min`, update `self.pomodoro.focus_s/break_s`, `_save_cfg()`.
  - `Cat._pin_under_cat() -> None` — toggle pin on `window_below(self.hwnd)`; on pin, re-raise the cat top-most; bubble feedback.

- [ ] **Step 1: Write the failing tests**

In `tests/test_config.py`, **replace** `test_phase4_pin_carry_defaults_present` with:

```python
    def test_phase4_pin_carry_defaults_present(self):
        pet = config.defaults()["pet"]
        for key in ("pin", "carry"):
            self.assertIn(key, pet)
            self.assertIsInstance(pet[key], bool)
        self.assertNotIn("pin_hotkey", pet)   # hotkey removed; pinning is cat-driven now
```

In `tests/test_smoke_pet.py`, **replace** the `TestPetPhase4PinCarry` class with:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPetPinAndSupport(unittest.TestCase):
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

    def test_pin_and_support_methods(self):
        root, cat = self._make_cat()
        try:
            self.assertFalse(hasattr(cat, "pin_hotkey"))     # hotkey path removed
            self.assertTrue(hasattr(cat, "pinset"))
            # Carry still works.
            cat._on_files_dropped(["C:\\a.txt", "C:\\b.txt"])
            self.assertEqual(cat._held, ["C:\\a.txt", "C:\\b.txt"])
            cat._release_held()
            self.assertEqual(cat._held, [])
            # Cat-driven pin runs without crashing (no real window under the cat in CI).
            cat._pin_under_cat()
            # Focus minutes write through to the Pomodoro object + config.
            cat._set_focus_minutes(40, 8)
            self.assertEqual(cat.pomodoro.focus_s, 40 * 60)
            self.assertEqual(cat.pomodoro.break_s, 8 * 60)
            self.assertEqual(cat.cfg["pet"]["focus_min"], 40)
            # Flag setter applies + persists; disabling pin releases pins.
            cat._set_cfg_flag("pin", False)
            self.assertFalse(cat.cfg["pet"]["pin"])
            self.assertEqual(cat.pinset.pinned(), set())
            cat.tick()
            cat.close()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PY -m unittest tests.test_config.TestConfig.test_phase4_pin_carry_defaults_present tests.test_smoke_pet.TestPetPinAndSupport -v`
Expected: FAIL — config still has `pin_hotkey`; `Cat` has no `_set_focus_minutes`/`_set_cfg_flag`, still has `pin_hotkey` attribute.

- [ ] **Step 3a: Remove `pin_hotkey` from `config.py`**

In `config.py` `DEFAULTS["pet"]`, change the last pet line from:

```python
            "pin": True, "pin_hotkey": ["ctrl", "shift", "P"], "carry": True},
```

to:

```python
            "pin": True, "carry": True},
```

- [ ] **Step 3b: Edit `pet.pyw` — `__init__` pin/state block**

Replace the Phase-4 init block (currently lines ~143-153):

```python
        # Phase 4 "power-tools": Pin (hotkey toggles any window always-on-top) and
        # Catch & Carry (drop files on the cat; click to release as CF_HDROP).
        # Both event-driven (hotkey edge / WM_DROPFILES) -- no per-frame cost.
        self.hwnd = window._hwnd_of(root)
        self.pinset = pins.PinSet(window.set_topmost)
        self._held = []                   # files the cat is currently carrying
        self.pin_hotkey = None
        self.drop_target = None
        self._tick_after = None
        self._apply_pin_enabled()         # install the hotkey poller iff enabled
        self._apply_carry_enabled()       # install the drop target iff enabled
```

with:

```python
        # Phase 4 "power-tools": Pin (right-click the cat to pin the window under
        # it; the cat stays on top) and Catch & Carry (drop files on the cat;
        # click to release as CF_HDROP). Event-driven (menu / WM_DROPFILES).
        self.hwnd = window._hwnd_of(root)
        self.pinset = pins.PinSet(window.set_topmost)
        self._held = []                   # files the cat is currently carrying
        self.drop_target = None
        self._tick_after = None
        self._next_topmost = 0.0          # low-rate cat top-most re-assert cursor
        self._apply_pin_enabled()         # release pins if the feature is off
        self._apply_carry_enabled()       # install the drop target iff enabled
```

- [ ] **Step 3c: Edit `pet.pyw` — `_apply_pin_enabled`, remove `_toggle_pin`, add `_pin_under_cat`**

Replace `_apply_pin_enabled` (currently lines ~207-218) with:

```python
    def _apply_pin_enabled(self):
        """Pinning is driven from the right-click menu (the window under the cat),
        so there is no poller to install -- disabling the feature just releases
        whatever the cat is currently holding up."""
        if not self.cfg["pet"].get("pin", True):
            self.pinset.unpin_all()
```

Delete the entire `_toggle_pin` method (currently lines ~230-238). Add `_pin_under_cat` in its place:

```python
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
```

- [ ] **Step 3d: Edit `pet.pyw` — add support methods, refactor `_toggle_cfg`**

Replace `_toggle_cfg` (currently lines ~268-281) with these four methods:

```python
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
```

(`_menu_var` stays as-is for now; the menu checkbuttons still use it until Task 5 removes them.)

- [ ] **Step 3e: Edit `pet.pyw` — `tick` top-most re-assert**

In `tick`, immediately **after** the Break-nudges block (currently lines ~591-593) and **before** `try: self.draw(now)`, insert:

```python
        # Keep the cat above any window it has pinned: a pinned window the user
        # clicks would otherwise rise over it. Gated to when pins exist and
        # rate-limited to ~1/s; SWP_NOACTIVATE -> no focus theft, no flicker.
        if self.pinset.pinned() and now >= self._next_topmost:
            self._next_topmost = now + 1.0
            window.set_topmost(self.hwnd, True)
```

- [ ] **Step 3f: Edit `pet.pyw` — `close()` remove pin_hotkey teardown**

In `close`, delete this block (currently lines ~626-630):

```python
        try:
            if getattr(self, "pin_hotkey", None):
                self.pin_hotkey.stop()
        except Exception:
            pass
```

- [ ] **Step 4: Run the targeted tests, then the full suite**

Run: `PY -m unittest tests.test_config tests.test_smoke_pet -v`
Expected: PASS (the new `TestPetPinAndSupport` + the updated config test).

Run: `PY -m unittest discover -s tests -p "test_*.py"`
Expected: ends in `OK`. (`test_smoke_pet` launches `pet.pyw`, proving no import/wiring breakage; the menu still builds with its old checkbuttons — that's fine, Task 5 slims it.)

- [ ] **Step 5: Commit**

```bash
git add pet.pyw config.py tests/test_config.py tests/test_smoke_pet.py
git commit -m "Pin redesign: cat-driven pin, cat stays on top, drop the pin hotkey"
```

---

### Task 4: Settings window (`petkit/settings.py`) with Focus / Reminders / Pin / More tabs

**Files:**
- Create: `petkit/settings.py`
- Test: `tests/test_smoke_settings.py`

**Interfaces:**
- Consumes: a `Cat` exposing `root`, `cfg`, `pomodoro` (`state`, `remaining(now)`), `reminders` (`pending`, `add`, `remove`), `pinset` (`pinned`, `toggle`, `unpin_all`), and methods `_start_focus`, `_pause_focus`, `_resume_focus`, `_stop_focus`, `_set_focus_minutes`, `_set_cfg_flag`, `_pin_under_cat` (Task 3); plus `petkit.reminders.due_from_fields/format_due` (Task 1) and `winkit.window.window_title` (Task 2).
- Produces: `class SettingsWindow` with `open(tab=None)` and `close()`. `open` creates the Toplevel on first call and raises/selects on later calls (singleton). `tab` is one of `"Focus"`, `"Reminders"`, `"Pin"`, `"More"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_smoke_settings.py`:

```python
import os
import unittest


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestSettingsWindow(unittest.TestCase):
    def _make_cat(self):
        import tkinter as tk
        import winkit.window as window
        import config
        import pet as petmod
        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("%dx%d+120+120" % (petmod.WIN, petmod.WIN))
        canvas = tk.Canvas(root, width=petmod.WIN, height=petmod.WIN,
                           bg=window.KEY_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        root.update()
        return root, petmod.Cat(root, canvas, config.defaults())

    def test_open_build_all_tabs_and_close(self):
        import petkit.settings as settings
        root, cat = self._make_cat()
        try:
            win = settings.SettingsWindow(cat)
            win.open()
            self.assertIsNotNone(win.win)
            # Exercise the dynamic refresh paths with a pending reminder + the
            # focus-saver, none of which should raise.
            cat.reminders.add("ping", 9999999999)
            win._refresh_reminders()
            win._refresh_pins()
            win._focus_var.set("30"); win._break_var.set("7"); win._on_save_focus()
            self.assertEqual(cat.cfg["pet"]["focus_min"], 30)
            # Add via structured fields ("in 5 min").
            win._mode_var.set("in"); win._amount_var.set("5"); win._unit_var.set("min")
            win._msg_var.set("water"); win._on_add_reminder()
            self.assertTrue(any(i["text"] == "water" for i in cat.reminders.pending()))
            win.open("Pin")               # re-open selects a tab, no second window
            win.close()
            self.assertIsNone(win.win)
            win.open()                    # reopening recreates cleanly
            self.assertIsNotNone(win.win)
            win.close()
            cat.close()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PY -m unittest tests.test_smoke_settings -v`
Expected: FAIL/ERROR — `No module named 'petkit.settings'`.

- [ ] **Step 3: Implement `petkit/settings.py`**

Create `petkit/settings.py`:

```python
"""The cat's Settings window: a normal (titled, movable) Toplevel hosting a
ttk.Notebook with Focus / Reminders / Pin / More tabs. Built on demand and
reused as a singleton; reads/writes the live cfg and calls back into Cat for
actions. GUI glue only -- the testable logic lives in petkit.reminders and
winkit.window. Guards every after()/refresh against TclError like bubble.py."""
import time
import tkinter as tk
from tkinter import ttk

import petkit.reminders as reminders
import winkit.window as window

_MORE_TOGGLES = (
    ("petting", "Petting & purr"),
    ("catnap", "Box catnap"),
    ("greeter", "Welcome-back greeting"),
    ("nudges", "Break nudges"),
    ("carry", "Catch & carry files"),
)


class SettingsWindow:
    def __init__(self, cat):
        self.cat = cat
        self.win = None
        self._nb = None
        self._tabs = {}
        self._after = None

    # --- lifecycle ------------------------------------------------------
    def open(self, tab=None):
        if self.win is not None:
            try:
                self.win.deiconify(); self.win.lift(); self.win.focus_force()
            except tk.TclError:
                self.win = None
        if self.win is None:
            self._build()
        if tab is not None and tab in self._tabs:
            try:
                self._nb.select(self._tabs[tab])
            except tk.TclError:
                pass

    def close(self):
        if self._after is not None:
            try:
                self.win.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None

    def _build(self):
        self.win = tk.Toplevel(self.cat.root)
        self.win.title("Cat · Settings")
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._nb = ttk.Notebook(self.win)
        self._nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._tabs = {}
        self._build_focus_tab()
        self._build_reminders_tab()
        self._build_pin_tab()
        self._build_more_tab()
        self._refresh_reminders()
        self._refresh_pins()
        self._tick_remaining()

    def _add_tab(self, name):
        frame = tk.Frame(self._nb)
        self._nb.add(frame, text=name)
        self._tabs[name] = frame
        return frame

    # --- Focus tab ------------------------------------------------------
    def _build_focus_tab(self):
        f = self._add_tab("Focus")
        pet = self.cat.cfg["pet"]
        self._focus_var = tk.StringVar(value=str(pet.get("focus_min", 25)))
        self._break_var = tk.StringVar(value=str(pet.get("break_min", 5)))
        self._focus_status = tk.StringVar(value="")
        row = tk.Frame(f); row.pack(anchor="w", padx=10, pady=(10, 4))
        tk.Label(row, text="Focus").pack(side="left")
        tk.Spinbox(row, from_=1, to=600, width=4, textvariable=self._focus_var).pack(side="left", padx=(4, 2))
        tk.Label(row, text="min   Break").pack(side="left")
        tk.Spinbox(row, from_=1, to=120, width=4, textvariable=self._break_var).pack(side="left", padx=(4, 2))
        tk.Label(row, text="min").pack(side="left")
        tk.Button(row, text="Save", command=self._on_save_focus).pack(side="left", padx=8)
        tk.Label(f, textvariable=self._focus_status, fg="#3a7").pack(anchor="w", padx=10)
        ctl = tk.Frame(f); ctl.pack(anchor="w", padx=10, pady=8)
        tk.Button(ctl, text="▶ Start", command=self.cat._start_focus).pack(side="left")
        tk.Button(ctl, text="⏸ Pause", command=self.cat._pause_focus).pack(side="left", padx=4)
        tk.Button(ctl, text="▶ Resume", command=self.cat._resume_focus).pack(side="left")
        tk.Button(ctl, text="■ Stop", command=self.cat._stop_focus).pack(side="left", padx=4)
        self._remaining_var = tk.StringVar(value="idle")
        tk.Label(f, textvariable=self._remaining_var).pack(anchor="w", padx=10, pady=(0, 10))

    def _on_save_focus(self):
        try:
            fm, bm = int(self._focus_var.get()), int(self._break_var.get())
        except (TypeError, ValueError):
            self._focus_status.set("enter whole minutes"); return
        if fm <= 0 or bm <= 0:
            self._focus_status.set("minutes must be > 0"); return
        self.cat._set_focus_minutes(fm, bm)
        self._focus_status.set("saved ✓")

    def _tick_remaining(self):
        if self.win is None:
            return
        st = self.cat.pomodoro.state
        if st in ("focus", "break", "paused"):
            rem = int(max(0, self.cat.pomodoro.remaining(time.monotonic())))
            self._remaining_var.set("%s  %d:%02d" % (st, rem // 60, rem % 60))
        else:
            self._remaining_var.set("idle")
        try:
            self._after = self.win.after(500, self._tick_remaining)
        except tk.TclError:
            self._after = None

    # --- Reminders tab --------------------------------------------------
    def _build_reminders_tab(self):
        f = self._add_tab("Reminders")
        pet = self.cat.cfg["pet"]
        self._rem_enable = tk.IntVar(value=1 if pet.get("reminders", True) else 0)
        tk.Checkbutton(f, text="Enable reminders", variable=self._rem_enable,
                       command=lambda: self.cat._set_cfg_flag("reminders", self._rem_enable.get())
                       ).pack(anchor="w", padx=10, pady=(8, 2))
        self._msg_var = tk.StringVar()
        self._mode_var = tk.StringVar(value="in")
        self._amount_var = tk.StringVar(value="20")
        self._unit_var = tk.StringVar(value="min")
        self._hh_var = tk.StringVar(value="9")
        self._mm_var = tk.StringVar(value="00")
        self._rem_status = tk.StringVar(value="")
        mrow = tk.Frame(f); mrow.pack(anchor="w", padx=10, pady=2)
        tk.Label(mrow, text="Message").pack(side="left")
        tk.Entry(mrow, width=26, textvariable=self._msg_var).pack(side="left", padx=4)
        inrow = tk.Frame(f); inrow.pack(anchor="w", padx=10, pady=2)
        tk.Radiobutton(inrow, text="in", variable=self._mode_var, value="in").pack(side="left")
        tk.Spinbox(inrow, from_=0, to=999, width=4, textvariable=self._amount_var).pack(side="left", padx=2)
        tk.OptionMenu(inrow, self._unit_var, "min", "hours").pack(side="left")
        atrow = tk.Frame(f); atrow.pack(anchor="w", padx=10, pady=2)
        tk.Radiobutton(atrow, text="at", variable=self._mode_var, value="at").pack(side="left")
        tk.Spinbox(atrow, from_=0, to=23, width=3, textvariable=self._hh_var).pack(side="left", padx=2)
        tk.Label(atrow, text=":").pack(side="left")
        tk.Spinbox(atrow, from_=0, to=59, width=3, textvariable=self._mm_var).pack(side="left", padx=2)
        tk.Button(atrow, text="Add", command=self._on_add_reminder).pack(side="left", padx=8)
        tk.Label(f, textvariable=self._rem_status, fg="#c33").pack(anchor="w", padx=10)
        tk.Frame(f, height=1, bg="#ccc").pack(fill="x", padx=10, pady=4)
        self._rem_list = tk.Frame(f)
        self._rem_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _on_add_reminder(self):
        mode = self._mode_var.get()
        if mode == "in":
            due = reminders.due_from_fields("in", self._amount_var.get(),
                                            self._unit_var.get(), 0, 0, time.time())
        else:
            due = reminders.due_from_fields("at", 0, "min",
                                            self._hh_var.get(), self._mm_var.get(), time.time())
        if due is None:
            self._rem_status.set("couldn't read that time"); return
        self._rem_status.set("")
        self.cat.reminders.add(self._msg_var.get().strip() or "Reminder", due)
        self._msg_var.set("")
        self._refresh_reminders()

    def _refresh_reminders(self):
        if self.win is None:
            return
        for w in self._rem_list.winfo_children():
            w.destroy()
        pending = self.cat.reminders.pending()
        if not pending:
            tk.Label(self._rem_list, text="(no reminders)", fg="#888").pack(anchor="w")
            return
        now = time.time()
        for item in pending:
            row = tk.Frame(self._rem_list); row.pack(fill="x", pady=1)
            tk.Button(row, text="✕", width=2,
                      command=lambda it=item: self._remove_reminder(it)).pack(side="right")
            tk.Label(row, text=reminders.format_due(item["due"], now), fg="#666").pack(side="right", padx=6)
            tk.Label(row, text="• " + item["text"], anchor="w").pack(side="left")

    def _remove_reminder(self, item):
        self.cat.reminders.remove(item["text"], item["due"])
        self._refresh_reminders()

    # --- Pin tab --------------------------------------------------------
    def _build_pin_tab(self):
        f = self._add_tab("Pin")
        pet = self.cat.cfg["pet"]
        self._pin_enable = tk.IntVar(value=1 if pet.get("pin", True) else 0)
        tk.Checkbutton(f, text="Enable pin", variable=self._pin_enable,
                       command=lambda: self.cat._set_cfg_flag("pin", self._pin_enable.get())
                       ).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Label(f, text="Move the cat over a window, then use “Pin this window” "
                         "(right-click the cat or the button below).",
                 wraplength=300, justify="left", fg="#555").pack(anchor="w", padx=10)
        brow = tk.Frame(f); brow.pack(anchor="w", padx=10, pady=6)
        tk.Button(brow, text="\U0001F4CC Pin the window under me",
                  command=self._on_pin_under_cat).pack(side="left")
        tk.Button(brow, text="Unpin all", command=self._on_unpin_all).pack(side="left", padx=8)
        tk.Frame(f, height=1, bg="#ccc").pack(fill="x", padx=10, pady=4)
        self._pin_list = tk.Frame(f)
        self._pin_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _on_pin_under_cat(self):
        self.cat._pin_under_cat()
        self._refresh_pins()

    def _on_unpin_all(self):
        self.cat.pinset.unpin_all()
        self._refresh_pins()

    def _unpin_one(self, hwnd):
        self.cat.pinset.toggle(hwnd)      # toggling a pinned hwnd unpins it
        self._refresh_pins()

    def _refresh_pins(self):
        if self.win is None:
            return
        for w in self._pin_list.winfo_children():
            w.destroy()
        pinned = sorted(self.cat.pinset.pinned())
        if not pinned:
            tk.Label(self._pin_list, text="(nothing pinned)", fg="#888").pack(anchor="w")
            return
        for hwnd in pinned:
            row = tk.Frame(self._pin_list); row.pack(fill="x", pady=1)
            title = window.window_title(hwnd) or ("window %d" % hwnd)
            if len(title) > 34:
                title = title[:33] + "…"
            tk.Button(row, text="✕", width=2,
                      command=lambda h=hwnd: self._unpin_one(h)).pack(side="right")
            tk.Label(row, text="• " + title, anchor="w").pack(side="left")

    # --- More tab -------------------------------------------------------
    def _build_more_tab(self):
        f = self._add_tab("More")
        self._more_vars = {}
        for key, label in _MORE_TOGGLES:
            var = tk.IntVar(value=1 if self.cat.cfg["pet"].get(key, True) else 0)
            self._more_vars[key] = var
            tk.Checkbutton(f, text=label, variable=var,
                           command=lambda k=key, v=var: self.cat._set_cfg_flag(k, v.get())
                           ).pack(anchor="w", padx=10, pady=2)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PY -m unittest tests.test_smoke_settings -v`
Expected: PASS (window builds all four tabs, refresh + save + add paths run, reopen works).

- [ ] **Step 5: Commit**

```bash
git add petkit/settings.py tests/test_smoke_settings.py
git commit -m "Add the cat Settings window (Focus/Reminders/Pin/More tabs)"
```

---

### Task 5: Slim the right-click menu + wire the Settings window into `pet.pyw`

**Files:**
- Modify: `pet.pyw`
- Test: `tests/test_smoke_pet.py`

**Interfaces:**
- Consumes: `petkit.settings.SettingsWindow` (Task 4); the Cat support methods (Task 3); `window.window_below`/`is_pinned` for the dynamic Pin label.
- Produces: `Cat._build_menu(now) -> tk.Menu` (slim, no checkbuttons; testable), `Cat._open_settings(tab=None)` (singleton). Removes `_menu_var`, `_menu_vars`, `_add_reminder_dialog`, `_cancel_reminder` (and stops using in-menu toggles).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_smoke_pet.py` a menu-structure test (reuse the `TestPetPinAndSupport._make_cat` pattern; add a new class):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPetMenuSlim(unittest.TestCase):
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

    def test_menu_has_settings_and_no_checkbuttons(self):
        import time
        root, cat = self._make_cat()
        try:
            m = cat._build_menu(time.monotonic())
            labels, has_check = [], False
            for i in range(m.index("end") + 1):
                t = m.type(i)
                if t == "checkbutton":
                    has_check = True
                elif t == "command":
                    labels.append(m.entrycget(i, "label"))
            self.assertFalse(has_check)                                   # toggles moved to window
            self.assertTrue(any("Settings" in s for s in labels))
            self.assertTrue(any("Pin this window" in s for s in labels))
            cat._open_settings("Focus")
            self.assertIsNotNone(cat.settings.win)
            cat._open_settings()                                         # singleton: still one window
            cat.close()                                                  # closes the settings window too
        finally:
            root.destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PY -m unittest tests.test_smoke_pet.TestPetMenuSlim -v`
Expected: FAIL/ERROR — `Cat` has no `_build_menu` / `_open_settings`; the current menu still has checkbuttons.

- [ ] **Step 3a: Add the settings import**

In `pet.pyw`, add to the import block (next to the other `import petkit.* as ...` lines):

```python
import petkit.settings as settings
```

- [ ] **Step 3b: Init the singleton reference**

In `Cat.__init__`, add (next to the other Phase-4 init, e.g. right after `self._next_topmost = 0.0`):

```python
        self.settings = None              # lazily-built Settings window (singleton)
```

- [ ] **Step 3c: Replace `_on_right_click` with `_build_menu` + a thin opener**

Replace the entire `_on_right_click` method (currently lines ~283-345) with:

```python
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
```

- [ ] **Step 3d: Remove the now-dead menu helpers**

Delete these methods entirely from `pet.pyw`:
- `_menu_var` (currently lines ~258-266) and any remaining reference to `self._menu_vars`.
- `_cancel_reminder` (currently lines ~363-365).
- `_add_reminder_dialog` (currently lines ~367-404).

Also, in `_set_cfg_flag` (added in Task 3) the `getattr(self, "_menu_vars", None)` guard now always sees no menu vars — leave it as written (harmless and keeps the method generic).

- [ ] **Step 3e: Close the settings window in `close()`**

In `Cat.close`, add (e.g. after the `drop_target` teardown block):

```python
        try:
            if getattr(self, "settings", None):
                self.settings.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run the targeted test, then the full suite**

Run: `PY -m unittest tests.test_smoke_pet.TestPetMenuSlim -v`
Expected: PASS.

Run: `PY -m unittest discover -s tests -p "test_*.py"`
Expected: ends in `OK`.

- [ ] **Step 5: Commit**

```bash
git add pet.pyw tests/test_smoke_pet.py
git commit -m "Slim the right-click menu to actions; wire the Settings window"
```

---

## Self-Review

**1. Spec coverage** (against `docs/superpowers/specs/2026-06-26-cat-settings-window-design.md`):
- Slim default menu, toggles removed from it → Task 5 (`_build_menu`, menu-structure test asserts no checkbuttons). ✓
- Dedicated `ttk.Notebook` Settings window, singleton, on-demand → Task 4 + Task 5 (`_open_settings`). ✓
- Focus tab (minute fields + Save + Start/Pause/Stop + live MM:SS) → Task 4 `_build_focus_tab`/`_tick_remaining`; durations applied via Task 3 `_set_focus_minutes`. ✓
- Reminders tab (structured `in`/`at` add + pending list + per-item remove + enable toggle) → Task 4 `_build_reminders_tab`; math in Task 1 `due_from_fields`/`format_due`; precise delete in Task 1 `Reminders.remove`. ✓
- Pin tab (enable, pin-under-cat button, pinned list w/ unpin, unpin all; no hotkey) → Task 4 `_build_pin_tab`; titles via Task 2 `window_title`. ✓
- More tab (petting/catnap/greeter/nudges/carry) → Task 4 `_build_more_tab` + Task 3 `_set_cfg_flag`. ✓
- Pin redesign: cat-driven via window under the cat → Task 3 `_pin_under_cat` + Task 2 `window_below`; cat stays on top (re-raise on pin + gated ~1/s re-assert) → Task 3. ✓
- Remove `pin_hotkey`, no new config keys → Task 3 (config.py + test). ✓
- Menu Pin item reflects state / "Pin this window" vs "Unpin this window" → Task 5 `_build_menu`. ✓
- Testing strategy (pure TDD; Win32 smoke; GUI smoke; menu-structure assertion) → Tasks 1/2/4/5. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows the assertions; commands use the explicit `PY` interpreter path. ✓

**3. Type consistency:** `due_from_fields(mode, amount, unit, hh, mm, now_epoch)` and `format_due(due_epoch, now_epoch)` are called with matching argument order in Task 4 (`_on_add_reminder`, `_refresh_reminders`). `Reminders.remove(text, due)` matches the `_remove_reminder` call. `window_below(hwnd)`/`window_title(hwnd)` signatures match their callers in Tasks 3/4/5. `SettingsWindow.open(tab)`/`close()` match the test and `Cat._open_settings`. Cat methods produced in Task 3 (`_set_cfg_flag`, `_set_focus_minutes`, `_pin_under_cat`, `_save_cfg`) are consumed with matching names in Tasks 4/5. `Pomodoro.focus_s/break_s` attribute names match `petkit/pomodoro.py`. ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-26-cat-settings-window.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints.
