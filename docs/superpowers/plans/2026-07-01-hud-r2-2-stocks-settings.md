# Stock Tickers in the Settings Window Implementation Plan

> For agentic workers: use subagent-driven-development to execute; steps use checkbox syntax.

**Goal:** Wire the `stocks` feed type into the HUD's Feed Settings window so a stock
watchlist can be built and edited from the GUI instead of by hand-editing
`config.json`: an add-a-stocks-feed form (Title, Symbols, Range, Interval); an
inline editor on each existing stocks feed row (drop one ticker with `✕`, append
one with a small entry + `+`); and a `Tab` dropdown shown for news-type feeds so a
feed lands in the right tab. A new pure `parse_symbols` helper does the text→list
cleaning and is unit-tested directly (the GUI stays thin glue).

**Architecture:** Reuse the existing settings seams unchanged. All testable logic
lives in `feedkit/model.py` (`parse_symbols`, `normalize_feed` — already present);
`feedkit/settings.py` only assembles raw dicts and calls the existing scoped
`_persist`. The stocks branch of `normalize_feed` already validates/cleans symbols,
so settings does no validation of its own beyond calling `normalize_feed` and
surfacing its `error`. The `Tab` dropdown is gated on `model.is_news_type(ftype)`
so it automatically covers the future `weather` type without a hard dependency.

**Tech Stack:** Python 3.12 standard library only. `tkinter`/`ttk` (settings
window), `re` (symbol cleaning). No third-party packages.

## Global Constraints

- Pure Python 3.12 stdlib; no third-party packages.
- Never weaken urllib default TLS; only http/https may reach the browser.
- config.json is gitignored and holds a live GitHub PAT — never echo/log/commit it;
  every runtime config write goes through config.update(path, {...}) (scoped
  read-modify-write) so it cannot clobber another toy's keys.
- The HUD must never crash on bad external input: every parser returns a safe
  default; every ctypes/WinRT/Tk call is guarded (try/except).
- Lightweight: no busy loops; background polling is mtime/interval-gated.
- Test runner — use this EXACT command form in every "run the test" step:
    `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path> -v`
  run from the repo root. Bare "python" is broken on this machine.
- Commit trailer, EXACTLY (every commit step ends with this line):
    `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## Task 1: `parse_symbols` pure helper in `feedkit/model.py`

**Files:**
- Modify: `C:\Users\Warren\Toybox\feedkit\model.py`
- Test: `C:\Users\Warren\Toybox\tests\test_feed_model.py` (extend — add one class)

**Interfaces:**
- Produces: `feedkit.model.parse_symbols(text) -> list[str]` — split a
  comma/whitespace-separated ticker string; upper-case; strip each token to
  `[A-Z0-9.^-]`; dedupe preserving first-seen order; cap at 10. Non-str/empty → `[]`.
  Never raises. Mirrors the cleaning `normalize_feed` already applies to a stocks
  feed's `symbols`.
- Consumes: nothing (pure; uses `re`, already imported in `model.py`).

Steps:

- [ ] Step: write the failing test — append this class to the end of
  `C:\Users\Warren\Toybox\tests\test_feed_model.py`, immediately BEFORE the final
  `if __name__ == "__main__":` block:

```python
class TestParseSymbols(unittest.TestCase):
    def test_splits_on_commas_and_spaces_uppercases(self):
        self.assertEqual(model.parse_symbols("spy, meta nvda"), ["SPY", "META", "NVDA"])

    def test_strips_junk_chars_keeps_allowed(self):
        self.assertEqual(model.parse_symbols("brk-b ^gspc a@b!"), ["BRK-B", "^GSPC", "AB"])

    def test_dedupes_preserving_first_seen_order(self):
        self.assertEqual(model.parse_symbols("aapl AAPL msft aapl"), ["AAPL", "MSFT"])

    def test_caps_at_ten(self):
        syms = model.parse_symbols(" ".join("S%d" % i for i in range(20)))
        self.assertEqual(len(syms), 10)
        self.assertEqual(syms[0], "S0")
        self.assertEqual(syms[-1], "S9")

    def test_empty_and_non_str_return_empty(self):
        self.assertEqual(model.parse_symbols(""), [])
        self.assertEqual(model.parse_symbols("   ,  "), [])
        self.assertEqual(model.parse_symbols(None), [])
        self.assertEqual(model.parse_symbols(123), [])
