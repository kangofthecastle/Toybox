# HUD GPU usage row + media controls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live GPU-utilization row and a play/pause/next/prev media-control row to the System Monitor HUD.

**Architecture:** Follows the existing split — pure aggregation math in `sysmetrics.py`, Win32 `ctypes` in `winkit/`, and `hud.pyw` wiring canvas items. GPU% comes from PDH `\GPU Engine(*)\Utilization Percentage` counters; media controls synthesize system media virtual-keys. Both header rows are always visible; GPU degrades to a dim `GPU --%` when no counters exist.

**Tech Stack:** Python 3.12 stdlib only — `tkinter`, `ctypes` (on `pdh.dll` and `user32.dll`). No pip.

## Global Constraints

- Pure Python 3.12 stdlib only — **no pip, ever**.
- Win32 stays in `winkit/`: GPU PDH ctypes join `winkit/metrics.py` (next to `CpuSampler`); media ctypes go in new `winkit/media.py`. Pure GPU aggregation lives in `sysmetrics.py` (no ctypes, no Tk).
- GPU sampling must **never crash the tick**: every PDH failure path returns `None` → HUD renders `GPU --%`.
- Media calls are best-effort: swallow exceptions (an unconsumed media key is a no-op).
- Media glyphs render in **Segoe UI Symbol** (Consolas lacks them).
- Both new rows are always on — no config keys, no menu items.
- TDD: write the failing test first, watch it fail, minimal code to pass. Commit after each task.
- **Test runner** (bare `python` is a broken MS-Store stub → exit 49). Run all commands from the repo root `C:\Users\Warren\Toybox`:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`
- End every commit message with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

## File Structure

- `sysmetrics.py` — **modify**: add pure `gpu_percent(instances)`.
- `winkit/metrics.py` — **modify**: add PDH structs/signatures + `GpuSampler`.
- `winkit/media.py` — **create**: `play_pause()`, `next_track()`, `prev_track()`.
- `hud.pyw` — **modify**: GPU row + media row (constants, state, render, click).
- `tests/test_sysmetrics.py` — **modify**: `TestGpuPercent`.
- `tests/test_gpu_sampler.py` — **create**: Windows-only `GpuSampler` smoke.
- `tests/test_media.py` — **create**: media VK-code assertions.
- `tests/test_smoke_hud.py` — **modify**: GPU row + media row rendering/click tests.

---

### Task 1: Pure GPU aggregation — `sysmetrics.gpu_percent`

**Files:**
- Modify: `sysmetrics.py`
- Test: `tests/test_sysmetrics.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `gpu_percent(instances) -> float | None` — `instances` is an iterable of `(instance_name, value)` pairs where `instance_name` is a PDH GPU-Engine instance string containing an `engtype_<Type>` token. Sums `value`s per engine type, returns the max type-sum clamped to `[0, 100]`, or `None` when no `engtype`-bearing instance is present.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sysmetrics.py` (before the `if __name__` block):

```python
from sysmetrics import gpu_percent


