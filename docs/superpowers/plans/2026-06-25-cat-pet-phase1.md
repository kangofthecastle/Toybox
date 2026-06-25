# Cat Pet — Phase 1 "It's a cat" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the procedural vector-blob pet with an animated pixel-art **cat** sprite that keeps music reactivity (now a colored glow aura + hops), tracks the cursor with overlay pupils, shifts glow hue by time of day, and stays draggable/lightweight.

**Architecture:** A reusable `winkit/sprites.py` turns the cat PNG sheets into cached, nearest-neighbor-zoomed Tk frames. New pure-logic `petkit` modules supply the time-of-day persona (`persona.py`), the pupil-deflection math + per-frame eye anchors (`eyes.py`), and the pre-baked radial glow images (`glow.py`). `pet.pyw` is rewritten to compose them on the existing transparent color-key overlay: glow image behind, animated cat image, two tracking pupils in front.

**Tech Stack:** Python 3.12 stdlib only — tkinter (Tk 8.6 PhotoImage for PNG + `zoom`), ctypes (via existing `winkit`), `winsound` later. No third-party packages.

## Global Constraints

- **Pure Python 3.12 stdlib only** (tkinter + ctypes + winreg). **NO third-party packages** (no pip), no PIL/numpy.
- **Super lightweight** (hard requirement): per-frame work O(1); no per-frame pixel manipulation; adaptive 8↔30 fps preserved; all heavy work (glow image bake) is cached/one-time.
- **Windows 10**, single user session. Reuse the `winkit` package; do not duplicate its OS glue.
- Overlay transparent color key is `winkit.window.KEY_COLOR == "#010101"`; **never paint that exact color** except to mean "transparent."
- Sprite sheets are bundled in-repo under `assets/cat/` (do not read from the user's Downloads folder at runtime). Sheets are 32×32 frames, binary alpha (0/255).
- Tests use `unittest` (run with `python -m unittest`); there is no pytest. GUI/Win32 tests are Windows-only and may `skipTest` when Tk has no display.
- Interpreter for running tests: `C:\Users\Warren\AppData\Local\Programs\Python\Python312\python.exe`.

---

### Task 1: `winkit/sprites.py` — sprite-sheet frame loader + bundled assets

**Files:**
- Create: `assets/cat/Idle.png`, `assets/cat/Box3.png`, `assets/cat/drculacat.png` (copied from `C:\Users\Warren\Downloads\CatPackFree\CatPackFree\`)
- Create: `winkit/sprites.py`
- Test: `tests/test_sprites.py`

**Interfaces:**
- Produces: `SpriteSheet(master, path, frame_w=32, frame_h=32)` with attribute `frame_count: int` and method `frame(index: int, zoom: int = 1) -> tk.PhotoImage` (cached per `(index, zoom)`; `index` wraps mod `frame_count`).

- [ ] **Step 1: Bundle the assets**

```bash
mkdir -p "C:/Users/Warren/Toybox/assets/cat"
cp "C:/Users/Warren/Downloads/CatPackFree/CatPackFree/Idle.png" \
   "C:/Users/Warren/Downloads/CatPackFree/CatPackFree/Box3.png" \
   "C:/Users/Warren/Downloads/CatPackFree/CatPackFree/drculacat.png" \
   "C:/Users/Warren/Toybox/assets/cat/"
```
Expected: three PNGs present in `assets/cat/`.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_sprites.py
import os
import tkinter as tk
import unittest

import winkit.sprites as sprites

ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets", "cat")


class TestSpriteSheet(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as e:
            self.skipTest("no Tk/display: %s" % e)

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_idle_has_ten_frames(self):
        s = sprites.SpriteSheet(self.root, os.path.join(ASSETS, "Idle.png"))
        self.assertEqual(s.frame_count, 10)

    def test_frame_is_nearest_neighbor_zoomed(self):
        s = sprites.SpriteSheet(self.root, os.path.join(ASSETS, "Idle.png"))
        f = s.frame(0, zoom=4)
        self.assertEqual((f.width(), f.height()), (128, 128))

    def test_frame_is_cached(self):
        s = sprites.SpriteSheet(self.root, os.path.join(ASSETS, "Idle.png"))
        self.assertIs(s.frame(2, 4), s.frame(2, 4))

    def test_index_wraps(self):
        s = sprites.SpriteSheet(self.root, os.path.join(ASSETS, "Idle.png"))
        self.assertIs(s.frame(12, 4), s.frame(2, 4))  # 12 % 10 == 2


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run it, verify it fails**

Run: `python -m unittest tests.test_sprites -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'winkit.sprites'`.

- [ ] **Step 4: Implement `winkit/sprites.py`**

```python
"""Load a horizontal sprite sheet (PNG) into cached, nearest-neighbor-zoomed
Tk frames. Pure rendering glue: one PhotoImage per (frame, zoom). Binary-alpha
PNGs only (the cat pack), so frames need no alpha compositing. Tk 8.6+ (PNG)."""
import tkinter as tk


class SpriteSheet:
    def __init__(self, master, path, frame_w=32, frame_h=32):
        self._master = master
        self._sheet = tk.PhotoImage(master=master, file=path)
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.frame_count = self._sheet.width() // frame_w
        self._cache = {}

    def frame(self, index, zoom=1):
        index %= self.frame_count
        key = (index, zoom)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        fw, fh = self.frame_w, self.frame_h
        cell = tk.PhotoImage(master=self._master, width=fw, height=fh)
        x0 = index * fw
        # 'set' compositing copies source pixels (incl. alpha) verbatim.
        cell.tk.call(str(cell), "copy", str(self._sheet),
                     "-from", x0, 0, x0 + fw, fh, "-to", 0, 0,
                     "-compositingrule", "set")
        img = cell.zoom(zoom) if zoom > 1 else cell
        self._cache[key] = img
        return img
```

- [ ] **Step 5: Run it, verify it passes**

Run: `python -m unittest tests.test_sprites -v`
Expected: PASS (4 tests), or `skipped` if no display. Run full suite `python -m unittest discover -s tests -q` — still OK.

- [ ] **Step 6: Commit**

```bash
git add winkit/sprites.py tests/test_sprites.py assets/cat
git commit -F - <<'EOF'
Add winkit.sprites sheet loader + bundle cat sprite assets

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: `petkit/persona.py` — time-of-day persona (pure logic)

**Files:**
- Create: `petkit/__init__.py` (empty), `petkit/persona.py`
- Test: `tests/test_persona.py`

**Interfaces:**
- Produces: `band_name(hour: int) -> str` ("morning"|"day"|"evening"|"night"); `glow_rgb(hour: int) -> (int,int,int)`; `greeting(hour: int) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_persona.py
import unittest
import petkit.persona as persona


class TestPersona(unittest.TestCase):
    def test_band_boundaries(self):
        self.assertEqual(persona.band_name(0), "night")
        self.assertEqual(persona.band_name(4), "night")
        self.assertEqual(persona.band_name(5), "morning")
        self.assertEqual(persona.band_name(10), "morning")
        self.assertEqual(persona.band_name(11), "day")
        self.assertEqual(persona.band_name(16), "day")
        self.assertEqual(persona.band_name(17), "evening")
        self.assertEqual(persona.band_name(20), "evening")
        self.assertEqual(persona.band_name(21), "night")
        self.assertEqual(persona.band_name(23), "night")

    def test_glow_rgb_is_triple(self):
        rgb = persona.glow_rgb(13)
        self.assertEqual(len(rgb), 3)
        self.assertTrue(all(0 <= c <= 255 for c in rgb))

    def test_greeting_is_nonempty(self):
        self.assertTrue(persona.greeting(8))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python -m unittest tests.test_persona -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'petkit'`.

- [ ] **Step 3: Implement**

```python
# petkit/__init__.py
```
(empty file)

```python
# petkit/persona.py
"""Time-of-day persona: maps the wall clock to a glow hue + greeting tone.
Pure logic (hour injected) so it's unit-testable."""

# name -> (r, g, b, greeting)
_BANDS = {
    "morning": (255, 196, 120, "morning"),    # warm amber
    "day":     (120, 200, 255, "hello"),       # cool daylight blue
    "evening": (255, 140, 110, "evening"),     # sunset coral
    "night":   (150, 120, 255, "late night"),  # violet
}


def band_name(hour):
    if hour < 5 or hour >= 21:
        return "night"
    if hour < 11:
        return "morning"
    if hour < 17:
        return "day"
    return "evening"


def glow_rgb(hour):
    return _BANDS[band_name(hour)][:3]


def greeting(hour):
    return _BANDS[band_name(hour)][3]
```

- [ ] **Step 4: Run it, verify it passes**

Run: `python -m unittest tests.test_persona -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add petkit/__init__.py petkit/persona.py tests/test_persona.py
git commit -F - <<'EOF'
Add petkit.persona time-of-day glow palette

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: `petkit/eyes.py` — pupil deflection math + per-frame eye anchors

**Files:**
- Create: `petkit/eyes.py`
- Create: `tools/calibrate_eyes.py` (offline anchor generator)
- Test: `tests/test_eyes.py`

**Interfaces:**
- Produces: `pupil_offset(dx: float, dy: float, reach: float = 55.0, max_off: float = 1.4) -> (float, float)` — pupil offset in sprite px toward the cursor vector, clamped. `EYES: dict[str, list[tuple[tuple,tuple]]]` — `EYES["idle"]` is 10 `((lx,ly),(rx,ry))` anchor pairs in 32-space.

- [ ] **Step 1: Write the failing test (the pure deflection math)**

```python
# tests/test_eyes.py
import math
import unittest
import petkit.eyes as eyes


class TestPupilOffset(unittest.TestCase):
    def test_centered_cursor_no_offset(self):
        self.assertEqual(eyes.pupil_offset(0.0, 0.0), (0.0, 0.0))

    def test_points_toward_cursor(self):
        ox, oy = eyes.pupil_offset(100.0, 0.0)   # far to the right
        self.assertGreater(ox, 0.0)
        self.assertAlmostEqual(oy, 0.0, places=6)

    def test_clamped_to_max_off(self):
        ox, oy = eyes.pupil_offset(10_000.0, 10_000.0, max_off=1.4)
        self.assertLessEqual(math.hypot(ox, oy), 1.4 + 1e-6)

    def test_grows_with_distance_until_reach(self):
        near = math.hypot(*eyes.pupil_offset(10.0, 0.0, reach=55.0, max_off=1.4))
        far = math.hypot(*eyes.pupil_offset(55.0, 0.0, reach=55.0, max_off=1.4))
        self.assertGreater(far, near)

    def test_idle_anchor_table_shape(self):
        table = eyes.EYES["idle"]
        self.assertEqual(len(table), 10)
        for left, right in table:
            for (x, y) in (left, right):
                self.assertTrue(0 <= x < 32 and 0 <= y < 32)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python -m unittest tests.test_eyes -v`
Expected: FAIL — `No module named 'petkit.eyes'`.

- [ ] **Step 3: Write the calibration tool**

```python
# tools/calibrate_eyes.py
"""Print the EYES["idle"] anchor table by finding the two dark eye clusters in
each Idle.png frame. Run once; paste the output into petkit/eyes.py.
    python tools/calibrate_eyes.py
"""
import os
import struct
import zlib

SHEET = os.path.join(os.path.dirname(__file__), "..", "assets", "cat", "Idle.png")
FW = FH = 32
EYE_BAND = range(8, 18)   # rows where the eyes live
DARK = 95                 # luminance below this counts as "eye/outline ink"


def _decode_rgba(path):
    d = open(path, "rb").read(); i = 8; idat = b""; W = H = ct = 0
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]; typ = d[i + 4:i + 8]
        data = d[i + 8:i + 8 + ln]; i += 12 + ln
        if typ == b"IHDR": W, H, _, ct = struct.unpack(">IIBB", data[:10])
        elif typ == b"IDAT": idat += data
        elif typ == b"IEND": break
    raw = zlib.decompress(idat); ch = 4 if ct == 6 else 3; stride = W * ch
    out = bytearray(); prev = bytearray(stride); p = 0
    for _y in range(H):
        f = raw[p]; p += 1; line = bytearray(raw[p:p + stride]); p += stride
        for x in range(stride):
            a = line[x - ch] if x >= ch else 0; b = prev[x]; c = prev[x - ch] if x >= ch else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                pp = a + b - c; pa = abs(pp - a); pb = abs(pp - b); pc = abs(pp - c)
                line[x] = (line[x] + (a if (pa <= pb and pa <= pc) else (b if pb <= pc else c))) & 255
        out += line; prev = line
    return W, H, ch, bytes(out)


def main():
    W, H, ch, px = _decode_rgba(SHEET)
    frames = W // FW
    table = []
    for fi in range(frames):
        groups = {"l": [], "r": []}
        for y in EYE_BAND:
            for x in range(FW):
                o = (y * W + fi * FW + x) * ch
                r, g, b = px[o], px[o + 1], px[o + 2]
                a = px[o + 3] if ch == 4 else 255
                if a > 0 and (0.299 * r + 0.587 * g + 0.114 * b) < DARK:
                    groups["l" if x < FW // 2 else "r"].append((x, y))
        def centroid(pts, fallback):
            if not pts:
                return fallback
            return (round(sum(p[0] for p in pts) / len(pts)),
                    round(sum(p[1] for p in pts) / len(pts)))
        left = centroid(groups["l"], (12, 13))
        right = centroid(groups["r"], (20, 13))
        table.append((left, right))
    print('    "idle": [')
    for left, right in table:
        print(f"        ({left}, {right}),")
    print("    ],")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the calibration tool and capture the table**

Run: `python tools/calibrate_eyes.py`
Expected: 10 lines like `((12, 13), (20, 13)),`. Sanity-check: left x ≈ 10–14, right x ≈ 18–22, y ≈ 11–15, values monotonic-ish across frames. Keep this output for Step 5.

- [ ] **Step 5: Implement `petkit/eyes.py` (paste the calibrated table)**

```python
# petkit/eyes.py
"""Cursor-tracking pupils for the sprite cat.

`pupil_offset` is the pure deflection math. `EYES[state]` is a per-frame table
of (left_eye, right_eye) anchor points in 32-space sprite coordinates -- the
eyes drift a few px across the idle frames, so pupils are re-seated each frame.
Regenerate the table with `python tools/calibrate_eyes.py` and paste below."""
import math


def pupil_offset(dx, dy, reach=55.0, max_off=1.4):
    """Offset (ox,oy) in sprite px for a pupil whose eye is `dx,dy` screen px
    from the cursor: points toward the cursor, grows with distance up to
    `reach`, clamped to `max_off` sprite px."""
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return (0.0, 0.0)
    f = min(1.0, d / reach) * max_off / d
    return (dx * f, dy * f)


EYES = {
    # PASTE the output of tools/calibrate_eyes.py here. The values below are a
    # reasonable default for a 32x32 front-facing cat; regenerate to fit exactly.
    "idle": [
        ((12, 13), (20, 13)),
        ((12, 13), (20, 13)),
        ((12, 13), (20, 13)),
        ((12, 13), (20, 13)),
        ((12, 13), (20, 13)),
        ((12, 13), (20, 13)),
        ((12, 13), (20, 13)),
        ((12, 13), (20, 13)),
        ((12, 13), (20, 13)),
        ((12, 13), (20, 13)),
    ],
}
```

- [ ] **Step 6: Run it, verify it passes**

Run: `python -m unittest tests.test_eyes -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add petkit/eyes.py tools/calibrate_eyes.py tests/test_eyes.py
git commit -F - <<'EOF'
Add petkit.eyes pupil-tracking math + calibrated idle anchors

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: `petkit/glow.py` — pre-baked radial glow images

**Files:**
- Create: `petkit/glow.py`
- Test: `tests/test_glow.py`

**Interfaces:**
- Produces: `glow_pixel(dist, radius, hue, key, level) -> (int,int,int)` (pure gradient color); `GlowCache(master, key_rgb, size=140, levels=6)` with `get(hue: (int,int,int), level: float 0..1) -> tk.PhotoImage` (cached, hue quantized).

- [ ] **Step 1: Write the failing test (pure gradient math)**

```python
# tests/test_glow.py
import unittest
import petkit.glow as glow

HUE = (255, 120, 168)
KEY = (1, 1, 1)


class TestGlowPixel(unittest.TestCase):
    def test_center_full_level_is_hue(self):
        self.assertEqual(glow.glow_pixel(0.0, 70.0, HUE, KEY, 1.0), HUE)

    def test_rim_is_key_color(self):
        self.assertEqual(glow.glow_pixel(70.0, 70.0, HUE, KEY, 1.0), KEY)

    def test_beyond_rim_is_key_color(self):
        self.assertEqual(glow.glow_pixel(200.0, 70.0, HUE, KEY, 1.0), KEY)

    def test_zero_level_is_key_everywhere(self):
        self.assertEqual(glow.glow_pixel(0.0, 70.0, HUE, KEY, 0.0), KEY)

    def test_monotonic_falloff(self):
        near = glow.glow_pixel(10.0, 70.0, HUE, KEY, 1.0)[0]
        far = glow.glow_pixel(50.0, 70.0, HUE, KEY, 1.0)[0]
        self.assertGreaterEqual(near, far)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python -m unittest tests.test_glow -v`
Expected: FAIL — `No module named 'petkit.glow'`.

- [ ] **Step 3: Implement `petkit/glow.py`**

```python
"""Pre-baked radial glow sprites for the pet: a soft disc fading from a hue at
the center to the overlay key color at the rim (so the rim is the key color =
transparent on the color-key window -- no alpha needed, no fringe). Built once
per (quantized hue, level) and cached. `glow_pixel` is the pure gradient (unit-
tested); the PhotoImage assembly needs Tk and runs at startup / lazily."""
import tkinter as tk


def glow_pixel(dist, radius, hue, key, level):
    """(r,g,b) at `dist` from center: hue*level at center fading to `key` at the
    rim (>= radius). `level` 0..1 scales peak brightness toward the hue."""
    if radius <= 0:
        return tuple(key)
    t = dist / radius
    if t >= 1.0:
        return tuple(key)
    k = ((1.0 - t) ** 2) * level
    return tuple(int(round(key[c] + (hue[c] - key[c]) * k)) for c in range(3))


class GlowCache:
    def __init__(self, master, key_rgb, size=140, levels=6):
        self._master = master
        self._key = tuple(key_rgb)
        self._size = size
        self._levels = max(2, levels)
        self._cache = {}

    def get(self, hue, level):
        lv = int(round(max(0.0, min(1.0, level)) * (self._levels - 1)))
        hq = tuple((c // 16) * 16 for c in hue)   # quantize to bound cache size
        ckey = (hq, lv)
        hit = self._cache.get(ckey)
        if hit is not None:
            return hit
        img = self._build(hq, lv / (self._levels - 1))
        self._cache[ckey] = img
        return img

    def _build(self, hue, level):
        n = self._size
        r = n / 2.0
        img = tk.PhotoImage(master=self._master, width=n, height=n)
        rows = []
        for y in range(n):
            cells = []
            dy2 = (y - r) ** 2
            for x in range(n):
                d = (((x - r) ** 2) + dy2) ** 0.5
                rr, gg, bb = glow_pixel(d, r, hue, self._key, level)
                cells.append("#%02x%02x%02x" % (rr, gg, bb))
            rows.append("{" + " ".join(cells) + "}")
        img.put(" ".join(rows))
        return img
```

- [ ] **Step 4: Run it, verify it passes**

Run: `python -m unittest tests.test_glow -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add petkit/glow.py tests/test_glow.py
git commit -F - <<'EOF'
Add petkit.glow pre-baked radial glow (fades hue -> key color)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: Rewrite `pet.pyw` — the sprite cat window

**Files:**
- Modify (rewrite): `pet.pyw`
- Modify: `config.py` (add `"zoom": 4` to `DEFAULTS["pet"]`)
- Modify if needed: `tests/test_config.py` (only if it asserts the exact `pet` dict)
- Reuse: `tests/test_smoke_pet.py` (launches `pet.pyw` under `TOYBOX_SMOKE`)

**Interfaces:**
- Consumes: `winkit.sprites.SpriteSheet`, `petkit.persona`, `petkit.eyes`, `petkit.glow.GlowCache`, existing `winkit.{window,audio,input,startup}`, `beat_detector.BeatDetector`, `config`.
- Preserves behavior: borderless transparent topmost overlay; grab-to-drag with persisted `pet.x/pet.y`; single-instance `Toybox_pet`; `watch_for_quit`; adaptive `idle_fps`/`active_fps`; `TOYBOX_SMOKE` auto-close.

- [ ] **Step 1: Extend the pet config defaults**

In `config.py`, change the `"pet"` default to add a zoom factor:

```python
    "pet": {"x": None, "y": None, "sensitivity": 1.6, "floor": 0.02,
            "smoothing": 0.4, "idle_fps": 8, "active_fps": 30, "zoom": 4},
```

Run: `python -m unittest tests.test_config -v`
Expected: PASS. If a test asserts the exact `pet` dict literal, update it to include `"zoom": 4` (mirror the pattern already used for other keys), then re-run to PASS.

- [ ] **Step 2: Rewrite `pet.pyw`**

```python
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
```

- [ ] **Step 3: Run the full unit suite**

Run: `python -m unittest discover -s tests -q`
Expected: OK (all prior tests + the new sprites/persona/eyes/glow tests). Fix any `test_config` assertion that pinned the old `pet` dict.

- [ ] **Step 4: Smoke-launch the cat and verify it renders (visual)**

Run (auto-closes after 1.2 s):
```bash
cd "C:/Users/Warren/Toybox" && TOYBOX_SMOKE=1200 "C:/Users/Warren/AppData/Local/Programs/Python/Python312/pythonw.exe" pet.pyw
```
Then screenshot the bottom-center of the screen and confirm: the **cat** renders crisply (no fringe), a soft colored **glow** sits behind it, and two **pupils** are visible on the cat's eyes. (Reuse the PowerShell `CopyFromScreen` capture used elsewhere in this project; capture around the placed window.) Play audio briefly and confirm the glow brightens and the cat hops; move the cursor and confirm the pupils shift toward it.

- [ ] **Step 5: Confirm `test_smoke_pet.py` still passes**

Run: `python -m unittest tests.test_smoke_pet -v`
Expected: PASS (the smoke launcher exits cleanly under `TOYBOX_SMOKE`).

- [ ] **Step 6: Commit**

```bash
git add pet.pyw config.py tests/test_config.py
git commit -F - <<'EOF'
Rewrite pet.pyw as a sprite cat: glow aura, idle animation, tracking pupils

Replaces the vector blob with pixel-art cat frames over a time-of-day glow;
music drives glow intensity + hops; pupils track the cursor per-frame.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Self-Review

**Spec coverage (Phase 1 scope):** sprite engine → Task 1; time-of-day persona → Task 2; tracking pupils + per-frame anchors → Task 3 + Task 5 `_draw_pupils`; glow (music + persona) → Task 4 + Task 5 `draw`; drag/persist, single-instance, quit-watcher, adaptive fps → Task 5 (preserved). Phase 1 "It's a cat" is fully covered; Phases 2–4 (bubble/menu, petting, catnap, assistant abilities, power-tools) are out of this plan by design.

**Placeholder scan:** No "TODO"/"TBD". The one generated artifact (eye-anchor table) has a concrete generation step (Task 3 Step 4) and a working default so the code runs even if calibration is skipped.

**Type/name consistency:** `SpriteSheet.frame(index, zoom)` — used in Task 5 as `self.sheet.frame(self.frame_i, self.zoom)`. `glow.GlowCache.get(hue, level)` — used as `self.glow.get(self.hue, ...)`. `eyes.EYES["idle"]` (10 pairs) and `eyes.pupil_offset(dx, dy)` — used in `_draw_pupils`. `persona.glow_rgb(hour)` — used for `self.hue`. `config.DEFAULTS["pet"]["zoom"]` — read as `pet.get("zoom", 4)`. All consistent.

**Lightweight check:** per frame = one image swap (cached), one glow-image swap (cached, hue/level quantized), two oval `coords`, one audio read — all O(1). Glow bake happens lazily and is cached. Adaptive fps preserved.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-06-25-cat-pet-phase1.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints for review.

Which approach? (And Phases 2–4 will each get their own plan in the same style once Phase 1 lands.)