```

- [ ] Step: run it, expect FAIL — the helper does not exist yet, so the class errors
  with `AttributeError: module 'feedkit.model' has no attribute 'parse_symbols'`:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model.TestParseSymbols -v
```

- [ ] Step: implement — in `C:\Users\Warren\Toybox\feedkit\model.py`, insert the
  following directly AFTER the `format_quote_line` function (which ends with the
  `return "%-5s %7.2f %s%.1f%%" % (...)` line) and BEFORE the `NEWS_TABS = (...)`
  definition:

```python
_SYMBOL_JUNK = re.compile(r"[^A-Z0-9.^-]")
_SYMBOL_SPLIT = re.compile(r"[,\s]+")


def parse_symbols(text):
    """Split a comma/whitespace-separated ticker string into a clean symbol list:
    upper-cased, stripped to [A-Z0-9.^-], deduped preserving first-seen order, and
    capped at 10. Never raises; non-str or empty input -> []. Mirrors the cleaning
    normalize_feed applies to a stocks feed's 'symbols'."""
    if not isinstance(text, str):
        return []
    out = []
    for tok in _SYMBOL_SPLIT.split(text):
        clean = _SYMBOL_JUNK.sub("", tok.strip().upper())
        if clean and clean not in out:
            out.append(clean)
            if len(out) >= 10:
                break
    return out
```

- [ ] Step: run it, expect PASS:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model.TestParseSymbols -v
```

- [ ] Step: commit:

```
git add feedkit/model.py tests/test_feed_model.py
git commit -m "$(printf 'feedkit.model: add parse_symbols ticker-cleaning helper\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 2: Add-a-stocks-feed form + Tab dropdown in `feedkit/settings.py`

**Files:**
- Modify: `C:\Users\Warren\Toybox\feedkit\settings.py`
- Test: `C:\Users\Warren\Toybox\tests\test_smoke_hud.py` (extend the existing
  `TestFeedSettings` class — add methods)

**Interfaces:**
- Produces: `feedkit.settings._TYPES` gains `"stocks"` (appears in the Add dropdown).
- Produces: `_render_fields()` renders, for `ftype == "stocks"`, entry rows
  `Title`/`Symbols`/`Interval s`, a `Range` `OptionMenu` bound to
  `self._range_var` (values `model.STOCK_RANGE_ORDER`, default
  `model.DEFAULT_STOCK_RANGE`); and, for any `model.is_news_type(ftype)`, a `Tab`
  `OptionMenu` bound to `self._tab_var` (values = the `model.NEWS_TABS` keys,
  default `"global"`).
- Produces: `_on_add()` writes `raw["symbols"] = model.parse_symbols(<Symbols text>)`
  and `raw["range"] = self._range_var.get()` for stocks; writes
  `raw["tab"] = self._tab_var.get()` for every news-type feed; pinned types
  (github/notifications/search) get no `tab` key.
- Consumes: `feedkit.model.parse_symbols`, `feedkit.model.is_news_type`,
  `feedkit.model.NEWS_TABS`, `feedkit.model.STOCK_RANGE_ORDER`,
  `feedkit.model.DEFAULT_STOCK_RANGE`, `feedkit.model.normalize_feed` (all already
  exist in `model.py`; `parse_symbols` added in Task 1).

Steps:

- [ ] Step: write the failing test — append these three methods INSIDE the existing
  `class TestFeedSettings(_HudTestBase):` in
  `C:\Users\Warren\Toybox\tests\test_smoke_hud.py` (place them after
  `test_search_on_add_builds_query_feed`, keeping them at the same indentation as
  the other `test_*` methods in that class):

