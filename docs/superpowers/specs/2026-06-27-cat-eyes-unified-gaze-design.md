# Cat Eyes: Unified Gaze (both pupils move together) — Design

**Date:** 2026-06-27
**Status:** Approved (design)
**Runtime:** Python 3.12 stdlib only (tkinter + ctypes + math). Extends the
sprite-cat pet toy (`pet.pyw`) and the pure `petkit/eyes.py`. No pip, ever.

## Problem

The pet cat tracks the cursor with two pixel eyes. Each eye is a 2×2 sprite
block holding a 1px white catchlight dot that floats toward the cursor. Today
`pet.pyw._draw_eyes` computes the dot position **independently per eye**: it
calls `eyes.pupil_offset(...)` with each eye's own center→cursor vector, then
snaps the resulting dot to a coarse grid (`step = max(1, z // 2)`, ~3 positions
per axis).

Because the two eye centers sit ~7 sprite-px apart, their center→cursor vectors
differ slightly. Near a grid threshold, one eye crosses to the next snap step
while the other has not — so one pupil hops and the other holds. The user reads
this divergence as the eyes "not matching," which looks wrong.

## Goal

Both pupils always occupy the **identical** position within their eye block, so
they move in lockstep. The gaze is computed **once** from a single reference
point (the midpoint between the two eyes) and copied to both eyes. This is
marginally less "accurate" — the right eye no longer aims from its own socket —
but visually unified, which is the desired tradeoff.

## Approach

### New pure helper — `petkit/eyes.py`

Add a pure function (no Tk, no `time.*`; takes injected values, unit-tested in
`tests/test_eyes.py`) that lifts the dot snapping/clamping currently inlined in
`pet.pyw` out into testable logic:

```
pupil_dot_offset(dx, dy, base, dot, step, reach=55.0, max_off=1.4) -> (ldx, ldy)
```

- `dx, dy` — the gaze vector (screen px from the eye/reference center to the
  cursor), the same units `pupil_offset` already takes.
- `base` — the eye block's side length in window px (the cat renders this as
  `2 * z`).
- `dot` — the white dot's side length in window px (`z`).
- `step` — the snap grid in window px (`max(1, z // 2)`).
- Returns `(ldx, ldy)`: the dot's **integer top-left position within the block**,
  i.e. an offset in `[0, base - dot]` on each axis.

Behavior, mirroring today's inline math but in block-local coordinates:
1. `ox, oy = pupil_offset(dx, dy, reach, max_off)` — the sub-pixel deflection.
2. Center the dot in the block, then float it toward the cursor:
   `ld = round(base/2 + o - dot/2)` per axis.
3. Clamp so the dot stays fully inside the block: `ld = clamp(ld, 0, base - dot)`.
4. Snap to the grid: `ld = round(ld / step) * step`.

The function is **deterministic**: identical inputs yield identical output —
this property is what guarantees both eyes match when fed the same gaze vector.

### Caller change — `pet.pyw._draw_eyes`

Compute the gaze vector **once** from the midpoint of the two open-eye blocks,
then place both dots at *(each eye's own integer base top-left) + (the shared
`ldx, ldy`)*:

1. Both eyes' top-left corners come from the per-frame `EYES["idle"]` anchors
   (unchanged). Compute each eye's base top-left in window space (`bx, by`) and
   the **midpoint center** `mcx, mcy` = average of the two blocks' centers.
2. `ldx, ldy = eyes.pupil_dot_offset(gx - (rootx + mcx), gy - (rooty + mcy),
   base=2*z, dot=z, step=max(1, z // 2), reach=EYE_REACH, max_off=EYE_MAX_OFF)`.
3. For each eye, place its dot at `(int(round(bx)) + ldx, int(round(by)) + ldy)`.

The blink path, closed-eye path, base/lid rendering, and the `EYES` table are
unchanged. Only the open-eye dot placement moves from per-eye to shared.

Because both open eyes share the same `z`, the same `base`, the same `dot`, and
(per frame) the same `ay` anchor row, applying one `(ldx, ldy)` to both blocks
puts each dot at the same place within its own block — the eyes always match.

## Testing strategy

**Unit (`tests/test_eyes.py`, pure — extend existing file):**
- Centered cursor (`dx=dy=0`) → dot centered in the block:
  `pupil_dot_offset(0, 0, base=8, dot=4, step=2)` returns the centered offset
  `(2, 2)` (block 8, dot 4 → center top-left = 2; on the grid).
- Far-right cursor → dot pinned to the clamped right edge and on the grid:
  `pupil_dot_offset(10_000, 0, base=8, dot=4, step=2)` has `ldx == base - dot`
  (`4`) and `ldy == 2`.
- Both axes land on the step grid: every returned coordinate is a multiple of
  `step` (checked across several gaze vectors).
- Output stays inside the block: `0 <= ldx <= base - dot` and
  `0 <= ldy <= base - dot` for extreme inputs.
- Determinism: identical inputs return identical output (the both-eyes-match
  property).

`pupil_offset`'s existing tests and the `EYES` table test are unchanged.

**Smoke (Windows-only — existing `tests/test_smoke_pet.py`):** the pet launches,
draws frames (open and blinking), and exits cleanly with empty stderr. No new
smoke test needed; the existing one exercises `_draw_eyes` and would surface any
exception from the refactor.

## Constraints (carry verbatim into the plan)

- Pure Python 3.12 stdlib only — **no pip, ever** (tkinter, ctypes, math).
- Win32 stays in `winkit/`; pet logic stays in `pet.pyw` + pure `petkit/` modules.
  No new winkit or petkit modules — `pupil_dot_offset` joins existing
  `petkit/eyes.py`.
- Pure logic takes injected values and lives in `petkit/eyes.py` (no `time.*`,
  no Tk inside pure functions).
- TDD: failing test first, watch it fail, minimal code to pass.
- Reference point is the **midpoint** of the two eyes (chosen over left-eye-tracks;
  they differ by <1px of gaze).
- Test runner (bare `python` is a broken MS-Store stub → exit 49):
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`
- Commit after each task; end commit messages with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
