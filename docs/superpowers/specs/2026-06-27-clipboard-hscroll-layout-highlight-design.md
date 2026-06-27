# Clipboard: Horizontal Scroll + Layout Toggle + Current-Copy Highlight — Design

**Date:** 2026-06-27
**Status:** Approved (design)
**Runtime:** Python 3.12 stdlib only (tkinter + ctypes + json). Extends the
top-level Clipboard toy (`clipboard.pyw`) and a new pure `clip_view.py`. No pip, ever.

## Overview

Three independent quality-of-life tweaks to the Clipboard panel
(`ClipPanel` in `clipboard.pyw`), sharing one spec/plan because each is small
and touches the same window:

1. **Horizontal scroll** — entries stop truncating at 46 characters. Each
   section renders the full single-line text and gains a horizontal scrollbar
   (plus Shift+MouseWheel) so long entries are readable end-to-end. Per-row
   controls move into a fixed left cluster so the text is the only thing that
   extends rightward.
2. **Layout toggle** — a header control flips the panel between today's
   side-by-side columns (ALL left, FAVORITES right) and a stacked view (ALL
   top, FAVORITES bottom). The choice persists in `config.json`.
3. **Current-copy highlight** — the row whose text equals the live system
   clipboard is marked with a teal left accent bar and a subtle tint, in both
   sections.

Each ships as its own working, tested increment. The pure-logic-takes-injected-
values discipline is preserved by putting all non-Tk view logic in a new
`clip_view.py` that is unit-tested without launching Tk (mirroring the existing
`clip_store.py` / `clip_history.py` split).

## New pure module — `clip_view.py`

`clipboard.pyw` runs side effects at import (path insertion, `guard_streams`)
and pulls in Tk + winkit, so its helpers cannot be unit-tested directly. All
new pure view logic lives in `clip_view.py` (no Tk import), unit-tested in
`tests/test_clip_view.py`:

- `flatten_line(text) -> str` — collapse to one display line **without any
  length cap**: `"\r\n"`→`" "`, `"\r"`→`" "`, `"\n"`→`" ⏎ "`, `"\t"`→`" "`,
  then `strip()`; an empty result returns `"⏎"`. This replaces the flattening
  half of the old `_one_line`; the 46-char cap (`LINE_CAP`) is removed.
