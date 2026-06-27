# Clipboard: Horizontal Scroll + Layout Toggle + Current-Copy Highlight — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Clipboard panel horizontal scrolling for full-length entries, a toggle between side-by-side and stacked layouts, and a highlight on the row matching the live system clipboard.

**Architecture:** A new pure `clip_view.py` holds all non-Tk view logic (text flattening, layout normalization/toggle, panel sizing) so it is unit-tested without launching Tk — mirroring the existing `clip_store.py` / `clip_history.py` split. `clipboard.pyw`'s `ClipPanel` consumes those helpers and gains the Tk wiring. GUI wiring is verified by a Windows-only smoke run that opens and drives the panel.

**Tech Stack:** Python 3.12 standard library only — `tkinter`, `json`, `os`, `time`, `tempfile`. No third-party packages.

## Global Constraints

- Pure Python 3.12 stdlib only — **no pip, ever** (`tkinter`, `ctypes`, `json`, `os`, `time`, `tempfile`).
- Win32 stays in `winkit/`; the Clipboard toy is a top-level `.pyw` plus pure modules (`clip_store.py`, `clip_history.py`, new `clip_view.py`). **No new winkit or petkit code.**
- Pure logic takes injected values and lives in `clip_view.py` (no `time.*`, no Tk inside pure functions).
- TDD: failing test first, watch it fail, minimal code to pass.
- New `config.json` key: **`clipboard.layout` only**; values `"columns"` / `"stacked"`; default `"columns"`; any other value coerced to `"columns"` by the panel (via `clip_view.normalize_layout`).
- Test runner (bare `python` is a broken MS-Store stub → exit 49):
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`
- Run individual tests with `-m unittest tests.<module> -v`; the full suite with
  `-m unittest discover -s tests -t .` from the repo root (`C:/Users/Warren/Toybox`).
- Commit after each task; end commit messages with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## File Structure

- **`clip_view.py`** (new, pure): `flatten_line`, `normalize_layout`, `next_layout`, `panel_size`. No Tk import.
- **`config.py`** (modify): add `"layout": "columns"` to `DEFAULTS["clipboard"]`.
- **`clipboard.pyw`** (modify): horizontal-scroll sections + left-cluster rows (Task 2), layout toggle + rebuild (Task 3), current-copy highlight (Task 4), plus a smoke-only `_smoke_exercise`.
- **`tests/smoke.py`** (modify): `run_smoke` gains an `extra_env` parameter.
- **`tests/test_clip_view.py`** (new): unit tests for the pure helpers.
- **`tests/test_config.py`** (modify): layout default + round-trip + coercion.
- **`tests/test_smoke_clipboard.py`** (modify): a panel smoke test driving the new paths.

---

### Task 1: Pure `clip_view` helpers + `clipboard.layout` config key

**Files:**
- Create: `clip_view.py`
- Create: `tests/test_clip_view.py`
- Modify: `config.py` (`DEFAULTS["clipboard"]`)
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces (consumed by Tasks 2–4):
  - `clip_view.flatten_line(text: str) -> str` — one display line, **no length cap**.
  - `clip_view.normalize_layout(layout: str) -> str` — `"columns"`/`"stacked"`, else `"columns"`.
  - `clip_view.next_layout(layout: str) -> str` — the other layout; unknown → `"stacked"`.
  - `clip_view.panel_size(layout: str) -> (int, int)` — `"columns"`→`(632, 420)`, `"stacked"`→`(380, 640)`, unknown → `(632, 420)`.
  - `config.DEFAULTS["clipboard"]["layout"] == "columns"`.

- [ ] **Step 1: Write the failing tests for the pure helpers**

Create `tests/test_clip_view.py`:

```python
import unittest

import clip_view


