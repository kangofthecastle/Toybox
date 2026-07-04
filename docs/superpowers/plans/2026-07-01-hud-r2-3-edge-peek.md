# Edge-peek Dock-to-Edge Auto-hide Implementation Plan

> For agentic workers: use subagent-driven-development to execute; steps use checkbox syntax.

**Goal:** Let the user drag the HUD near a screen edge to *dock* it. Once docked
the window slides mostly off-screen, leaving a small lip; hovering the lip slides
it fully into view (`<Enter>`), and moving the pointer away slides it back out
(`<Leave>`). Dragging the window away from the edge undocks it. The dock state is
**session-only** — it is never written to `config.json` — mirroring the existing
width-expand session toggle (`self.width`).

**Architecture:** Two module-level pure functions in `hud.pyw` do all the math:
`edge_for(...)` decides which edge (if any) a dropped window snaps to, and
`docked_geometry(...)` produces the exact Tk geometry string for a docked window
in its hidden or revealed state. The `Hud` instance holds `self._dock_edge`
session state plus a tiny chained-`after()` slide animator (`_dock_animate` /
`_dock_step`). Dock detection hooks into the existing drag-release path
(`_on_release`); reveal/hide hook into new `<Enter>`/`<Leave>` canvas bindings.
All window measurements come from `winfo_width()/winfo_height()` (the *current*
realized size), never from the `WIDTH`/`HEIGHT` constants, so edge-peek composes
automatically with the width-expand toggle and with any header rows other
Round-2 features add. Every Tk call is wrapped in try/except so a bad geometry
request can never crash the HUD.

**Tech Stack:** Python 3.12 standard library only. `tkinter` (window geometry,
event bindings, `after()` scheduling). No new modules, no new files besides tests.

## Global Constraints

- Pure Python 3.12 stdlib; no third-party packages.
- Never weaken urllib default TLS; only http/https may reach the browser.
- config.json is gitignored and holds a live GitHub PAT — never echo/log/commit
  it; every runtime config write goes through config.update(path, {...}) (scoped
  read-modify-write) so it cannot clobber another toy's keys.
- The HUD must never crash on bad external input: every parser returns a safe
  default; every ctypes/WinRT/Tk call is guarded (try/except).
- Lightweight: no busy loops; background polling is mtime/interval-gated.
- Test runner — use this EXACT command form in every "run the test" step:
    `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path> -v`
  run from the repo root. Bare "python" is broken on this machine.
- Commit trailer, EXACTLY (every commit step ends with this line):
    `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

### Notes for the executor (edge-peek specifics)

- **No layout / HEIGHT changes.** Edge-peek adds *no* header row and does not
  touch the CPU/RAM/GPU/media/clock stack. It reads live window size via
  `winfo_width()/winfo_height()`, so it needs no edit to `HEIGHT`, `_relayout_header`,
  or `_resize`, and it stays correct after earlier Round-2 features shift those
  rows. Do not hard-code any window size.
- **Session-only state.** `self._dock_edge` is never persisted; do not add it to
  `_save()` / `config.update`. It resets to `None` on each launch, exactly like
  `self.width`.
- **Tk geometry sign convention.** Negative offsets are emitted as `+-214`
  (from `"%dx%d+%d+%d" % (...)`). This matches the existing `_on_drag` code
  (`self.root.geometry(f"+{x}+{y}")` with negative `x`), so Tk already handles it.

---

## Task 1: `edge_for` — which screen edge a dropped window snaps to

**Files:**
- Modify: `C:\Users\Warren\Toybox\hud.pyw`
- Test: `C:\Users\Warren\Toybox\tests\test_smoke_hud.py`

**Interfaces:**
- Produces: `edge_for(x, y, w, h, sw, sh, threshold) -> 'left' | 'right' | 'top' | 'bottom' | None`
  — returns the edge whose distance to the window is `<= threshold`, choosing the
  nearest on ties in the fixed order left, right, top, bottom; `None` if no edge
  is within `threshold`.
- Consumes: nothing (pure).

- [ ] Step: write the failing test — add this class to the end of
  `C:\Users\Warren\Toybox\tests\test_smoke_hud.py` (just before the
  `if __name__ == "__main__":` block):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudEdgeFor(unittest.TestCase):
    # screen 1920x1080, window 220x134, threshold 24 px.
    SW, SH, W, H, T = 1920, 1080, 220, 134, 24

    def test_left_edge(self):
        import hud as hudmod
        self.assertEqual(hudmod.edge_for(10, 300, self.W, self.H, self.SW, self.SH, self.T),
                         "left")

    def test_right_edge(self):
        import hud as hudmod
        # x+w = 1910 -> right gap 10; left gap 1690 -> right wins.
        self.assertEqual(hudmod.edge_for(1690, 300, self.W, self.H, self.SW, self.SH, self.T),
                         "right")

    def test_top_edge(self):
        import hud as hudmod
        self.assertEqual(hudmod.edge_for(800, 10, self.W, self.H, self.SW, self.SH, self.T),
                         "top")

    def test_bottom_edge(self):
        import hud as hudmod
        # y+h = 1064 -> bottom gap 16; top gap 930 -> bottom wins.
        self.assertEqual(hudmod.edge_for(800, 930, self.W, self.H, self.SW, self.SH, self.T),
                         "bottom")

    def test_center_is_none(self):
        import hud as hudmod
        self.assertIsNone(hudmod.edge_for(800, 500, self.W, self.H, self.SW, self.SH, self.T))

    def test_corner_ties_prefer_left(self):
        import hud as hudmod
        # top-left corner: left gap == top gap == 10 -> left wins by fixed order.
        self.assertEqual(hudmod.edge_for(10, 10, self.W, self.H, self.SW, self.SH, self.T),
                         "left")

    def test_partly_offscreen_left_still_docks(self):
        import hud as hudmod
        # already dragged past the edge (negative x) counts as within threshold.
        self.assertEqual(hudmod.edge_for(-40, 300, self.W, self.H, self.SW, self.SH, self.T),
                         "left")

    def test_just_outside_threshold_is_none(self):
        import hud as hudmod
        # every gap is 25 (> 24): x=25, right gap 1920-245=1675, y=25, bottom gap 921.
        self.assertIsNone(hudmod.edge_for(25, 25, self.W, self.H, self.SW, self.SH, self.T))
```

