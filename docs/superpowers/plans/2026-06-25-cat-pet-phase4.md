# Cat Pet — Phase 4 "Power-tools" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two power-tools — **Pin** (a hotkey that toggles any window under the cursor always-on-top) and **Catch & Carry** (drop files onto the cat; it holds them; click to release them onto the clipboard as `CF_HDROP` so a normal Ctrl+V drops them anywhere).

**Architecture:** The pure, unit-testable cores live apart from the OS glue: `petkit/pins.py` (pinned-set bookkeeping, injected toggle fn) and `winkit/dnd.build_dropfiles()` (the `DROPFILES`/`CF_HDROP` byte layout). The Win32 surfaces — topmost toggle + window-at-point in `winkit/window.py`, and the `WM_DROPFILES` wndproc subclass + clipboard writer in `winkit/dnd.py` — are thin and covered by Windows smoke tests. Everything wires additively into `pet.pyw` (a `HotkeyPoller` for Pin; a `FileDropTarget` on the pet HWND for Carry). Event-driven; no per-frame cost.

**Tech Stack:** Python 3.12 stdlib only — ctypes (user32/kernel32/shell32), struct, tkinter.

## Global Constraints

- Pure stdlib only; no pip/third-party imports.
- Pure-logic modules (`petkit/pins.py`, `winkit.dnd.build_dropfiles`) take injected dependencies / are pure functions — unit-tested cross-platform.
- Win32 code lives in `winkit/`; pet-feature logic lives in `petkit/`.
- 64-bit-safe ctypes throughout: `LRESULT = ctypes.c_ssize_t`; `WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)`; use `GetWindowLongPtrW`/`SetWindowLongPtrW` (fall back to the non-Ptr names on x86, as `winkit/window.py` already does); **keep a strong Python reference to any `WNDPROC` callback or it is GC'd → crash** (see `winkit/tray.py`).
- A subclassed wndproc MUST chain unhandled messages to the original via `CallWindowProcW`, and `FileDropTarget.close()` MUST restore the original proc.
- Per-frame work unchanged; Pin/Carry are event-driven (hotkey edge, WM_DROPFILES).
- Test runner: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -p "test_*.py"`.
- Windows-only tests guard with `@unittest.skipUnless(os.name == "nt", "Windows only")`.

---

### Task 1: Topmost + window-at-point helpers (winkit/window.py)

**Files:**
- Modify: `winkit/window.py` (append; reuse the existing `_user32`, `_get`/`_set`, `SetWindowPos`)
- Test: `tests/test_winkit_system.py` (append a Windows smoke test class)

**Interfaces:**
- Produces: `winkit.window.set_topmost(hwnd, on) -> bool` (SetWindowPos HWND_TOPMOST/HWND_NOTOPMOST), `winkit.window.is_topmost(hwnd) -> bool` (WS_EX_TOPMOST bit), `winkit.window.root_window_at(x, y) -> int` (WindowFromPoint → GetAncestor GA_ROOT; 0 if none).

- [ ] **Step 1: Write the failing Windows smoke test** (new class in `tests/test_winkit_system.py`):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPinHelpers(unittest.TestCase):
    def test_set_topmost_toggles_exstyle(self):
        import winkit.window as W
        W.enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.geometry("60x60+0+0")
        root.update()
        try:
            hwnd = W._hwnd_of(root)
            self.assertTrue(W.set_topmost(hwnd, True))
            self.assertTrue(W.is_topmost(hwnd))
            self.assertTrue(W.set_topmost(hwnd, False))
            self.assertFalse(W.is_topmost(hwnd))
        finally:
            root.destroy()

    def test_root_window_at_returns_int(self):
        import winkit.window as W
        self.assertIsInstance(W.root_window_at(0, 0), int)
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** in `winkit/window.py` (append; add the constants/decls near the top with the other ones):

```python
WS_EX_TOPMOST = 0x00000008
GA_ROOT = 2
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

_user32.WindowFromPoint.restype = wintypes.HWND
_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]


def is_topmost(hwnd):
    return bool(int(_get(hwnd, GWL_EXSTYLE) or 0) & WS_EX_TOPMOST)