class TestFlattenLine(unittest.TestCase):
    def test_plain_text_unchanged(self):
        self.assertEqual(clip_view.flatten_line("hello world"), "hello world")

    def test_newline_becomes_return_glyph(self):
        self.assertEqual(clip_view.flatten_line("a\nb"), "a ⏎ b")

    def test_crlf_becomes_space(self):
        self.assertEqual(clip_view.flatten_line("a\r\nb"), "a b")

    def test_carriage_return_becomes_space(self):
        self.assertEqual(clip_view.flatten_line("a\rb"), "a b")

    def test_tab_becomes_space(self):
        self.assertEqual(clip_view.flatten_line("a\tb"), "a b")

    def test_whitespace_only_returns_glyph(self):
        self.assertEqual(clip_view.flatten_line("   "), "⏎")
        self.assertEqual(clip_view.flatten_line(""), "⏎")

    def test_long_text_not_truncated(self):
        s = "x" * 500
        self.assertEqual(clip_view.flatten_line(s), s)
        self.assertEqual(len(clip_view.flatten_line(s)), 500)


class TestLayoutHelpers(unittest.TestCase):
    def test_normalize_keeps_known(self):
        self.assertEqual(clip_view.normalize_layout("columns"), "columns")
        self.assertEqual(clip_view.normalize_layout("stacked"), "stacked")

    def test_normalize_unknown_to_columns(self):
        self.assertEqual(clip_view.normalize_layout("weird"), "columns")
        self.assertEqual(clip_view.normalize_layout(""), "columns")

    def test_next_layout_toggles(self):
        self.assertEqual(clip_view.next_layout("columns"), "stacked")
        self.assertEqual(clip_view.next_layout("stacked"), "columns")

    def test_next_layout_unknown_to_stacked(self):
        self.assertEqual(clip_view.next_layout("weird"), "stacked")

    def test_panel_size_known(self):
        self.assertEqual(clip_view.panel_size("columns"), (632, 420))
        self.assertEqual(clip_view.panel_size("stacked"), (380, 640))

    def test_panel_size_unknown_falls_back_to_columns(self):
        self.assertEqual(clip_view.panel_size("weird"), (632, 420))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_view -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clip_view'`.

- [ ] **Step 3: Create the pure module**

Create `clip_view.py`:

```python
"""Pure view-logic for the clipboard panel (no Tk; unit-tested).

Kept separate from clipboard.pyw because that module runs side effects at
import (path insertion, stream guarding) and pulls in Tk + winkit, so its
helpers cannot be unit-tested directly. Mirrors clip_store.py / clip_history.py.
"""

_COLUMNS = "columns"
_STACKED = "stacked"
_SIZES = {_COLUMNS: (632, 420), _STACKED: (380, 640)}


def flatten_line(text):
    """Collapse text to one display line (no length cap).

    CRLF and CR become a space; LF becomes a ' ⏎ ' marker; tabs become spaces;
    the result is stripped. An empty result returns the '⏎' glyph.
    """
    flat = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ⏎ ")
    flat = flat.replace("\t", " ").strip()
    return flat or "⏎"


def normalize_layout(layout):
    """Return layout if it is a known value, else 'columns'."""
    return layout if layout in (_COLUMNS, _STACKED) else _COLUMNS


def next_layout(layout):
    """The other layout; an unknown value toggles to 'stacked'."""
    return _COLUMNS if layout == _STACKED else _STACKED


def panel_size(layout):
    """(width, height) for the panel Toplevel; unknown -> columns size."""
    return _SIZES.get(layout, _SIZES[_COLUMNS])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_clip_view -v`
Expected: PASS (all 13 tests).

- [ ] **Step 5: Write the failing config tests**

Append these methods inside `class TestConfig` in `tests/test_config.py` (the
`_write` helper already exists in that class):

```python
    def test_clipboard_layout_default(self):
        self.assertEqual(config.defaults()["clipboard"]["layout"], "columns")

    def test_clipboard_layout_roundtrip(self):
        cfg = config.defaults()
        cfg["clipboard"]["layout"] = "stacked"
        config.save(self.path, cfg)
        self.assertEqual(config.load(self.path)["clipboard"]["layout"], "stacked")

    def test_clipboard_layout_non_string_falls_back(self):
        self._write({"clipboard": {"layout": 5}})
        cfg = config.load(self.path)
        self.assertEqual(cfg["clipboard"]["layout"], "columns")
```