- `normalize_layout(layout) -> str` — returns `layout` if it is `"columns"` or
  `"stacked"`, else `"columns"`. Used when reading the config value (config.py
  only type-coerces, it does not constrain the string's domain).
- `next_layout(layout) -> str` — `"columns"` if `layout == "stacked"` else
  `"stacked"` (so an unrecognized value toggles to `"stacked"`).
- `panel_size(layout) -> (int, int)` — `(width, height)` for the Toplevel:
  `"columns"`→`(632, 420)` (today's size), `"stacked"`→`(380, 640)`; any other
  value falls back to the columns size.

## Component 1 — Horizontal scroll (full, untruncated rows)

**Where:** `clipboard.pyw` (`_build_column`, the row builders, `refresh`).

Today `_one_line()` flattens **and** caps each entry at `LINE_CAP = 46` chars
with a `…`, and `_build_column` pins the canvas's inner frame to a fixed width
(`width=COL_W - 16`) so content can only scroll vertically.

- **Scrolling:** the inner frame is created with its natural width (no forced
  width), so it can exceed the viewport. Each section uses a `grid` of:
  canvas (0,0), vertical `Scrollbar` (0,1, `sticky="ns"`), horizontal
  `Scrollbar` (1,0, `sticky="ew"`), with row/column weights so the canvas
  fills. `canvas.configure(yscrollcommand=..., xscrollcommand=...)`. Plain
  `<MouseWheel>` scrolls vertically (unchanged); `<Shift-MouseWheel>` scrolls
  horizontally (`canvas.xview_scroll(int(-e.delta/120), "units")`). The wheel
  bindings are attached/removed on `<Enter>`/`<Leave>` as today.
- **Rows render full text:** the text label uses `clip_view.flatten_line(...)`
  (no cap). `_one_line` and `LINE_CAP` are deleted.
- **Control layout (approach 1a):** the interactive controls move into a
  compact, left-anchored cluster so the text is the only element that extends
  right. Left-to-right within each row:
  - ALL section: `[accent] [☐ check] [☆ star] [✕ delete] [time] [len] [text…→]`
  - FAVORITES section: `[accent] [★ unfavorite] [✕ delete] [time] [len] [text…→]`
  - `[accent]` is a 3px-wide `Frame` at the far left (Component 3 colors it; in
    this component it is the section background). The text label is packed
    `side="left"` with **no** `expand`, so its natural width drives the row
    width; the section's horizontal scrollbar reveals the tail. All other
    elements keep a fixed width, so they stay in view at rest (xview 0).
- `refresh()` resets each canvas's horizontal view to the left (`xview_moveto(0)`)
  after rebuilding rows, so filtering/star/delete never leaves the view scrolled.

**Why 1a (vs. keeping the spread layout):** with full-width rows, a
right-anchored delete button drifts off-screen for long entries. A fixed left
cluster keeps every control reachable at rest; only reading a long entry's tail
requires scrolling.

## Component 2 — Layout toggle (columns ↔ stacked)

**Where:** `clipboard.pyw` (header, a refactored `_build_body`, `_place`) and a
new `config.json` key.

- **Config:** `DEFAULTS["clipboard"]` gains `"layout": "columns"`. Values are
  `"columns"` (default) or `"stacked"`; the panel coerces any other value with
  `clip_view.normalize_layout`. `config.py` already type-coerces a non-string to
  the default, so a hand-edited bad value can never crash the panel.
- **Panel state:** `ClipPanel.__init__` sets
  `self.layout = clip_view.normalize_layout(app.cfg["clipboard"]["layout"])`
  and `self.panel_w, self.panel_h = clip_view.panel_size(self.layout)`. `_place`
  uses `self.panel_w/self.panel_h` instead of the module constants `PANEL_W/PANEL_H`.
- **Body building:** the body is built by a factored `_build_body()` that reads
  `self.layout`:
  - `"columns"`: two columns, fixed `width=COL_W`, packed `side="left"`/`"right"`
    (today's behavior).
  - `"stacked"`: two full-width sections packed `side="top"`/`"bottom"`, each
    `fill="both", expand=True` so they split the height; the fixed width is not
    applied. ALL is on top, FAVORITES on the bottom.
  `_build_body` stores `self.all_inner` / `self.fav_inner` (the row containers)
  exactly as today, so `refresh()` is layout-agnostic.
- **Header control:** a small layout-toggle `Label` (glyph `▥` for columns,
  `▤` for stacked, reflecting the *current* layout) sits in the header beside
  the `≡` menu. Clicking it runs `_toggle_layout`:
  1. `self.layout = clip_view.next_layout(self.layout)`
  2. write `app.cfg["clipboard"]["layout"] = self.layout`; `app.save_cfg()`
  3. recompute `self.panel_w/self.panel_h`; resize + reposition the window
  4. destroy and rebuild the body (`_rebuild_body`), then `refresh()` and
     update the toggle glyph.
  The rebuild keeps the header (search text, capture toggle) and footer intact;
  the typed search filter and current `_selected` set survive a toggle.

## Component 3 — Current-copy highlight

**Where:** `clipboard.pyw` (`refresh`, `_row_frame`, the row builders).

- `refresh()` reads the live system clipboard once via a guarded helper
  `_current_clip()` (`self.app.root.clipboard_get()` wrapped in
  `try/except tk.TclError`, returning `None` on failure/empty). It stores the
  result as `self._current` for the row builders.
- A row whose `entry["text"] == self._current` is marked:
  - its `[accent]` frame (from Component 1) is colored `TEAL` instead of the
    section background — always visible regardless of row background;
  - when the row is **not** hovered or checkbox-selected, its background is a
    teal-tinted `CURRENT_BG = "#243b3b"` instead of `COL_BG`.
- **Background precedence** (in `_row_frame`'s hover handler and the row
  builders' initial background): hover (`ROW_HOVER`) > checkbox-selected
  (`SEL_BG`) > current (`CURRENT_BG`) > base (`COL_BG`). The accent bar shows
  for the current row independent of this precedence.
- Applies in **both** sections (the current clipboard text may be a favorite).
- Evaluated on every `refresh()` (open, search keystroke, star/delete). It is
  **not** live-polled while the panel sits open — the panel is a transient
  picker that is opened, used, and closed; the capture poll does not refresh an
  open panel today and will not start.

## Testing strategy

- **`clip_view` (unit, pure — `tests/test_clip_view.py`):**
  - `flatten_line`: plain text unchanged; `"a\nb"`→`"a ⏎ b"`; `"a\r\nb"`→`"a b"`;
    `"a\tb"`→`"a b"`; whitespace-only→`"⏎"`; a 500-char string is returned in
    full (length preserved, no `…`) — proves the cap is gone.
  - `normalize_layout`: `"columns"`/`"stacked"` pass through; `"weird"`/`""`→`"columns"`.
  - `next_layout`: `"columns"`→`"stacked"`, `"stacked"`→`"columns"`, unknown→`"stacked"`.
  - `panel_size`: each known layout returns its tuple; unknown→columns tuple.
- **Config (unit — extend `tests/test_config.py`):** default
  `clipboard.layout == "columns"`; a saved `"stacked"` round-trips through
  `load`; a non-string layout coerces to `"columns"`.
- **Smoke harness (`tests/smoke.py`):** `run_smoke` gains an optional
  `extra_env=None` parameter merged into the child environment (backward
  compatible).
- **Panel smoke (Windows-only — extend `tests/test_smoke_clipboard.py`):**
  `clipboard.pyw`'s smoke branch, when `TOYBOX_SMOKE_PANEL` is set, runs a
  `_smoke_exercise(app)` that: seeds a ~200-char single entry, sets the system
  clipboard to that text (highlight path), opens the panel, and schedules a
  `_toggle_layout` (so both columns and stacked build). A new test launches
  with `extra_env={"TOYBOX_SMOKE_PANEL": "1"}` and asserts exit 0 with empty
  stderr — any exception in a Tk `after` callback prints a traceback to stderr
  and fails the test. The existing pure-launch test is unchanged.

## Constraints (carry verbatim into the plan)

- Pure Python 3.12 stdlib only — **no pip, ever** (tkinter, ctypes, json, os,
  time, tempfile).
- Win32 stays in `winkit/`; the Clipboard toy is a top-level `.pyw` plus pure
  modules (`clip_store.py`, `clip_history.py`, and new `clip_view.py`). No new
  winkit or petkit code.
- Pure logic takes injected values and lives in `clip_view.py` (no `time.*`,
  no Tk inside pure functions).
- TDD: failing test first, watch it fail, minimal code to pass.
- New `config.json` key: `clipboard.layout` only; values `"columns"`/`"stacked"`;
  default `"columns"`; any other value coerced to `"columns"` by the panel.
- Test runner (bare `python` is a broken MS-Store stub → exit 49):
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`
- Commit after each task; end commit messages with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
