# HUD Tabbed Feeds + Stock Ticker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group the HUD's non-GitHub feeds into four switchable tabs (Global/Markets/Tech/Sports, default Tech) with an always-pinned GitHub section and two independent refreshes, and add a `stocks` feed type that renders per-symbol price + day %change + a drawn mini price chart with a `1D 1W 1M 3M` window toggle.

**Architecture:** Reuse the existing feedkit split — pure `model.py` (types, URL builders, `normalize_feed`), pure `parse.py` (defensive parsers), glue `manager.py` (daemon-worker fetch→parse→queue), canvas `hud.pyw`. Stocks data comes from Yahoo's keyless v8 chart endpoint via the existing `fetch`. Tabs and stock range are **session state** (no config writes). Backend (model→parse→manager) lands first, then the HUD rendering/interaction, then a one-time config data migration.

**Tech Stack:** Python 3.12 stdlib only (tkinter, urllib, json, math, collections, threading, queue). No pip/third-party.

## Global Constraints

Every task's requirements implicitly include these (copied verbatim from the spec):

- Pure Python 3.12 **stdlib only — no pip / third-party, ever**.
- Tests run from repo root with: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path>` (bare `python`/`python3` is a broken MS-Store stub — do not use it).
- Default urllib TLS, **never weakened**; only `http`/`https` may reach the browser (the `is_web_url` gate) — stock/quote click targets are https literals.
- This feature performs **no config writes** in the running code (range + active tab are session state), so no sibling-toy restart is required after it lands. The one-time config **data** migration (Task 10) is a manual edit, not runtime code.
- Commit trailer EXACTLY: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Network access only via the Bash tool.
- Branch: `hud-stock-ticker`, rebased onto `origin/main` (`3b4531f`, which merged PR #4 — the GPU-row + media-controls work); spec commit is `d64182f`.
- `config.json` is gitignored and holds the user's live GitHub PAT — never echo, log, or commit its contents.

---

## Integration Note — rebased onto main (GPU + media rows)

This branch was rebased onto `origin/main` `3b4531f`, which merged PR #4 (a GPU% sparkline row + a media-controls row). `hud.pyw` now has a **5-row metrics header** — CPU / RAM / GPU / clock (+ old ⟳) / media — and `HEIGHT = 134` (was 96). Consequences already folded into this plan (all in Task 8):

- Feeds start at `y = PAD + 5 * ROW_H + 4` (not `3 * ROW_H`).
- The GPU sparkline (`_gpu_text`/`_gpu_line`) and media controls (`_media_prev/_media_play/_media_next`, `_media_hits`) are **persistent header items** created once in `__init__` — never clear or remove them. `_draw_feeds` only clears `self._feed_items`.
- `_on_release` now dispatches media clicks via `_media_at` → `_do_media`. Task 8's rewrite **keeps** that branch and removes only the old reload `_in_reload` branch.
- New tests `TestHudGpuRow` / `TestHudMediaRow` in `tests/test_smoke_hud.py` must keep passing; `test_reload_control_click_reloads` (still present) is the one Task 8 deletes.
- No `feedkit/`, `model`, `parse`, or `manager` files changed on main — **Tasks 1–7, 9, 10 are unaffected.**

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `feedkit/model.py` | modify | Add `stocks` type; `Quote` namedtuple; stock range/label constants; `yahoo_chart_url`/`yahoo_quote_web_url`/`format_quote_line`; tab constants + `coerce_tab`/`coerce_default_tab`; `is_news_type`/`is_pinned_type`; `normalize_feed` stocks branch + `tab` on news feeds |
| `feedkit/parse.py` | modify | `parse_stock_chart(body, symbol)` → `Quote` or `None`, never raises |
| `feedkit/manager.py` | modify | `_process_stocks` + dispatch; `set_stock_range`; `refresh` |
| `hud.pyw` | modify | `_stock_points` (pure) + partition helpers; tabbed layout + interactions; stocks tile + range toggle |
| `tests/test_feed_model.py` | modify | Model unit tests |
| `tests/test_feed_parse.py` | modify | `parse_stock_chart` tests |
| `tests/test_feed_manager.py` | modify | `_process_stocks`/`set_stock_range`/`refresh` tests |
| `tests/test_smoke_hud.py` | modify | `_stock_points`, partition, tab, stocks HUD tests |
| `config.json` | manual data edit (Task 10) | Place existing feeds in tabs, add stocks feed, add `hud.default_tab` |

`feedkit/settings.py` is **unchanged** — tabs/stocks are configured by editing `config.json`.

---

## Task 1: model.py — stock display primitives

**Files:**
- Modify: `feedkit/model.py` (add near the top-level helpers, e.g. after `is_web_url`)
- Test: `tests/test_feed_model.py`

**Interfaces:**
- Consumes: `urllib.parse` (already imported in `model.py`).
- Produces: `Quote = namedtuple("Quote", ["symbol","price","change_pct","series"])`; constants `STOCK_RANGES` (dict range→bar-interval), `STOCK_RANGE_ORDER` (tuple), `STOCK_RANGE_LABELS` (dict), `DEFAULT_STOCK_RANGE = "1mo"`; `yahoo_chart_url(symbol, range_) -> str`; `yahoo_quote_web_url(symbol) -> str`; `format_quote_line(quote) -> str`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_model.py`:

```python
class TestStockPrimitives(unittest.TestCase):
    def test_quote_shape(self):
        q = model.Quote("SPY", 746.77, -1.3, [1.0, 2.0])
        self.assertEqual(q._fields, ("symbol", "price", "change_pct", "series"))
        self.assertEqual(q.symbol, "SPY")

    def test_chart_url_maps_range_to_interval(self):
        self.assertEqual(
            model.yahoo_chart_url("SPY", "1mo"),
            "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
            "?range=1mo&interval=1d&includePrePost=false")
        self.assertIn("range=1d&interval=5m", model.yahoo_chart_url("SPY", "1d"))
        self.assertIn("range=5d&interval=30m", model.yahoo_chart_url("SPY", "5d"))
        self.assertIn("range=3mo&interval=1d", model.yahoo_chart_url("SPY", "3mo"))

    def test_chart_url_unknown_range_falls_back_to_default(self):
        self.assertIn("range=1mo&interval=1d", model.yahoo_chart_url("SPY", "zzz"))

    def test_chart_url_percent_encodes_symbol(self):
        self.assertIn("/chart/%5EGSPC?", model.yahoo_chart_url("^GSPC", "1mo"))

    def test_quote_web_url_is_browser_url(self):
        u = model.yahoo_quote_web_url("SPY")
        self.assertEqual(u, "https://finance.yahoo.com/quote/SPY")
        self.assertTrue(model.is_web_url(u))

    def test_format_quote_line_down(self):
        q = model.Quote("SPY", 746.77, -1.3, [])
        self.assertEqual(model.format_quote_line(q), "SPY    746.77 ▼1.3%")

    def test_format_quote_line_up_and_zero(self):
        self.assertTrue(model.format_quote_line(model.Quote("META", 563.29, 0.14, [])).endswith("△0.1%"))
        self.assertIn("△", model.format_quote_line(model.Quote("X", 1.0, 0.0, [])))  # 0.0 -> up
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model.TestStockPrimitives -v`
Expected: FAIL (AttributeError: module 'feedkit.model' has no attribute 'Quote'/'yahoo_chart_url'/…).

- [ ] **Step 3: Implement**

In `feedkit/model.py`, after the `is_web_url` definition (before the GitHub builders is fine), add:

```python
Quote = namedtuple("Quote", ["symbol", "price", "change_pct", "series"])
# price, change_pct are floats; series is list[float] (may be empty).

STOCK_RANGES = {"1d": "5m", "5d": "30m", "1mo": "1d", "3mo": "1d"}   # range -> bar interval
STOCK_RANGE_ORDER = ("1d", "5d", "1mo", "3mo")
STOCK_RANGE_LABELS = {"1d": "1D", "5d": "1W", "1mo": "1M", "3mo": "3M"}
DEFAULT_STOCK_RANGE = "1mo"


def yahoo_chart_url(symbol, range_):
    """Yahoo v8 chart endpoint for one symbol. Unknown range -> DEFAULT_STOCK_RANGE.
    The symbol is percent-encoded (e.g. '^GSPC' -> '%5EGSPC'). Keyless; the
    feedkit default UA returns HTTP 200."""
    r = range_ if range_ in STOCK_RANGES else DEFAULT_STOCK_RANGE
    return ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
            "?range=%s&interval=%s&includePrePost=false"
            % (urllib.parse.quote(symbol, safe=""), r, STOCK_RANGES[r]))


def yahoo_quote_web_url(symbol):
    """Browser quote page for a symbol (the tile's click target)."""
    return "https://finance.yahoo.com/quote/%s" % urllib.parse.quote(symbol, safe="")


def format_quote_line(quote):
    """One-line quote render: '<sym> <price> <arrow><|pct|>%'. Arrow is up (green)
    when change_pct >= 0 (exactly 0.0 counts as up), else down. Example:
    'SPY    746.77 ▼1.3%'."""
    arrow = "△" if quote.change_pct >= 0 else "▼"
    return "%-5s %7.2f %s%.1f%%" % (quote.symbol, quote.price, arrow, abs(quote.change_pct))
```

> Note: the tests use `△`/`▼` (▲/▼) so the plan stays ASCII-safe; the source may use the literal glyphs. Keep the format string exactly `"%-5s %7.2f %s%.1f%%"`.

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: PASS (all, including the pre-existing model tests).

- [ ] **Step 5: Commit**

```bash
git add feedkit/model.py tests/test_feed_model.py
git commit -m "feat(feedkit): stock quote/url/format model primitives" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: model.py — tab constants + type classification

**Files:**
- Modify: `feedkit/model.py`
- Test: `tests/test_feed_model.py`

**Interfaces:**
- Produces: `NEWS_TABS` (tuple of `(key, label)` pairs, ordered global→markets→tech→sports); `DEFAULT_TAB = "tech"`; `coerce_tab(value) -> str` (default `"global"`); `coerce_default_tab(value) -> str` (default `"tech"`); `is_news_type(t) -> bool` (true for rss/json/text/stocks); `is_pinned_type(t) -> bool` (true for github/notifications/search).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_model.py`:

```python
class TestTabsAndTypes(unittest.TestCase):
    def test_news_tabs_order_and_labels(self):
        self.assertEqual([k for k, _ in model.NEWS_TABS],
                         ["global", "markets", "tech", "sports"])
        self.assertEqual(dict(model.NEWS_TABS)["markets"], "Markets")

    def test_coerce_tab_valid_and_default_global(self):
        self.assertEqual(model.coerce_tab("markets"), "markets")
        self.assertEqual(model.coerce_tab("nope"), "global")
        self.assertEqual(model.coerce_tab(None), "global")

    def test_coerce_default_tab_valid_and_default_tech(self):
        self.assertEqual(model.coerce_default_tab("global"), "global")
        self.assertEqual(model.coerce_default_tab("bogus"), "tech")
        self.assertEqual(model.coerce_default_tab(None), "tech")

    def test_is_news_type(self):
        for t in ("rss", "json", "text", "stocks"):
            self.assertTrue(model.is_news_type(t), t)
        for t in ("github", "notifications", "search", "?", None):
            self.assertFalse(model.is_news_type(t), t)

    def test_is_pinned_type(self):
        for t in ("github", "notifications", "search"):
            self.assertTrue(model.is_pinned_type(t), t)
        for t in ("rss", "json", "text", "stocks", "?", None):
            self.assertFalse(model.is_pinned_type(t), t)
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model.TestTabsAndTypes -v`
Expected: FAIL (no attribute `NEWS_TABS`/`coerce_tab`/…).

- [ ] **Step 3: Implement**

In `feedkit/model.py`, add (near the stock constants from Task 1):

