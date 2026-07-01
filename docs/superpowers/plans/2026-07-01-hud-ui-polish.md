# HUD Tabbed-Feeds UI/UX Polish Implementation Plan

> **For agentic workers:** Implement task-by-task with strict TDD. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Sharpen the tabbed-HUD + stock-ticker UI: an unmistakable active-tab indicator, pixel-accurate ellipsis truncation, a divider before the pinned GitHub section, a filled up/down sparkline for the ticker, and mouse-over hover feedback on tabs and clickable rows.

**Design (approved):** Scope = "Core + hover feedback". Accent color = cyan `#33d6ff` (already the CPU sparkline color) for the active-tab underline and the active range-toggle segment. Hover highlight = a subtle full-width band behind clickable feed rows, and a pill behind the hovered tab/range segment. All changes are additive canvas drawing on `hud.pyw`; the 5-row metrics header (CPU/RAM/GPU/clock/media) is left alone.

**Tech Stack:** Python 3.12 stdlib only (tkinter Canvas). No pip.

## Global Constraints

Every task's requirements implicitly include these:

- Pure Python 3.12 **stdlib only — no pip / third-party, ever**.
- Tests run from repo root with: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path>` (bare `python`/`python3` is a broken MS-Store stub — do not use it).
- Commit trailer EXACTLY: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Branch `hud-stock-ticker` (already checked out); base is the current tip `bdbe57f`.
- Do NOT change the security gates (`_register_hit`/`_open_at`/`is_web_url`), the drain loop's correctness, or the persistent header items. Hover must never register or open a URL.
- Keep all existing tests green (baseline: 521 tests). New tests must assert real, observable canvas behavior.
- Do not weaken TLS; no config writes added by these changes.

---

## Task 1: Pixel-accurate ellipsis for feed titles and item lines

Char-count `_fit` (cap 30) lets some 30-char strings overflow 220px and hard-clip with no ellipsis. Add a pixel-measured fitter and use it for the plain feed title, single-line item rows, and the notification subtitle.

**Files:** Modify `hud.pyw`; Test `tests/test_smoke_hud.py`.

**Interfaces:** Produces `Hud._fit_px(text, x_start) -> str` (trims with `…` to fit from `x_start` to the right margin at FEED_FONT width; short text returned unchanged).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smoke_hud.py`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudFitPx(_HudTestBase):
    def test_fit_px_unit(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            m = hud._feed_font_measure.measure
            short = "hi"
            self.assertEqual(hud._fit_px(short, hudmod.PAD + 6), short)     # fits -> unchanged
            long = "x" * 300
            out = hud._fit_px(long, hudmod.PAD + 6)
            self.assertTrue(out.endswith("…"))                             # truncated + marker
            self.assertLessEqual(m(out), hudmod.WIDTH - hudmod.PAD - (hudmod.PAD + 6))
        finally:
            hud.close(); root.destroy()

    def test_long_item_line_gets_ellipsis(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        feeds = [{"type": "rss", "url": "https://x", "title": "T", "tab": "tech"}]
        root, hud = self._make_hud(feeds)
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult(
                "ok", [Item("This is a very long headline that will not fit inside the width", "https://x/a")],
                None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("…"))                       # ellipsis rendered
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudFitPx -v`
Expected: FAIL (no `_fit_px`).

- [ ] **Step 3: Implement**

3a. Add the method to `Hud` (next to `_fit_line1`):

```python
    def _fit_px(self, text, x_start):
        """Trim text with an ellipsis so it fits from x_start to the right margin
        at FEED_FONT width (pixel-accurate, unlike the char-count _fit)."""
        m = self._feed_font_measure.measure
        budget = WIDTH - PAD - x_start
        if m(text) <= budget:
            return text
        while text and m(text + "…") > budget:
            text = text[:-1]
        return text + "…"
```

3b. In `_draw_tile`, replace the three char-count fits:
- the title: `text=_fit(title)` → `text=self._fit_px(title, PAD)`
- the single-line row: `text=_fit(text)` → `text=self._fit_px(text, PAD + 6)`
- the notification subtitle: `text=_fit(subtitle)` → `text=self._fit_px(subtitle, PAD + 12)`

(Leave `_fit_line1` and the short stock-tile strings unchanged.)

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): pixel-accurate ellipsis for feed titles and lines" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Active-tab underline, active range-toggle underline, GitHub divider

Add the cyan accent + hover-bg constants; draw a 2px cyan underline under the active tab and the active range-toggle segment; draw a thin dim divider line above the pinned GitHub header.

**Files:** Modify `hud.pyw`; Test `tests/test_smoke_hud.py`.

**Interfaces:** Produces module constants `ACCENT = "#33d6ff"`, `HOVER_BG = "#24242e"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smoke_hud.py`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudAccents(_HudTestBase):
    def _accent_rects(self, hud):
        import hud as hudmod
        return [i for i in hud._feed_items
                if hud.canvas.type(i) == "rectangle"
                and hud.canvas.itemcget(i, "fill") == hudmod.ACCENT]

    def test_active_tab_has_accent_underline(self):
        root, hud = self._make_hud([])
        try:
            hud.active_tab = "tech"
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(self._accent_rects(hud), "no accent underline for active tab")
        finally:
            hud.close(); root.destroy()

    def test_github_divider_line_drawn(self):
        import hud as hudmod
        feeds = [{"type": "github", "repo": "o/r", "title": "Repo"}]
        root, hud = self._make_hud(feeds)
        try:
            hud._draw_feeds(); root.update_idletasks()
            spans = []
            for i in hud._feed_items:
                if hud.canvas.type(i) == "line":
                    x0, _y0, x1, _y1 = hud.canvas.coords(i)
                    spans.append((x0, x1))
            self.assertTrue(any(x0 <= hudmod.PAD + 1 and x1 >= hudmod.WIDTH - hudmod.PAD - 1
                                for x0, x1 in spans), "no full-width divider before GitHub")
        finally:
            hud.close(); root.destroy()

    def test_active_range_segment_has_accent(self):
        import feedkit.manager as manager
        from feedkit.model import Quote
        feed = {"type": "stocks", "title": "Markets", "symbols": ["SPY"], "range": "1mo", "tab": "markets"}
        root, hud = self._make_hud([feed])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult("ok", [Quote("SPY", 1.0, 0.5, [1.0, 2.0])], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(self._accent_rects(hud), "no accent underline for active range")
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudAccents -v`
Expected: FAIL (no `ACCENT`; no underline/divider).

- [ ] **Step 3: Implement**

3a. Add constants near `STOCK_CHART_H` in `hud.pyw`:

```python
ACCENT = "#33d6ff"         # cyan: active-tab + active range-toggle indicator
HOVER_BG = "#24242e"       # subtle highlight band behind the hovered row/tab
```

3b. In `_draw_tab_bar`, inside the loop after `w = self._feed_font_measure.measure(label)` and the `_register_action(...)`, add the underline for the active tab:

```python
            if active:
                uy = row_y + FEED_LINE_H // 2 - 1
                ul = c.create_rectangle(x, uy, x + w, uy + 2, fill=ACCENT, outline="")
                self._feed_items.append(ul)
```

(`x` is the label's left edge, `w` its width, so the bar sits directly under it. `x` advances afterward as before.)

3c. In `_draw_github_header`, at the very top of the method body (before drawing the "GitHub" text), draw the divider spanning the content width:

```python
        dv = c.create_line(PAD, y + 1, WIDTH - PAD, y + 1, fill=FEED_DIM, width=1)
        self._feed_items.append(dv)
```

3d. In `_draw_range_toggle`, inside the loop after `w = self._feed_font_measure.measure(label)` and the `_register_action(...)`, add the underline for the active segment (the segment spans `x - w` to `x`, anchor="e"):

```python
            if active:
                uy = row_y + FEED_LINE_H // 2 - 1
                ul = c.create_rectangle(x - w, uy, x, uy + 2, fill=ACCENT, outline="")
                self._feed_items.append(ul)
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): accent underline for active tab/range + GitHub divider" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Filled up/down sparkline for the stock ticker

Draw a subtle stippled fill under the price polyline (colored by up/down), so the mini chart reads like a real sparkline instead of a thin line.

**Files:** Modify `hud.pyw` (`_draw_stock_tile`); Test `tests/test_smoke_hud.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_smoke_hud.py` (in `TestHudStocks`):

```python
    def test_chart_has_filled_polygon(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._q(series=(740.0, 745.0, 742.0, 748.0))], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(any(hud.canvas.type(i) == "polygon" for i in hud._feed_items),
                            "no filled chart polygon")
            self.assertTrue(any(hud.canvas.type(i) == "line" for i in hud._feed_items),
                            "line still drawn on top")
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudStocks.test_chart_has_filled_polygon -v`
Expected: FAIL (no polygon item).

- [ ] **Step 3: Implement**

In `_draw_stock_tile`, replace the chart-drawing block:

```python
            pts = _stock_points(q.series, PAD + 6, WIDTH - PAD, y + 2, y + STOCK_CHART_H - 2)
            if pts:
                ln = c.create_line(*pts, fill=color, width=1)
                self._feed_items.append(ln)
```

with a filled polygon (down to the chart bottom) beneath the line:

```python
            pts = _stock_points(q.series, PAD + 6, WIDTH - PAD, y + 2, y + STOCK_CHART_H - 2)
            if pts:
                bottom = y + STOCK_CHART_H - 2
                poly = c.create_polygon(*(pts + [pts[-2], bottom, pts[0], bottom]),
                                        fill=color, stipple="gray25", outline="")
                self._feed_items.append(poly)
                ln = c.create_line(*pts, fill=color, width=1)
                self._feed_items.append(ln)
```

(`stipple="gray25"` gives a dithered ~25% fill — tkinter has no true alpha. The line stays crisp on top.)

- [ ] **Step 4: Run to verify it passes**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudStocks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): filled up/down sparkline for stock ticker" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Hover feedback on tabs and clickable rows

Bind `<Motion>`/`<Leave>`; when the cursor is over a clickable feed row, highlight a full-width band behind it; over a tab or range segment, highlight a pill behind that segment. The highlight is a single canvas rectangle lowered beneath text, re-established after each 250ms redraw so it never flickers while the cursor is still.

**Files:** Modify `hud.pyw` (`__init__` state + bindings, `_draw_feeds`, new methods); Test `tests/test_smoke_hud.py`.

**Interfaces:** Produces `Hud._on_motion(event)`, `Hud._on_leave(event)`, `Hud._hover_zone_at(x, y) -> (x0,y0,x1,y1)|None`, `Hud._apply_hover()`; state `self._hover_xy`, `self._hover_item`, `self._hover_rect`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smoke_hud.py`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudHover(_HudTestBase):
    def _evt(self, x, y):
        return type("E", (), {"x": x, "y": y})()

    def _feeds(self):
        return [{"type": "rss", "url": "https://t", "title": "TechFeed", "tab": "tech"}]

    def _first_hit_point(self, hud):
        y0, y1, _url = hud._hit[0]
        return (hud_mid_x(), (y0 + y1) // 2)

    def test_hover_over_row_creates_highlight(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult("ok", [Item("line one", "https://t/a")], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._hit, "expected a clickable row")
            y0, y1, _u = hud._hit[0]
            hud._on_motion(self._evt(60, (y0 + y1) // 2))
            self.assertIsNotNone(hud._hover_item)
            self.assertEqual(hud.canvas.type(hud._hover_item), "rectangle")
        finally:
            hud.close(); root.destroy()

    def test_leave_clears_highlight(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult("ok", [Item("line one", "https://t/a")], None, None)
            hud._draw_feeds(); root.update_idletasks()
            y0, y1, _u = hud._hit[0]
            hud._on_motion(self._evt(60, (y0 + y1) // 2))
            self.assertIsNotNone(hud._hover_item)
            hud._on_leave(self._evt(0, 0))
            self.assertIsNone(hud._hover_item)
        finally:
            hud.close(); root.destroy()

    def test_hover_over_empty_space_no_highlight(self):
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            hud._draw_feeds(); root.update_idletasks()
            hud._on_motion(self._evt(5, 100000))                 # far below everything
            self.assertIsNone(hud._hover_item)
        finally:
            hud.close(); root.destroy()

    def test_highlight_survives_redraw(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult("ok", [Item("line one", "https://t/a")], None, None)
            hud._draw_feeds(); root.update_idletasks()
            y0, y1, _u = hud._hit[0]
            hud._on_motion(self._evt(60, (y0 + y1) // 2))
            self.assertIsNotNone(hud._hover_item)
            hud._draw_feeds(); root.update_idletasks()             # 250ms-loop style redraw
            self.assertIsNotNone(hud._hover_item)                  # re-established, no flicker-to-none
        finally:
            hud.close(); root.destroy()
```

Also add this module-level helper near the top of `tests/test_smoke_hud.py` (used by the hover tests):

```python
def hud_mid_x():
    import hud as hudmod
    return hudmod.WIDTH // 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudHover -v`
Expected: FAIL (no `_on_motion`/`_hover_item`).

- [ ] **Step 3: Implement**

3a. In `__init__`, next to `self._feed_items = []` (the hit/action/feed-item init block), add hover state:

```python
        self._hover_xy = None      # last cursor (x, y) over the canvas, or None
        self._hover_item = None    # the highlight rectangle canvas id, or None
        self._hover_rect = None    # the (x0,y0,x1,y1) currently highlighted, or None
```

3b. In `__init__`, in the canvas binding loop, add motion + leave (alongside the existing binds):

```python
            w.bind("<Motion>", self._on_motion)
            w.bind("<Leave>", self._on_leave)
```

3c. Add the hover methods to `Hud` (near `_action_at`):

```python
    def _hover_zone_at(self, x, y):
        """Rectangle (x0,y0,x1,y1) to highlight for the clickable thing under the
        cursor, or None. A tab/range action highlights its own segment (a pill);
        a clickable feed row highlights the full content width. Refresh/dismiss
        glyph zones are intentionally not highlighted."""
        for y0, y1, x0, x1, action in self._action_hits:
            if y0 <= y <= y1 and x0 <= x <= x1 and action[0] in ("tab", "range"):
                return (x0 - 3, y0, x1 + 3, y1)
        for y0, y1, _url in self._hit:
            if y0 <= y <= y1:
                return (PAD, y0, WIDTH - PAD, y1)
        return None

    def _apply_hover(self):
        """Reconcile the highlight rectangle with the current cursor position.
        No-op when the target band is unchanged (avoids per-motion churn)."""
        rect = self._hover_zone_at(*self._hover_xy) if self._hover_xy else None
        if rect == self._hover_rect:
            return
        self._hover_rect = rect
        if self._hover_item is not None:
            self.canvas.delete(self._hover_item)
            self._hover_item = None
        if rect is not None:
            self._hover_item = self.canvas.create_rectangle(*rect, fill=HOVER_BG, outline="")
            self.canvas.tag_lower(self._hover_item)     # behind text/lines/charts

    def _on_motion(self, event):
        self._hover_xy = (event.x, event.y)
        self._apply_hover()

    def _on_leave(self, event):
        self._hover_xy = None
        self._apply_hover()
```

3d. In `_draw_feeds`, make the highlight survive redraws. At the TOP (right after the `for item_id in self._feed_items: c.delete(item_id)` / list resets), drop the stale highlight:

```python
        if self._hover_item is not None:
            c.delete(self._hover_item)
            self._hover_item = None
        self._hover_rect = None
```

and at the very END of `_draw_feeds` (after `self._resize(y + PAD)`), re-establish it against the fresh zones:

```python
        self._apply_hover()
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS (incl. the subprocess smoke launch).

- [ ] **Step 5: Full suite + commit**

Run the whole suite first:
`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests`
Expected: PASS (all modules).

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): hover highlight on tabs and clickable feed rows" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Active-tab clarity** → Task 2 (cyan underline). **Ellipsis truncation** → Task 1 (`_fit_px`). **GitHub divider** → Task 2. **Filled sparkline** → Task 3. **Hover feedback** → Task 4. Accent = cyan `#33d6ff`, hover = `#24242e`, both defined once (Task 2).
- **Security untouched:** hover reads `_hit`/`_action_hits` only for geometry and never calls `_register_hit`/`webbrowser`; no new URL paths. `_register_hit`/`_open_at`/`is_web_url` unchanged.
- **No flicker:** `_draw_feeds` deletes + re-applies the single hover item within one synchronous redraw; `_apply_hover` short-circuits when the band is unchanged.
- **Type consistency:** `_hover_zone_at` returns a 4-tuple consumed by `_apply_hover`'s `create_rectangle(*rect)`; `_hover_rect` compared by value to skip redundant redraws.
- **No config writes.** All changes are canvas drawing + event handlers.