```python
    def test_stocks_type_in_add_dropdown(self):
        import feedkit.settings as settings
        self.assertIn("stocks", settings._TYPES)

    def test_stocks_render_fields_has_symbols_range_tab(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("stocks")
            hud.settings._render_fields()
            self.assertIn("symbols", hud.settings._fields)
            self.assertIsNotNone(hud.settings._range_var)
            self.assertIsNotNone(hud.settings._tab_var)
            self.assertNotIn("url", hud.settings._fields)
            hud.close()
        finally:
            root.destroy()

    def test_stocks_on_add_builds_symbols_range_tab_feed(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("stocks")
            hud.settings._render_fields()
            hud.settings._fields["title"].set("Markets")
            hud.settings._fields["symbols"].set("spy, nvda aapl")
            hud.settings._range_var.set("1d")
            hud.settings._tab_var.set("markets")
            hud.settings._on_add()
            added = hud.cfg["feeds"][-1]
            self.assertEqual(added["type"], "stocks")
            self.assertEqual(added["symbols"], ["SPY", "NVDA", "AAPL"])
            self.assertEqual(added["range"], "1d")
            self.assertEqual(added["tab"], "markets")
            self.assertTrue(hud.manager.feeds[-1]["valid"])
            hud.close()
        finally:
            root.destroy()

    def test_rss_on_add_writes_tab_notifications_does_not(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("rss")
            hud.settings._render_fields()
            hud.settings._fields["title"].set("R")
            hud.settings._fields["url"].set("https://x/y")
            hud.settings._tab_var.set("tech")
            hud.settings._on_add()
            self.assertEqual(hud.cfg["feeds"][-1]["tab"], "tech")
            hud.settings._type_var.set("notifications")
            hud.settings._render_fields()
            hud.settings._fields["title"].set("N")
            hud.settings._on_add()
            self.assertNotIn("tab", hud.cfg["feeds"][-1])
            hud.close()
        finally:
            root.destroy()
```

- [ ] Step: run it, expect FAIL — `stocks` is not in `_TYPES` yet, `_render_fields`
  builds no stocks spec / `_range_var` / `_tab_var`, and `_on_add` writes no
  `symbols`/`range`/`tab`. Expect `KeyError: 'stocks'` (spec dict lookup) /
  `AttributeError` on `_range_var`/`_tab_var` / assertion failures:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestFeedSettings.test_stocks_type_in_add_dropdown tests.test_smoke_hud.TestFeedSettings.test_stocks_render_fields_has_symbols_range_tab tests.test_smoke_hud.TestFeedSettings.test_stocks_on_add_builds_symbols_range_tab_feed tests.test_smoke_hud.TestFeedSettings.test_rss_on_add_writes_tab_notifications_does_not -v
```

- [ ] Step: implement — make three edits in `C:\Users\Warren\Toybox\feedkit\settings.py`.

  (a) Add `"stocks"` to `_TYPES`. Replace the line:

```python
_TYPES = ("rss", "json", "text", "github", "notifications", "search")
```

  with:

```python
_TYPES = ("rss", "json", "text", "github", "notifications", "search", "stocks")
```

  (b) Replace the ENTIRE `_render_fields` method with this version (adds the
  `stocks` spec entry, the `Range` OptionMenu, and the news-type `Tab` OptionMenu):

```python
    def _render_fields(self):
        for w in self._fields_frame.winfo_children():
            w.destroy()
        self._fields = {}
        ftype = self._type_var.get()
        spec = {
            "rss":  [("title", "Title"), ("url", "URL"), ("items", "Items"), ("interval", "Interval s")],
            "json": [("title", "Title"), ("url", "URL"), ("path", "JSON path"),
                     ("text", "field:text"), ("urlfield", "field:url"),
                     ("items", "Items"), ("interval", "Interval s")],
            "text": [("title", "Title"), ("url", "URL"), ("regex", "Regex (opt)"),
                     ("items", "Items"), ("interval", "Interval s")],
            "github": [("title", "Title"), ("repo", "owner/name"), ("branch", "Branch"),
                       ("interval", "Interval s")],
            "notifications": [("title", "Title"), ("items", "Items"), ("interval", "Interval s")],
            "search": [("title", "Title"), ("query", "Query"),
                       ("items", "Items"), ("interval", "Interval s")],
            "stocks": [("title", "Title"), ("symbols", "Symbols"), ("interval", "Interval s")],
        }[ftype]
        for key, label in spec:
            row = tk.Frame(self._fields_frame); row.pack(anchor="w", pady=1)
            tk.Label(row, text=label, width=10, anchor="w").pack(side="left")
            var = tk.StringVar()
            tk.Entry(row, width=30, textvariable=var).pack(side="left")
            self._fields[key] = var
        if ftype == "github":
            self._show_ci = tk.IntVar(value=1)
            self._show_notif = tk.IntVar(value=1)
            crow = tk.Frame(self._fields_frame); crow.pack(anchor="w", pady=1)
            tk.Checkbutton(crow, text="CI", variable=self._show_ci).pack(side="left")
            tk.Checkbutton(crow, text="Notifications", variable=self._show_notif).pack(side="left")
        if ftype == "search":
            prow = tk.Frame(self._fields_frame); prow.pack(anchor="w", pady=1)
            tk.Label(prow, text="Preset", width=10, anchor="w").pack(side="left")
            self._preset_var = tk.StringVar(value="")
            tk.OptionMenu(prow, self._preset_var, *_SEARCH_PRESETS,
                          command=self._apply_search_preset).pack(side="left")
        if ftype == "stocks":
            rrow = tk.Frame(self._fields_frame); rrow.pack(anchor="w", pady=1)
            tk.Label(rrow, text="Range", width=10, anchor="w").pack(side="left")
            self._range_var = tk.StringVar(value=model.DEFAULT_STOCK_RANGE)
            tk.OptionMenu(rrow, self._range_var, *model.STOCK_RANGE_ORDER).pack(side="left")
        if model.is_news_type(ftype):
            trow = tk.Frame(self._fields_frame); trow.pack(anchor="w", pady=1)
            tk.Label(trow, text="Tab", width=10, anchor="w").pack(side="left")
            self._tab_var = tk.StringVar(value="global")
            tk.OptionMenu(trow, self._tab_var, *[k for k, _ in model.NEWS_TABS]).pack(side="left")
        tk.Button(self._fields_frame, text="Add feed", command=self._on_add).pack(anchor="w", pady=4)
