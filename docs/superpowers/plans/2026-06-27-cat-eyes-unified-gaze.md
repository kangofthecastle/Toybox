# Cat Eyes: Unified Gaze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the pet cat's two pupils always move together by computing the gaze once (from the eyes' midpoint) and seating the identical dot offset in both eye blocks.

**Architecture:** Lift the per-eye dot snapping/clamping currently inlined in `pet.pyw._draw_eyes` into a new pure, unit-tested `petkit/eyes.pupil_dot_offset(...)` that returns the white dot's block-local top-left. `_draw_eyes` then calls it once with the gaze vector measured from the midpoint of the two eyes and applies the same `(ldx, ldy)` to both eyes.

**Tech Stack:** Python 3.12 stdlib only (tkinter, ctypes, math). No pip.

## Global Constraints

- Pure Python 3.12 stdlib only — **no pip, ever** (tkinter, ctypes, math).
- Win32 stays in `winkit/`; pet logic stays in `pet.pyw` + pure `petkit/` modules. No new winkit/petkit modules — `pupil_dot_offset` joins existing `petkit/eyes.py`.
- Pure logic takes injected values and lives in `petkit/eyes.py` (no `time.*`, no Tk inside pure functions).
- TDD: failing test first, watch it fail, minimal code to pass.
- Reference point is the **midpoint** of the two eyes (chosen over left-eye-tracks).
- Test runner (bare `python` is a broken MS-Store stub → exit 49): `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`. Run all commands from the repo root `C:\Users\Warren\Toybox`.
- Commit after each task; end commit messages with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: Pure `pupil_dot_offset` helper

**Files:**
- Modify: `petkit/eyes.py` (add one function after `pupil_offset`, lines 23-31)
- Test: `tests/test_eyes.py` (add one `TestCase` after `TestPupilOffset`)

**Interfaces:**
- Consumes: existing `pupil_offset(dx, dy, reach=55.0, max_off=1.4) -> (ox, oy)` in the same module.
- Produces: `pupil_dot_offset(dx, dy, base, dot, step, reach=55.0, max_off=1.4) -> (ldx, ldy)` where `ldx, ldy` are integer block-local top-left coordinates of the dot, each in `[0, base - dot]`. Task 2's `pet.pyw._draw_eyes` calls this.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_eyes.py` (after the `TestPupilOffset` class, before `if __name__`):

```python
class TestPupilDotOffset(unittest.TestCase):
    # base=8 (2x2 block at zoom 4), dot=4 (1px catchlight), step=2 (snap grid).
    def test_centered_cursor_centers_dot(self):
        # Cursor on the eye center -> no deflection -> dot centered:
        # top-left = (base - dot) / 2 = 2, which is already on the step-2 grid.
        self.assertEqual(eyes.pupil_dot_offset(0.0, 0.0, 8, 4, 2), (2, 2))

    def test_far_right_pins_to_right_edge(self):
        ldx, ldy = eyes.pupil_dot_offset(10_000.0, 0.0, 8, 4, 2)
        self.assertEqual(ldx, 8 - 4)   # clamped + snapped to the right edge
        self.assertEqual(ldy, 2)       # vertically still centered

    def test_snaps_to_step_grid(self):
        for gx in (-200.0, -40.0, -5.0, 5.0, 40.0, 200.0):
            for gy in (-200.0, -5.0, 5.0, 200.0):
                ldx, ldy = eyes.pupil_dot_offset(gx, gy, 8, 4, 2)
                self.assertEqual(ldx % 2, 0, f"ldx={ldx} off grid")
                self.assertEqual(ldy % 2, 0, f"ldy={ldy} off grid")

    def test_stays_inside_block(self):
        for gx in (-9999.0, 0.0, 9999.0):
            for gy in (-9999.0, 0.0, 9999.0):
                ldx, ldy = eyes.pupil_dot_offset(gx, gy, 8, 4, 2)
                self.assertGreaterEqual(ldx, 0)
                self.assertLessEqual(ldx, 8 - 4)
                self.assertGreaterEqual(ldy, 0)
                self.assertLessEqual(ldy, 8 - 4)

    def test_deterministic_identical_inputs(self):
        # The both-eyes-match property: same gaze in -> same dot out.
        a = eyes.pupil_dot_offset(123.0, -45.0, 8, 4, 2)
        b = eyes.pupil_dot_offset(123.0, -45.0, 8, 4, 2)
        self.assertEqual(a, b)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_eyes -v`
Expected: FAIL — `AttributeError: module 'petkit.eyes' has no attribute 'pupil_dot_offset'`.

- [ ] **Step 3: Write the minimal implementation**

Add to `petkit/eyes.py` immediately after `pupil_offset` (after line 31, before the `EYES = {` table):

```python
def pupil_dot_offset(dx, dy, base, dot, step, reach=55.0, max_off=1.4):
    """Block-local top-left (ldx, ldy) of the white catchlight dot within an
    eye's ``base``x``base`` block, for a gaze vector (dx, dy) in screen px from
    the eye/reference center to the cursor.

    The ``dot``-px-square dot is centered in the block, floated toward the
    cursor by ``pupil_offset``, clamped to stay fully inside the block, then
    snapped to a ``step``-px grid so the gaze reads pixel-art-steppy. Pure and
    deterministic: identical inputs give identical output, so feeding both eyes
    the same gaze vector keeps the pupils in lockstep.
    """
    ox, oy = pupil_offset(dx, dy, reach, max_off)
    ldx = int(round(base / 2.0 + ox - dot / 2.0))
    ldy = int(round(base / 2.0 + oy - dot / 2.0))
    ldx = min(max(ldx, 0), base - dot)
    ldy = min(max(ldy, 0), base - dot)
    ldx = int(round(ldx / step)) * step
    ldy = int(round(ldy / step)) * step
    return (ldx, ldy)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_eyes -v`