- [ ] Step: run it, expect FAIL — the function does not exist yet:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudEdgeFor -v
```

  Expected failure: `AttributeError: module 'hud' has no attribute 'edge_for'`
  on every test method.

- [ ] Step: implement — in `C:\Users\Warren\Toybox\hud.pyw`, add this
  module-level function immediately after `_stock_points` (i.e. after its
  `return pts` line, before `def _repo_short`):

```python
def edge_for(x, y, w, h, sw, sh, threshold):
    """Which screen edge a window at (x, y) sized (w, h) on an sw x sh screen is
    within `threshold` px of, or None. Ties (a corner) resolve to the nearest,
    scanning left, right, top, bottom so a perfect tie prefers the earlier edge.
    A window dragged partly off-screen (negative gap) still counts as docked."""
    gaps = {
        "left": x,
        "right": sw - (x + w),
        "top": y,
        "bottom": sh - (y + h),
    }
    best = None
    for edge in ("left", "right", "top", "bottom"):
        gap = gaps[edge]
        if gap <= threshold and (best is None or gap < gaps[best]):
            best = edge
    return best
```

- [ ] Step: run it, expect PASS:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudEdgeFor -v
```

- [ ] Step: commit:

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "hud: add edge_for() edge-detection helper for edge-peek dock

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `docked_geometry` — geometry string for a docked window

**Files:**
- Modify: `C:\Users\Warren\Toybox\hud.pyw`
- Test: `C:\Users\Warren\Toybox\tests\test_smoke_hud.py`

**Interfaces:**
- Produces: `docked_geometry(edge, x, y, w, h, sw, sh, revealed, lip) -> "WxH+X+Y"`
  — the Tk geometry string for a window docked at `edge`. `revealed=True` pins it
  fully on-screen against that edge; `revealed=False` pushes it off-screen leaving
  `lip` px visible. The non-docked axis coordinate (`y` for left/right, `x` for
  top/bottom) is preserved from the input.
- Consumes: nothing (pure).