```

  (c) Replace the ENTIRE `_on_add` method with this version (adds the `stocks`
  branch and the news-type `tab` write):

```python
    def _on_add(self):
        ftype = self._type_var.get()
        g = lambda k: self._fields[k].get().strip()
        raw = {"type": ftype, "title": g("title")}
        if g("interval"):
            raw["interval"] = _as_int(g("interval"))
        if ftype == "github":
            raw["repo"] = g("repo")
            if g("branch"):
                raw["branch"] = g("branch")
            show = []
            if self._show_ci.get():
                show.append("ci")
            if self._show_notif.get():
                show.append("notifications")
            raw["show"] = show
        elif ftype == "notifications":
            if g("items"):
                raw["items"] = _as_int(g("items"))
        elif ftype == "search":
            raw["query"] = g("query")
            if g("items"):
                raw["items"] = _as_int(g("items"))
        elif ftype == "stocks":
            raw["symbols"] = model.parse_symbols(g("symbols"))
            raw["range"] = self._range_var.get()
        else:
            raw["url"] = g("url")
            if g("items"):
                raw["items"] = _as_int(g("items"))
            if ftype == "json":
                raw["path"] = g("path")
                raw["fields"] = {"text": g("text"), "url": g("urlfield") or None}
            elif ftype == "text" and g("regex"):
                raw["regex"] = g("regex")
        if model.is_news_type(ftype):
            raw["tab"] = self._tab_var.get()
        norm = model.normalize_feed(raw)
        if not norm.get("valid"):
            self._status.set(norm.get("error") or "invalid feed")
            return
        self._status.set("")
        self._add_feed_dict(raw)
```

- [ ] Step: run it, expect PASS:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestFeedSettings.test_stocks_type_in_add_dropdown tests.test_smoke_hud.TestFeedSettings.test_stocks_render_fields_has_symbols_range_tab tests.test_smoke_hud.TestFeedSettings.test_stocks_on_add_builds_symbols_range_tab_feed tests.test_smoke_hud.TestFeedSettings.test_rss_on_add_writes_tab_notifications_does_not -v
```

- [ ] Step: also run the whole `TestFeedSettings` class to confirm no regression in
  the existing rss/github/notifications/search settings tests:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestFeedSettings -v
```

- [ ] Step: commit:

```
git add feedkit/settings.py tests/test_smoke_hud.py
git commit -m "$(printf 'feedkit.settings: stocks add-feed form + news-type Tab dropdown\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 3: Inline per-symbol editor on existing stocks feed rows