class TestGpuPercent(unittest.TestCase):
    # instance names mimic PDH: "..._eng_N_engtype_<Type>"
    def _n(self, engtype, eng=0):
        return "pid_100_luid_0x0_0x1_phys_0_eng_%d_engtype_%s" % (eng, engtype)

    def test_single_engine(self):
        self.assertAlmostEqual(gpu_percent([(self._n("3D"), 40.0)]), 40.0)

    def test_sums_within_a_type(self):
        # two Copy engines: 30 + 25 = 55
        pairs = [(self._n("Copy", 13), 30.0), (self._n("Copy", 14), 25.0)]
        self.assertAlmostEqual(gpu_percent(pairs), 55.0)

    def test_max_across_types_wins(self):
        pairs = [(self._n("3D"), 40.0),
                 (self._n("Copy", 13), 30.0), (self._n("Copy", 14), 25.0)]  # Copy=55 > 3D=40
        self.assertAlmostEqual(gpu_percent(pairs), 55.0)

    def test_clamped_to_100(self):
        pairs = [(self._n("3D", 0), 60.0), (self._n("3D", 1), 60.0)]  # 120 -> 100
        self.assertAlmostEqual(gpu_percent(pairs), 100.0)

    def test_empty_is_none(self):
        self.assertIsNone(gpu_percent([]))

    def test_instances_without_engtype_are_ignored(self):
        self.assertIsNone(gpu_percent([("pid_1_luid_no_marker", 99.0)]))

    def test_mixed_ignores_non_engtype(self):
        pairs = [("no_marker_here", 99.0), (self._n("3D"), 10.0)]
        self.assertAlmostEqual(gpu_percent(pairs), 10.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_sysmetrics.TestGpuPercent -v`
Expected: FAIL — `ImportError: cannot import name 'gpu_percent'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `sysmetrics.py`:

```python
def gpu_percent(instances):
    """Aggregate Windows GPU Engine utilization into one 0..100 percentage.

    `instances` is an iterable of (instance_name, value) pairs. Each name is a
    PDH "\\GPU Engine(...)" instance carrying an `engtype_<Type>` token; value is
    that instance's Utilization Percentage. Utilizations are summed per engine
    type (there are often several Copy engines) and the busiest engine type wins
    -- approximating Task Manager's GPU%. Returns a float in [0, 100], or None
    when no engtype-bearing instance is present.
    """
    marker = "engtype_"
    totals = {}
    for name, value in instances:
        i = name.rfind(marker)
        if i == -1:
            continue
        engtype = name[i + len(marker):]
        totals[engtype] = totals.get(engtype, 0.0) + value
    if not totals:
        return None
    return max(0.0, min(100.0, max(totals.values())))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_sysmetrics -v`
Expected: PASS (the new `TestGpuPercent` cases plus the existing `TestCpuPercent`).

- [ ] **Step 5: Commit**

```bash
git add sysmetrics.py tests/test_sysmetrics.py
git commit -m "feat(sysmetrics): gpu_percent pure aggregation (sum per engtype, max, clamp)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: GPU sampler — `winkit/metrics.GpuSampler`

**Files:**
- Modify: `winkit/metrics.py`
- Test: `tests/test_gpu_sampler.py` (create)

**Interfaces:**
- Consumes: `sysmetrics.gpu_percent` (Task 1).
- Produces: `metrics.GpuSampler()` with `sample() -> float | None`. First `sample()` after construction may read low/0 (utilization counters are time-based; `__init__` takes the baseline). Returns `None` — never raises — when GPU counters are unavailable.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gpu_sampler.py`:

```python
import os
import unittest


@unittest.skipUnless(os.name == "nt", "Windows only (PDH ctypes)")
class TestGpuSampler(unittest.TestCase):
    def test_sample_returns_float_or_none_and_never_raises(self):
        import winkit.metrics as metrics
        s = metrics.GpuSampler()
        for _ in range(2):                 # first is the baseline, second reads
            v = s.sample()
            self.assertTrue(v is None or isinstance(v, float))
            if isinstance(v, float):
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 100.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_gpu_sampler -v`
Expected: FAIL — `AttributeError: module 'winkit.metrics' has no attribute 'GpuSampler'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `winkit/metrics.py`:

```python
# --- GPU utilization via PDH GPU Engine counters --------------------------
_pdh = ctypes.WinDLL("pdh", use_last_error=True)

PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2
_GPU_COUNTER_PATH = r"\GPU Engine(*)\Utilization Percentage"
_PDH_VALID_CSTATUS = (0x00000000, 0x00000001)  # VALID_DATA, NEW_DATA


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    # DWORD CStatus; then an 8-byte union -> ctypes pads to align the double at 8.
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _PDH_FMT_COUNTERVALUE)]