- [ ] Step: write the failing test — add this class to the end of
  `C:\Users\Warren\Toybox\tests\test_smoke_hud.py` (just before the
  `if __name__ == "__main__":` block):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudDockedGeometry(unittest.TestCase):
    # screen 1920x1080, window 220x134 at x=50 y=300, lip 6 px.
    SW, SH, W, H, X, Y, LIP = 1920, 1080, 220, 134, 50, 300, 6

    def _geo(self, edge, revealed):
        import hud as hudmod
        return hudmod.docked_geometry(edge, self.X, self.Y, self.W, self.H,
                                      self.SW, self.SH, revealed, self.LIP)

    def test_left_hidden_leaves_lip(self):
        # X = lip - w = 6 - 220 = -214; y preserved.
        self.assertEqual(self._geo("left", False), "220x134+-214+300")

    def test_left_revealed_pins_to_zero(self):
        self.assertEqual(self._geo("left", True), "220x134+0+300")

    def test_right_hidden_leaves_lip(self):
        # X = sw - lip = 1914; y preserved.
        self.assertEqual(self._geo("right", False), "220x134+1914+300")

    def test_right_revealed_pins_to_edge(self):
        # X = sw - w = 1700.
        self.assertEqual(self._geo("right", True), "220x134+1700+300")

    def test_top_hidden_leaves_lip(self):
        # Y = lip - h = 6 - 134 = -128; x preserved.
        self.assertEqual(self._geo("top", False), "220x134+50+-128")

    def test_top_revealed_pins_to_zero(self):
        self.assertEqual(self._geo("top", True), "220x134+50+0")

    def test_bottom_hidden_leaves_lip(self):
        # Y = sh - lip = 1074.
        self.assertEqual(self._geo("bottom", False), "220x134+50+1074")

    def test_bottom_revealed_pins_to_edge(self):
        # Y = sh - h = 946.
        self.assertEqual(self._geo("bottom", True), "220x134+50+946")

    def test_unknown_edge_keeps_position(self):
        # a None/garbage edge is a no-op: keep the window where it is.
        self.assertEqual(self._geo(None, False), "220x134+50+300")
```

- [ ] Step: run it, expect FAIL — the function does not exist yet:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudDockedGeometry -v
```

  Expected failure: `AttributeError: module 'hud' has no attribute 'docked_geometry'`
  on every test method.

- [ ] Step: implement — in `C:\Users\Warren\Toybox\hud.pyw`, add this
  module-level function immediately after the `edge_for` function added in Task 1
  (before `def _repo_short`):

```python
def docked_geometry(edge, x, y, w, h, sw, sh, revealed, lip):
    """Tk geometry string "WxH+X+Y" for a window docked at `edge`. When revealed
    it pins flush to that edge; when hidden it slides off-screen leaving `lip` px
    visible. The cross-axis coordinate is preserved. An unknown edge is a no-op
    (keeps the current x, y). Negative offsets format as +-N, which Tk accepts
    (same convention as the drag handler)."""
    nx, ny = x, y
    if edge == "left":
        nx = 0 if revealed else lip - w
    elif edge == "right":
        nx = sw - w if revealed else sw - lip
    elif edge == "top":
        ny = 0 if revealed else lip - h
    elif edge == "bottom":
        ny = sh - h if revealed else sh - lip
    return "%dx%d+%d+%d" % (w, h, nx, ny)
```