def set_topmost(hwnd, on):
    """Toggle a window's always-on-top z-order. Returns the SetWindowPos BOOL."""
    insert_after = HWND_TOPMOST if on else HWND_NOTOPMOST
    return bool(_user32.SetWindowPos(
        hwnd, ctypes.c_void_p(insert_after), 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))


def root_window_at(x, y):
    """The top-level (root ancestor) window under screen point (x, y); 0 if none."""
    pt = wintypes.POINT(x, y)
    hwnd = _user32.WindowFromPoint(pt)
    if not hwnd:
        return 0
    root = _user32.GetAncestor(hwnd, GA_ROOT)
    return int(root or hwnd)
```

(Note: `SetWindowPos.argtypes` already declares the 2nd arg as `HWND`; passing `ctypes.c_void_p(-1)` for `HWND_TOPMOST` is the established way to pass the sentinel safely.)

- [ ] **Step 4: Run the suite, watch pass. Commit** `feat: add topmost-toggle + window-at-point helpers`.

---

### Task 2: Pinned-set bookkeeping (petkit/pins.py)

**Files:**
- Create: `petkit/pins.py`
- Test: `tests/test_pins.py`

**Interfaces:**
- Produces: `PinSet(toggle_fn)` where `toggle_fn(hwnd, on)` applies the OS change; `.toggle(hwnd) -> bool` flips pin state for `hwnd` (calls `toggle_fn`, returns the new state), `.is_pinned(hwnd) -> bool`, `.pinned() -> set`, `.unpin_all()` (un-pins every tracked hwnd via `toggle_fn(hwnd, False)`).

- [ ] **Step 1: Write failing tests** `tests/test_pins.py`:

```python
import unittest
from petkit.pins import PinSet