_pdh.PdhOpenQueryW.restype = wintypes.DWORD
_pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_void_p)]
_pdh.PdhAddEnglishCounterW.restype = wintypes.DWORD
_pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                       ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_pdh.PdhCollectQueryData.restype = wintypes.DWORD
_pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
_pdh.PdhGetFormattedCounterArrayW.restype = wintypes.DWORD
_pdh.PdhGetFormattedCounterArrayW.argtypes = [
    ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]


class GpuSampler:
    """Stateful GPU-utilization sampler over the PDH GPU Engine counters.

    sample() returns a 0..100 float, or None when GPU counters are unavailable
    (the HUD then shows 'GPU --%'). Never raises. Mirrors CpuSampler: __init__
    opens the query and takes a baseline collect, so the first sample() may read
    low until two collections span an interval."""

    def __init__(self):
        self._query = None
        self._counter = None
        try:
            hq = ctypes.c_void_p()
            if _pdh.PdhOpenQueryW(None, 0, ctypes.byref(hq)) != 0:
                return
            hc = ctypes.c_void_p()
            if _pdh.PdhAddEnglishCounterW(hq, _GPU_COUNTER_PATH, 0, ctypes.byref(hc)) != 0:
                return
            _pdh.PdhCollectQueryData(hq)   # baseline for the rate counter
            self._query = hq
            self._counter = hc
        except Exception:
            self._query = None
            self._counter = None

    def sample(self):
        if self._query is None or self._counter is None:
            return None
        try:
            if _pdh.PdhCollectQueryData(self._query) != 0:
                return None
            size = wintypes.DWORD(0)
            count = wintypes.DWORD(0)
            status = _pdh.PdhGetFormattedCounterArrayW(
                self._counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None)
            if status != PDH_MORE_DATA or size.value == 0:
                return None
            buf = (ctypes.c_byte * size.value)()
            status = _pdh.PdhGetFormattedCounterArrayW(
                self._counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count),
                ctypes.cast(buf, ctypes.c_void_p))
            if status != 0:
                return None
            items = ctypes.cast(buf, ctypes.POINTER(_PDH_FMT_COUNTERVALUE_ITEM_W))
            pairs = []
            for i in range(count.value):
                it = items[i]
                if it.FmtValue.CStatus in _PDH_VALID_CSTATUS and it.szName:
                    pairs.append((it.szName, it.FmtValue.doubleValue))
            return sysmetrics.gpu_percent(pairs)
        except Exception:
            return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_gpu_sampler -v`
Expected: PASS (this machine has GPU Engine counters, so `sample()` returns a float in `[0, 100]`; a machine without them would return `None` and still pass).

- [ ] **Step 5: Commit**

```bash
git add winkit/metrics.py tests/test_gpu_sampler.py
git commit -m "feat(winkit): GpuSampler reads PDH \GPU Engine utilization

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: HUD GPU row (layout + render + tick)

**Files:**
- Modify: `hud.pyw`
- Test: `tests/test_smoke_hud.py`

**Interfaces:**
- Consumes: `metrics.GpuSampler` (Task 2), the existing `_update_spark`.
- Produces: HUD state `self.gpu` (float | None), `self.gpu_hist`, canvas item `self._gpu_text`, sparkline `self._gpu_line`, band `self._gpu_band`. Header is now 4 rows (CPU / RAM / GPU / clock); feeds baseline moves to `PAD + 4 * ROW_H + 4`; `HEIGHT` becomes `112`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_smoke_hud.py` (append before the `if __name__` block):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudGpuRow(_HudTestBase):
    def _texts(self, hud):
        return [hud.canvas.itemcget(i, "text") for i in hud.canvas.find_all()
                if hud.canvas.type(i) == "text"]

    def test_gpu_row_shows_percent(self):
        root, hud = self._make_hud([])
        try:
            hud.gpu = 42.0
            hud._draw()
            self.assertTrue(any("GPU" in t and "42" in t for t in self._texts(hud)))
        finally:
            hud.close(); root.destroy()

    def test_gpu_row_degrades_when_none(self):
        root, hud = self._make_hud([])
        try:
            hud.gpu = None
            hud._draw()
            self.assertEqual(hud.canvas.itemcget(hud._gpu_text, "text"), "GPU  --%")
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudGpuRow -v`
Expected: FAIL — `AttributeError: 'Hud' object has no attribute 'gpu'` (or `_gpu_text`).