```python
NEWS_TABS = (("global", "Global"), ("markets", "Markets"),
             ("tech", "Tech"), ("sports", "Sports"))
DEFAULT_TAB = "tech"
_TAB_KEYS = frozenset(k for k, _ in NEWS_TABS)
_NEWS_TYPES = ("rss", "json", "text", "stocks")
_PINNED_TYPES = ("github", "notifications", "search")


def coerce_tab(value):
    """A valid tab key for a news feed; unknown/missing -> 'global'."""
    return value if value in _TAB_KEYS else "global"


def coerce_default_tab(value):
    """A valid tab key for hud.default_tab; unknown/missing -> DEFAULT_TAB ('tech')."""
    return value if value in _TAB_KEYS else DEFAULT_TAB


def is_news_type(t):
    """True for tabbed news feed types (rss/json/text/stocks)."""
    return t in _NEWS_TYPES


def is_pinned_type(t):
    """True for pinned GitHub-family feed types (github/notifications/search)."""
    return t in _PINNED_TYPES
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/model.py tests/test_feed_model.py
git commit -m "feat(feedkit): tab constants and news/pinned type classifiers" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: model.py — normalize_feed stocks branch + `tab` on news feeds

**Files:**
- Modify: `feedkit/model.py:204` (`_VALID_TYPES`) and `feedkit/model.py:224-311` (`normalize_feed`)
- Test: `tests/test_feed_model.py`

**Interfaces:**
- Consumes: `STOCK_RANGES`, `DEFAULT_STOCK_RANGE` (Task 1); `coerce_tab`, `is_news_type` (Task 2); `re`, `_coerce_int` (already in `model.py`).
- Produces: normalized dicts where every **news-type** feed (valid or invalid) carries a `"tab"` key, and a valid `stocks` feed carries `{"symbols": list[str], "range": str, "interval": int, "tab": str, "title": str}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_model.py`:

```python
class TestNormalizeStocksAndTab(unittest.TestCase):
    def test_news_feeds_get_tab(self):
        self.assertEqual(model.normalize_feed(
            {"type": "rss", "url": "https://x/y", "tab": "tech"})["tab"], "tech")
        self.assertEqual(model.normalize_feed(
            {"type": "rss", "url": "https://x/y"})["tab"], "global")          # missing -> global
        self.assertEqual(model.normalize_feed(
            {"type": "rss", "url": "https://x/y", "tab": "nope"})["tab"], "global")  # unknown -> global

    def test_invalid_news_feed_still_has_tab(self):
        f = model.normalize_feed({"type": "rss", "tab": "markets"})            # missing url -> invalid
        self.assertFalse(f["valid"])
        self.assertEqual(f["tab"], "markets")

    def test_pinned_feeds_have_no_tab(self):
        self.assertNotIn("tab", model.normalize_feed({"type": "notifications"}))
        self.assertNotIn("tab", model.normalize_feed({"type": "github", "repo": "o/r"}))

    def test_stocks_minimal_valid(self):
        f = model.normalize_feed({"type": "stocks", "symbols": ["spy", "META"],
                                  "range": "1d", "tab": "markets"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["symbols"], ["SPY", "META"])                       # upper-cased
        self.assertEqual(f["range"], "1d")
        self.assertEqual(f["tab"], "markets")
        self.assertEqual(f["interval"], 300)                                  # default
        self.assertEqual(f["title"], "Markets")                              # default title

    def test_stocks_cleans_and_caps_symbols(self):
        f = model.normalize_feed({"type": "stocks",
                                  "symbols": ["a b!", "", 5, "BRK-B", "^GSPC"] + ["X%d" % i for i in range(20)]})
        self.assertEqual(f["symbols"][:4], ["AB", "BRK-B", "^GSPC", "X0"])    # junk stripped, non-str dropped
        self.assertLessEqual(len(f["symbols"]), 10)                          # capped at 10

    def test_stocks_no_usable_symbol_invalid(self):
        f = model.normalize_feed({"type": "stocks", "symbols": ["", "!!", 3]})
        self.assertFalse(f["valid"])
        self.assertIn("symbols", f["error"])
        self.assertEqual(f["title"], "Markets")                              # titled for the error tile

    def test_stocks_bad_range_defaults(self):
        self.assertEqual(model.normalize_feed(
            {"type": "stocks", "symbols": ["SPY"], "range": "10y"})["range"], "1mo")

    def test_stocks_interval_floor_120(self):
        self.assertEqual(model.normalize_feed(
            {"type": "stocks", "symbols": ["SPY"], "interval": 5})["interval"], 120)

    def test_stocks_default_tab_global_when_missing(self):
        self.assertEqual(model.normalize_feed(
            {"type": "stocks", "symbols": ["SPY"]})["tab"], "global")         # like any news feed
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model.TestNormalizeStocksAndTab -v`
Expected: FAIL (`stocks` currently `unknown type`; no `tab` key).

- [ ] **Step 3: Implement**

3a. Add `"stocks"` to `_VALID_TYPES` (`feedkit/model.py:204`):

```python
_VALID_TYPES = ("rss", "json", "text", "github", "notifications", "search", "stocks")
```

3b. In `normalize_feed`, right after the generic interval line (currently `out["interval"] = _coerce_int(raw.get("interval"), floor, floor, 86400)`), add the one place that stamps a tab on every news-type feed (valid or not):

```python
    if is_news_type(ftype):
        out["tab"] = coerce_tab(raw.get("tab"))
```

3c. Add the `stocks` branch. Place it immediately before the `# github` fallthrough comment (after the `search` branch's `return out`):

```python
    if ftype == "stocks":
        # default 300 / floor 120 (mirrors search/notifications), set explicitly.
        out["interval"] = _coerce_int(raw.get("interval"), 300, 120, 86400)
        raw_syms = raw.get("symbols")
        symbols = []
        if isinstance(raw_syms, list):
            for s in raw_syms:
                if not isinstance(s, str):
                    continue
                clean = re.sub(r"[^A-Z0-9.^-]", "", s.strip().upper())
                if clean:
                    symbols.append(clean)
                if len(symbols) >= 10:
                    break
        if not symbols:
            out.update(valid=False, error="stocks feed needs 'symbols'",
                       title=title or "Markets")
            return out
        out["symbols"] = symbols
        rng = raw.get("range")
        out["range"] = rng if rng in STOCK_RANGES else DEFAULT_STOCK_RANGE
        out["title"] = title or "Markets"
        return out
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: PASS (new + all pre-existing normalize tests).

- [ ] **Step 5: Commit**

```bash
git add feedkit/model.py tests/test_feed_model.py
git commit -m "feat(feedkit): normalize stocks feeds and tab field on news feeds" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: parse.py — parse_stock_chart

**Files:**
- Modify: `feedkit/parse.py` (add `import math` at top; add the function near `parse_search_items`)
- Test: `tests/test_feed_parse.py`

**Interfaces:**
- Consumes: `feedkit.model.Quote` (Task 1); `json`, `math`.
- Produces: `parse_stock_chart(body, symbol) -> model.Quote | None`. Never raises. Price = `meta.regularMarketPrice`, falling back to the last finite `close`; `change_pct = (price-prev)/prev*100` using `meta.chartPreviousClose` (then `meta.previousClose`), else `0.0`; `series` = finite `close` values only; returns `None` when there is no usable price.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_parse.py`:

```python
def _chart_body(price=746.77, prev=756.0, closes=(740.0, 745.0, 746.77), result=True):
    if not result:
        return json.dumps({"chart": {"result": None, "error": {"code": "Not Found"}}}).encode()
    return json.dumps({"chart": {"result": [{
        "meta": {"regularMarketPrice": price, "chartPreviousClose": prev},
        "indicators": {"quote": [{"close": list(closes)}]}}], "error": None}}).encode()


class TestParseStockChart(unittest.TestCase):
    def test_normal(self):
        q = parse.parse_stock_chart(_chart_body(), "SPY")
        self.assertEqual(q.symbol, "SPY")
        self.assertAlmostEqual(q.price, 746.77)
        self.assertAlmostEqual(q.change_pct, (746.77 - 756.0) / 756.0 * 100.0)
        self.assertEqual(q.series, [740.0, 745.0, 746.77])

    def test_null_closes_filtered(self):
        q = parse.parse_stock_chart(_chart_body(closes=(740.0, None, 746.77)), "SPY")
        self.assertEqual(q.series, [740.0, 746.77])

    def test_result_null_is_none(self):
        self.assertIsNone(parse.parse_stock_chart(_chart_body(result=False), "SPY"))

    def test_missing_price_uses_last_close(self):
        body = json.dumps({"chart": {"result": [{
            "meta": {"chartPreviousClose": 100.0},
            "indicators": {"quote": [{"close": [98.0, 101.0]}]}}]}}).encode()
        q = parse.parse_stock_chart(body, "X")
        self.assertAlmostEqual(q.price, 101.0)                 # fallback to last close
        self.assertAlmostEqual(q.change_pct, 1.0)             # (101-100)/100*100

    def test_missing_prevclose_is_zero_change(self):
        body = json.dumps({"chart": {"result": [{
            "meta": {"regularMarketPrice": 50.0},
            "indicators": {"quote": [{"close": [50.0]}]}}]}}).encode()
        self.assertEqual(parse.parse_stock_chart(body, "X").change_pct, 0.0)

    def test_zero_prevclose_is_zero_change(self):
        self.assertEqual(parse.parse_stock_chart(_chart_body(prev=0.0), "X").change_pct, 0.0)

    def test_garbage_never_raises(self):
        for bad in (b"not json{", b"", b"[]", b'{"chart":{}}', b'{"chart":{"result":[{}]}}'):
            self.assertIsNone(parse.parse_stock_chart(bad, "X"), bad)
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse.TestParseStockChart -v`
Expected: FAIL (no attribute `parse_stock_chart`).

- [ ] **Step 3: Implement**

Add `import math` to the imports at the top of `feedkit/parse.py`. Then add:

```python
def _finite_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_stock_chart(body, symbol):
    """Parse a Yahoo v8 chart response into a Quote, or None. NEVER raises
    (defensive over untrusted bytes). Price prefers meta.regularMarketPrice and
    falls back to the last finite close; change_pct is the day's move vs
    chartPreviousClose (then previousClose), 0.0 when that is missing/zero;
    series is the finite close list."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    try:
        chart = data.get("chart") if isinstance(data, dict) else None
        results = chart.get("result") if isinstance(chart, dict) else None
        if not results:
            return None
        result = results[0]
        if not isinstance(result, dict):
            return None
        meta = result.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        series = []
        indicators = result.get("indicators")
        if isinstance(indicators, dict):
            qlist = indicators.get("quote")
            if isinstance(qlist, list) and qlist and isinstance(qlist[0], dict):
                closes = qlist[0].get("close")
                if isinstance(closes, list):
                    series = [float(c) for c in closes if _finite_num(c)]
        price = meta.get("regularMarketPrice")
        if not _finite_num(price):
            price = series[-1] if series else None
        if not _finite_num(price):
            return None
        price = float(price)
        prev = meta.get("chartPreviousClose")
        if not _finite_num(prev):
            prev = meta.get("previousClose")
        if _finite_num(prev) and float(prev) != 0.0:
            change_pct = (price - float(prev)) / float(prev) * 100.0
        else:
            change_pct = 0.0
        return model.Quote(symbol, price, change_pct, series)
    except Exception:
        return None
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/parse.py tests/test_feed_parse.py
git commit -m "feat(feedkit): parse_stock_chart (Yahoo v8 -> Quote, never raises)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: manager.py — _process_stocks + dispatch

**Files:**
- Modify: `feedkit/manager.py:163-169` (`_fetch_and_process` dispatch) and add `_process_stocks`
- Test: `tests/test_feed_manager.py` (add `import json` at top)

**Interfaces:**
- Consumes: `model.yahoo_chart_url` (Task 1); `parse.parse_stock_chart` (Task 4); `self._fetch`, `self._cache`, `self._lock`, `FeedResult`.
- Produces: `_process_stocks(idx, feed) -> FeedResult`. No token. Per-symbol conditional GET under cache key `(idx, "stk", symbol)` storing `{etag, lm, quote}`. Tile state: `ok` if ≥1 symbol refreshed with no error this cycle; `stale` if any quotes survive but an error occurred; `error` if no quotes at all. `result.items` is a `list[Quote]`.

- [ ] **Step 1: Write the failing tests**

At the top of `tests/test_feed_manager.py`, add `import json`. Then add:

```python
class TestProcessStocks(unittest.TestCase):
    def _chart(self, price, prev, closes):
        return json.dumps({"chart": {"result": [{
            "meta": {"regularMarketPrice": price, "chartPreviousClose": prev},
            "indicators": {"quote": [{"close": list(closes)}]}}], "error": None}}).encode()

    FEED = {"type": "stocks", "symbols": ["SPY", "META"], "range": "1mo", "tab": "markets"}

    def test_all_ok_two_quotes(self):
        def fake(url, **kw):
            if "chart/SPY" in url:
                return _ok(self._chart(746.77, 756.0, [740.0, 745.0, 746.77]))
            return _ok(self._chart(563.29, 562.0, [560.0, 561.0, 563.29]))
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "ok")
        self.assertEqual([q.symbol for q in result.items], ["SPY", "META"])
        self.assertAlmostEqual(result.items[0].price, 746.77)

    def test_one_symbol_error_after_success_is_stale_retained(self):
        state = {"n": 0}
        def fake(url, **kw):
            if "chart/SPY" in url:
                return _ok(self._chart(746.77, 756.0, [740.0, 746.77]))
            state["n"] += 1
            return _ok(self._chart(563.29, 562.0, [560.0, 563.29])) if state["n"] == 1 else _err("offline")
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        m._last.clear()
        m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.error, "offline")
        self.assertEqual(len(result.items), 2)                # META retained from cache

    def test_not_modified_reuses_quote(self):
        responses = [_ok(self._chart(746.77, 756.0, [740.0, 746.77])), _nm()]
        m = manager.FeedManager([{"type": "stocks", "symbols": ["SPY"], "range": "1mo"}],
                                fetch_fn=lambda u, **k: responses.pop(0))
        m._run_once(0.0); m.drain()
        m._last.clear()
        m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "ok")
        self.assertAlmostEqual(result.items[0].price, 746.77)

    def test_all_fail_no_cache_is_error(self):
        m = manager.FeedManager([{"type": "stocks", "symbols": ["SPY"], "range": "1mo"}],
                                fetch_fn=lambda u, **k: _err("offline"))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")
        self.assertEqual(result.items, [])
        self.assertEqual(result.error, "offline")
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager.TestProcessStocks -v`
Expected: FAIL (stocks feed not dispatched; `_process_stocks` missing).

- [ ] **Step 3: Implement**

3a. In `_fetch_and_process` (`feedkit/manager.py:163`), add the stocks dispatch (no token) after the `search` branch:

```python
        if feed["type"] == "search":
            return self._process_search(idx, feed, token)
        if feed["type"] == "stocks":
            return self._process_stocks(idx, feed)
```

3b. Add the method (place it after `_process_search`):

```python
    def _process_stocks(self, idx, feed):
        """Per-symbol Yahoo chart fetch (no token). Conditional GET per symbol under
        cache key (idx,'stk',symbol) -> {etag, lm, quote}. not_modified reuses the
        cached Quote (fresh); error keeps the cached Quote if any (stale); a 200 is
        parsed, keeping the prior Quote on a None parse. Tile freshness is coarse:
        one flaky symbol dims/annotates the whole tile."""
        range_ = feed["range"]
        quotes = []
        any_error = None
        refreshed = False
        for symbol in feed["symbols"]:
            key = (idx, "stk", symbol)
            with self._lock:
                cache = self._cache.get(key, {})
            res = self._fetch(model.yahoo_chart_url(symbol, range_),
                              etag=cache.get("etag"), last_modified=cache.get("lm"))
            if res.status == "not_modified":
                q = cache.get("quote")
                if q is not None:
                    quotes.append(q)
                    refreshed = True
                continue
            if res.status == "error":
                any_error = res.error
                q = cache.get("quote")
                if q is not None:
                    quotes.append(q)
                continue
            q = parse.parse_stock_chart(res.body, symbol)
            if q is None:
                any_error = any_error or "bad data"
                prev = cache.get("quote")
                if prev is not None:
                    quotes.append(prev)
                continue
            quotes.append(q)
            refreshed = True
            with self._lock:
                self._cache[key] = {"etag": res.etag, "lm": res.last_modified, "quote": q}
        if refreshed and not any_error:
            state = "ok"
        elif quotes:
            state = "stale"
        else:
            state = "error"
        return FeedResult(state, quotes, None, any_error)
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/manager.py tests/test_feed_manager.py
git commit -m "feat(feedkit): _process_stocks per-symbol conditional fetch" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: manager.py — set_stock_range + refresh

**Files:**
- Modify: `feedkit/manager.py` (add two public methods, near `set_feeds`/`set_token`)
- Test: `tests/test_feed_manager.py`

**Interfaces:**
- Consumes: `model.STOCK_RANGES` (Task 1); `self.feeds`, `self._cache`, `self._last`, `self._lock`.
- Produces: `set_stock_range(idx, code)` — session-state range change (no-op unless `idx` is a valid `stocks` feed and `code` in `STOCK_RANGES`); replaces `self.feeds[idx]` with a copy carrying the new range and drops that feed's `(idx,"stk",*)` cache + `self._last[idx]`. `refresh(indices)` — drops `self._last` for the given indices so the worker re-issues a **conditional** GET next tick.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_manager.py`:

```python
class TestStockRangeAndRefresh(unittest.TestCase):
    def _chart(self, price=100.0, prev=99.0, closes=(98.0, 100.0)):
        return json.dumps({"chart": {"result": [{
            "meta": {"regularMarketPrice": price, "chartPreviousClose": prev},
            "indicators": {"quote": [{"close": list(closes)}]}}], "error": None}}).encode()

    def test_set_stock_range_updates_and_refetches(self):
        urls = []
        def fake(url, **kw):
            urls.append(url); return _ok(self._chart())
        feed = {"type": "stocks", "symbols": ["SPY"], "range": "1mo", "tab": "markets"}
        m = manager.FeedManager([feed], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        self.assertIn("range=1mo", urls[0])
        m.set_stock_range(0, "1d")
        self.assertEqual(m.feeds[0]["range"], "1d")
        self.assertNotIn(0, m._last)                          # last-fetch dropped -> due next tick
        self.assertFalse(any(isinstance(k, tuple) and len(k) == 3 and k[0] == 0 and k[1] == "stk"
                             for k in m._cache))              # stk cache cleared
        m._run_once(5.0)
        self.assertTrue(any("range=1d" in u for u in urls[1:]))   # refetched with new range

    def test_set_stock_range_ignores_unknown_code_and_nonstocks(self):
        feed = {"type": "stocks", "symbols": ["SPY"], "range": "1mo", "tab": "markets"}
        rss = {"type": "rss", "url": "https://x"}
        m = manager.FeedManager([feed, rss], fetch_fn=lambda u, **k: _ok(self._chart()))
        m.set_stock_range(0, "zzz")
        self.assertEqual(m.feeds[0]["range"], "1mo")          # unknown code -> unchanged
        m.set_stock_range(1, "1d")
        self.assertNotIn("range", m.feeds[1])                 # non-stocks idx -> unchanged
        m.set_stock_range(99, "1d")                           # out of range -> no crash

    def test_refresh_drops_last_for_given_indices_only(self):
        a = {"type": "rss", "url": "https://a"}
        b = {"type": "rss", "url": "https://b"}
        m = manager.FeedManager([a, b], fetch_fn=lambda u, **k: _ok(RSS))
        m._run_once(0.0); m.drain()
        self.assertIn(0, m._last); self.assertIn(1, m._last)
        m.refresh([0])
        self.assertNotIn(0, m._last)
        self.assertIn(1, m._last)
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager.TestStockRangeAndRefresh -v`
Expected: FAIL (no `set_stock_range`/`refresh`).

- [ ] **Step 3: Implement**

Add to `FeedManager` (after `set_token`):

```python
    def set_stock_range(self, idx, code):
        """UI-thread session-state range change for a stocks feed. No-op unless idx
        is a valid stocks feed and code is a known range. Replaces the feed with a
        copy carrying the new range and drops its (idx,'stk',*) cache + last-fetch
        so the worker refetches the new range next tick."""
        with self._lock:
            if not (0 <= idx < len(self.feeds)):
                return
            feed = self.feeds[idx]
            if not feed.get("valid") or feed.get("type") != "stocks" or code not in model.STOCK_RANGES:
                return
            new = dict(feed)
            new["range"] = code
            self.feeds[idx] = new
            for k in [k for k in self._cache
                      if isinstance(k, tuple) and len(k) == 3 and k[0] == idx and k[1] == "stk"]:
                self._cache.pop(k, None)
            self._last.pop(idx, None)

    def refresh(self, indices):
        """Force a conditional re-fetch of the given feed indices on the next tick
        by dropping their last-fetch time (validators kept -> a 304 reuses cache)."""
        with self._lock:
            for idx in indices:
                self._last.pop(idx, None)
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/manager.py tests/test_feed_manager.py
git commit -m "feat(feedkit): set_stock_range and refresh control methods" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: hud.pyw — _stock_points + partition helpers

**Files:**
- Modify: `hud.pyw` (add module-level `_stock_points`; add `_news_indices`/`_github_indices` methods to `Hud`)
- Test: `tests/test_smoke_hud.py`

**Interfaces:**
- Consumes: `feedmodel.is_news_type`/`is_pinned_type` (Task 2); `self.manager.feeds`.
- Produces: module-level pure `_stock_points(series, x_left, x_right, top, bottom) -> list[float]` (flat `[x0,y0,x1,y1,...]`; `[]` for <2 points; min→bottom, max→top; flat series → midline). `Hud._news_indices()`/`Hud._github_indices()` → lists of feed indices in config order.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smoke_hud.py`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestStockPoints(unittest.TestCase):
    def test_empty_and_single_return_empty(self):
        import hud as hudmod
        self.assertEqual(hudmod._stock_points([], 0, 30, 0, 20), [])
        self.assertEqual(hudmod._stock_points([5.0], 0, 30, 0, 20), [])

    def test_flat_series_is_midline(self):
        import hud as hudmod
        pts = hudmod._stock_points([5.0, 5.0, 5.0], 0, 20, 0, 20)
        self.assertTrue(all(abs(y - 10.0) < 1e-9 for y in pts[1::2]))

    def test_monotonic_scales_min_bottom_max_top(self):
        import hud as hudmod
        pts = hudmod._stock_points([1.0, 2.0, 3.0, 4.0], 0, 30, 0, 20)
        self.assertEqual(pts[0], 0)      # x_left
        self.assertEqual(pts[1], 20)     # min -> bottom
        self.assertEqual(pts[-2], 30)    # x_right
        self.assertEqual(pts[-1], 0)     # max -> top


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudPartition(_HudTestBase):
    def test_news_and_github_indices(self):
        feeds = [
            {"type": "rss", "url": "https://a", "title": "A", "tab": "tech"},
            {"type": "github", "repo": "o/r", "title": "R"},
            {"type": "stocks", "symbols": ["SPY"], "range": "1mo", "tab": "markets"},
            {"type": "notifications", "title": "N"},
        ]
        root, hud = self._make_hud(feeds)
        try:
            self.assertEqual(hud._news_indices(), [0, 2])
            self.assertEqual(hud._github_indices(), [1, 3])
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestStockPoints tests.test_smoke_hud.TestHudPartition -v`
Expected: FAIL (no `_stock_points`/`_news_indices`).

- [ ] **Step 3: Implement**

3a. Add the module-level helper to `hud.pyw` (near `_fit`/`_repo_short`):

```python
def _stock_points(series, x_left, x_right, top, bottom):
    """Polyline coords for a price series scaled by its own min->max (min at the
    bottom edge, max at the top edge), spread evenly across [x_left, x_right].
    Returns [] for <2 points; a flat series draws a horizontal midline. Unlike
    _update_spark this is min/max-scaled because prices are not 0..100."""
    n = len(series)
    if n < 2:
        return []
    lo, hi = min(series), max(series)
    span = hi - lo
    mid = (top + bottom) / 2.0
    dx = (x_right - x_left) / (n - 1)
    pts = []
    for i, v in enumerate(series):
        x = x_left + i * dx
        y = mid if span <= 0 else bottom - (v - lo) / span * (bottom - top)
        pts.extend((x, y))
    return pts
```

3b. Add the partition methods to `Hud` (near `_github_token`):

```python
    def _news_indices(self):
        """Indices of news-family feeds (rss/json/text/stocks), config order."""
        return [i for i, f in enumerate(self.manager.feeds)
                if feedmodel.is_news_type(f.get("type"))]

    def _github_indices(self):
        """Indices of pinned GitHub-family feeds (github/notifications/search)."""
        return [i for i, f in enumerate(self.manager.feeds)
                if feedmodel.is_pinned_type(f.get("type"))]
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestStockPoints tests.test_smoke_hud.TestHudPartition -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): pure _stock_points helper and news/github index partition" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: hud.pyw — tabbed layout + interactions

This is the core restructure: a tab bar switches the visible news tab, the GitHub section is always pinned below, and two ⟳ controls refresh news vs GitHub. The old single header ⟳ is removed. Stocks-tile drawing is **not** in this task (Task 9).

**Files:**
- Modify: `hud.pyw` — `__init__` (add `active_tab`, remove `_reload_item`/`_reload_box`), remove `_in_reload`, restructure `_on_release`, replace `_feed_tiles`→`_tile_for`, restructure `_draw_feeds`, add `_draw_tab_bar`/`_draw_github_header`/`_draw_tile`, add `_dispatch_action`/`_set_active_tab`/`_refresh_news`/`_refresh_github`/`_set_stock_range`. **Preserve** the GPU/media persistent header items and the `_media_at`→`_do_media` click branch (see Integration Note).
- Test: `tests/test_smoke_hud.py` (remove `test_reload_control_click_reloads`; add tab/refresh tests)

**Interfaces:**
- Consumes: `feedmodel.NEWS_TABS`, `coerce_default_tab`, `coerce_tab` (Task 2); `_news_indices`/`_github_indices` (Task 7); `manager.refresh` (Task 6); `manager.set_stock_range` (Task 6, used by `_set_stock_range`); existing `_register_hit`/`_register_action`/`_action_at`/`_do_dismiss`.
- Produces: `self.active_tab` (session state). `_tile_for(idx, feed)` returns a 5-tuple `(title, title_url, color, lines, header_action)` for existing types (stocks 2-tuple added in Task 9). Click actions: `("tab", key)`, `("refresh", "news"|"github")`, plus the existing `("one"|"all", ...)` dismiss tuples; `("range", idx, code)` is handled here but produced in Task 9.

- [ ] **Step 1: Write the failing tests**

In `tests/test_smoke_hud.py`, **delete** `test_reload_control_click_reloads` (it references `hud._reload_box`, removed in this task). Then add:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudTabs(_HudTestBase):
    def _feeds(self):
        return [
            {"type": "rss", "url": "https://t", "title": "TechFeed", "tab": "tech"},
            {"type": "rss", "url": "https://g", "title": "GlobalFeed", "tab": "global"},
            {"type": "github", "repo": "o/r", "title": "Repo"},
        ]

    def _click(self, hud, pred):
        for (y0, y1, x0, x1, a) in hud._action_hits:
            if pred(a):
                ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
                hud._moved = False
                hud._on_release(ev)
                return a
        return None

    def test_four_tab_labels_render(self):
        root, hud = self._make_hud([])
        try:
            hud._draw_feeds(); root.update_idletasks()
            for label in ("Global", "Markets", "Tech", "Sports"):
                self.assertTrue(hud._feed_has_text(label), label)
        finally:
            hud.close(); root.destroy()

    def test_only_active_tab_feeds_drawn_github_always(self):
        import feedkit.manager as manager
        from feedkit.model import Item, Status
        root, hud = self._make_hud(self._feeds())
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [Item("techline", "https://x/t")], None, None)
            hud.feed_state[1] = manager.FeedResult("ok", [Item("globalline", "https://x/g")], None, None)
            hud.feed_state[2] = manager.FeedResult("ok", [], Status("Repo passing", "success",
                                                                    "https://github.com/o/r/actions"), None)
            hud.active_tab = "tech"
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("TechFeed"))
            self.assertFalse(hud._feed_has_text("GlobalFeed"))   # other tab hidden
            self.assertTrue(hud._feed_has_text("Repo"))          # github always
        finally:
            hud.close(); root.destroy()

    def test_default_tab_selects_initial_tab(self):
        import tkinter as tk
        import config, hud as hudmod
        root = tk.Tk(); root.overrideredirect(True)
        cfg = config.defaults(); cfg["feeds"] = []
        cfg["hud"]["default_tab"] = "markets"
        root.geometry("%dx%d+100+100" % (hudmod.WIDTH, hudmod.HEIGHT))
        hud = hudmod.Hud(root, cfg)
        try:
            self.assertEqual(hud.active_tab, "markets")
        finally:
            hud.close(); root.destroy()

    def test_tab_click_changes_active_tab_no_refetch(self):
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            calls = []
            hud.manager.refresh = lambda idxs: calls.append(list(idxs))
            hud._draw_feeds(); root.update_idletasks()
            self._click(hud, lambda a: a == ("tab", "global"))
            self.assertEqual(hud.active_tab, "global")
            self.assertEqual(calls, [])                          # switching does not refetch
            self.assertTrue(hud._feed_has_text("GlobalFeed"))
        finally:
            hud.close(); root.destroy()

    def test_news_refresh_calls_manager_refresh_with_news_indices(self):
        root, hud = self._make_hud(self._feeds())
        try:
            calls = []
            hud.manager.refresh = lambda idxs: calls.append(list(idxs))
            hud._draw_feeds(); root.update_idletasks()
            self._click(hud, lambda a: a == ("refresh", "news"))
            self.assertEqual(calls, [[0, 1]])                    # the two rss feeds
        finally:
            hud.close(); root.destroy()

    def test_github_refresh_rereads_token_and_refreshes_github(self):
        import config
        root, hud = self._make_hud(self._feeds(), isolate_cfg=True)
        try:
            seed = config.defaults(); seed["hud"]["github_token"] = "ghp_new"
            config.save(hud.CFG_PATH, seed)
            os.environ.pop("TOYBOX_GITHUB_TOKEN", None)          # ensure cfg wins
            tok, ref = [], []
            hud.manager.set_token = lambda t: tok.append(t)
            hud.manager.refresh = lambda idxs: ref.append(list(idxs))
            hud._draw_feeds(); root.update_idletasks()
            self._click(hud, lambda a: a == ("refresh", "github"))
            self.assertEqual(tok, ["ghp_new"])                  # token re-read from config
            self.assertEqual(ref, [[2]])                        # the github feed index
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudTabs -v`
Expected: FAIL (no `active_tab`/tab bar/refresh dispatch).

- [ ] **Step 3: Implement**

3a. In `__init__`, add near the other state init (e.g. after `self.feed_state = {}`):

```python
        self.active_tab = feedmodel.coerce_default_tab(cfg["hud"].get("default_tab"))
```

3b. In `__init__`, **remove** the two lines that create the old reload control:

```python
        self._reload_item = c.create_text(WIDTH - PAD, y3, anchor="e",
                                          text=RELOAD_GLYPH, fill=DIM, font=CLOCK_FONT)
        self._reload_box = (WIDTH - PAD - ACTION_ZONE_W, y3 - 10, WIDTH, y3 + 10)
```

3c. **Remove** the `_in_reload` method entirely.

3d. Replace `_on_release` so it dispatches through `_action_at`. Drop **only** the `_in_reload` branch; **keep** the `_media_at`→`_do_media` branch (persistent media controls, added on main) and the drag-save path unchanged:

```python
    def _on_release(self, event):
        if not self._moved:
            key = self._media_at(event.x, event.y)        # persistent media glyph zones (unchanged)
            if key is not None:
                self._do_media(key)
                return
            action = self._action_at(event.x, event.y)   # tab/refresh/range/dismiss zones
            if action is not None:
                self._dispatch_action(action)
                return
            url = self._open_at(event.x, event.y)
            if url:
                try:
                    webbrowser.open(url, new=2)
                except Exception:
                    pass
            return  # a plain click (no drag) must not rewrite config.json
        self._moved = False
        self.cfg["hud"]["x"] = self.root.winfo_x()
        self.cfg["hud"]["y"] = self.root.winfo_y()
        self._save()

    def _dispatch_action(self, action):
        kind = action[0]
        if kind == "tab":
            self._set_active_tab(action[1])
        elif kind == "refresh":
            (self._refresh_news if action[1] == "news" else self._refresh_github)()
        elif kind == "range":
            self._set_stock_range(action[1], action[2])
        else:
            self._do_dismiss(action)
```

3e. Rename `_feed_tiles` (the generator) to `_tile_for(self, idx, feed)` that **returns** one tile tuple for the given feed. This is a mechanical conversion of the existing per-feed body: each `yield (...)` + `continue` becomes `return (...)`, and it takes `idx`/`feed` directly instead of looping. Concretely:

```python
    def _tile_for(self, idx, feed):
        """Return one tile tuple for a feed: a 5-tuple (title, title_url, color,
        lines, header_action). (Task 9 adds a ('stocks', payload) 2-tuple.)"""
        title = feed.get("title") or "feed"
        if not feed.get("valid"):
            return (title, None, FEED_DIM, [("! " + (feed.get("error") or "invalid"), None, True)], None)
        result = self.feed_state.get(idx)
        if result is None:
            return (title, None, FEED_FG, [("loading…", None, True)], None)
        if feed["type"] == "notifications":
            # ... body identical to the current notifications branch, but each
            #     `yield X; continue` becomes `return X`.
            ...
            return (header, "https://github.com/notifications", FEED_FG, lines, header_action)
        if feed["type"] == "search":
            ...
            return (header, web, FEED_FG, lines, None)
        if result.status is not None:                 # github tile
            color = STATE_HEX.get(result.status.state, FEED_DIM)
            lines = [("! " + result.error, None, True)] if result.error else []
            return (result.status.text, result.status.url, color, lines, None)
        dim = result.state in ("stale", "error")
        lines = [(it.text, it.url, dim) for it in result.items]
        if result.error:
            lines = [("! " + result.error, None, True)] + lines
        if not lines:
            lines = [("(empty)", None, True)]
        return (title, None, FEED_FG, lines, None)
```

(Copy the notifications/search branch bodies verbatim from the current `_feed_tiles`, changing only `yield…; continue` → `return…`.)

3f. Add `_draw_tile(self, idx, feed, y) -> new_y` — the current per-tile drawing loop body, extracted, consuming `_tile_for`:

```python
    def _draw_tile(self, idx, feed, y):
        tile = self._tile_for(idx, feed)
        # (Task 9 inserts: if len(tile) == 2: return self._draw_stock_tile(idx, tile[1], y))
        title, title_url, color, lines, header_action = tile
        c = self.canvas
        y += FEED_TITLE_GAP
        tid = c.create_text(PAD, y, anchor="w", text=_fit(title), fill=color, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        self._register_hit(y, title_url)
        if header_action is not None:
            mk = c.create_text(WIDTH - PAD, y, anchor="e", text=MARKALL_GLYPH,
                               fill=FEED_DIM, font=FEED_TITLE_FONT)
            self._feed_items.append(mk)
            self._register_action(y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, header_action)
        y += FEED_LINE_H
        for row in lines:
            if len(row) == 3:
                text, url, dim = row
                lid = c.create_text(PAD + 6, y, anchor="w", text=_fit(text),
                                    fill=(FEED_DIM if dim else FEED_FG), font=FEED_FONT)
                self._feed_items.append(lid)
                self._register_hit(y, url)
                y += FEED_LINE_H
            else:
                line1, url, color, subtitle, age, dismiss = row
                reserve = ACTION_ZONE_W if dismiss else 0
                l1 = c.create_text(PAD + 6, y, anchor="w",
                                   text=self._fit_line1(line1, age, reserve),
                                   fill=color, font=FEED_FONT)
                self._feed_items.append(l1)
                if age:
                    aid = c.create_text(WIDTH - PAD - reserve, y, anchor="e", text=age,
                                        fill=FEED_DIM, font=FEED_FONT)
                    self._feed_items.append(aid)
                if dismiss is not None:
                    xg = c.create_text(WIDTH - PAD, y, anchor="e", text=DISMISS_GLYPH,
                                       fill=FEED_DIM, font=FEED_FONT)
                    self._feed_items.append(xg)
                    self._register_action(y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, dismiss)
                self._register_hit(y, url)
                y += FEED_LINE_H
                l2 = c.create_text(PAD + 12, y, anchor="w", text=_fit(subtitle),
                                   fill=FEED_DIM, font=FEED_FONT)
                self._feed_items.append(l2)
                self._register_hit(y, url)
                y += FEED_LINE_H
        return y
```

3g. Replace `_draw_feeds` with the tabbed structure:

```python
    def _draw_feeds(self):
        c = self.canvas
        for item_id in self._feed_items:
            c.delete(item_id)
        self._feed_items = []
        self._hit = []
        self._action_hits = []
        y = PAD + 5 * ROW_H + 4                   # below the 5-row header (CPU/RAM/GPU/clock/media)
        y = self._draw_tab_bar(y)
        news = [i for i in self._news_indices()
                if self.manager.feeds[i].get("tab") == self.active_tab]
        for idx in news:
            y = self._draw_tile(idx, self.manager.feeds[idx], y)
        if not news:
            pid = c.create_text(PAD + 6, y + FEED_TITLE_GAP + FEED_LINE_H // 2, anchor="w",
                                text="no feeds", fill=FEED_DIM, font=FEED_FONT)
            self._feed_items.append(pid)
            y += FEED_TITLE_GAP + FEED_LINE_H
        y = self._draw_github_header(y)
        for idx in self._github_indices():
            y = self._draw_tile(idx, self.manager.feeds[idx], y)
        self._resize(y + PAD)

    def _draw_tab_bar(self, y):
        c = self.canvas
        row_y = y + FEED_LINE_H // 2
        x = PAD
        for key, label in feedmodel.NEWS_TABS:
            active = (key == self.active_tab)
            tid = c.create_text(x, row_y, anchor="w", text=label,
                                fill=(FEED_FG if active else FEED_DIM),
                                font=(FEED_TITLE_FONT if active else FEED_FONT))
            self._feed_items.append(tid)
            w = self._feed_font_measure.measure(label)
            self._register_action(row_y, x, x + w, ("tab", key))
            x += w + 6
        rid = c.create_text(WIDTH - PAD, row_y, anchor="e", text=RELOAD_GLYPH,
                            fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(rid)
        self._register_action(row_y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, ("refresh", "news"))
        return y + FEED_LINE_H + FEED_TITLE_GAP

    def _draw_github_header(self, y):
        c = self.canvas
        row_y = y + FEED_LINE_H // 2
        tid = c.create_text(PAD, row_y, anchor="w", text="GitHub", fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        rid = c.create_text(WIDTH - PAD, row_y, anchor="e", text=RELOAD_GLYPH,
                            fill=FEED_DIM, font=FEED_TITLE_FONT)
        self._feed_items.append(rid)
        self._register_action(row_y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, ("refresh", "github"))
        return y + FEED_LINE_H + FEED_TITLE_GAP
```

3h. Add the interaction handlers (near `_reload_feeds`):

```python
    def _set_active_tab(self, key):
        self.active_tab = feedmodel.coerce_tab(key)
        self._draw_feeds()

    def _refresh_news(self):
        idxs = self._news_indices()
        for i in idxs:
            self.feed_state.pop(i, None)
        self.manager.refresh(idxs)
        self._draw_feeds()

    def _refresh_github(self):
        reloaded = config.load(self.CFG_PATH)
        self.cfg["hud"]["github_token"] = reloaded["hud"].get("github_token", "")
        self.manager.set_token(self._github_token())
        idxs = self._github_indices()
        for i in idxs:
            self.feed_state.pop(i, None)
        self.manager.refresh(idxs)
        self._draw_feeds()

    def _set_stock_range(self, idx, code):
        self.manager.set_stock_range(idx, code)
        self.feed_state.pop(idx, None)
        self._draw_feeds()
```

> `_set_stock_range` is defined here so `_dispatch_action` never references a missing method; the range **zones** that trigger it are produced in Task 9.

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS (new tab tests + all pre-existing HUD tests, including the subprocess smoke launch).

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): tabbed news layout, pinned GitHub, dual refresh controls" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: hud.pyw — stocks tile + range toggle

**Files:**
- Modify: `hud.pyw` — add stock color/height constants; `_tile_for` stocks branch; `_draw_tile` 2-tuple dispatch; `_draw_stock_tile`; `_draw_range_toggle`
- Test: `tests/test_smoke_hud.py`

**Interfaces:**
- Consumes: `feedmodel.format_quote_line`, `yahoo_quote_web_url`, `STOCK_RANGE_ORDER`, `STOCK_RANGE_LABELS` (Task 1); `_stock_points` (Task 7); `_set_stock_range`/`_dispatch_action` (Task 8); `_register_hit`/`_register_action`.
- Produces: `_tile_for` returns `("stocks", payload)` (a `dict` with `title`, `range`, `quotes` list[Quote], `state`, `error`) for `stocks` feeds; `_draw_tile` dispatches on `len(tile) == 2`; `_draw_stock_tile(idx, payload, y) -> new_y` renders quote lines (up/down colored) + drawn charts + a right-aligned `1D 1W 1M 3M` toggle whose segments register `("range", idx, code)` actions.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smoke_hud.py`:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudStocks(_HudTestBase):
    FEED = {"type": "stocks", "title": "Markets", "symbols": ["SPY", "META"],
            "range": "1mo", "tab": "markets"}

    def _q(self, symbol="SPY", price=746.77, change=-1.3, series=(740.0, 745.0, 746.77)):
        from feedkit.model import Quote
        return Quote(symbol, price, change, list(series))

    def test_tile_renders_quote_chart_and_toggle(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult("ok", [self._q()], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("SPY"))                       # quote line
            self.assertTrue(hud._feed_has_text("1M"))                        # toggle labels
            self.assertTrue(hud._feed_has_text("3M"))
            self.assertTrue(any(hud.canvas.type(i) == "line" for i in hud._feed_items))  # chart polyline
            self.assertTrue(any(u == "https://finance.yahoo.com/quote/SPY" for (_, _, u) in hud._hit))
        finally:
            hud.close(); root.destroy()

    def test_up_and_down_colors(self):
        import feedkit.manager as manager, hud as hudmod
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._q(symbol="DN", change=-1.3), self._q(symbol="UP", change=0.5)], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(_fill_of(hud, "DN"), hudmod.STOCK_DOWN)
            self.assertEqual(_fill_of(hud, "UP"), hudmod.STOCK_UP)
        finally:
            hud.close(); root.destroy()

    def test_range_toggle_click_calls_set_stock_range(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            calls = []
            hud.manager.set_stock_range = lambda idx, code: calls.append((idx, code))
            hud.feed_state[0] = manager.FeedResult("ok", [self._q()], None, None)
            hud._draw_feeds(); root.update_idletasks()
            hit = None
            for (y0, y1, x0, x1, a) in hud._action_hits:
                if a == ("range", 0, "1d"):
                    hit = (y0, y1, x0, x1); break
            self.assertIsNotNone(hit, "no 1D range zone")
            y0, y1, x0, x1 = hit
            ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
            hud._moved = False; hud._on_release(ev)
            self.assertEqual(calls, [(0, "1d")])
        finally:
            hud.close(); root.destroy()

    def test_loading_placeholder_when_no_quotes(self):
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud._draw_feeds(); root.update_idletasks()          # feed_state[0] is None
            self.assertTrue(hud._feed_has_text("loading"))
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudStocks -v`
Expected: FAIL (stocks tile not drawn; `STOCK_DOWN` missing).

- [ ] **Step 3: Implement**

3a. Add constants near `STATE_HEX` in `hud.pyw`:

```python
STOCK_UP = "#3fb950"       # green: day change >= 0
STOCK_DOWN = "#f85149"     # red: day change < 0
STOCK_CHART_H = 20         # px per drawn price-chart row
```

3b. In `_draw_tile`, insert the 2-tuple dispatch right after `tile = self._tile_for(idx, feed)`:

```python
        tile = self._tile_for(idx, feed)
        if len(tile) == 2:                       # ("stocks", payload)
            return self._draw_stock_tile(idx, tile[1], y)
        title, title_url, color, lines, header_action = tile
```

3c. In `_tile_for`, add the stocks branch (after the `result is None` guard, before the `notifications` branch):

```python
        if feed["type"] == "stocks":
            payload = {"title": feed.get("title") or "Markets", "range": feed["range"],
                       "quotes": list(result.items), "state": result.state,
                       "error": result.error}
            return ("stocks", payload)
```

> The `result is None` guard already returns a `loading…` 5-tuple before this branch — but a stocks feed with no result should show its toggle too. So instead of relying on that guard, handle the None case inside the stocks branch by moving the stocks check **above** the `result is None` guard:

```python
        if feed.get("valid") and feed["type"] == "stocks":
            result = self.feed_state.get(idx)
            payload = {"title": feed.get("title") or "Markets", "range": feed["range"],
                       "quotes": list(result.items) if result else [],
                       "state": result.state if result else "loading",
                       "error": result.error if result else None}
            return ("stocks", payload)
```

Place this block immediately after the `if not feed.get("valid"): return …` early-return (so invalid stocks feeds still render the error tile, and valid ones always render the toggle even before the first fetch).

3d. Add the drawing methods:

```python
    def _draw_stock_tile(self, idx, payload, y):
        c = self.canvas
        y += FEED_TITLE_GAP
        row_y = y + FEED_LINE_H // 2
        tid = c.create_text(PAD, row_y, anchor="w", text=_fit(payload["title"]),
                            fill=FEED_FG, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        self._draw_range_toggle(idx, payload["range"], row_y)
        y += FEED_LINE_H
        quotes = payload["quotes"]
        if not quotes:
            msg = ("! " + payload["error"]) if (payload["state"] != "loading" and payload["error"]) else "loading…"
            lid = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                                text=_fit(msg), fill=FEED_DIM, font=FEED_FONT)
            self._feed_items.append(lid)
            return y + FEED_LINE_H
        stale = payload["state"] in ("stale", "error")
        for q in quotes:
            color = FEED_DIM if stale else (STOCK_UP if q.change_pct >= 0 else STOCK_DOWN)
            url = feedmodel.yahoo_quote_web_url(q.symbol)
            lid = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                                text=_fit(feedmodel.format_quote_line(q)),
                                fill=color, font=FEED_FONT)
            self._feed_items.append(lid)
            self._register_hit(y + FEED_LINE_H // 2, url)
            y += FEED_LINE_H
            pts = _stock_points(q.series, PAD + 6, WIDTH - PAD, y + 2, y + STOCK_CHART_H - 2)
            if pts:
                ln = c.create_line(*pts, fill=color, width=1)
                self._feed_items.append(ln)
            self._register_hit(y + STOCK_CHART_H // 2, url)
            y += STOCK_CHART_H
        return y

    def _draw_range_toggle(self, idx, current, row_y):
        c = self.canvas
        x = WIDTH - PAD
        for code in reversed(feedmodel.STOCK_RANGE_ORDER):        # draw right->left; 3M rightmost
            label = feedmodel.STOCK_RANGE_LABELS[code]
            active = (code == current)
            tid = c.create_text(x, row_y, anchor="e", text=label,
                                fill=(FEED_FG if active else FEED_DIM), font=FEED_FONT)
            self._feed_items.append(tid)
            w = self._feed_font_measure.measure(label)
            self._register_action(row_y, x - w, x, ("range", idx, code))
            x -= w + 6
```

- [ ] **Step 4: Run to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run the whole suite first:
`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -v`
Expected: PASS (all modules).

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): stocks tile with mini chart and 1D/1W/1M/3M toggle" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: config.json data migration (manual, no test cycle)

This is a one-time **data** edit of the gitignored `config.json` (not runtime code, not committed). The code already defaults gracefully (missing `tab` → global, missing `default_tab` → tech), so this only *places* feeds correctly and adds the ticker.

**Guardrails:**
- **Never print `config.json` contents** — it holds the live GitHub PAT. Do not echo, log, or paste it.
- The migration must **preserve every existing key** (including `hud.github_token`); it only adds `tab` fields, appends the stocks feed, and sets `hud.default_tab`. It is idempotent.
- Because a running toy could overwrite the file, **stop the HUD (and any other running toy) before migrating**, then relaunch after.

**Steps:**

- [ ] **Step 1: Confirm the toys are stopped** (ask the user to close the HUD/clipboard/pet, or confirm they are not running). Do not proceed while the HUD is running.

- [ ] **Step 2: Run the idempotent migration** via Bash with real Python (it reads/writes `config.json` in place, prints only a redacted summary — never the token):

```bash
"C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe" - "C:/Users/Warren/Toybox/config.json" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    cfg = json.load(f)

TAB_BY_TITLE = {
    "Guardian World": "global",
    "MarketWatch": "markets", "CNBC Markets": "markets",
    "Hacker News": "tech", "GH Trending": "tech", "Ars AI": "tech",
    "r/reddevils": "sports",
}
feeds = cfg.get("feeds", [])
news = {"rss", "json", "text", "stocks"}
for fd in feeds:
    if isinstance(fd, dict) and fd.get("type") in news and "tab" not in fd:
        fd["tab"] = TAB_BY_TITLE.get(fd.get("title"), "global")

if not any(isinstance(fd, dict) and fd.get("type") == "stocks" for fd in feeds):
    feeds.append({"type": "stocks", "title": "Markets",
                  "symbols": ["SPY", "META", "GOOGL", "AMZN", "NFLX"],
                  "range": "1mo", "tab": "markets"})
cfg["feeds"] = feeds
cfg.setdefault("hud", {}).setdefault("default_tab", "tech")

with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)

# redacted summary only — NEVER print the token
print("feeds:", [(fd.get("title"), fd.get("type"), fd.get("tab")) for fd in feeds if isinstance(fd, dict)])
print("default_tab:", cfg["hud"].get("default_tab"))
print("has_token:", bool(cfg["hud"].get("github_token")))
PY
```

Expected: a `feeds:` line showing each feed's `(title, type, tab)`, a stocks "Markets" entry present, `default_tab: tech`, and `has_token: True` (confirming the token survived — without revealing it). Titles in the user's config that differ from `TAB_BY_TITLE` fall back to `global`; if the printed tabs look wrong, adjust the mapping to the actual titles and re-run (it is idempotent).

- [ ] **Step 3: Verify the HUD launches and renders** the tabbed layout + Markets ticker:

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestSmokeHud -v`
Expected: PASS (clean launch/exit). Then have the user relaunch the HUD normally and confirm the tab bar, tab switching, the GitHub pinned section, and the Markets ticker with its `1D 1W 1M 3M` toggle all render.

- [ ] **Step 4: No commit.** `config.json` is gitignored — nothing to commit for this task.

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:
- Tabbed layout / four fixed tabs / only-active rendered → Tasks 2, 8.
- Pinned GitHub section + two refreshes (news all-tabs; github re-reads token) → Task 8.
- `hud.default_tab` (session reset to tech) → Tasks 2, 8.
- Stocks feed config + `normalize_feed` (symbols clean/cap, range coercion, interval, title, tab) → Task 3.
- Yahoo URL / quote URL / `format_quote_line` / `Quote` → Task 1.
- `parse_stock_chart` (all edge cases, never raises) → Task 4.
- `_process_stocks` (per-symbol conditional GET, stale-on-error, coarse state) → Task 5.
- `set_stock_range` / `refresh` → Task 6.
- `_stock_points`, partition helpers, tab bar, github header, stock tile + toggle, click dispatch, refresh handlers → Tasks 7, 8, 9.
- Error handling (loading/`! error`/stale dim) → Tasks 5, 9.
- Config migration → Task 10.
- "No config writes" constraint → honored (only session state; migration is manual data).

**2. Placeholder scan** — the only intentional "copy the existing body" is Task 8 step 3e (converting `_feed_tiles`' notifications/search branches to `return`); their exact source is in the current `hud.pyw:326-375` and must be transcribed verbatim, not summarized. Every new function is shown in full.

**3. Type consistency** — `Quote(symbol, price, change_pct, series)` used identically in Tasks 1/4/5/9; `("tab", key)`/`("refresh", "news"|"github")`/`("range", idx, code)` action tuples produced (Tasks 8/9) and consumed (`_dispatch_action`, Task 8) consistently; `_tile_for` 5-tuple vs stocks 2-tuple distinguished by `len(tile) == 2` in `_draw_tile`; cache key `(idx, "stk", symbol)` written in `_process_stocks` (Task 5) and cleared in `set_stock_range` (Task 6) with the same shape.

**Ordering note (pre-flight):** Tasks are strictly ordered — model (1→2→3) → parse (4) → manager (5→6) → HUD (7→8→9) → data (10). Task 9's stocks-tile rendering **must** land before Task 10 adds a stocks feed to `config.json`, or a stocks `FeedResult` would reach `_draw_tile`'s generic path and fail on `Quote.text`. No task contradicts another or the Global Constraints.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-30-hud-tabbed-feeds-and-stocks.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, spec+quality review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints.

Which approach?