class TestPinSet(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.pins = PinSet(lambda hwnd, on: self.calls.append((hwnd, on)) or True)

    def test_toggle_pins_then_unpins(self):
        self.assertTrue(self.pins.toggle(100))     # now pinned
        self.assertTrue(self.pins.is_pinned(100))
        self.assertEqual(self.calls[-1], (100, True))
        self.assertFalse(self.pins.toggle(100))    # now unpinned
        self.assertFalse(self.pins.is_pinned(100))
        self.assertEqual(self.calls[-1], (100, False))

    def test_tracks_multiple(self):
        self.pins.toggle(1)
        self.pins.toggle(2)
        self.assertEqual(self.pins.pinned(), {1, 2})

    def test_unpin_all_clears_and_calls_off(self):
        self.pins.toggle(1)
        self.pins.toggle(2)
        self.calls.clear()
        self.pins.unpin_all()
        self.assertEqual(self.pins.pinned(), set())
        self.assertEqual(sorted(c[0] for c in self.calls), [1, 2])
        self.assertTrue(all(c[1] is False for c in self.calls))
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** `petkit/pins.py`:

```python
"""Tracks which windows the cat has pinned always-on-top. The OS toggle is
injected (toggle_fn(hwnd, on)) so the bookkeeping is pure and unit-testable."""


class PinSet:
    def __init__(self, toggle_fn):
        self._toggle = toggle_fn
        self._pinned = set()

    def is_pinned(self, hwnd):
        return hwnd in self._pinned

    def pinned(self):
        return set(self._pinned)

    def toggle(self, hwnd):
        on = hwnd not in self._pinned
        self._toggle(hwnd, on)
        if on:
            self._pinned.add(hwnd)
        else:
            self._pinned.discard(hwnd)
        return on

    def unpin_all(self):
        for hwnd in list(self._pinned):
            self._toggle(hwnd, False)
        self._pinned.clear()
```

- [ ] **Step 4: Run, watch pass. Commit** `feat: add PinSet pinned-window bookkeeping`.

---

### Task 3: CF_HDROP byte builder + clipboard writer (winkit/dnd.py)

**Files:**
- Create: `winkit/dnd.py`
- Test: `tests/test_dnd.py` (pure byte-layout tests)

**Interfaces:**
- Produces: `winkit.dnd.build_dropfiles(paths) -> bytes` (a `DROPFILES` header + wide, double-NUL-terminated path list) and `winkit.dnd.set_clipboard_files(paths) -> bool` (place the paths on the clipboard as `CF_HDROP` so Ctrl+V in Explorer drops them).

- [ ] **Step 1: Write failing pure tests** `tests/test_dnd.py`:

```python
import struct
import unittest
from winkit.dnd import build_dropfiles


class TestBuildDropfiles(unittest.TestCase):
    def test_header_layout(self):
        blob = build_dropfiles(["C:\\a.txt"])
        # DROPFILES = pFiles(DWORD)=20, pt.x, pt.y, fNC, fWide(=1) -> 5x int32
        p_files, x, y, f_nc, f_wide = struct.unpack("<Iiiii", blob[:20])
        self.assertEqual(p_files, 20)
        self.assertEqual((x, y, f_nc), (0, 0, 0))
        self.assertEqual(f_wide, 1)

    def test_path_list_is_wide_and_double_null_terminated(self):
        blob = build_dropfiles(["C:\\a.txt"])
        tail = blob[20:].decode("utf-16-le")
        self.assertEqual(tail, "C:\\a.txt\x00\x00")

    def test_multiple_paths(self):
        blob = build_dropfiles(["a", "b"])
        tail = blob[20:].decode("utf-16-le")
        self.assertEqual(tail, "a\x00b\x00\x00")

    def test_even_byte_length(self):
        self.assertEqual(len(build_dropfiles(["x"])) % 2, 0)
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** `winkit/dnd.py` (the builder is pure; the clipboard writer is a thin Win32 wrapper):

```python
"""Catch & Carry native glue: build a CF_HDROP blob and put dropped file paths
on the clipboard, plus a WM_DROPFILES wndproc subclass (FileDropTarget, Task 4).

The byte-layout builder is pure and unit-tested; the Win32 calls follow the
64-bit-safe idiom in winkit/tray.py."""
import ctypes
import struct
from ctypes import wintypes

_DROPFILES_SIZE = 20          # sizeof(DROPFILES): pFiles + POINT + fNC + fWide
CF_HDROP = 15
_GMEM_MOVEABLE = 0x0002


def build_dropfiles(paths):
    """A DROPFILES struct followed by a wide, double-NUL-terminated path list."""
    header = struct.pack("<Iiiii", _DROPFILES_SIZE, 0, 0, 0, 1)  # fWide=1
    body = ("".join(p + "\0" for p in paths) + "\0").encode("utf-16-le")
    return header + body


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]


def set_clipboard_files(paths):
    """Put paths on the clipboard as CF_HDROP. Returns True on success."""
    if not paths:
        return False
    blob = build_dropfiles(paths)
    h = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(blob))
    if not h:
        return False
    ptr = _kernel32.GlobalLock(h)
    if not ptr:
        _kernel32.GlobalFree(h)
        return False
    ctypes.memmove(ptr, blob, len(blob))
    _kernel32.GlobalUnlock(h)
    if not _user32.OpenClipboard(None):
        _kernel32.GlobalFree(h)
        return False
    try:
        _user32.EmptyClipboard()
        if not _user32.SetClipboardData(CF_HDROP, h):
            _kernel32.GlobalFree(h)     # we still own it on failure
            return False
        return True                      # ownership transferred to the clipboard
    finally:
        _user32.CloseClipboard()
```

- [ ] **Step 4: Run the pure tests, watch pass. Commit** `feat: add CF_HDROP builder + clipboard file writer`.

---

### Task 4: WM_DROPFILES wndproc subclass (winkit/dnd.py)

**Files:**
- Modify: `winkit/dnd.py` (append `FileDropTarget`)
- Test: `tests/test_winkit_system.py` (append a Windows smoke test)

**Interfaces:**
- Produces: `winkit.dnd.FileDropTarget(hwnd, on_drop)` — calls `DragAcceptFiles(hwnd, True)`, subclasses the window's wndproc to handle `WM_DROPFILES` (parses paths via `DragQueryFileW`, calls `on_drop(list_of_paths)`), and `.close()` restores the original wndproc and calls `DragAcceptFiles(hwnd, False)`.

- [ ] **Step 1: Write the failing Windows smoke test** (append to `tests/test_winkit_system.py`):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestFileDropTarget(unittest.TestCase):
    def test_install_and_restore(self):
        import winkit.window as W
        import winkit.dnd as D
        W.enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.geometry("60x60+0+0")
        root.update()
        got = []
        try:
            hwnd = W._hwnd_of(root)
            target = D.FileDropTarget(hwnd, got.append)
            self.assertNotEqual(target._old_proc, 0)   # captured the original proc
            target.close()                              # restores without crashing
            root.update()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement** `FileDropTarget` in `winkit/dnd.py` (append). Critical: keep `self._proc` (the WNDPROC instance) alive; chain via `CallWindowProcW`; restore on close.

```python
import os  # add to the existing imports at the top of winkit/dnd.py