- [ ] **Step 3a: Add the GPU color constant**

In `hud.pyw`, modify the color block (currently lines ~42-43):

```python
CPU_COLOR = "#33d6ff"  # cyan
RAM_COLOR = "#ff5cc8"  # magenta
GPU_COLOR = "#7ee787"  # green
```

- [ ] **Step 3b: Bump HEIGHT**

Change the `HEIGHT` constant (line ~30):

```python
HEIGHT = 112          # 4 header rows (CPU/RAM/GPU/clock) + margin
```

- [ ] **Step 3c: Add GPU state in `__init__`**

In `Hud.__init__`, after the `self.ram_hist` / `self.ram` lines (~89-92), add:

```python
        self.gpu_sampler = metrics.GpuSampler()
        self.gpu_hist = collections.deque(maxlen=HISTORY)
        self.gpu = None
```

- [ ] **Step 3d: Insert the GPU row into the persistent canvas layout**

Replace the row-position/creation block in `__init__` (currently):

```python
        y1 = PAD + ROW_H // 2
        y2 = PAD + ROW_H + ROW_H // 2
        y3 = PAD + 2 * ROW_H + ROW_H // 2
        self._cpu_text = c.create_text(LABEL_X, y1, anchor="w", text="CPU   0%", fill=FG, font=FONT)
        self._ram_text = c.create_text(LABEL_X, y2, anchor="w", text="RAM   0%", fill=FG, font=FONT)
        self._clock_text = c.create_text(WIDTH // 2, y3, anchor="center", text="", fill=DIM, font=CLOCK_FONT)
```

with (GPU becomes row 3, clock shifts to row 4):

```python
        y1 = PAD + ROW_H // 2
        y2 = PAD + ROW_H + ROW_H // 2
        ygpu = PAD + 2 * ROW_H + ROW_H // 2
        y3 = PAD + 3 * ROW_H + ROW_H // 2
        self._cpu_text = c.create_text(LABEL_X, y1, anchor="w", text="CPU   0%", fill=FG, font=FONT)
        self._ram_text = c.create_text(LABEL_X, y2, anchor="w", text="RAM   0%", fill=FG, font=FONT)
        self._gpu_text = c.create_text(LABEL_X, ygpu, anchor="w", text="GPU   0%", fill=FG, font=FONT)
        self._clock_text = c.create_text(WIDTH // 2, y3, anchor="center", text="", fill=DIM, font=CLOCK_FONT)
```

Then, just after the `self._ram_line = ...` / `self._cpu_band` / `self._ram_band` block (~132-135), add the GPU sparkline + band:

```python
        self._gpu_line = c.create_line(0, 0, 0, 0, fill=GPU_COLOR, width=1, state="hidden")
        self._gpu_band = (PAD + 2 * ROW_H + 1, PAD + 3 * ROW_H - 1)
```

(The `_reload_item` / `_reload_box` are computed from `y3`, so they follow the clock down automatically — no change needed.)

- [ ] **Step 3e: Sample GPU in `tick`**

In `tick`, after `self.ram_hist.append(self.ram)` (~266), add:

```python
        self.gpu = self.gpu_sampler.sample()
        if self.gpu is not None:
            self.gpu_hist.append(self.gpu)
```

- [ ] **Step 3f: Render the GPU row in `_draw`**

In `_draw`, after the `RAM` `itemconfig` line (~273), add the GPU text + sparkline:

```python
        if self.gpu is None:
            c.itemconfig(self._gpu_text, text="GPU  --%", fill=DIM)
        else:
            c.itemconfig(self._gpu_text, text=f"GPU {self.gpu:3.0f}%", fill=FG)
        self._update_spark(self._gpu_line, self.gpu_hist, self._gpu_band)
```

- [ ] **Step 3g: Move the feeds baseline down one row**

In `_draw_feeds`, change (line ~426):

```python
        y = PAD + 3 * ROW_H + 4
```

to:

```python
        y = PAD + 4 * ROW_H + 4
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS — `TestHudGpuRow` passes and every pre-existing HUD test (feeds, notifications, search, clicks, scoped-save, smoke launch) still passes.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): live GPU% row with sparkline (dim 'GPU --%' when no counters)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Media controls module — `winkit/media.py`

**Files:**
- Create: `winkit/media.py`
- Test: `tests/test_media.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `winkit.media.play_pause()`, `next_track()`, `prev_track()` — each taps a media virtual-key (keydown+keyup) and swallows errors. Internal seam `_keybd_event(vk, flags)` is the single ctypes call, monkeypatched by tests.

- [ ] **Step 1: Write the failing test**

Create `tests/test_media.py`:

```python
import os
import unittest


@unittest.skipUnless(os.name == "nt", "Windows only (user32 ctypes)")
class TestMedia(unittest.TestCase):
    def setUp(self):
        import winkit.media as media
        self.media = media
        self.calls = []
        self._orig = media._keybd_event
        media._keybd_event = lambda vk, flags: self.calls.append((vk, flags))
        self.addCleanup(setattr, media, "_keybd_event", self._orig)

    def test_play_pause_taps_playpause_vk_down_then_up(self):
        self.media.play_pause()
        self.assertEqual(self.calls,
                         [(0xB3, 0), (0xB3, self.media.KEYEVENTF_KEYUP)])

    def test_next_track_taps_next_vk(self):
        self.media.next_track()
        self.assertEqual(self.calls,
                         [(0xB0, 0), (0xB0, self.media.KEYEVENTF_KEYUP)])

    def test_prev_track_taps_prev_vk(self):
        self.media.prev_track()
        self.assertEqual(self.calls,
                         [(0xB1, 0), (0xB1, self.media.KEYEVENTF_KEYUP)])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_media -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'winkit.media'`.

- [ ] **Step 3: Write the minimal implementation**

Create `winkit/media.py`:

```python
"""System media controls: play/pause, next, and previous track via the media
virtual-keys (WM_APPCOMMAND equivalents). Player-agnostic; no now-playing state
is read. Pure ctypes on user32 -- no pip."""
import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD,
                                ctypes.c_void_p]
_user32.keybd_event.restype = None

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002


def _keybd_event(vk, flags):
    """Single ctypes call (the test seam). Swallows failures -- a media key no
    app consumes is a harmless no-op, never a crash."""
    try:
        _user32.keybd_event(vk, 0, flags, 0)
    except Exception:
        pass


def _tap(vk):
    _keybd_event(vk, 0)
    _keybd_event(vk, KEYEVENTF_KEYUP)


def play_pause():
    _tap(VK_MEDIA_PLAY_PAUSE)


def next_track():
    _tap(VK_MEDIA_NEXT_TRACK)


def prev_track():
    _tap(VK_MEDIA_PREV_TRACK)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_media -v`
Expected: PASS — all three VK taps recorded as down (flags 0) then up (`KEYEVENTF_KEYUP`).

- [ ] **Step 5: Commit**

