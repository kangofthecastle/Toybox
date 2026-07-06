# HUD Volume Slider + Mute Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax. TDD: failing test → run (fail) → implement → run (pass) → commit.

**Goal:** Add a draggable master-volume slider with a mute/unmute speaker glyph to the HUD, directly under the now-playing band.

**Architecture:** A new guarded, stdlib-only `winkit/audiovolume.py` reads/sets the default render endpoint's master volume + mute via Core Audio (`IAudioEndpointVolume`) through ctypes — shaped like `winkit/nowplaying.py` (pure helpers + blanket-guarded COM that NEVER raises). Unlike SMTC, endpoint-volume calls are fast and synchronous, so the HUD calls them on the Tk main thread: it refreshes the shown level ~1 Hz inside `tick()` and applies changes inline from the drag/click/wheel handlers (throttled). Pressing on the slider or glyph is intercepted before the window-drag logic. Nothing is written to `config.json` (volume is OS-owned), so the config-clobber / restart-all-toys concern does not apply.

**Tech Stack:** Python 3.12 stdlib only — `ctypes` (Core Audio via `ole32.dll`), `tkinter` canvas. No third-party packages.

## Global Constraints

- Pure Python 3.12 stdlib; no third-party packages.
- The HUD must never crash on bad state: every ctypes/COM call is blanket-guarded and returns a safe default; `audiovolume` functions NEVER raise.
- No `config.json` writes for volume (system-owned) — so no restart-all-toys concern.
- Lightweight: no new threads, no busy loops; volume is read once per existing 1 Hz `tick()` and applies are throttled to ~30 ms during a drag.
- Test runner — EXACT form in every "run the test" step, from repo root:
    `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path> -v`
- Commit trailer — match the repo's existing trailer (verify with `git log -1` before the first commit); the established form is:
    `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

- **Create** `winkit/audiovolume.py` — pure UI-math helpers + guarded Core Audio `get()/set_level()/set_mute()/toggle_mute()`. One responsibility: talk to the volume endpoint safely.
- **Create** `tests/test_audiovolume.py` — pure-helper unit tests + a Core-Audio smoke test (never raises; no net device change).
- **Modify** `hud.pyw` — volume-row layout constants, persistent canvas items, `_draw_volume()`, `_refresh_volume()` (called in `tick()`), the slider/glyph hit-tests, press/drag/release/wheel gating, and `_relayout_header` repositioning.
- **Modify** `tests/test_smoke_hud.py` — a `TestHudVolume` class (patches `audiovolume` so no test ever changes the real device).

---

## Task 1: Pure volume UI-math helpers

Create `winkit/audiovolume.py` with only the pure helpers (no COM yet).

**Files:** Create `winkit/audiovolume.py`; Test `tests/test_audiovolume.py`.

**Interfaces — Produces:**
- `clamp01(x) -> float` in `[0,1]`; bad input → `0.0`.
- `level_from_x(x, x_left, x_right) -> float` in `[0,1]` (fraction of a click/drag along the track; clamps; `x_right<=x_left` or bad → `0.0`).
- `x_from_level(level, x_left, x_right) -> int` (knob pixel-x for a level; clamps into the track).
- `format_pct(level) -> str` — `""` for `None`; else `"%d%%"` of `round(clamp01(level)*100)`.
- `step_level(level, delta) -> float` — `clamp01(level + delta)`; bad → `clamp01(delta)`.

- [ ] **Step 1: Write the failing test** — create `tests/test_audiovolume.py`:

```python
import os
import unittest
import unittest.mock as mock

import winkit.audiovolume as av


class TestClamp01(unittest.TestCase):
    def test_mid(self):
        self.assertAlmostEqual(av.clamp01(0.4), 0.4)

    def test_below_zero(self):
        self.assertEqual(av.clamp01(-3.0), 0.0)

    def test_above_one(self):
        self.assertEqual(av.clamp01(5.0), 1.0)

    def test_bad_input(self):
        self.assertEqual(av.clamp01(None), 0.0)


class TestLevelFromX(unittest.TestCase):
    def test_left_edge_is_zero(self):
        self.assertEqual(av.level_from_x(10, 10, 210), 0.0)

    def test_right_edge_is_one(self):
        self.assertEqual(av.level_from_x(210, 10, 210), 1.0)

    def test_quarter(self):
        self.assertAlmostEqual(av.level_from_x(60, 10, 210), 0.25)

    def test_left_of_track_clamps_zero(self):
        self.assertEqual(av.level_from_x(-99, 10, 210), 0.0)

    def test_right_of_track_clamps_one(self):
        self.assertEqual(av.level_from_x(9999, 10, 210), 1.0)

    def test_degenerate_track_is_zero(self):
        self.assertEqual(av.level_from_x(50, 10, 10), 0.0)

    def test_bad_input(self):
        self.assertEqual(av.level_from_x(None, None, None), 0.0)