**Files:**
- Modify: `C:\Users\Warren\Toybox\feedkit\settings.py`
- Test: `C:\Users\Warren\Toybox\tests\test_smoke_hud.py` (extend the existing
  `TestFeedSettings` class — add methods)

**Interfaces:**
- Produces: `_refresh_list()` renders, under each stocks feed's summary row, a
  symbol editor (via the new `_render_symbol_editor(index, feed)`): one `✕`
  button per current ticker plus a small entry + `+` button to append a ticker.
- Produces: `_remove_symbol(index, symbol) -> None` — drop one ticker from the raw
  stocks feed's `symbols`, persist via the existing scoped `_persist`, refresh.
- Produces: `_add_symbol(index, var) -> None` — parse `var.get()` with
  `model.parse_symbols`, append to the raw feed's `symbols` (deduped, capped 10),
  persist, refresh; no-op when the entry parses to nothing.
- Consumes: `feedkit.model.parse_symbols` (Task 1), `feedkit.model.normalize_feed`,
  the existing `self._persist` and `self._list` frame.

Steps:

- [ ] Step: write the failing test — append these three methods INSIDE the existing
  `class TestFeedSettings(_HudTestBase):` in
  `C:\Users\Warren\Toybox\tests\test_smoke_hud.py` (after the methods added in
  Task 2, same indentation):

```python
    def test_remove_symbol_drops_ticker_and_persists(self):
        feed = {"type": "stocks", "title": "Markets",
                "symbols": ["SPY", "META", "NVDA"], "range": "1mo", "tab": "markets"}
        root, hud = self._make_hud([feed], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._remove_symbol(0, "META")
            self.assertEqual(hud.cfg["feeds"][0]["symbols"], ["SPY", "NVDA"])
            self.assertTrue(hud.manager.feeds[0]["valid"])
            hud.close()
        finally:
            root.destroy()

    def test_add_symbol_appends_ticker_deduped_and_capped(self):
        import tkinter as tk
        feed = {"type": "stocks", "title": "Markets",
                "symbols": ["SPY"], "range": "1mo", "tab": "markets"}
        root, hud = self._make_hud([feed], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            var = tk.StringVar()
            var.set("nvda, spy")                     # 'spy' already present -> deduped
            hud.settings._add_symbol(0, var)
            self.assertEqual(hud.cfg["feeds"][0]["symbols"], ["SPY", "NVDA"])
            # empty/garbage entry is a no-op
            blank = tk.StringVar(); blank.set("  !!  ")
            hud.settings._add_symbol(0, blank)
            self.assertEqual(hud.cfg["feeds"][0]["symbols"], ["SPY", "NVDA"])
            hud.close()
        finally:
            root.destroy()

    def test_stocks_feed_row_renders_symbol_chips_and_add(self):
        feed = {"type": "stocks", "title": "Markets",
                "symbols": ["SPY", "NVDA"], "range": "1mo", "tab": "markets"}
        root, hud = self._make_hud([feed], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            texts = []

            def walk(w):
                for c in w.winfo_children():
                    try:
                        texts.append(c.cget("text"))
                    except Exception:
                        pass
                    walk(c)
            walk(hud.settings._list)
            self.assertIn("SPY", texts)
            self.assertIn("NVDA", texts)
            self.assertIn("+", texts)                # add-ticker button present
            hud.close()
        finally:
            root.destroy()
```

- [ ] Step: run it, expect FAIL — `_remove_symbol`/`_add_symbol` don't exist and
  `_refresh_list` renders no per-symbol chips, so expect `AttributeError:
  'FeedSettingsWindow' object has no attribute '_remove_symbol'` and a missing
  `"SPY"`/`"+"` text assertion:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestFeedSettings.test_remove_symbol_drops_ticker_and_persists tests.test_smoke_hud.TestFeedSettings.test_add_symbol_appends_ticker_deduped_and_capped tests.test_smoke_hud.TestFeedSettings.test_stocks_feed_row_renders_symbol_chips_and_add -v