```bash
git add winkit/media.py tests/test_media.py
git commit -m "feat(winkit): media.py play_pause/next/prev via media VKs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: HUD media-controls row

**Files:**
- Modify: `hud.pyw`
- Test: `tests/test_smoke_hud.py`

**Interfaces:**
- Consumes: `winkit.media` (Task 4); the existing `_on_release` non-drag click path and `_in_reload` pattern.
- Produces: canvas items `self._media_prev` / `self._media_play` / `self._media_next`; `self._media_hits` (list of `(x0, x1, y0, y1, key)` with `key` in `"prev"|"playpause"|"next"`); methods `_media_at(x, y)` and `_do_media(key)`. Header becomes 5 rows; feeds baseline moves to `PAD + 5 * ROW_H + 4`; `HEIGHT` becomes `134`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_smoke_hud.py` (append before the `if __name__` block):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudMediaRow(_HudTestBase):
    def _texts(self, hud):
        return [hud.canvas.itemcget(i, "text") for i in hud.canvas.find_all()
                if hud.canvas.type(i) == "text"]

    def test_media_glyphs_rendered(self):
        root, hud = self._make_hud([])
        try:
            texts = self._texts(hud)
            for g in ("⏮", "⏯", "⏭"):
                self.assertIn(g, texts)
        finally:
            hud.close(); root.destroy()

    def test_media_clicks_call_controls_in_order(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            calls = []
            with mock.patch.object(hudmod.media, "prev_track", lambda: calls.append("prev")), \
                 mock.patch.object(hudmod.media, "play_pause", lambda: calls.append("playpause")), \
                 mock.patch.object(hudmod.media, "next_track", lambda: calls.append("next")):
                for (x0, x1, y0, y1, key) in hud._media_hits:
                    ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
                    hud._moved = False
                    hud._on_release(ev)
            self.assertEqual(sorted(calls), ["next", "playpause", "prev"])
            self.assertEqual(len(calls), 3)
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudMediaRow -v`
Expected: FAIL — `AttributeError: 'Hud' object has no attribute '_media_hits'` (and `hud.media` unset).

- [ ] **Step 3a: Import the media module and add glyph/font constants**

In `hud.pyw`, add to the imports (after `import winkit.metrics as metrics`, ~17):

```python
import winkit.media as media
```

Add near the font constants (after `CLOCK_FONT`, ~45):

```python
MEDIA_FONT = ("Segoe UI Symbol", 12)
MEDIA_PREV = "⏮"
MEDIA_PLAY = "⏯"
MEDIA_NEXT = "⏭"
```

- [ ] **Step 3b: Bump HEIGHT to fit the 5th row**

Change the `HEIGHT` constant:

```python
HEIGHT = 134          # 5 header rows (CPU/RAM/GPU/clock/media) + margin
```

- [ ] **Step 3c: Create the media row in `__init__`**

In `Hud.__init__`, immediately after the GPU sparkline/band block added in Task 3 (`self._gpu_band = ...`), add:

```python
        ymedia = PAD + 4 * ROW_H + ROW_H // 2
        cx = WIDTH // 2
        gap = 44
        self._media_prev = c.create_text(cx - gap, ymedia, text=MEDIA_PREV, fill=FG, font=MEDIA_FONT)
        self._media_play = c.create_text(cx, ymedia, text=MEDIA_PLAY, fill=FG, font=MEDIA_FONT)
        self._media_next = c.create_text(cx + gap, ymedia, text=MEDIA_NEXT, fill=FG, font=MEDIA_FONT)
        half = ACTION_ZONE_W
        self._media_hits = [
            (cx - gap - half, cx - gap + half, ymedia - 11, ymedia + 11, "prev"),
            (cx - half,       cx + half,       ymedia - 11, ymedia + 11, "playpause"),
            (cx + gap - half, cx + gap + half, ymedia - 11, ymedia + 11, "next"),
        ]
```

- [ ] **Step 3d: Handle media clicks in `_on_release`**

In `_on_release`, inside the `if not self._moved:` block, right after the reload-control check (the `if self._in_reload(...)` block, ~185-187), add:

```python
            key = self._media_at(event.x, event.y)     # media glyph zones
            if key is not None:
                self._do_media(key)
                return
```

- [ ] **Step 3e: Add the media hit-test and dispatch methods**

Add these two methods to `Hud` (e.g. right after `_in_reload`, ~209):

```python
    def _media_at(self, x, y):
        """Return the media-control key at (x, y) among the three fixed glyph
        zones, or None. Boxes are constants (persistent glyphs), like _reload_box."""
        for x0, x1, y0, y1, key in self._media_hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return key
        return None

    def _do_media(self, key):
        """Dispatch a media-control click to winkit.media (looked up as a module
        attribute so tests can monkeypatch it)."""
        if key == "prev":
            media.prev_track()
        elif key == "playpause":
            media.play_pause()
        elif key == "next":
            media.next_track()
```

- [ ] **Step 3f: Move the feeds baseline down one more row**

In `_draw_feeds`, change (updated in Task 3 to `4 * ROW_H`):

```python
        y = PAD + 4 * ROW_H + 4
```

to:

```python
        y = PAD + 5 * ROW_H + 4
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS — `TestHudMediaRow` (glyphs render; each zone dispatches its control) plus all prior HUD tests including `TestHudGpuRow`.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): media controls row (prev/play-pause/next) sending media keys

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Full-suite run + manual verification + branch wrap

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -v`
Expected: PASS — the entire suite is green (new GPU/media tests + all pre-existing toy tests). No errors, no failures.

- [ ] **Step 2: Manually launch the HUD and eyeball the new rows**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/pythonw.exe hud.pyw`
Confirm by observation:
- A `GPU  NN%` row appears between RAM and the clock, its number changes over a few seconds, and a green sparkline scrolls.
- The `⏮ ⏯ ⏭` glyphs render as real media symbols (not tofu boxes ▯). If they are tofu, the font fallback failed — revisit `MEDIA_FONT`.
- Start a track (Spotify / browser), then click `⏯` (pauses/resumes), `⏭` (next), `⏮` (prev). Each affects playback.
- Drag the HUD by the media row — it still moves the window (a drag is not a media click).