- [ ] Step: run it, expect PASS:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudDockedGeometry -v
```

- [ ] Step: commit:

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "hud: add docked_geometry() hidden/revealed geometry helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Dock on drag-release + slide-to-hidden animation

**Files:**
- Modify: `C:\Users\Warren\Toybox\hud.pyw`
- Test: `C:\Users\Warren\Toybox\tests\test_smoke_hud.py`

**Interfaces:**
- Produces: `self._dock_edge` session state (init `None`); `Hud._maybe_dock()`
  (called from `_on_release` after a real drag); `Hud._dock_animate(revealed)`;
  `Hud._dock_step()`; `Hud._target_from(edge, revealed)`; `close()` cancels the
  pending dock `after()`.
- Consumes: `edge_for` (Task 1), `docked_geometry` (Task 2), the module constants
  `DOCK_THRESHOLD`, `DOCK_LIP`, `DOCK_ANIM_MS`, `DOCK_ANIM_STEPS`.

- [ ] Step: write the failing test — add this class to the end of
  `C:\Users\Warren\Toybox\tests\test_smoke_hud.py` (just before the
  `if __name__ == "__main__":` block):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudEdgePeekDock(_HudTestBase):
    def test_drop_near_left_edge_docks_and_slides_off(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._save = lambda: None                 # never touch config.json here
            root.geometry("%dx%d+0+150" % (hudmod.WIDTH, hudmod.HEIGHT))
            root.update_idletasks()
            ev = type("E", (), {"x": 5, "y": 5, "x_root": 0, "y_root": 150})()
            hud._moved = True                        # simulate a drag having occurred
            hud._on_release(ev)                      # release near the left edge
            self.assertEqual(hud._dock_edge, "left")     # docked
            self.assertIsNotNone(hud._dock_after)        # slide-to-hidden started
            # drive the chained animation to completion synchronously
            for _ in range(hudmod.DOCK_ANIM_STEPS + 2):
                hud._dock_step()
            root.update_idletasks()
            self.assertLess(root.winfo_x(), 0)           # window slid off the left edge
        finally:
            hud.close(); root.destroy()

    def test_drop_in_center_undocks(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._save = lambda: None
            sw = root.winfo_screenwidth(); sh = root.winfo_screenheight()
            mx = max(0, min(sw // 2, sw - hudmod.WIDTH))
            my = max(0, min(sh // 2, sh - hudmod.HEIGHT))
            root.geometry("%dx%d+%d+%d" % (hudmod.WIDTH, hudmod.HEIGHT, mx, my))
            root.update_idletasks()
            hud._dock_edge = "left"                  # pretend it was docked before
            ev = type("E", (), {"x": 5, "y": 5, "x_root": mx, "y_root": my})()
            hud._moved = True
            hud._on_release(ev)                      # released in the middle
            self.assertIsNone(hud._dock_edge)        # no edge -> undocked
        finally:
            hud.close(); root.destroy()

    def test_close_cancels_pending_dock_after(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._save = lambda: None
            root.geometry("%dx%d+0+150" % (hudmod.WIDTH, hudmod.HEIGHT))
            root.update_idletasks()
            hud._dock_edge = "left"
            hud._dock_animate(revealed=False)        # schedules an after()
            self.assertIsNotNone(hud._dock_after)
            hud.close()                              # must cancel it without raising
            self.assertIsNone(hud._dock_after)
        finally:
            root.destroy()
```

- [ ] Step: run it, expect FAIL — the state and methods do not exist yet:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudEdgePeekDock -v
```

  Expected failure: `AttributeError: 'Hud' object has no attribute '_dock_edge'`
  (and `_dock_after` / `_dock_animate` / `_dock_step`).

- [ ] Step: implement — four edits in `C:\Users\Warren\Toybox\hud.pyw`.

  **(a)** Add the dock constants. Find the line `HISTORY = 60           # ~60 samples in the deque`
  and insert the constants block right after it:

```python
HISTORY = 60           # ~60 samples in the deque

# Edge-peek dock-to-edge (Feature 6). All session-only, like the width toggle.
DOCK_THRESHOLD = 24    # px from a screen edge (on drop) that triggers docking
DOCK_LIP = 6           # px of the window left peeking when docked and hidden
DOCK_ANIM_MS = 30      # per-frame delay of the slide animation
DOCK_ANIM_STEPS = 4    # frames per slide (reveal or hide)
```

  **(b)** Add the dock session state. Find the line
  `        self.width = WIDTH        # session-only; resets narrow each launch`
  and insert the four state lines right after it:

```python
        self.width = WIDTH        # session-only; resets narrow each launch
        self._dock_edge = None    # None|'left'|'right'|'top'|'bottom'; session-only
        self._dock_after = None   # pending dock-slide after() id (cancelled on close)
        self._dock_target = None  # (w, h, x, y) the slide animates toward, or None
        self._dock_steps = 0      # frames left in the current slide
```

  **(c)** Hook dock detection into the drag-release save path. Find this block in
  `_on_release`:

```python
        self._moved = False
        self.cfg["hud"]["x"] = self.root.winfo_x()
        self.cfg["hud"]["y"] = self.root.winfo_y()
        self._save()
```

  and add the `_maybe_dock()` call at the end of it:

```python
        self._moved = False
        self.cfg["hud"]["x"] = self.root.winfo_x()
        self.cfg["hud"]["y"] = self.root.winfo_y()
        self._save()
        self._maybe_dock()
```

  **(d)** Add the dock methods. Insert them immediately before the `_open_at`
  method (i.e. before the `    def _open_at(self, x, y):` line):