```

- [ ] Step: implement — make two edits in `C:\Users\Warren\Toybox\feedkit\settings.py`.

  (a) Replace the ENTIRE `_refresh_list` method with this version (adds the stocks
  editor call after the summary row; everything else is unchanged):

```python
    def _refresh_list(self):
        if self.win is None:
            return
        try:
            for w in self._list.winfo_children():
                w.destroy()
            feeds = self.hud.cfg.get("feeds", [])
            if not feeds:
                tk.Label(self._list, text="(no feeds)", fg="#888").pack(anchor="w")
                return
            for i, feed in enumerate(feeds):
                norm = model.normalize_feed(feed)
                row = tk.Frame(self._list); row.pack(fill="x", pady=1)
                tk.Button(row, text="✕", width=2,
                          command=lambda idx=i: self._remove(idx)).pack(side="right")
                label = "%s  [%s]%s" % (norm.get("title", "feed"), feed.get("type", "?"),
                                        "" if norm.get("valid") else "  !")
                tk.Label(row, text=label, anchor="w").pack(side="left")
                if isinstance(feed, dict) and feed.get("type") == "stocks":
                    self._render_symbol_editor(i, feed)
        except tk.TclError:
            return
```

  (b) Add the three new methods. Insert them in `feedkit/settings.py` immediately
  AFTER the `_refresh_list` method you just replaced and BEFORE the
  `# --- GitHub tab ---` comment / `_build_github_tab` method:

```python
    def _render_symbol_editor(self, index, feed):
        """Under a stocks feed row: each current ticker with a ✕ to drop it, plus a
        small entry + '+' to append one. Edits the raw feed's symbol list in place
        and persists via the scoped _persist."""
        syms = feed.get("symbols") if isinstance(feed.get("symbols"), list) else []
        chips = tk.Frame(self._list); chips.pack(fill="x", padx=(20, 0))
        for sym in syms:
            if not isinstance(sym, str):
                continue
            chip = tk.Frame(chips); chip.pack(side="left", padx=2)
            tk.Label(chip, text=sym).pack(side="left")
            tk.Button(chip, text="✕", width=2,
                      command=lambda idx=index, s=sym: self._remove_symbol(idx, s)).pack(side="left")
        arow = tk.Frame(self._list); arow.pack(fill="x", padx=(20, 0))
        addvar = tk.StringVar()
        tk.Entry(arow, width=8, textvariable=addvar).pack(side="left")
        tk.Button(arow, text="+", width=2,
                  command=lambda idx=index, v=addvar: self._add_symbol(idx, v)).pack(side="left")

    def _remove_symbol(self, index, symbol):
        """Drop one ticker from a stocks feed's raw symbol list and persist."""
        feeds = list(self.hud.cfg.get("feeds", []))
        if not (0 <= index < len(feeds)) or not isinstance(feeds[index], dict):
            return
        feed = dict(feeds[index])
        feed["symbols"] = [s for s in feed.get("symbols", []) if s != symbol]
        feeds[index] = feed
        self.hud.cfg["feeds"] = feeds
        self._persist()
        self._refresh_list()

    def _add_symbol(self, index, var):
        """Append parsed ticker(s) to a stocks feed's raw symbol list (deduped, cap
        10) and persist. No-op when the entry parses to nothing."""
        feeds = list(self.hud.cfg.get("feeds", []))
        if not (0 <= index < len(feeds)) or not isinstance(feeds[index], dict):
            return
        added = model.parse_symbols(var.get())
        if not added:
            return
        feed = dict(feeds[index])
        existing = feed.get("symbols") if isinstance(feed.get("symbols"), list) else []
        combined = " ".join([str(s) for s in existing] + added)
        feed["symbols"] = model.parse_symbols(combined)
        feeds[index] = feed
        self.hud.cfg["feeds"] = feeds
        self._persist()
        self._refresh_list()
```

- [ ] Step: run it, expect PASS:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestFeedSettings.test_remove_symbol_drops_ticker_and_persists tests.test_smoke_hud.TestFeedSettings.test_add_symbol_appends_ticker_deduped_and_capped tests.test_smoke_hud.TestFeedSettings.test_stocks_feed_row_renders_symbol_chips_and_add -v
```

- [ ] Step: run the whole settings class + the model tests to confirm no regression:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestFeedSettings tests.test_feed_model -v
```

- [ ] Step: commit:

```
git add feedkit/settings.py tests/test_smoke_hud.py
git commit -m "$(printf 'feedkit.settings: inline per-symbol add/remove on stocks feed rows\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```
