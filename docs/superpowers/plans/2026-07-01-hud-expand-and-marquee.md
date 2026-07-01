# HUD Expand Toggle + Hover Marquee Implementation Plan

> **For agentic workers:** Implement task-by-task with strict TDD. Steps use checkbox (`- [ ]`) syntax.

**Goal:** (1) An expand button that toggles the whole HUD between its normal `220px` and a wide `560px` (session-only, resets narrow each launch). (2) Hovering a truncated feed line scrolls its full text horizontally (marquee) so it's readable.

**Design (approved):** Wide width = `560px`. Session-only (NO config writes — resets narrow each launch, like the tab/range state). Expand button = a `↔` glyph at the right of the tab bar, just left of the news ⟳. Marquee = a smooth left-scrolling loop of the hovered line's full text, only for lines that are actually truncated; stops and restores on leave.

**Tech Stack:** Python 3.12 stdlib only (tkinter Canvas). No pip.

## Global Constraints

- Pure Python 3.12 **stdlib only — no pip / third-party, ever**.
- Tests run from repo root with: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path>` (bare `python` is a broken MS-Store stub).
- Commit trailer EXACTLY: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Branch `hud-stock-ticker` (already checked out); base is the current tip (Task 1 base = current HEAD; Task 2 base = Task 1's commit).
- **NO config writes** — width and marquee are session state. Do not touch the security gates (`_register_hit`/`_open_at`/`is_web_url`) or weaken TLS.
- Keep all existing tests green (baseline: 531). New tests assert real observable canvas/state behavior.
- Do not break the persistent header items or the drain/tick loops' correctness.

---

## Task 1: Dynamic width + expand toggle (220 ⇄ 560, session-only)

`WIDTH` is a module constant used throughout drawing. Introduce `self.width` (defaults to `WIDTH`), route all layout to it, add a `↔` expand button that toggles `self.width` between `WIDTH` and `WIDTH_WIDE`, repositions the persistent header items, resizes the window, and redraws.

**Files:** Modify `hud.pyw`; Test `tests/test_smoke_hud.py`.

**Interfaces:** Produces module const `WIDTH_WIDE = 560`, `EXPAND_GLYPH = "↔"`; `Hud.width` (int, session state); `Hud._toggle_width()`; `Hud._relayout_header()`; a `("width",)` action dispatched by `_dispatch_action`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smoke_hud.py`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudExpand(_HudTestBase):
    def test_toggle_changes_width_and_geometry(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            self.assertEqual(hud.width, hudmod.WIDTH)
            hud._toggle_width(); root.update_idletasks()
            self.assertEqual(hud.width, hudmod.WIDTH_WIDE)
            self.assertEqual(root.winfo_width(), hudmod.WIDTH_WIDE)
            hud._toggle_width(); root.update_idletasks()
            self.assertEqual(hud.width, hudmod.WIDTH)
            self.assertEqual(root.winfo_width(), hudmod.WIDTH)
        finally:
            hud.close(); root.destroy()

    def test_expand_action_registered_and_dispatches(self):
        root, hud = self._make_hud([])
        try:
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(any(a == ("width",) for (_y0, _y1, _x0, _x1, a) in hud._action_hits),
                            "no expand-button action zone")
            import hud as hudmod
            hud._dispatch_action(("width",)); root.update_idletasks()
            self.assertEqual(hud.width, hudmod.WIDTH_WIDE)       # dispatch toggled it
        finally:
            hud.close(); root.destroy()

    def test_relayout_recenters_header(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._toggle_width(); root.update_idletasks()
            cx = hud.canvas.coords(hud._clock_text)[0]
            self.assertEqual(cx, hudmod.WIDTH_WIDE // 2)         # clock recentered when wide
        finally:
            hud.close(); root.destroy()

    def test_wide_reduces_truncation(self):
        root, hud = self._make_hud([])
        try:
            text = "A moderately long headline that overflows the narrow width only"
            narrow = hud._fit_px(text, 16)
            hud._toggle_width()
            wide = hud._fit_px(text, 16)
            self.assertTrue(narrow.endswith("…"))                # truncated when narrow
            self.assertEqual(wide, text)                         # full text fits when wide
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudExpand -v`
Expected: FAIL (no `width`/`_toggle_width`/`WIDTH_WIDE`).

- [ ] **Step 3: Implement**

3a. Add constants near `WIDTH` (after `HEIGHT`):

```python
WIDTH_WIDE = 560       # the "expanded" fixed width (session-only toggle)
```

and near `RELOAD_GLYPH`:

```python
EXPAND_GLYPH = "↔"    # ↔  toggle narrow(220) <-> wide(560)
```

3b. In `__init__`, BEFORE the persistent header items are created, add `self.width = WIDTH`. Then convert every persistent-header x that depends on width to use `self.width`:
- `_clock_text` center: `WIDTH // 2` → `self.width // 2`
- media `cx = WIDTH // 2` → `cx = self.width // 2`
(The `_media_hits` are computed from `cx`, so they follow.)

3c. **Route all layout to `self.width`.** In every METHOD body (not the module-constant definitions), replace `WIDTH` with `self.width`. This includes: `_update_spark` (use `self.width - PAD` as the right edge instead of the module `SPARK_RIGHT`), `_fit_px`, `_fit_line1`, `_draw_feeds`, `_draw_tab_bar`, `_draw_github_header`, `_draw_tile`, `_draw_stock_tile`, `_draw_range_toggle`, `_register_action` call sites, `_hover_zone_at`, and `_resize` (`self.root.geometry("%dx%d" % (self.width, new_h))`). Leave the module-level `WIDTH`, `HEIGHT`, `SPARK_RIGHT`, `SPARK_LEFT` definitions as-is (they define the narrow defaults). After editing, grep `hud.pyw` for `WIDTH` and confirm the only remaining bare `WIDTH` references are the module-constant definitions and `WIDTH_WIDE`; every in-method usage is `self.width`.

3d. In `_draw_tab_bar`, draw the expand button just left of the ⟳ and register its action. Replace the reload block at the end of the method:

```python
        rid = c.create_text(self.width - PAD, row_y, anchor="e", text=RELOAD_GLYPH,
                            fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(rid)
        self._register_action(row_y, self.width - PAD - ACTION_ZONE_W, self.width, ("refresh", "news"))
        ex_x = self.width - PAD - ACTION_ZONE_W - 6
        eid = c.create_text(ex_x, row_y, anchor="e", text=EXPAND_GLYPH,
                            fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(eid)
        self._register_action(row_y, ex_x - ACTION_ZONE_W, ex_x, ("width",))
        return y + FEED_LINE_H + FEED_TITLE_GAP
```

3e. In `_dispatch_action`, add the `width` branch (before the dismiss `else`):

```python
        elif kind == "width":
            self._toggle_width()
```

3f. Add the toggle + relayout methods (near `_set_active_tab`):

```python
    def _toggle_width(self):
        """Session-only toggle between narrow (WIDTH) and wide (WIDTH_WIDE). No
        config write. Repositions the persistent header, resizes the window, and
        redraws the feeds at the new width."""
        self.width = WIDTH_WIDE if self.width == WIDTH else WIDTH
        self._relayout_header()
        self._draw()          # repaint header (clock/media/sparklines) at the new width
        self._draw_feeds()    # reflow feeds + resize the window (via _resize)

    def _relayout_header(self):
        """Move the width-dependent persistent header items to the current width:
        the centered clock and the media glyphs (+ their hit zones). Sparklines
        re-right-align on the next _update_spark, which reads self.width."""
        c = self.canvas
        cx = self.width // 2
        c.coords(self._clock_text, cx, self.canvas.coords(self._clock_text)[1])
        ymedia = PAD + 4 * ROW_H + ROW_H // 2
        gap = 44
        c.coords(self._media_prev, cx - gap, ymedia)
        c.coords(self._media_play, cx, ymedia)
        c.coords(self._media_next, cx + gap, ymedia)
        half = ACTION_ZONE_W
        self._media_hits = [
            (cx - gap - half, cx - gap + half, ymedia - 11, ymedia + 11, "prev"),
            (cx - half,       cx + half,       ymedia - 11, ymedia + 11, "playpause"),
            (cx + gap - half, cx + gap + half, ymedia - 11, ymedia + 11, "next"),
        ]
```

> Note: `_relayout_header` re-derives `ymedia`/`gap`/`half` exactly as `__init__` does — keep them identical. If `__init__` is later changed, update both.

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): expand button toggles narrow/wide (220/560), session-only" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Redraw-on-change drain + hover marquee for truncated lines

Stop the unconditional 250ms redraw (so the marquee isn't reset four times a second), track which drawn feed lines are truncated + their full text, and animate a horizontal scroll of the hovered truncated line.

**Files:** Modify `hud.pyw`; Test `tests/test_smoke_hud.py`.

**Interfaces:** Produces `Hud._scroll_lines` (list of records `{item, full, x_start, y0, y1}`), `Hud._marquee` (dict or None), `Hud._marquee_after`, `Hud._marquee_step()`, `Hud._start_marquee(rec)`, `Hud._stop_marquee()`. `_drain_feeds` redraws only when `drain()` returns results.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smoke_hud.py`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudMarquee(_HudTestBase):
    def _evt(self, x, y):
        return type("E", (), {"x": x, "y": y})()

    def _long_feed(self):
        return [{"type": "rss", "url": "https://t", "title": "T", "tab": "tech"}]

    def _draw_long(self, hud, root):
        import feedkit.manager as manager
        from feedkit.model import Item
        hud.active_tab = "tech"
        hud.feed_state[0] = manager.FeedResult(
            "ok", [Item("This headline is far too long to fit within the narrow hud width for sure",
                        "https://t/a")], None, None)
        hud._draw_feeds(); root.update_idletasks()

    def test_drain_without_new_data_does_not_redraw(self):
        root, hud = self._make_hud(self._long_feed())
        try:
            calls = []
            orig = hud._draw_feeds
            hud._draw_feeds = lambda: (calls.append(1), orig())[1]
            hud.manager.drain = lambda: []
            hud._drain_feeds()
            self.assertEqual(calls, [])                          # no new data -> no redraw
            import feedkit.manager as manager
            from feedkit.model import Item
            hud.manager.drain = lambda: [(0, manager.FeedResult("ok", [Item("x", "https://t/x")], None, None))]
            hud._drain_feeds()
            self.assertEqual(calls, [1])                         # new data -> one redraw
        finally:
            if hud._drain_after:
                root.after_cancel(hud._drain_after)
            hud.close(); root.destroy()

    def test_hover_truncated_line_starts_and_animates_marquee(self):
        root, hud = self._make_hud(self._long_feed())
        try:
            self._draw_long(hud, root)
            self.assertTrue(hud._scroll_lines, "expected a truncated (scrollable) line")
            rec = hud._scroll_lines[0]
            before = hud.canvas.itemcget(rec["item"], "text")
            hud._on_motion(self._evt(60, (rec["y0"] + rec["y1"]) // 2))
            self.assertIsNotNone(hud._marquee)
            hud._marquee_step(); hud._marquee_step()
            after = hud.canvas.itemcget(rec["item"], "text")
            self.assertNotEqual(before, after)                  # text scrolled
        finally:
            hud._stop_marquee()
            hud.close(); root.destroy()

    def test_leave_stops_marquee_and_restores_text(self):
        root, hud = self._make_hud(self._long_feed())
        try:
            self._draw_long(hud, root)
            rec = hud._scroll_lines[0]
            truncated = hud.canvas.itemcget(rec["item"], "text")
            hud._on_motion(self._evt(60, (rec["y0"] + rec["y1"]) // 2))
            hud._marquee_step()
            hud._on_leave(self._evt(0, 0))
            self.assertIsNone(hud._marquee)
            self.assertEqual(hud.canvas.itemcget(rec["item"], "text"), truncated)   # restored
        finally:
            hud.close(); root.destroy()

    def test_hover_short_line_no_marquee(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud(self._long_feed())
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult("ok", [Item("short", "https://t/s")], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(hud._scroll_lines, [])             # nothing truncated
            for y0, y1, _u in hud._hit:
                hud._on_motion(self._evt(60, (y0 + y1) // 2))
            self.assertIsNone(hud._marquee)                     # short line never scrolls
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudMarquee -v`
Expected: FAIL (no `_scroll_lines`/`_marquee`/`_marquee_step`).

- [ ] **Step 3: Implement**

3a. In `__init__`, next to the hover state, add marquee state:

```python
        self._scroll_lines = []    # [{item, full, x_start, y0, y1}] truncated feed lines
        self._marquee = None       # active marquee dict, or None
        self._marquee_after = None # pending after() id
```

3b. Make `_drain_feeds` redraw only on new data:

```python
    def _drain_feeds(self):
        self._drain_after = None
        changed = False
        for idx, result in self.manager.drain():
            self.feed_state[idx] = result
            changed = True
        if changed:
            try:
                self._draw_feeds()
            except tk.TclError:
                return
        self._drain_after = self.root.after(250, self._drain_feeds)
```

3c. In `_draw_feeds`, reset `self._scroll_lines = []` alongside the other list resets at the top, and STOP any running marquee (its item id is about to be invalid):

```python
        self._stop_marquee()
        self._scroll_lines = []
```

3d. Record truncated lines when drawing them. In `_draw_tile`, for the single-line row branch (`len(row) == 3`), after creating `lid` with the fitted text, record it if it was actually truncated:

```python
            if len(row) == 3:
                text, url, dim = row
                fitted = self._fit_px(text, PAD + 6)
                lid = c.create_text(PAD + 6, y, anchor="w", text=fitted,
                                    fill=(FEED_DIM if dim else FEED_FG), font=FEED_FONT)
                self._feed_items.append(lid)
                if fitted != text:
                    self._scroll_lines.append({"item": lid, "full": text, "x_start": PAD + 6,
                                               "y0": y - FEED_LINE_H // 2, "y1": y + FEED_LINE_H // 2})
                self._register_hit(y, url)
                y += FEED_LINE_H
```

(This replaces the current inline `text=self._fit_px(text, PAD + 6)` with the `fitted` capture so truncation can be detected.)

3e. Add the marquee methods (near `_apply_hover`):

```python
    def _scroll_line_at(self, x, y):
        """The scrollable (truncated) line record under (x, y), or None."""
        for rec in self._scroll_lines:
            if rec["y0"] <= y <= rec["y1"]:
                return rec
        return None

    def _start_marquee(self, rec):
        if self._marquee is not None and self._marquee["item"] == rec["item"]:
            return
        self._stop_marquee()
        self._marquee = {"item": rec["item"], "full": rec["full"] + "    ",
                         "x_start": rec["x_start"], "offset": 0}
        self._marquee_after = self.root.after(400, self._marquee_step)   # brief pause, then scroll

    def _marquee_step(self):
        m = self._marquee
        if m is None:
            return
        s = m["full"]
        view = s[m["offset"]:] + s[:m["offset"]]
        try:
            self.canvas.itemconfig(m["item"], text=self._fit_px(view, m["x_start"]))
        except tk.TclError:
            self._stop_marquee(); return
        m["offset"] = (m["offset"] + 1) % len(s)
        self._marquee_after = self.root.after(110, self._marquee_step)

    def _stop_marquee(self):
        if self._marquee_after is not None:
            try:
                self.root.after_cancel(self._marquee_after)
            except Exception:
                pass
            self._marquee_after = None
        if self._marquee is not None:
            rec = next((r for r in self._scroll_lines if r["item"] == self._marquee["item"]), None)
            if rec is not None:
                try:
                    self.canvas.itemconfig(rec["item"], text=self._fit_px(rec["full"], rec["x_start"]))
                except tk.TclError:
                    pass
            self._marquee = None
```

3f. Drive the marquee from hover. In `_on_motion`, after `self._apply_hover()`, start/stop the marquee based on the hovered line:

```python
    def _on_motion(self, event):
        self._hover_xy = (event.x, event.y)
        self._apply_hover()
        rec = self._scroll_line_at(event.x, event.y)
        if rec is not None:
            self._start_marquee(rec)
        else:
            self._stop_marquee()
```

and in `_on_leave`, stop it:

```python
    def _on_leave(self, event):
        self._hover_xy = None
        self._apply_hover()
        self._stop_marquee()
```

3g. In `close()`, cancel the marquee timer (add near the `_drain_after` cancel):

```python
        self._stop_marquee()
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS (incl. the subprocess smoke launch).

- [ ] **Step 5: Full suite + commit**

Run the whole suite first:
`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests`
Expected: PASS.

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): hover marquee scroll of truncated feed lines; redraw only on change" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Expand toggle** → Task 1 (`self.width`, `WIDTH_WIDE=560`, `_toggle_width`, `↔` button, header relayout). **Session-only:** `_toggle_width` writes no config; width resets to `WIDTH` each launch.
- **Hover marquee** → Task 2 (`_scroll_lines` tracks truncated lines with full text; `_on_motion` starts a scroll; `_marquee_step` loops; `_on_leave`/redraw/close stop + restore). Only genuinely-truncated lines (`fitted != text`) scroll.
- **Redraw churn removed:** `_drain_feeds` now redraws only on new data — fixes the marquee-reset-every-250ms and cuts idle work.
- **Interplay:** `_draw_feeds` calls `_stop_marquee()` before rebuilding (stale item ids), then `_apply_hover()` at the end re-establishes the hover band; the next `<Motion>` restarts the marquee if still over a truncated line.
- **Security/gates untouched.** No config writes. `_fit_px`/hover/marquee read geometry only; no new URL path.