```python
    def _maybe_dock(self):
        """On drag-release, snap to a screen edge if within DOCK_THRESHOLD (and
        slide to the hidden lip), else undock. Session-only; never persisted."""
        try:
            x = self.root.winfo_x(); y = self.root.winfo_y()
            w = self.root.winfo_width(); h = self.root.winfo_height()
            sw = self.root.winfo_screenwidth(); sh = self.root.winfo_screenheight()
        except Exception:
            return
        self._dock_edge = edge_for(x, y, w, h, sw, sh, DOCK_THRESHOLD)
        if self._dock_edge:
            self._dock_animate(revealed=False)   # slide out to the peeking lip

    def _target_from(self, edge, revealed):
        """Parse docked_geometry(edge, ...) into (w, h, x, y) ints for the slide
        animator. Uses the live window size so it composes with the width toggle."""
        w = self.root.winfo_width(); h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth(); sh = self.root.winfo_screenheight()
        x = self.root.winfo_x(); y = self.root.winfo_y()
        geo = docked_geometry(edge, x, y, w, h, sw, sh, revealed, DOCK_LIP)
        size, _, rest = geo.partition("+")       # "WxH", "+", "X+Y" (X may be -N)
        gw, gh = size.split("x")
        gx, gy = rest.split("+")
        return int(gw), int(gh), int(gx), int(gy)

    def _dock_animate(self, revealed):
        """Start (or restart) the chained-after slide toward the docked target for
        the current edge. No-op when not docked. Guarded so a bad geometry never
        crashes the HUD."""
        if not self._dock_edge:
            return
        if self._dock_after is not None:
            try:
                self.root.after_cancel(self._dock_after)
            except Exception:
                pass
            self._dock_after = None
        try:
            self._dock_target = self._target_from(self._dock_edge, revealed)
        except Exception:
            self._dock_target = None
            return
        self._dock_steps = DOCK_ANIM_STEPS
        self._dock_step()

    def _dock_step(self):
        """One frame of the dock slide: move a fraction toward _dock_target and, if
        frames remain, reschedule. The final frame snaps exactly and clears state."""
        if self._dock_target is None:
            return
        w, h, tx, ty = self._dock_target
        try:
            cx = self.root.winfo_x(); cy = self.root.winfo_y()
        except Exception:
            self._dock_target = None
            self._dock_after = None
            return
        if self._dock_steps <= 1:
            nx, ny = tx, ty
        else:
            nx = cx + (tx - cx) // self._dock_steps
            ny = cy + (ty - cy) // self._dock_steps
        try:
            self.root.geometry("%dx%d+%d+%d" % (w, h, nx, ny))
        except Exception:
            pass
        self._dock_steps -= 1
        if self._dock_steps <= 0:
            self._dock_target = None
            self._dock_after = None
        else:
            self._dock_after = self.root.after(DOCK_ANIM_MS, self._dock_step)
```

  **(e)** Cancel the pending dock slide on close. Find this block in `close()`:

```python
        if self._drain_after is not None:
            try:
                self.root.after_cancel(self._drain_after)
            except Exception:
                pass
            self._drain_after = None
```

  and add a matching guarded cancel for `_dock_after` right after it:

```python
        if self._drain_after is not None:
            try:
                self.root.after_cancel(self._drain_after)
            except Exception:
                pass
            self._drain_after = None
        if self._dock_after is not None:
            try:
                self.root.after_cancel(self._dock_after)
            except Exception:
                pass
            self._dock_after = None
```