- [ ] **Step 6: Run the config tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_config -v`
Expected: FAIL — `test_clipboard_layout_default` gets a `KeyError: 'layout'`.

- [ ] **Step 7: Add the config key**

In `config.py`, change the `"clipboard"` entry of `DEFAULTS` to add the `layout` key:

```python
    "clipboard": {"max_items": 30, "hotkey": ["ctrl", "shift", "V"],
                  "x": None, "y": None, "capture": True, "layout": "columns"},
```

- [ ] **Step 8: Run the config tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_config -v`
Expected: PASS (all tests, including the three new ones).

- [ ] **Step 9: Commit**

```bash
cd "C:/Users/Warren/Toybox"
git add clip_view.py tests/test_clip_view.py config.py tests/test_config.py
git commit -m "Add clip_view pure helpers + clipboard.layout config key

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Horizontal scroll + full-width rows + left-aligned controls

**Files:**
- Modify: `clipboard.pyw` (`ClipPanel.__init__`, `_build_header` left untouched, new `_build_body`, rewritten `_build_column`, `_place`, `refresh`, `_row_frame`, row builders, helper labels; delete `_one_line`, `LINE_CAP`, `_meta_labels`; capture `app` + add `_smoke_exercise` in `main`)
- Modify: `tests/smoke.py` (`run_smoke` gains `extra_env`)
- Modify: `tests/test_smoke_clipboard.py` (panel smoke test)

**Interfaces:**
- Consumes: `clip_view.flatten_line`, `clip_view.normalize_layout`, `clip_view.panel_size` (Task 1).
- Produces (for Tasks 3–4):
  - `ClipPanel.outer` — the panel's outer frame.
  - `ClipPanel.body` — the frame holding the two sections (rebuilt by Task 3).
  - `ClipPanel._build_body(self)` — builds `body` and sets `self.all_inner`,
    `self.all_canvas`, `self.fav_inner`, `self.fav_canvas`.
  - `ClipPanel._build_column(self, parent, title, side, fixed_width) -> (inner, canvas)`.
  - `ClipPanel.layout`, `ClipPanel.panel_w`, `ClipPanel.panel_h` instance attrs.
  - `_row_frame(self, parent, text) -> (row, bg)` and the row builders use a
    far-left 3px accent `Frame` (Task 4 colors it).
  - `_smoke_exercise(app)` and the `TOYBOX_SMOKE_PANEL` env gate in `main`.
  - `tests.smoke.run_smoke(script_name, timeout_ms=1500, extra_env=None)`.

This task contains **no new pure logic** (that was Task 1's `flatten_line`,
already unit-tested for the no-truncation guarantee). Its deliverable is the Tk
wiring, verified by a smoke run that opens the panel with a long entry and exits
cleanly (any exception in a Tk callback prints a traceback to stderr and fails
the test).

- [ ] **Step 1: Add `extra_env` to the smoke harness**

In `tests/smoke.py`, replace the `run_smoke` function with:

```python
def run_smoke(script_name, timeout_ms=1500, extra_env=None):
    env = dict(os.environ)
    env["TOYBOX_SMOKE"] = str(timeout_ms)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, script_name)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=(timeout_ms / 1000.0) + 15,
    )
    return proc.returncode, (proc.stderr or "")
```

- [ ] **Step 2: Add the panel smoke test**

In `tests/test_smoke_clipboard.py`, add this method to `class TestSmokeClipboard`:

```python
    def test_panel_smoke_clean(self):
        rc, err = run_smoke("clipboard.pyw", 1800,
                            extra_env={"TOYBOX_SMOKE_PANEL": "1"})
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.strip(), "")
```

- [ ] **Step 3: Run the panel smoke test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_clipboard.TestSmokeClipboard.test_panel_smoke_clean -v`
Expected: FAIL — `clipboard.pyw` does not yet honor `TOYBOX_SMOKE_PANEL` /
define `_smoke_exercise`, so the test fails (`NameError`/no exercise wired → the
implementer adds the wiring in Steps 4–9). If it passes trivially at this point
(env var ignored), that is acceptable — the implementation steps below add the
real coverage; re-run at Step 10.

- [ ] **Step 4: Add the current-copy palette constants and import**

