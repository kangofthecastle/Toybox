# HUD Expand-Button Relocation + Smooth Marquee Fixups

> **For agentic workers:** Implement task-by-task with strict TDD. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix two issues the user found live: (1) the `↔` expand button is crammed onto the tab row — dim, overlapping "Sports", and not clickable (its hit zone is shadowed by the tab). Move it into the header as a proper window control: bright cyan, dedicated click zone, reliably clickable at both widths. (2) The hover marquee jumps a whole character per step; make it smooth pixel-motion.

**Tech Stack:** Python 3.12 stdlib only (tkinter Canvas). No pip.

## Global Constraints

- Pure Python 3.12 **stdlib only — no pip / third-party, ever**.
- Tests run from repo root with: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path>` (bare `python` is a broken stub).
- Commit trailer EXACTLY: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Branch `hud-stock-ticker` (already checked out).
- **NO config writes** (width is session state). Do not touch the security gates (`_register_hit`/`_open_at`/`is_web_url`) or weaken TLS.
- Keep all existing tests green (baseline: 539). New/updated tests assert real observable canvas/state behavior.

---

## Task 1: Relocate the expand button into the header (clock row), bright + clickable

The expand button currently lives in `_draw_tab_bar` as a `("width",)` action zone that overlaps the tabs. Remove it from the tab bar and make it a **persistent header control** on the clock row (`y3`), right-aligned, drawn in `ACCENT` (cyan), with its own fixed hit box checked in `_on_release` (like the old `_reload_box`). The news `⟳` stays on the tab row.

**Files:** Modify `hud.pyw`; Test `tests/test_smoke_hud.py`.

**Interfaces:** Produces persistent `self._expand_text` (canvas id) + `self._expand_box` (x0,y0,x1,y1); `Hud._in_expand(x, y) -> bool`. Removes the tab-bar `("width",)` zone and the `_dispatch_action` `"width"` branch.

- [ ] **Step 1: Update the failing tests**

In `tests/test_smoke_hud.py`, in `class TestHudExpand`, REPLACE `test_expand_action_registered_and_dispatches` with a header-based test, and ADD a placement test:

```python
    def test_expand_button_is_header_control_not_on_tabbar(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._draw_feeds(); root.update_idletasks()
            # no ("width",) action zone remains on the tab bar
            self.assertFalse(any(a == ("width",) for (_a, _b, _c, _d, a) in hud._action_hits))
            # a bright (ACCENT) expand glyph exists as a persistent header item
            self.assertEqual(hud.canvas.itemcget(hud._expand_text, "fill"), hudmod.ACCENT)
            self.assertEqual(hud.canvas.itemcget(hud._expand_text, "text"), hudmod.EXPAND_GLYPH)
        finally:
            hud.close(); root.destroy()

    def test_click_in_expand_box_toggles_width(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            x0, y0, x1, y1 = hud._expand_box
            ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
            hud._moved = False
            hud._on_release(ev); root.update_idletasks()
            self.assertEqual(hud.width, hudmod.WIDTH_WIDE)   # a real click toggled it
            hud._moved = False
            # after widening, the box moved to the new right edge; recompute and click again
            x0, y0, x1, y1 = hud._expand_box
            ev2 = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
            hud._on_release(ev2); root.update_idletasks()
            self.assertEqual(hud.width, hudmod.WIDTH)        # toggled back
        finally:
            hud.close(); root.destroy()
```

(Keep `test_toggle_changes_width_and_geometry`, `test_relayout_recenters_header`, and `test_wide_reduces_truncation` as-is.)

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudExpand -v`
Expected: FAIL (no `_expand_text`/`_expand_box`; `("width",)` still on tab bar).

- [ ] **Step 3: Implement**

3a. In `__init__`, right after the `_clock_text` is created (clock row `y3`), add the persistent expand control (ACCENT is defined at module level; CLOCK_FONT is the bold clock font — larger and more visible than the tab font):

```python
        self._expand_text = c.create_text(self.width - PAD, y3, anchor="e",
                                          text=EXPAND_GLYPH, fill=ACCENT, font=CLOCK_FONT)
        self._expand_box = (self.width - PAD - ACTION_ZONE_W, y3 - 10, self.width, y3 + 10)
```

3b. In `_draw_tab_bar`, REMOVE the expand-button block (the `ex_x = ...`, its `create_text`, and its `_register_action(row_y, ex_x - ACTION_ZONE_W, ex_x, ("width",))`). Keep the news `⟳` block. The method should end with just the reload glyph + its action + `return y + FEED_LINE_H + FEED_TITLE_GAP`.

3c. In `_dispatch_action`, REMOVE the `elif kind == "width": self._toggle_width()` branch (nothing registers `("width",)` anymore).

3d. Add `_in_expand` (near `_media_at`):

```python
    def _in_expand(self, x, y):
        """True if (x, y) is within the fixed expand/collapse control on the clock
        row (a constant box, like the old _reload_box)."""
        x0, y0, x1, y1 = self._expand_box
        return x0 <= x <= x1 and y0 <= y <= y1
```

3e. In `_on_release`, at the very top of the `if not self._moved:` block (before the `_media_at` check), add the expand check:

```python
            if self._in_expand(event.x, event.y):
                self._toggle_width()
                return
```

3f. In `_relayout_header`, reposition the expand control to the new width (add after the clock/media repositioning):

```python
        y3 = PAD + 3 * ROW_H + ROW_H // 2
        c.coords(self._expand_text, self.width - PAD, y3)
        self._expand_box = (self.width - PAD - ACTION_ZONE_W, y3 - 10, self.width, y3 + 10)
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "fix(hud): move expand button to header (bright, clickable, off the tab row)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Smooth pixel-motion marquee (replace character-stepping)

Replace the character-slice scroll with smooth pixel motion: show the full text (the canvas clips overflow to the window edge) and animate the item's x-coordinate back and forth (a gentle bounce that reveals the full headline), ~2px every 33ms.

**Files:** Modify `hud.pyw` (`_start_marquee`, `_marquee_step`, `_stop_marquee`); Test `tests/test_smoke_hud.py`.

- [ ] **Step 1: Update the tests**

In `class TestHudMarquee`, REPLACE `test_hover_truncated_line_starts_and_animates_marquee` and `test_leave_stops_marquee_and_restores_text` with pixel-motion versions (the text becomes the full string; the item's **x-coordinate** moves):

```python
    def test_hover_truncated_line_scrolls_by_pixels(self):
        root, hud = self._make_hud(self._long_feed())
        try:
            self._draw_long(hud, root)
            self.assertTrue(hud._scroll_lines, "expected a truncated (scrollable) line")
            rec = hud._scroll_lines[0]
            hud._on_motion(self._evt(60, (rec["y0"] + rec["y1"]) // 2))
            self.assertIsNotNone(hud._marquee)
            self.assertEqual(hud.canvas.itemcget(rec["item"], "text"), rec["full"])   # full text shown
            x_before = hud.canvas.coords(rec["item"])[0]
            for _ in range(4):
                hud._marquee_step()
            x_after = hud.canvas.coords(rec["item"])[0]
            self.assertLess(x_after, x_before)              # scrolled left by pixels
        finally:
            hud._stop_marquee()
            hud.close(); root.destroy()

    def test_leave_stops_marquee_and_restores(self):
        root, hud = self._make_hud(self._long_feed())
        try:
            self._draw_long(hud, root)
            rec = hud._scroll_lines[0]
            truncated = hud.canvas.itemcget(rec["item"], "text")
            base_x = hud.canvas.coords(rec["item"])[0]
            hud._on_motion(self._evt(60, (rec["y0"] + rec["y1"]) // 2))
            for _ in range(4):
                hud._marquee_step()
            hud._on_leave(self._evt(0, 0))
            self.assertIsNone(hud._marquee)
            self.assertEqual(hud.canvas.itemcget(rec["item"], "text"), truncated)   # text restored
            self.assertAlmostEqual(hud.canvas.coords(rec["item"])[0], base_x, delta=0.5)  # x restored
        finally:
            hud.close(); root.destroy()
```

(Keep `test_drain_without_new_data_does_not_redraw` and `test_hover_short_line_no_marquee` as-is.)

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudMarquee -v`
Expected: FAIL (current marquee changes text, not x-coord).

- [ ] **Step 3: Implement** — replace the three marquee methods:

```python
    def _start_marquee(self, rec):
        if self._marquee is not None and self._marquee["item"] == rec["item"]:
            return
        self._stop_marquee()
        self.canvas.itemconfig(rec["item"], text=rec["full"])   # full text; window clips overflow
        budget = self.width - PAD - rec["x_start"]
        full_w = self._feed_font_measure.measure(rec["full"])
        self._marquee = {"item": rec["item"], "base_x": rec["x_start"],
                         "max": max(0, full_w - budget), "offset": 0, "dir": 1, "pause": 0}
        self._marquee_after = self.root.after(400, self._marquee_step)   # brief pause, then scroll

    def _marquee_step(self):
        m = self._marquee
        if m is None:
            return
        try:
            if m["pause"] > 0:
                m["pause"] -= 1
            else:
                m["offset"] += m["dir"] * 2
                if m["offset"] >= m["max"]:
                    m["offset"] = m["max"]; m["dir"] = -1; m["pause"] = 12
                elif m["offset"] <= 0:
                    m["offset"] = 0; m["dir"] = 1; m["pause"] = 12
            y = self.canvas.coords(m["item"])[1]
            self.canvas.coords(m["item"], m["base_x"] - m["offset"], y)
        except tk.TclError:
            self._stop_marquee(); return
        self._marquee_after = self.root.after(33, self._marquee_step)

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
                    y = self.canvas.coords(rec["item"])[1]
                    self.canvas.coords(rec["item"], rec["x_start"], y)
                    self.canvas.itemconfig(rec["item"], text=self._fit_px(rec["full"], rec["x_start"]))
                except tk.TclError:
                    pass
            self._marquee = None
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS (incl. the subprocess smoke launch).

- [ ] **Step 5: Full suite + commit**

`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests`
Expected: PASS.

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): smooth pixel-motion marquee (bounce reveal of truncated lines)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Expand button** now a persistent header control on the clock row (`ACCENT` cyan, `CLOCK_FONT`), with a dedicated `_expand_box` hit-tested in `_on_release` — no tab-row overlap, reliably clickable, repositioned by `_relayout_header` on toggle. The `("width",)` action + its dispatch branch are removed.
- **Marquee** now animates the canvas item's x-coordinate in 2px steps every 33ms with a bounce (reveals start→end→start), the window clipping the overflow. `_stop_marquee` restores both text and x. Interplay with `_draw_feeds`/`_on_leave`/`close` unchanged (all call `_stop_marquee`).
- Security/gates untouched; no config writes.