_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)
GWLP_WNDPROC = -4
WM_DROPFILES = 0x0233

_setlp = getattr(_user32, "SetWindowLongPtrW", None) or _user32.SetWindowLongW
_setlp.restype = ctypes.c_void_p
_setlp.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
_user32.CallWindowProcW.restype = LRESULT
_user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
_shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
_shell32.DragQueryFileW.restype = wintypes.UINT
_shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                    wintypes.LPWSTR, wintypes.UINT]
_shell32.DragFinish.argtypes = [wintypes.HANDLE]


def _query_dropped(hdrop):
    count = _shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
    paths = []
    for i in range(count):
        need = _shell32.DragQueryFileW(hdrop, i, None, 0)
        buf = ctypes.create_unicode_buffer(need + 1)
        _shell32.DragQueryFileW(hdrop, i, buf, need + 1)
        paths.append(buf.value)
    return paths


class FileDropTarget:
    """Accept WM_DROPFILES on an existing HWND by subclassing its wndproc."""

    def __init__(self, hwnd, on_drop):
        self.hwnd = hwnd
        self.on_drop = on_drop
        self._proc = WNDPROC(self._wnd_proc)        # KEEP a strong ref or GC -> crash
        _shell32.DragAcceptFiles(hwnd, True)
        self._old_proc = _setlp(hwnd, GWLP_WNDPROC,
                                ctypes.cast(self._proc, ctypes.c_void_p)) or 0

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            try:
                paths = _query_dropped(wparam)
                _shell32.DragFinish(wparam)
                if paths:
                    self.on_drop(paths)
            except Exception:
                pass
            return 0
        return _user32.CallWindowProcW(self._old_proc, hwnd, msg, wparam, lparam)

    def close(self):
        if self._old_proc:
            _setlp(self.hwnd, GWLP_WNDPROC, ctypes.c_void_p(self._old_proc))
            self._old_proc = 0
        try:
            _shell32.DragAcceptFiles(self.hwnd, False)
        except Exception:
            pass
```

- [ ] **Step 4: Run the suite, watch pass. Commit** `feat: add WM_DROPFILES wndproc subclass (FileDropTarget)`.

---

### Task 5: Wire Pin + Catch & Carry into pet.pyw

**Files:**
- Modify: `pet.pyw` (imports, `Cat.__init__`, `_on_release`, menu, `close`), `config.py` (`DEFAULTS["pet"]`)
- Test: `tests/test_config.py`, `tests/test_smoke_pet.py`

**Config additions** — extend `DEFAULTS["pet"]`:

```python
    "pin": True, "pin_hotkey": ["ctrl", "shift", "P"], "carry": True,