In `clipboard.pyw`, add the import near the other local imports (after
`import clip_store`):

```python
import clip_view
```

(The `CURRENT_BG` / `CURRENT_BAR` constants are added in Task 4.)

- [ ] **Step 5: Delete the truncation helpers**

In `clipboard.pyw`, delete the module-level constant `LINE_CAP = 46` and the
entire `_one_line` function. (The text now renders through
`clip_view.flatten_line`, which does not truncate.)

- [ ] **Step 6: Rewrite `ClipPanel.__init__`**

Replace the whole `__init__` method with:

```python
    def __init__(self, app):
        self.app = app
        self.store = app.store
        self._selected = set()   # texts checked in ALL
        self._anchor = None      # index in the current ALL view (for shift-select)
        self._all_texts = []     # texts currently shown in ALL (view order)
        self._suppress_close = False  # set while the options menu is open
        self.layout = clip_view.normalize_layout(app.cfg["clipboard"]["layout"])
        self.panel_w, self.panel_h = clip_view.panel_size(self.layout)

        win = tk.Toplevel(app.root)
        self.win = win
        win.overrideredirect(True)
        win.configure(bg=BORDER)
        win.attributes("-topmost", True)

        self.outer = tk.Frame(win, bg=PANEL_BG)
        self.outer.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_header(self.outer)

        self.footer = tk.Frame(self.outer, bg=PANEL_BG, height=34)
        self.footer.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        self.remove_btn = tk.Label(
            self.footer, text="", bg="#4a2b2b", fg="#ffd9d4",
            font=("Segoe UI", 9, "bold"), padx=10, pady=4, cursor="hand2")
        self.remove_btn.bind("<Button-1>", lambda e: self._remove_selected())

        self._build_body()

        win.bind("<Escape>", lambda e: self.close())
        win.bind("<FocusOut>", self._on_focus_out)
        self._place()
        win.deiconify()
        win.lift()
        win.focus_force()
        self.refresh()
        self.search.focus_set()
```

- [ ] **Step 7: Add `_build_body` and rewrite `_build_column`**

In `clipboard.pyw`, add a `_build_body` method and replace `_build_column`. The
`_build_column` signature gains `fixed_width` and returns `(inner, canvas)`;
each section uses a `grid` of canvas + vertical + horizontal scrollbars, the
inner frame is created at its natural width (so it can exceed the viewport), and
`<Shift-MouseWheel>` scrolls horizontally. `_build_body` builds the side-by-side
columns (Task 3 adds the stacked branch).

```python
    def _build_body(self):
        self.body = tk.Frame(self.outer, bg=PANEL_BG)
        self.body.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self.all_inner, self.all_canvas = self._build_column(
            self.body, "ALL", "left", True)
        self.fav_inner, self.fav_canvas = self._build_column(
            self.body, "FAVORITES", "right", True)

    def _build_column(self, parent, title, side, fixed_width):
        col = tk.Frame(parent, bg=COL_BG)
        if fixed_width:
            col.configure(width=COL_W)
            col.pack(side=side, fill="both", expand=True,
                     padx=(0, 6) if side == "left" else (6, 0))
            col.pack_propagate(False)
        else:
            col.pack(side=side, fill="both", expand=True,
                     pady=(0, 6) if side == "top" else (6, 0))
        tk.Label(col, text=title, bg=COL_BG, fg=DIM, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=8, pady=(6, 2))

        wrap = tk.Frame(col, bg=COL_BG)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=COL_BG, highlightthickness=0)
        vsb = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        hsb = tk.Scrollbar(wrap, orient="horizontal", command=canvas.xview)
        inner = tk.Frame(canvas, bg=COL_BG)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        def vwheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")

        def hwheel(e):
            canvas.xview_scroll(int(-e.delta / 120), "units")

        def on_enter(e, c=canvas, v=vwheel, h=hwheel):
            c.bind_all("<MouseWheel>", v)
            c.bind_all("<Shift-MouseWheel>", h)

        def on_leave(e, c=canvas):
            c.unbind_all("<MouseWheel>")
            c.unbind_all("<Shift-MouseWheel>")

        for w in (canvas, inner):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
        return inner, canvas
```