class TestXFromLevel(unittest.TestCase):
    def test_zero_at_left(self):
        self.assertEqual(av.x_from_level(0.0, 10, 210), 10)

    def test_one_at_right(self):
        self.assertEqual(av.x_from_level(1.0, 10, 210), 210)

    def test_half_midpoint(self):
        self.assertEqual(av.x_from_level(0.5, 10, 210), 110)

    def test_clamps_over_one(self):
        self.assertEqual(av.x_from_level(2.0, 10, 210), 210)


class TestFormatPct(unittest.TestCase):
    def test_none(self):
        self.assertEqual(av.format_pct(None), "")

    def test_rounds(self):
        self.assertEqual(av.format_pct(0.633), "63%")

    def test_full(self):
        self.assertEqual(av.format_pct(1.0), "100%")

    def test_zero(self):
        self.assertEqual(av.format_pct(0.0), "0%")


class TestStepLevel(unittest.TestCase):
    def test_up(self):
        self.assertAlmostEqual(av.step_level(0.5, 0.02), 0.52)

    def test_down(self):
        self.assertAlmostEqual(av.step_level(0.5, -0.02), 0.48)

    def test_clamps_high(self):
        self.assertEqual(av.step_level(0.99, 0.02), 1.0)

    def test_clamps_low(self):
        self.assertEqual(av.step_level(0.01, -0.05), 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it, expect FAIL** — `ModuleNotFoundError: No module named 'winkit.audiovolume'`.

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_audiovolume -v`

- [ ] **Step 3: Implement** — create `winkit/audiovolume.py` with the module docstring + the five pure helpers (strict, never-raise):

```python
"""Master-volume control for the default Windows playback (render) endpoint via
Core Audio (IAudioEndpointVolume) through ctypes. get()/set_level()/set_mute()/
toggle_mute() are blanket-guarded and NEVER raise on any machine (no device, COM
error, non-Windows). Also holds the pure UI-math helpers the HUD slider uses.
Pure Python 3.12 stdlib -- no pip."""


def clamp01(x):
    """x coerced into [0.0, 1.0]; 0.0 on bad input."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0.0:
        return 0.0
    if v >= 1.0:
        return 1.0
    return v


def level_from_x(x, x_left, x_right):
    """Fraction in [0,1] for a click/drag at pixel x on a track spanning
    [x_left, x_right]. 0.0 for a degenerate/backwards track or bad input."""
    try:
        x = float(x); lo = float(x_left); hi = float(x_right)
    except (TypeError, ValueError):
        return 0.0
    if hi <= lo:
        return 0.0
    return clamp01((x - lo) / (hi - lo))


def x_from_level(level, x_left, x_right):
    """Knob pixel-x for `level` on a track spanning [x_left, x_right]."""
    try:
        lo = int(x_left); hi = int(x_right)
    except (TypeError, ValueError):
        return 0
    return lo + int((hi - lo) * clamp01(level))


def format_pct(level):
    """'63%' for a level; '' for None."""
    if level is None:
        return ""
    return "%d%%" % round(clamp01(level) * 100)


def step_level(level, delta):
    """level + delta, clamped to [0,1]."""
    try:
        base = float(level)
    except (TypeError, ValueError):
        base = 0.0
    try:
        d = float(delta)
    except (TypeError, ValueError):
        d = 0.0
    return clamp01(base + d)
```

- [ ] **Step 4: Run it, expect PASS.**

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_audiovolume -v`

- [ ] **Step 5: Commit.**

```
git add winkit/audiovolume.py tests/test_audiovolume.py
git commit -m "Add pure volume UI-math helpers (clamp01, level_from_x, format_pct, ...)"
```

---

## Task 2: Guarded Core Audio get/set/mute

Append the ctypes Core Audio layer to `winkit/audiovolume.py`. Everything runs
inside `_with_epv`, which balances `CoInitializeEx`/`CoUninitialize` (so it never
contaminates the calling thread's COM apartment), acquires the endpoint, and
releases every COM pointer in `finally`. Any failure → the guarded return value
(`None`/`False`); it must never raise on any machine.

**Files:** Modify `winkit/audiovolume.py`; Test `tests/test_audiovolume.py`.

**Interfaces — Produces:**
- `get() -> (level: float in [0,1], muted: bool) | None` (guarded read).
- `set_level(frac) -> bool` — rejects non-numeric input (returns `False`, no COM); else sets the master scalar. Never raises.
- `set_mute(mute) -> bool` — sets mute to `bool(mute)`. Never raises.
- `toggle_mute() -> bool | None` — flips current mute (via `get()`+`set_mute`); `None` if the current state can't be read.

**Core Audio flow (all guarded, HRESULT-checked):**
`CoCreateInstance(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)` →
`IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender=0, eConsole=0)` (slot 4) →
`IMMDevice::Activate(IID_IAudioEndpointVolume, CLSCTX_ALL)` (slot 3) → then
`GetMasterVolumeLevelScalar` (slot 9) / `SetMasterVolumeLevelScalar` (slot 7,
`pguidEventContext=NULL`) / `GetMute` (slot 15) / `SetMute` (slot 14). IUnknown
slots 0–2; `Release` is slot 2.

- [ ] **Step 1: Write the failing test** — append to `tests/test_audiovolume.py` before `if __name__`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestCoreAudioSmoke(unittest.TestCase):
    def test_get_never_raises_and_is_well_shaped(self):
        v = av.get()
        if v is not None:
            level, muted = v
            self.assertIsInstance(level, float)
            self.assertGreaterEqual(level, 0.0)
            self.assertLessEqual(level, 1.0)
            self.assertIsInstance(muted, bool)

    def test_set_level_rejects_bad_input_without_touching_com(self):
        self.assertIs(av.set_level(None), False)
        self.assertIs(av.set_level("loud"), False)

    def test_round_trip_restore_never_raises(self):
        # Set level/mute back to their CURRENT values: exercises the real COM
        # write path with ZERO net change to the user's system.
        v = av.get()
        if v is not None:
            level, muted = v
            self.assertIn(av.set_level(level), (True, False))
            self.assertIn(av.set_mute(muted), (True, False))


class TestToggleMuteLogic(unittest.TestCase):
    def test_toggle_flips_current(self):
        calls = []
        with mock.patch.object(av, "get", lambda: (0.5, False)), \
             mock.patch.object(av, "set_mute", lambda b: calls.append(b) or True):
            self.assertEqual(av.toggle_mute(), True)   # False -> True
            self.assertEqual(calls, [True])

    def test_toggle_none_when_unreadable(self):
        with mock.patch.object(av, "get", lambda: None):
            self.assertIsNone(av.toggle_mute())
```

- [ ] **Step 2: Run it, expect FAIL** — `AttributeError: module 'winkit.audiovolume' has no attribute 'get'`.

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_audiovolume.TestCoreAudioSmoke tests.test_audiovolume.TestToggleMuteLogic -v`

- [ ] **Step 3: Implement** — append the COM layer to `winkit/audiovolume.py`:

```python
# --- Core Audio (IAudioEndpointVolume) via ctypes; guarded, never raises ---
import ctypes

_CLSID_ENUM = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"   # MMDeviceEnumerator
_IID_ENUM = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"      # IMMDeviceEnumerator
_IID_EPV = "{5CDF2C82-841E-4546-9722-0CF74078229A}"       # IAudioEndpointVolume
_CLSCTX_ALL = 0x17
_COINIT_MTA = 0x0
_ERENDER = 0
_ECONSOLE = 0


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text):
    g = _GUID()
    if ctypes.WinDLL("ole32").CLSIDFromString(ctypes.c_wchar_p(text),
                                              ctypes.byref(g)) != 0:
        raise OSError("bad guid")
    return g


def _call(ptr, slot, restype, argtypes, *args):
    """Invoke COM vtable method `slot` on interface pointer `ptr`."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    fn = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[slot]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(fn)(ptr, *args)


def _release(ptr):
    try:
        if ptr and ptr.value:
            _call(ptr, 2, ctypes.c_ulong, [])   # IUnknown::Release
    except Exception:
        pass


def _with_epv(fn):
    """Acquire the default render endpoint's IAudioEndpointVolume, run fn(epv),
    release everything, and balance COM init. Returns fn's result or None. Never
    raises."""
    try:
        ole32 = ctypes.WinDLL("ole32")
    except Exception:
        return None
    hr = ole32.CoInitializeEx(None, _COINIT_MTA)
    need_uninit = hr in (0, 1)          # S_OK / S_FALSE -> we own an init to undo
    enum = ctypes.c_void_p()
    device = ctypes.c_void_p()
    epv = ctypes.c_void_p()
    try:
        clsid = _guid(_CLSID_ENUM)
        iid_enum = _guid(_IID_ENUM)
        iid_epv = _guid(_IID_EPV)
        ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_uint,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        if ole32.CoCreateInstance(ctypes.byref(clsid), None, _CLSCTX_ALL,
                                  ctypes.byref(iid_enum), ctypes.byref(enum)) != 0 \
                or not enum.value:
            return None
        if _call(enum, 4, ctypes.c_long,
                 [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
                 _ERENDER, _ECONSOLE, ctypes.byref(device)) != 0 or not device.value:
            return None
        if _call(device, 3, ctypes.c_long,
                 [ctypes.POINTER(_GUID), ctypes.c_uint, ctypes.c_void_p,
                  ctypes.POINTER(ctypes.c_void_p)],
                 ctypes.byref(iid_epv), _CLSCTX_ALL, None,
                 ctypes.byref(epv)) != 0 or not epv.value:
            return None
        return fn(epv)
    except Exception:
        return None
    finally:
        for p in (epv, device, enum):
            _release(p)
        if need_uninit:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass


def get():
    """(level in [0,1], muted bool) for the default playback device, or None."""
    def _read(epv):
        lvl = ctypes.c_float(0.0)
        mute = ctypes.c_int(0)
        if _call(epv, 9, ctypes.c_long, [ctypes.POINTER(ctypes.c_float)],
                 ctypes.byref(lvl)) != 0:
            return None
        if _call(epv, 15, ctypes.c_long, [ctypes.POINTER(ctypes.c_int)],
                 ctypes.byref(mute)) != 0:
            return None
        return (clamp01(lvl.value), bool(mute.value))
    return _with_epv(_read)


def set_level(frac):
    """Set the master scalar to `frac` (0..1). Rejects non-numeric input without
    touching COM. Returns True on a completed write attempt, else False."""
    try:
        f = float(frac)
    except (TypeError, ValueError):
        return False
    f = clamp01(f)

    def _write(epv):
        return _call(epv, 7, ctypes.c_long, [ctypes.c_float, ctypes.c_void_p],
                     ctypes.c_float(f), None) == 0
    return bool(_with_epv(_write))


def set_mute(mute):
    """Set mute to bool(mute). Returns True on a completed write, else False."""
    b = 1 if mute else 0

    def _write(epv):
        return _call(epv, 14, ctypes.c_long, [ctypes.c_int, ctypes.c_void_p],
                     b, None) == 0
    return bool(_with_epv(_write))


def toggle_mute():
    """Flip the current mute state. Returns the new state, or None if unreadable."""
    cur = get()
    if cur is None:
        return None
    new = not cur[1]
    set_mute(new)
    return new
```

- [ ] **Step 4: Run it, expect PASS** (both new classes; no net change to the machine's volume).

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_audiovolume -v`

- [ ] **Step 5: Commit.**

```
git add winkit/audiovolume.py tests/test_audiovolume.py
git commit -m "Add guarded Core Audio volume get/set/mute (IAudioEndpointVolume)"
```

---

## Task 3: HUD volume row — layout + render + 1 Hz refresh

Add the reserved volume row under the now-playing band, its persistent canvas
items, `_draw_volume()`, and a `_refresh_volume()` called each `tick()`.

**Files:** Modify `hud.pyw`; Test `tests/test_smoke_hud.py`.

**Interfaces:**
- Consumes: `winkit.audiovolume` (`get`, `format_pct`, `clamp01`); existing
  `Hud.tick`, `Hud._relayout_header`, `PAD`, `ROW_H`, `WIDTH`, `ACCENT`,
  `NP_TRACK`, `DIM`, `FG`, `NOWPLAYING_H`.
- Produces (on `Hud`): `_vol_glyph`, `_vol_bar_bg`, `_vol_bar`, `_vol_knob`,
  `_vol_pct` (canvas ids); `_vol_row_y`, `_vol_bar_span`; `_vol_level` (float|None),
  `_vol_muted` (bool), `_vol_dragging` (bool), `_vol_press_glyph` (bool),
  `_vol_apply_at` (float); methods `_vol_bar_bounds`, `_refresh_volume`,
  `_draw_volume`.

**Relative-edit note:** the header rows/HEIGHT already carry `+ NOWPLAYING_H`.
Add `+ VOLUME_H` *alongside* that same term everywhere it appears (never against
absolute line numbers). Anchor the volume band under the now-playing band bottom.

### Steps

- [ ] **Step 1: Write the failing test** — append to `tests/test_smoke_hud.py` before the final `if __name__`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudVolume(_HudTestBase):
    """Volume slider + mute. audiovolume is patched so NO test ever changes the
    real device (set_level/set_mute are recorded; get() is deterministic)."""
    def setUp(self):
        super().setUp()
        import winkit.audiovolume as av
        self.vol_sets = []
        self.mute_sets = []
        for name, sink in (("set_level", self.vol_sets), ("set_mute", self.mute_sets)):
            p = mock.patch.object(av, name, (lambda s: (lambda v: s.append(v) or True))(sink))
            p.start(); self.addCleanup(p.stop)
        gp = mock.patch.object(av, "get", lambda: (0.5, False))
        gp.start(); self.addCleanup(gp.stop)

    def test_items_exist(self):
        root, hud = self._make_hud([])
        try:
            for item in (hud._vol_glyph, hud._vol_bar_bg, hud._vol_bar,
                         hud._vol_knob, hud._vol_pct):
                self.assertTrue(hud.canvas.coords(item) or
                                hud.canvas.itemcget(item, "text") is not None)
        finally:
            hud.close(); root.destroy()

    def test_draw_positions_fill_knob_and_pct(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._vol_level = 0.5; hud._vol_muted = False
            hud._draw_volume()
            v_left, v_right = hud._vol_bar_span
            x0, _y0, x1, _y1 = hud.canvas.coords(hud._vol_bar)
            self.assertAlmostEqual(x1, v_left + (v_right - v_left) * 0.5, delta=2)
            self.assertEqual(hud.canvas.itemcget(hud._vol_bar, "fill"), hudmod.ACCENT)
            self.assertEqual(hud.canvas.itemcget(hud._vol_pct, "text"), "50%")
        finally:
            hud.close(); root.destroy()

    def test_muted_greys_fill_and_swaps_glyph(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._vol_level = 0.7; hud._vol_muted = True
            hud._draw_volume()
            self.assertEqual(hud.canvas.itemcget(hud._vol_bar, "fill"), hudmod.DIM)
            self.assertEqual(hud.canvas.itemcget(hud._vol_glyph, "text"), hudmod.VOL_MUTED)
        finally:
            hud.close(); root.destroy()

    def test_refresh_reads_from_audiovolume(self):
        import winkit.audiovolume as av
        root, hud = self._make_hud([])
        try:
            with mock.patch.object(av, "get", lambda: (0.8, True)):
                hud._vol_level = None; hud._vol_muted = False
                hud._refresh_volume()
                self.assertAlmostEqual(hud._vol_level, 0.8)
                self.assertTrue(hud._vol_muted)
        finally:
            hud.close(); root.destroy()

    def test_refresh_skipped_while_dragging(self):
        import winkit.audiovolume as av
        root, hud = self._make_hud([])
        try:
            with mock.patch.object(av, "get", lambda: (0.1, False)):
                hud._vol_level = 0.9; hud._vol_dragging = True
                hud._refresh_volume()
                self.assertAlmostEqual(hud._vol_level, 0.9)   # drag value preserved
        finally:
            hud.close(); root.destroy()

    def test_layout_below_nowplaying_above_clock_no_jump(self):
        root, hud = self._make_hud([])
        try:
            np_y = hud.canvas.coords(hud._np_title)[1]
            vol_y = hud._vol_row_y
            clock_y = hud.canvas.coords(hud._clock_text)[1]
            self.assertLess(np_y, vol_y)
            self.assertLess(vol_y, clock_y)
        finally:
            hud.close(); root.destroy()

    def test_recenters_on_width_toggle(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._toggle_width(); root.update_idletasks()
            v_left, v_right = hud._vol_bar_span
            self.assertEqual(v_right, hudmod.WIDTH_WIDE - hudmod.PAD - hudmod.VOL_PCT_W)
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run it, expect FAIL** — `AttributeError: 'Hud' object has no attribute '_vol_glyph'` (and `VOL_MUTED`).

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudVolume -v`

- [ ] **Step 3: Implement** — edits to `hud.pyw`:

1) Import next to the other winkit imports (after `import winkit.nowplaying as nowplaying`):
```python
import winkit.audiovolume as audiovolume
```

2) After the `NOWPLAYING_H`/`NP_BAR_H`/`NP_TIME_W` constants, add the volume-row geometry:
```python
VOLUME_H = 24          # reserved band under the now-playing band: mute glyph + slider
VOL_BAR_H = 4          # slider track thickness (px)
VOL_KNOB_R = 6         # slider knob radius (px)
VOL_GLYPH_W = 22       # left inset reserved for the mute/speaker glyph
VOL_PCT_W = 34         # right inset reserved for the "100%" readout
```

3) Append `+ VOLUME_H` to the `HEIGHT` expression (which already has `+ NOWPLAYING_H`):
```python
HEIGHT = 156 + NOWPLAYING_H + VOLUME_H   # header rows + now-playing + volume band + margin
```

4) After the media styling block, add the volume glyphs/font:
```python
VOL_GLYPH_FONT = ("Segoe UI Symbol", 12)
VOL_LOUD = "\U0001F50A"    # 🔊 speaker with sound waves
VOL_MUTED = "\U0001F507"   # 🔇 muted speaker
```

5) In `__init__`, append `+ VOLUME_H` to the `y3` (clock/expand) expression:
```python
        y3 = PAD + 5 * ROW_H + ROW_H // 2 + NOWPLAYING_H + VOLUME_H   # clock + expand, below now-playing + volume bands
```

6) In `__init__`, immediately AFTER the now-playing block (after `self._np_duration = 0.0`), add the volume band items:
```python
        # Volume band: reserved directly below the now-playing band. A mute glyph,
        # a draggable slider (track + fill + knob), and a right-aligned percent.
        vy = (ymedia + ROW_H // 2) + NOWPLAYING_H + VOLUME_H // 2   # under the np band
        self._vol_row_y = vy
        v_left, v_right = self._vol_bar_bounds()
        self._vol_bar_span = (v_left, v_right)
        self._vol_glyph = c.create_text(PAD, vy, anchor="w", text=VOL_LOUD,
                                        fill=FG, font=VOL_GLYPH_FONT)
        self._vol_bar_bg = c.create_rectangle(v_left, vy - VOL_BAR_H // 2, v_right,
                                              vy + VOL_BAR_H // 2, fill=NP_TRACK, outline="")
        self._vol_bar = c.create_rectangle(v_left, vy - VOL_BAR_H // 2, v_left,
                                           vy + VOL_BAR_H // 2, fill=ACCENT, outline="")
        self._vol_knob = c.create_oval(v_left - VOL_KNOB_R, vy - VOL_KNOB_R,
                                       v_left + VOL_KNOB_R, vy + VOL_KNOB_R,
                                       fill=FG, outline="")
        self._vol_pct = c.create_text(self.width - PAD, vy, anchor="e", text="",
                                      fill=DIM, font=NP_TIME_FONT)
        self._vol_level = None       # 0..1, or None until first read
        self._vol_muted = False
        self._vol_dragging = False
        self._vol_press_glyph = False
        self._vol_apply_at = 0.0     # monotonic time of last COM write (drag throttle)
```

7) In `tick`, after `self._draw_nowplaying()`:
```python
        self._draw_nowplaying()
        self._refresh_volume()
        self._draw_volume()
```

8) Append `+ VOLUME_H` to the feed-column top in `_draw_feeds` (already `+ NOWPLAYING_H`):
```python
        y = PAD + 6 * ROW_H + 4 + NOWPLAYING_H + VOLUME_H    # below header rows + now-playing + volume bands
```

9) Add the methods (place near `_draw_nowplaying`):
```python
    def _vol_bar_bounds(self):
        """(x_left, x_right) of the slider track, inset for the glyph and percent."""
        return PAD + VOL_GLYPH_W, self.width - PAD - VOL_PCT_W

    def _refresh_volume(self):
        """Pull the live system level/mute (main-thread; the call is fast). Skipped
        while the user is dragging so the optimistic drag value is not clobbered."""
        if self._vol_dragging:
            return
        v = audiovolume.get()
        if v is not None:
            self._vol_level, self._vol_muted = v

    def _draw_volume(self):
        """Render the slider fill, knob, mute glyph and percent from _vol_level /
        _vol_muted. Muted greys the fill and swaps the glyph (the knob stays put so
        unmuting restores the level). Blank until the first read. Never raises."""
        c = self.canvas
        vy = self._vol_row_y
        v_left, v_right = self._vol_bar_span
        try:
            if self._vol_level is None:
                c.itemconfig(self._vol_pct, text="")
                c.coords(self._vol_bar, v_left, vy - VOL_BAR_H // 2, v_left,
                         vy + VOL_BAR_H // 2)
                return
            frac = audiovolume.clamp01(self._vol_level)
            kx = v_left + int((v_right - v_left) * frac)
            c.coords(self._vol_bar, v_left, vy - VOL_BAR_H // 2, kx, vy + VOL_BAR_H // 2)
            c.itemconfig(self._vol_bar, fill=(DIM if self._vol_muted else ACCENT))
            c.coords(self._vol_knob, kx - VOL_KNOB_R, vy - VOL_KNOB_R,
                     kx + VOL_KNOB_R, vy + VOL_KNOB_R)
            c.itemconfig(self._vol_glyph, text=(VOL_MUTED if self._vol_muted else VOL_LOUD))
            c.itemconfig(self._vol_pct, text=audiovolume.format_pct(frac))
        except tk.TclError:
            pass
```

10) In `_relayout_header`, after the now-playing recenter block (after `self._np_bar_span = (b_left, b_right)`), add the volume recenter:
```python
        v_left, v_right = self._vol_bar_bounds()
        self._vol_bar_span = (v_left, v_right)
        vy = self._vol_row_y
        c.coords(self._vol_glyph, PAD, vy)
        c.coords(self._vol_bar_bg, v_left, vy - VOL_BAR_H // 2, v_right, vy + VOL_BAR_H // 2)
        c.coords(self._vol_pct, self.width - PAD, vy)
```

11) In `_toggle_width`, after `self._draw_nowplaying()`:
```python
        self._draw_nowplaying()  # re-fill bar + reposition time labels at the new width
        self._draw_volume()      # reposition slider fill/knob at the new width
```

- [ ] **Step 4: Run it, expect PASS.**

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudVolume -v`

- [ ] **Step 5: Run the existing HUD geometry suites** (layout shift must not regress now-playing/media/feed tests):

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudNowPlaying tests.test_smoke_hud.TestHudNowPlayingMarquee -v`

- [ ] **Step 6: Commit.**

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "Render volume slider + mute glyph under the now-playing band"
```

---

## Task 4: HUD volume interaction — drag / click / mute / wheel

Wire the slider up: a press on the track drags the level (window does NOT move); a
press on the glyph toggles mute on release; the mouse wheel over the track nudges
±2%. Reuses the existing press/drag/release plumbing with volume checks in front.

**Files:** Modify `hud.pyw`; Test `tests/test_smoke_hud.py`.

**Interfaces:**
- Consumes: `winkit.audiovolume` (`level_from_x`, `set_level`, `set_mute`,
  `step_level`, `clamp01`); existing `_on_press`, `_on_drag`, `_on_release`,
  the canvas event bindings.
- Produces (on `Hud`): `_vol_hit`, `_vol_glyph_hit`, `_vol_set_from_x`,
  `_toggle_mute`, `_on_wheel`; volume gating inside `_on_press`/`_on_drag`/`_on_release`.

### Steps

- [ ] **Step 1: Write the failing test** — append to `tests/test_smoke_hud.py` before the final `if __name__` (same `TestHudVolume` patching applies, so put these in a second class that reuses it):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudVolumeInteraction(TestHudVolume):
    def _ev(self, x, y, x_root=0, y_root=0, delta=0):
        return type("E", (), {"x": x, "y": y, "x_root": x_root, "y_root": y_root,
                              "delta": delta})()

    def test_drag_sets_level_and_does_not_move_window(self):
        root, hud = self._make_hud([])
        try:
            root.update_idletasks()
            geo_before = root.geometry()
            v_left, v_right = hud._vol_bar_span
            vy = hud._vol_row_y
            hud._on_press(self._ev(v_left, vy, x_root=500, y_root=500))
            self.assertTrue(hud._vol_dragging)
            quarter = v_left + (v_right - v_left) // 4
            hud._on_drag(self._ev(quarter, vy, x_root=400, y_root=500))
            self.assertAlmostEqual(hud._vol_level, 0.25, delta=0.05)
            self.assertEqual(root.geometry(), geo_before)     # window did NOT move
            self.assertTrue(self.vol_sets)                    # a real set was requested
            hud._on_release(self._ev(quarter, vy))
            self.assertFalse(hud._vol_dragging)
        finally:
            hud.close(); root.destroy()

    def test_click_on_track_jumps_to_that_level(self):
        root, hud = self._make_hud([])
        try:
            v_left, v_right = hud._vol_bar_span
            vy = hud._vol_row_y
            three_q = v_left + 3 * (v_right - v_left) // 4
            hud._on_press(self._ev(three_q, vy, x_root=1, y_root=1))
            hud._on_release(self._ev(three_q, vy))
            self.assertAlmostEqual(hud._vol_level, 0.75, delta=0.05)
        finally:
            hud.close(); root.destroy()

    def test_glyph_click_toggles_mute(self):
        root, hud = self._make_hud([])
        try:
            hud._vol_muted = False
            gx, vy = PAD_X(hud), hud._vol_row_y
            hud._on_press(self._ev(gx, vy, x_root=1, y_root=1))
            self.assertTrue(hud._vol_press_glyph)
            hud._moved = False
            hud._on_release(self._ev(gx, vy))
            self.assertTrue(hud._vol_muted)
            self.assertEqual(self.mute_sets[-1], True)
        finally:
            hud.close(); root.destroy()

    def test_wheel_over_track_nudges_level(self):
        root, hud = self._make_hud([])
        try:
            hud._vol_level = 0.50; hud._vol_muted = False
            v_left, v_right = hud._vol_bar_span
            mid = (v_left + v_right) // 2
            hud._on_wheel(self._ev(mid, hud._vol_row_y, delta=120))
            self.assertAlmostEqual(hud._vol_level, 0.52, delta=0.001)
            hud._on_wheel(self._ev(mid, hud._vol_row_y, delta=-120))
            self.assertAlmostEqual(hud._vol_level, 0.50, delta=0.001)
        finally:
            hud.close(); root.destroy()

    def test_wheel_off_track_is_ignored(self):
        root, hud = self._make_hud([])
        try:
            hud._vol_level = 0.50
            hud._on_wheel(self._ev(5, 100000, delta=120))     # far below the row
            self.assertAlmostEqual(hud._vol_level, 0.50)
        finally:
            hud.close(); root.destroy()
```

Add this module-level helper near the top of `tests/test_smoke_hud.py` (after `hud_mid_x`):
```python
def PAD_X(hud):
    import hud as hudmod
    return hudmod.PAD
```

- [ ] **Step 2: Run it, expect FAIL** — `AttributeError: 'Hud' object has no attribute '_vol_hit'` / `_on_wheel`.

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudVolumeInteraction -v`

- [ ] **Step 3: Implement** — edits to `hud.pyw`:

1) Bind the wheel in the canvas-bindings loop in `__init__` (inside `for w in (self.canvas,):`), add:
```python
            w.bind("<MouseWheel>", self._on_wheel)
```

2) Replace `_on_press` so a slider/glyph press is intercepted before window-drag:
```python
    def _on_press(self, event):
        self._moved = False
        self._vol_dragging = False
        self._vol_press_glyph = self._vol_glyph_hit(event.x, event.y)
        self._drag_dx = event.x_root - self.root.winfo_x()
        self._drag_dy = event.y_root - self.root.winfo_y()
        if not self._vol_press_glyph and self._vol_hit(event.x, event.y):
            self._vol_dragging = True
            self._vol_set_from_x(event.x)
```

3) At the TOP of `_on_drag`, intercept an active slider drag (do NOT move the window):
```python
    def _on_drag(self, event):
        if self._vol_dragging:
            self._vol_set_from_x(event.x)
            return
        if self.lock_var.get():
            return  # position is locked
        ...unchanged...
```

4) At the TOP of `_on_release`, finalize a slider drag / handle a glyph click:
```python
    def _on_release(self, event):
        if self._vol_dragging:
            self._vol_dragging = False
            try:
                audiovolume.set_level(audiovolume.clamp01(self._vol_level))  # final position sticks
            except Exception:
                pass
            return
        if self._vol_press_glyph:
            self._vol_press_glyph = False
            if not self._moved and self._vol_glyph_hit(event.x, event.y):
                self._toggle_mute()
                return
        ...unchanged (the existing `if not self._moved:` block onward)...
```

5) Add the volume interaction methods (near `_draw_volume`):
```python
    def _vol_hit(self, x, y):
        """True if (x, y) is on the slider track (a generous vertical band)."""
        v_left, v_right = self._vol_bar_span
        return (v_left - 8 <= x <= v_right + 8 and
                self._vol_row_y - (VOL_KNOB_R + 5) <= y <= self._vol_row_y + (VOL_KNOB_R + 5))

    def _vol_glyph_hit(self, x, y):
        """True if (x, y) is on the mute/speaker glyph at the row's left."""
        return (PAD - 2 <= x <= PAD + VOL_GLYPH_W - 2 and
                self._vol_row_y - 10 <= y <= self._vol_row_y + 10)

    def _vol_set_from_x(self, x):
        """Set the level from a click/drag x: update the shown value immediately,
        unmute if muted (matches Windows), and write to the device (throttled to
        ~30 ms so a fast drag doesn't hammer COM)."""
        v_left, v_right = self._vol_bar_span
        frac = audiovolume.level_from_x(x, v_left, v_right)
        self._vol_level = frac
        if self._vol_muted:
            self._vol_muted = False
            audiovolume.set_mute(False)
        self._draw_volume()
        now = time.monotonic()
        if now - self._vol_apply_at >= 0.03:
            audiovolume.set_level(frac)
            self._vol_apply_at = now

    def _toggle_mute(self):
        self._vol_muted = not self._vol_muted
        audiovolume.set_mute(self._vol_muted)
        self._draw_volume()

    def _on_wheel(self, event):
        """Mouse wheel over the track nudges the level +/-2% per notch. Ignored
        elsewhere. Unmutes on a nudge up."""
        if not self._vol_hit(event.x, event.y):
            return
        step = 0.02 if getattr(event, "delta", 0) > 0 else -0.02
        base = self._vol_level if self._vol_level is not None else 0.0
        self._vol_level = audiovolume.step_level(base, step)
        if self._vol_muted and step > 0:
            self._vol_muted = False
            audiovolume.set_mute(False)
        audiovolume.set_level(self._vol_level)
        self._draw_volume()
```

- [ ] **Step 4: Run it, expect PASS.**

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudVolume tests.test_smoke_hud.TestHudVolumeInteraction -v`

- [ ] **Step 5: Run the full HUD suite + the audiovolume suite** (no regressions; window-drag / media / seek still work):

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud tests.test_audiovolume -v`

- [ ] **Step 6: Commit.**

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "Wire volume slider drag/click/wheel + mute-glyph toggle"
```

---

## Self-Review

- **Spec coverage:** slider (Task 3 render + Task 4 drag/click) ✓; mute/unmute (glyph toggle, Task 4; greyed fill, Task 3) ✓; live % (Task 3) ✓; reflects external changes (`_refresh_volume` 1 Hz, Task 3) ✓; Core Audio backend (Task 2) ✓; placement under now-playing band (Task 3) ✓; wide-mode (Task 3 `_relayout_header`) ✓.
- **No real-device mutation in tests:** `TestHudVolume` patches `set_level`/`set_mute`/`get`; the audiovolume smoke test only reads or restores-to-current. ✓
- **Never raises:** all COM behind `_with_epv` blanket try/except; every HUD draw guarded with `tk.TclError`. ✓
- **No config writes:** volume path never calls `_save`/`config.update`. ✓
- **Type consistency:** `get()` returns `(float, bool)|None` everywhere consumed; `_vol_level` is `float|None`; `_vol_bar_span` is `(int, int)`. ✓
- **Manual check after Task 4:** launch `py hud.pyw`, drag the slider (audio changes, window stays put), click the speaker (mutes/greys), scroll over it (±2%), toggle wide mode (slider widens).