Close the HUD (right-click → Close) when done.

- [ ] **Step 3: Verify the branch state**

Run: `git log --oneline main..hud-gpu-and-media`
Expected: the spec commit plus the five feature commits (Tasks 1-5), in order.

- [ ] **Step 4: Finish the branch**

Invoke the `superpowers:finishing-a-development-branch` skill to choose how to integrate (merge / PR / cleanup).

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:
- GPU pure aggregation (`sysmetrics.gpu_percent`, sum-per-engtype/max/clamp/None) → Task 1.
- `GpuSampler` PDH ctypes, baseline collect, graceful `None` → Task 2.
- HUD GPU row (state, layout shift, render, degraded `GPU --%`, tick append-only-when-float) → Task 3.
- `winkit/media.py` VKs via `keybd_event` → Task 4.
- HUD media row (glyphs in Segoe UI Symbol, non-drag click zones, dispatch) → Task 5.
- Testing strategy (pure `gpu_percent`, VK-code assertions, extended HUD smoke) → Tasks 1/4 tests + Tasks 3/5 tests + Task 6 full run.
- Non-goals (no metadata, no temp/disk/fan, no toggles) → nothing implements them; confirmed absent.

**2. Placeholder scan** — no `TBD`/`TODO`/"handle edge cases"/"similar to Task N"; every code step contains complete code.

**3. Type consistency** — `gpu_percent(instances) -> float | None` is produced in Task 1 and consumed by `GpuSampler.sample` in Task 2 and `Hud.tick`/`_draw` in Task 3. `GpuSampler().sample()` name matches `CpuSampler().sample()`. Media names `play_pause`/`next_track`/`prev_track` and `KEYEVENTF_KEYUP` are defined in Task 4 and used verbatim by Task 5's `_do_media` and by both tasks' tests. `_media_hits` tuple shape `(x0, x1, y0, y1, key)` is identical in the Task 5 constructor, `_media_at`, and the Task 5 test. Feed baseline multiplier is `3→4` (Task 3) then `4→5` (Task 5); `HEIGHT` is `96→112` (Task 3) then `112→134` (Task 5) — consistent progressions.