- [ ] **Step 8: Update `_place` to use the instance panel size**

Replace `_place` with (the only change is `PANEL_W`/`PANEL_H` → `self.panel_w`/`self.panel_h`):

```python
    def _place(self):
        self.win.update_idletasks()
        ix, iy = self.app.root.winfo_x(), self.app.root.winfo_y()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = ix + ICON + 8
        if x + self.panel_w > sw:
            x = ix - self.panel_w - 8
        x = max(8, min(x, sw - self.panel_w - 8))
        y = max(8, min(iy, sh - self.panel_h - 8))
        self.win.geometry("%dx%d+%d+%d" % (self.panel_w, self.panel_h, x, y))
```

The module-level `PANEL_W` / `PANEL_H` constants are now unused; delete them.
Keep `COL_W` (used by `_build_column`). Keep `PANEL_H`'s former value only inside
`clip_view.panel_size`.

- [ ] **Step 9: Rewrite `refresh`, `_row_frame`, the row builders, and the label helpers**

Replace `refresh` with (adds an `xview_moveto(0)` reset so filtering never leaves
a section scrolled right):

```python
    def refresh(self):
        needle = self.search_var.get().lower()
        for inner in (self.all_inner, self.fav_inner):
            for child in inner.winfo_children():
                child.destroy()
        now = time.time()

        recent = [e for e in self.store.recent() if needle in e["text"].lower()]
        favs = [e for e in self.store.favorites() if needle in e["text"].lower()]
        self._all_texts = [e["text"] for e in recent]
        self._selected &= set(self._all_texts)

        if not recent:
            self._empty(self.all_inner, "nothing copied yet" if not needle else "no matches")
        for i, e in enumerate(recent):
            self._all_row(i, e, now)
        if not favs:
            self._empty(self.fav_inner, "star items to keep them" if not needle else "no matches")
        for e in favs:
            self._fav_row(e, now)
        self._render_remove()
        for c in (self.all_canvas, self.fav_canvas):
            try:
                c.xview_moveto(0)
            except tk.TclError:
                pass
```

Replace `_row_frame` (now creates the far-left 3px accent `Frame`, which tracks
the hover background; Task 4 colors it teal for the current row) and return the
base background to callers:

```python
    def _row_frame(self, parent, text):
        bg = SEL_BG if text in self._selected else COL_BG
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=1)
        accent = tk.Frame(row, bg=bg, width=3)
        accent.pack(side="left", fill="y")

        def hover(on):
            b = ROW_HOVER if on else (SEL_BG if text in self._selected else COL_BG)
            row.config(bg=b)
            for c in row.winfo_children():
                if isinstance(c, tk.Label):
                    c.config(bg=b)
            accent.config(bg=b)
        row.bind("<Enter>", lambda e: hover(True))
        row.bind("<Leave>", lambda e: hover(False))
        return row, bg
```

Delete `_meta_labels`. Add three left-packing label helpers and give `_icon_btn`
a `side` parameter (default `"left"`):

```python
    def _icon_btn(self, row, glyph, color, bg, cmd, side="left"):
        b = tk.Label(row, text=glyph, bg=bg, fg=color, width=2,
                     font=("Segoe UI", 10), cursor="hand2")
        b.pack(side=side)
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def _time_lbl(self, row, entry, bg):
        ago = timeago.format_ago(time.time() - entry["time"])
        tk.Label(row, text=ago, bg=bg, fg=DIM, width=8, anchor="w",
                 font=("Segoe UI", 8)).pack(side="left")

    def _len_lbl(self, row, entry, bg):
        tk.Label(row, text=str(len(entry["text"])), bg=bg, fg=DIM, width=5,
                 anchor="w", font=("Segoe UI", 8)).pack(side="left")

    def _text_lbl(self, row, entry, bg):
        txt = tk.Label(row, text=clip_view.flatten_line(entry["text"]), bg=bg,
                       fg=FG, anchor="w", font=("Consolas", 9), cursor="hand2")
        txt.pack(side="left")
        txt.bind("<Button-1>", lambda e, t=entry["text"]: self._copy_and_close(t))
        return txt
```