Expected: PASS — all `TestPupilOffset` and `TestPupilDotOffset` tests green.

- [ ] **Step 5: Commit**

```bash
git add petkit/eyes.py tests/test_eyes.py
git commit -m "Cat eyes: add pure pupil_dot_offset (block-local dot, snapped)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Unify the gaze in `_draw_eyes`

**Files:**
- Modify: `pet.pyw` — `_draw_eyes` (lines 436-493)
- Test: `tests/test_smoke_pet.py` (existing — no new test; this Task is verified by the existing pet smoke + in-process draw tests staying green)

**Interfaces:**
- Consumes: `eyes.pupil_dot_offset(dx, dy, base, dot, step, reach=55.0, max_off=1.4) -> (ldx, ldy)` from Task 1.
- Produces: no new public surface; `_draw_eyes` keeps its `(self, cx, feet_y, now)` signature and side-effect behavior (places `e["base"]` / `e["dot"]` / blink items per eye).

This Task is a refactor of one method: the per-eye `pupil_offset` + inline clamp/snap is replaced by a single `pupil_dot_offset` call from the eyes' midpoint, applied to both eyes. No unit test exists for `_draw_eyes` (it is Tk-rendering), so the gate is: the pure logic is already covered by Task 1, and the existing pet smoke test plus the in-process `cat.draw(...)` tests in `tests/test_smoke_pet.py` must stay green (they call `_draw_eyes` for real frames).

- [ ] **Step 1: Confirm the existing pet tests pass before the change (baseline)**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_pet -v`
Expected: PASS (baseline green before refactoring).

- [ ] **Step 2: Replace the `_draw_eyes` body from `blinking = ...` onward**

In `pet.pyw`, the method head (lines 436-448) is unchanged:

```python
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
```

Replace everything from the current line 450 (`blinking = now < self.blink_until`) through the end of the method (line 493) with:

```python
        blinking = now < self.blink_until
        base = 2 * z                                 # 8x8 px black base over each eye
        if not blinking:
            # Unified gaze: compute the dot's block-local offset ONCE from the
            # midpoint of the two eyes, then seat the SAME (ldx, ldy) in both
            # blocks. Both open eyes share z/base, so one offset places each dot
            # identically within its own block -- the pupils always move together
            # (no per-eye snap-grid divergence where one hops and the other holds).
            (lax, lay), (rax, ray) = anchors
            mcx = left_px + ((lax + rax) / 2.0) * z + base / 2.0   # midpoint center
            mcy = top_px + ((lay + ray) / 2.0) * z + base / 2.0
            ldx, ldy = eyes.pupil_dot_offset(
                gx - (rootx + mcx), gy - (rooty + mcy),
                base, z, max(1, z // 2),
                reach=EYE_REACH, max_off=EYE_MAX_OFF)

        for e, (ax, ay) in zip(self.eyes, anchors):
            bx = left_px + ax * z                    # 2x2 base top-left (window space)
            by = top_px + ay * z
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

            # Open eye: black 2x2 base, white 1px dot at the shared block-local
            # offset computed above from the eyes' midpoint.
            self.canvas.coords(e["base"], bx, by, bx + base, by + base)
            dx = int(round(bx)) + ldx
            dy = int(round(by)) + ldy
            self.canvas.coords(e["dot"], dx, dy, dx + z, dy + z)
            self.canvas.itemconfig(e["base"], state="normal")
            self.canvas.itemconfig(e["dot"], state="normal")
            self.canvas.itemconfig(e["lid"], state="hidden")
            self.canvas.itemconfig(e["dash"], state="hidden")
```

Note: `base = 2 * z` moves out of the loop (it is constant and the midpoint calc needs it). The old per-eye `ecx, ecy, ox, oy, bxi, byi, step` locals and the `eyes.pupil_offset(...)` call are gone from `pet.pyw` (that math now lives in `pupil_dot_offset`). `pet.pyw` still imports `petkit.eyes as eyes`, so `pupil_offset` remains reachable through the module — do not remove the import.

- [ ] **Step 3: Run the pet tests to verify they still pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_pet -v`
Expected: PASS — `test_launches_and_exits_clean` exits 0 with empty stderr, and the in-process `cat.draw(...)` / `cat.tick()` tests run a frame through the refactored `_draw_eyes` without raising.

- [ ] **Step 4: Run the full suite**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -v`
Expected: PASS — full suite green (the new `TestPupilDotOffset` tests included; existing count + 5).

- [ ] **Step 5: Commit**

```bash
git add pet.pyw
git commit -m "Cat eyes: unify gaze so both pupils move together

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- New pure `pupil_dot_offset` with the exact contract (center → float → clamp → snap, block-local) → Task 1. ✓
- `_draw_eyes` computes gaze once from the midpoint and applies the shared offset to both eyes → Task 2. ✓
- Midpoint reference point → Task 2 Step 2 (`mcx, mcy`). ✓
- Unit tests (centered, far-edge, grid-snap, in-bounds, determinism) → Task 1 Step 1. ✓
- Smoke coverage of the refactor → Task 2 Steps 3-4. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full code. ✓

**Type consistency:** `pupil_dot_offset(dx, dy, base, dot, step, reach, max_off) -> (ldx, ldy)` is defined identically in Task 1 (signature + impl) and called with matching positional/keyword args in Task 2 (`base, z, max(1, z // 2), reach=EYE_REACH, max_off=EYE_MAX_OFF`). The centered worked example `(8,4,2) -> (2,2)` and the far-right `-> (4,2)` match the clamp-then-snap implementation. ✓