```

- [ ] **Step 1: Config test first** — assert `config.defaults()["pet"]` has `pin`/`carry` (bools) and `pin_hotkey` (list). Run→fail, add, run→pass. Commit `feat: add pin/carry pet config defaults`.

- [ ] **Step 2: Construct objects** in `Cat.__init__`: `import winkit.dnd as dnd`, `import petkit.pins as pins` (and `winkit.window` is already imported as `window`). Compute the pet HWND once: `self.hwnd = window._hwnd_of(root)`. Build:
  - `self.pinset = pins.PinSet(window.set_topmost)`
  - `self._held = []` (files the cat is carrying)
  - if `pet.get("pin", True)`: `self.pin_hotkey = wkinput.HotkeyPoller(root, pet.get("pin_hotkey") or ["ctrl","shift","P"], self._toggle_pin)`
  - if `pet.get("carry", True)`: `self.drop_target = dnd.FileDropTarget(self.hwnd, self._on_files_dropped)` (else `self.drop_target = None`)

- [ ] **Step 3: Pin handler** `_toggle_pin`:

```python
    def _toggle_pin(self):
        if not self.cfg["pet"].get("pin", True):
            return
        x, y = wkinput.cursor_pos()
        hwnd = window.root_window_at(x, y)
        if not hwnd or hwnd == self.hwnd:      # ignore empty desktop / the cat itself
            return
        on = self.pinset.toggle(hwnd)
        self.bubble.say("\U0001F4CC pinned" if on else "unpinned", secs=2)
```

- [ ] **Step 4: Catch & Carry handlers:**

```python
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
```

Hook release into the existing left-click `_on_release`: when the click did NOT drag (`not self._moved`) and `self._held` is non-empty, call `self._release_held()` and return (don't treat it as a position save). Keep the existing drag-persist behavior otherwise.

- [ ] **Step 5: Menu additions** — extend the toggle tuple with `("pin", "Pin window (hotkey)")` and `("carry", "Catch & carry files")`. When `self._held`, add above the toggles: `m.add_command(label="Drop %d file(s) → clipboard" % len(self._held), command=self._release_held)` and `m.add_command(label="Let go", command=lambda: setattr(self, "_held", []))`. If any windows are pinned, add `m.add_command(label="Unpin all (%d)" % len(self.pinset.pinned()), command=self._unpin_all)` where `_unpin_all` calls `self.pinset.unpin_all()` and bubbles a confirmation. Toggling `pin`/`carry` off should also tear down/rebuild the poller/target lazily — simplest: gate behavior on the config flag inside the handlers (already done), and on toggle just leave the poller/target installed (it no-ops when disabled). (The `pin_hotkey` poller checks `cfg["pet"]["pin"]` in `_toggle_pin`; `FileDropTarget`'s `on_drop` checks `cfg["pet"]["carry"]`.)

- [ ] **Step 6: Cleanup** — in `Cat.close()`, tear down native resources so quitting is clean: `if self.pin_hotkey: self.pin_hotkey.stop()`, `self.pinset.unpin_all()`, `if self.drop_target: self.drop_target.close()`. (Guard each with `getattr`/`try` since they may be absent when disabled.)

- [ ] **Step 7: Smoke + full suite** — run `tests/test_smoke_pet.py` (constructs the Cat, now installing the hotkey poller + drop target on a real HWND under `TOYBOX_SMOKE`) and the whole suite. All green. Add a minimal assertion to the pet smoke test that `cat.pinset` exists and `cat.hwnd` is a non-zero int.

- [ ] **Step 8: Commit** `feat: wire Pin hotkey + Catch & Carry into the cat`.

---

## Self-Review Notes

- Spec coverage: Pin (T1 topmost/window-at-point, T2 bookkeeping, T5 hotkey wiring + feedback) and Catch & Carry (T3 CF_HDROP builder + clipboard writer, T4 WM_DROPFILES subclass, T5 drop→hold→release wiring). Both Phase 4 spec items covered.
- Type consistency: `set_topmost(hwnd, on)`/`root_window_at(x, y)`, `PinSet(toggle_fn).toggle/unpin_all/pinned`, `build_dropfiles(paths)`/`set_clipboard_files(paths)`, `FileDropTarget(hwnd, on_drop).close` — signatures match between producing tasks (T1–T4) and the T5 call sites. `PinSet(window.set_topmost)` matches `set_topmost(hwnd, on)`.
- Safety: the only GC-sensitive object (`FileDropTarget._proc`) is held on the instance; `close()` restores the original wndproc and is called from `Cat.close()`; the clipboard `HGLOBAL` ownership transfer is handled (freed only on `SetClipboardData` failure).
- Lightweight: Pin is a hotkey edge (existing `HotkeyPoller`); Carry is event-driven (`WM_DROPFILES`). No new per-frame work.