Replace `_all_row` and `_fav_row` (controls now form a left cluster; the full
text label is the last, right-extending element):

```python
    def _all_row(self, index, entry, now):
        text = entry["text"]
        row, bg = self._row_frame(self.all_inner, text)
        chk = tk.Label(row, text="☑" if text in self._selected else "☐", bg=bg,
                       fg=TEAL if text in self._selected else STAR_OFF,
                       font=("Segoe UI", 10), cursor="hand2")
        chk.pack(side="left", padx=(2, 0))
        chk.bind("<Button-1>", lambda e, i=index, t=text: self._on_check(i, t, e))
        star = tk.Label(row, text="☆", bg=bg, fg=STAR_OFF, width=2,
                        font=("Segoe UI", 10), cursor="hand2")
        star.pack(side="left")
        star.bind("<Button-1>", lambda e, t=text: self._favorite(t))
        self._icon_btn(row, "✕", DIM, bg, lambda t=text: self._delete(t))
        self._time_lbl(row, entry, bg)
        self._len_lbl(row, entry, bg)
        self._text_lbl(row, entry, bg)

    def _fav_row(self, entry, now):
        text = entry["text"]
        row, bg = self._row_frame(self.fav_inner, text)
        self._icon_btn(row, "★", STAR_ON, bg, lambda t=text: self._unfavorite(t))
        self._icon_btn(row, "✕", DIM, bg, lambda t=text: self._delete(t))
        self._time_lbl(row, entry, bg)
        self._len_lbl(row, entry, bg)
        self._text_lbl(row, entry, bg)
```

- [ ] **Step 10: Capture `app` and add the smoke exercise in `main`**

In `clipboard.pyw`, add the `_smoke_exercise` function just above `def main():`:

```python
def _smoke_exercise(app):
    """Open the panel during a smoke run so its build paths execute."""
    long_text = "lorem ipsum dolor sit amet " * 8  # ~216 chars, one line
    app.store.add(long_text, time.time())
    app.open_panel()
```

In `main`, change the `ClipboardApp(...)` line to capture the instance and add
the smoke-panel gate:

```python
    window.enable_dpi_awareness()
    root = tk.Tk()
    app = ClipboardApp(root, store, cfg)
    startup.watch_for_quit("Toybox_clipboard", root.after, root.destroy)

    ms = _smoke_ms()
    if ms:
        if os.environ.get("TOYBOX_SMOKE_PANEL"):
            _smoke_exercise(app)
        root.after(ms, root.destroy)
    root.mainloop()
```

- [ ] **Step 11: Run the panel smoke test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_clipboard -v`
Expected: PASS (both the existing launch test and `test_panel_smoke_clean`),
stderr empty.

- [ ] **Step 12: Run the full suite to verify no regressions**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -t .`
Expected: OK (all tests pass).

- [ ] **Step 13: Commit**

```bash
cd "C:/Users/Warren/Toybox"
git add clipboard.pyw tests/smoke.py tests/test_smoke_clipboard.py
git commit -m "Clipboard: full-width rows with horizontal scroll, left-aligned controls

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Layout toggle (side-by-side ↔ stacked)

**Files:**
- Modify: `clipboard.pyw` (`_build_header` adds the toggle button; `_build_body`
  gains the stacked branch; new `_render_layout_btn`, `_toggle_layout`,
  `_rebuild_body`; `_smoke_exercise` toggles once)

**Interfaces:**
- Consumes: `clip_view.next_layout`, `clip_view.panel_size` (Task 1); `self.layout`,
  `self.panel_w/h`, `self.body`, `self._build_body`, `self._place` (Task 2).
- Produces (for Task 4 smoke): `_smoke_exercise` schedules `panel._toggle_layout`.

- [ ] **Step 1: Point the smoke exercise at the (not-yet-existing) toggle**

In `clipboard.pyw`, replace `_smoke_exercise` with:

```python
def _smoke_exercise(app):
    """Open the panel during a smoke run, then toggle its layout, so both
    layouts' build paths execute."""
    long_text = "lorem ipsum dolor sit amet " * 8  # ~216 chars, one line
    app.store.add(long_text, time.time())
    app.open_panel()
    panel = app.panel
    if panel is not None:
        app.root.after(300, panel._toggle_layout)