- [ ] Step: run it, expect PASS:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudEdgePeekDock -v
```

- [ ] Step: commit:

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "hud: dock to screen edge on drag-release and slide to hidden lip

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Reveal on hover, hide on leave (`<Enter>`/`<Leave>`)

**Files:**
- Modify: `C:\Users\Warren\Toybox\hud.pyw`
- Test: `C:\Users\Warren\Toybox\tests\test_smoke_hud.py`

**Interfaces:**
- Produces: `Hud._on_dock_enter(event)` and `Hud._on_dock_leave(event)` bound to
  the canvas `<Enter>`/`<Leave>` with `add="+"` (so the existing `<Leave>` hover
  cleanup keeps working); reveal/hide reuse `_dock_animate` from Task 3.
- Consumes: `self._dock_edge`, `_dock_animate` (Task 3).

- [ ] Step: write the failing test — add this class to the end of
  `C:\Users\Warren\Toybox\tests\test_smoke_hud.py` (just before the
  `if __name__ == "__main__":` block):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudEdgePeekReveal(_HudTestBase):
    def _drive(self, hud, n=8):
        for _ in range(n):
            hud._dock_step()

    def test_enter_reveals_and_leave_hides_when_docked(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._save = lambda: None
            root.geometry("%dx%d+0+150" % (hudmod.WIDTH, hudmod.HEIGHT))
            root.update_idletasks()
            hud._dock_edge = "left"
            # start hidden (slid off the left edge)
            hud._dock_animate(revealed=False); self._drive(hud); root.update_idletasks()
            self.assertLess(root.winfo_x(), 0)
            # hover the lip -> reveal fully on-screen
            hud._on_dock_enter(type("E", (), {"x": 1, "y": 1})())
            self._drive(hud); root.update_idletasks()
            self.assertEqual(root.winfo_x(), 0)
            # pointer leaves -> hide back to the lip
            hud._on_dock_leave(type("E", (), {"x": -1, "y": -1})())
            self._drive(hud); root.update_idletasks()
            self.assertLess(root.winfo_x(), 0)
        finally:
            hud.close(); root.destroy()

    def test_enter_and_leave_are_noops_when_not_docked(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._save = lambda: None
            root.geometry("%dx%d+400+400" % (hudmod.WIDTH, hudmod.HEIGHT))
            root.update_idletasks()
            self.assertIsNone(hud._dock_edge)
            hud._on_dock_enter(type("E", (), {"x": 1, "y": 1})())   # must not raise
            hud._on_dock_leave(type("E", (), {"x": 1, "y": 1})())   # must not raise
            self.assertIsNone(hud._dock_target)                     # no animation started
        finally:
            hud.close(); root.destroy()

    def test_enter_leave_bound_on_canvas_not_root(self):
        # regression guard: dock hover bindings live on the canvas (like the other
        # mouse bindings), never on root, so they can't double-fire.
        root, hud = self._make_hud([])
        try:
            for seq in ("<Enter>", "<Leave>"):
                self.assertEqual(hud.root.bind(seq), "", "%s must not be bound on root" % seq)
                self.assertNotEqual(hud.canvas.bind(seq), "", "%s must be bound on canvas" % seq)
        finally:
            hud.close(); root.destroy()
```

- [ ] Step: run it, expect FAIL — the handlers and bindings do not exist yet:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudEdgePeekReveal -v
```

  Expected failure: `AttributeError: 'Hud' object has no attribute '_on_dock_enter'`
  (and `test_enter_leave_bound_on_canvas_not_root` fails because `<Enter>` is not
  yet bound on the canvas).

- [ ] Step: implement — two edits in `C:\Users\Warren\Toybox\hud.pyw`.

  **(a)** Bind the dock hover handlers on the canvas. Find the existing bind loop:

```python
        for w in (self.canvas,):
            w.bind("<Button-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)
            w.bind("<Button-3>", self._on_menu)
            w.bind("<Motion>", self._on_motion)
            w.bind("<Leave>", self._on_leave)
```

  and add the two dock bindings at the end of the loop body (the `add="+"` on
  `<Leave>` appends the dock-hide handler after the existing `_on_leave` hover
  cleanup, keeping both):

```python
        for w in (self.canvas,):
            w.bind("<Button-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)
            w.bind("<Button-3>", self._on_menu)
            w.bind("<Motion>", self._on_motion)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Enter>", self._on_dock_enter, add="+")
            w.bind("<Leave>", self._on_dock_leave, add="+")
```

  **(b)** Add the two handlers. Insert them immediately before the `_maybe_dock`
  method added in Task 3 (i.e. before the `    def _maybe_dock(self):` line):

```python
    def _on_dock_enter(self, event):
        """Pointer entered the window: if docked, slide fully into view."""
        if self._dock_edge:
            self._dock_animate(revealed=True)

    def _on_dock_leave(self, event):
        """Pointer left the window: if docked, slide back out to the peeking lip."""
        if self._dock_edge:
            self._dock_animate(revealed=False)

```

- [ ] Step: run it, expect PASS:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudEdgePeekReveal -v
```

- [ ] Step: run the full edge-peek + regression set to confirm nothing broke
  (the existing `<Leave>` hover-cleanup and click-binding tests still pass):

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudEdgeFor tests.test_smoke_hud.TestHudDockedGeometry tests.test_smoke_hud.TestHudEdgePeekDock tests.test_smoke_hud.TestHudEdgePeekReveal tests.test_smoke_hud.TestHudClickAndMenu tests.test_smoke_hud.TestHudHover -v
```

- [ ] Step: commit:

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "hud: reveal docked HUD on hover, hide on leave

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