```

- [ ] **Step 2: Run the panel smoke test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_clipboard.TestSmokeClipboard.test_panel_smoke_clean -v`
Expected: FAIL — the scheduled `panel._toggle_layout` raises
`AttributeError: 'ClipPanel' object has no attribute '_toggle_layout'` inside the
Tk `after` callback, printing a traceback to stderr (non-empty stderr → assertion fails).

- [ ] **Step 3: Add the stacked branch to `_build_body`**

Replace `_build_body` with:

```python
    def _build_body(self):
        self.body = tk.Frame(self.outer, bg=PANEL_BG)
        self.body.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        if self.layout == "stacked":
            self.all_inner, self.all_canvas = self._build_column(
                self.body, "ALL", "top", False)
            self.fav_inner, self.fav_canvas = self._build_column(
                self.body, "FAVORITES", "bottom", False)
        else:
            self.all_inner, self.all_canvas = self._build_column(
                self.body, "ALL", "left", True)
            self.fav_inner, self.fav_canvas = self._build_column(
                self.body, "FAVORITES", "right", True)
```

- [ ] **Step 4: Add the toggle button to the header**

In `_build_header`, add the layout-toggle label after the `burger` block (and
before the `search` Entry block). Insert:

```python
        self.layout_btn = tk.Label(hdr, bg=PANEL_BG, fg=DIM,
                                   font=("Segoe UI", 12), cursor="hand2")
        self.layout_btn.pack(side="right", padx=(0, 8))
        self.layout_btn.bind("<Button-1>", lambda e: self._toggle_layout())
        self.layout_btn.bind("<Enter>", lambda e: self.layout_btn.config(fg=FG))
        self.layout_btn.bind("<Leave>", lambda e: self.layout_btn.config(fg=DIM))
        self._render_layout_btn()
```

- [ ] **Step 5: Add the toggle / rebuild methods**

Add these three methods to `ClipPanel` (place them just after `_build_body`):

```python
    def _render_layout_btn(self):
        # Glyph reflects the CURRENT layout: stacked rows vs. side-by-side columns.
        self.layout_btn.config(text="▤" if self.layout == "stacked" else "▥")

    def _rebuild_body(self):
        try:
            self.body.destroy()
        except tk.TclError:
            pass
        self._build_body()
        self.refresh()

    def _toggle_layout(self):
        self.layout = clip_view.next_layout(self.layout)
        self.app.cfg["clipboard"]["layout"] = self.layout
        self.app.save_cfg()
        self.panel_w, self.panel_h = clip_view.panel_size(self.layout)
        self._place()
        self._rebuild_body()
        self._render_layout_btn()
```

- [ ] **Step 6: Run the panel smoke test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_clipboard -v`
Expected: PASS — the panel opens (columns), toggles to stacked mid-run, both
build cleanly, stderr empty.

- [ ] **Step 7: Run the full suite to verify no regressions**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -t .`
Expected: OK.

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/Warren/Toybox"
git add clipboard.pyw
git commit -m "Clipboard: toggle between side-by-side and stacked layouts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Highlight the entry matching the live clipboard

**Files:**
- Modify: `clipboard.pyw` (add `CURRENT_BG` / `CURRENT_BAR` constants; `__init__`
  inits `self._current`; new `_current_clip` + `_base_bg`; `refresh`, `_row_frame`,
  `_all_row`, `_fav_row` become current-aware; `_smoke_exercise` sets the clipboard)

**Interfaces:**
- Consumes: `self._selected`, `_row_frame`, the row builders, `refresh` (Task 2).
- Produces: nothing later depends on this (final feature).

- [ ] **Step 1: Set the live clipboard in the smoke exercise**

In `clipboard.pyw`, replace `_smoke_exercise` with (sets the system clipboard to
the seeded entry *before* opening, so the first `refresh` exercises the highlight
path):

```python
def _smoke_exercise(app):
    """Seed a long entry, point the live clipboard at it (highlight path), open
    the panel, then toggle its layout — so every new build path executes."""
    long_text = "lorem ipsum dolor sit amet " * 8  # ~216 chars, one line
    app.store.add(long_text, time.time())
    try:
        app.root.clipboard_clear()
        app.root.clipboard_append(long_text)
    except tk.TclError:
        pass
    app.open_panel()
    panel = app.panel
    if panel is not None:
        app.root.after(300, panel._toggle_layout)
```

- [ ] **Step 2: Add the current-copy palette constants**

In `clipboard.pyw`, add these two lines to the "Panel theme" constant block
(near `SEL_BG` / `STAR_ON`):

```python
CURRENT_BG = "#243b3b"   # teal-tinted row bg for the live-clipboard entry
CURRENT_BAR = TEAL       # left accent bar for the live-clipboard entry
```

- [ ] **Step 3: Make `refresh` read the live clipboard, and rows current-aware**

Add `self._current = None` to `__init__` — insert it right after the
`self._suppress_close = False` line:

```python
        self._current = None     # text of the live system clipboard (for highlight)
```

Add the guarded reader method (place it next to `_copy_and_close`):

```python
    def _current_clip(self):
        try:
            t = self.app.root.clipboard_get()
        except tk.TclError:
            return None
        return t if t and t.strip() else None
```

In `refresh`, add this line immediately after `needle = self.search_var.get().lower()`:

```python
        self._current = self._current_clip()
```

- [ ] **Step 4: Add `_base_bg` and make `_row_frame` / rows current-aware**

Add a background-precedence helper and rewrite `_row_frame` (the accent turns
teal for the current row; precedence is hover > selected > current > base):

```python
    def _base_bg(self, text, is_current):
        if text in self._selected:
            return SEL_BG
        if is_current:
            return CURRENT_BG
        return COL_BG

    def _row_frame(self, parent, text, is_current):
        bg = self._base_bg(text, is_current)
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=1)
        accent = tk.Frame(row, bg=(CURRENT_BAR if is_current else bg), width=3)
        accent.pack(side="left", fill="y")

        def hover(on):
            b = ROW_HOVER if on else self._base_bg(text, is_current)
            row.config(bg=b)
            for c in row.winfo_children():
                if isinstance(c, tk.Label):
                    c.config(bg=b)
            accent.config(bg=(CURRENT_BAR if is_current else b))
        row.bind("<Enter>", lambda e: hover(True))
        row.bind("<Leave>", lambda e: hover(False))
        return row, bg
```

Update the two row builders to compute `is_current` and pass it through. Replace
the first two lines of `_all_row`:

```python
    def _all_row(self, index, entry, now):
        text = entry["text"]
        is_current = (text == self._current)
        row, bg = self._row_frame(self.all_inner, text, is_current)
```

(the rest of `_all_row` is unchanged), and the first two lines of `_fav_row`:

```python
    def _fav_row(self, entry, now):
        text = entry["text"]
        is_current = (text == self._current)
        row, bg = self._row_frame(self.fav_inner, text, is_current)
```

(the rest of `_fav_row` is unchanged).

- [ ] **Step 5: Run the panel smoke test to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_clipboard -v`
Expected: PASS — the panel opens with the live clipboard pointed at the seeded
entry (highlight path runs in both layouts), stderr empty.

- [ ] **Step 6: Run the full suite to verify no regressions**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -t .`
Expected: OK.

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/Warren/Toybox"
git add clipboard.pyw
git commit -m "Clipboard: highlight the entry matching the live clipboard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Manual verification (after all tasks)

Not automated (the smoke tests prove no-crash; these confirm the UX). Run
`pythonw clipboard.pyw`, open the panel (Ctrl+Shift+V or right-click the icon):

1. Copy a very long line → it appears in full; a horizontal scrollbar lets you
   read to the end; Shift+MouseWheel scrolls sideways; the controls stay at the left.
2. Click the **▥/▤** header toggle → the panel switches between side-by-side and
   stacked; the choice survives closing and reopening the panel (persisted to
   `config.json`).
3. The row whose text equals the current clipboard shows a teal left bar + tint,
   in whichever section it lives.
```
