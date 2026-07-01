# HUD Tabbed Feeds + Stock Ticker — Design

**Status:** approved design, ready for implementation plan
**Date:** 2026-06-30
**Branch:** `hud-stock-ticker` (off `main`)

## Overview

Two changes to the HUD feeds area, built together:

1. **Tabbed news layout.** The non-GitHub feeds are grouped into four tabs —
   **Global**, **Markets**, **Tech**, **Sports** — and only the active tab's
   feeds render at a time. A tab bar under the metrics header switches tabs. The
   GitHub-family feeds (Notifications / PR-search / repo tiles) are **not**
   tabbed: they stay pinned in a section that is always visible, below the active
   tab. Two independent refresh controls — one for news, one for GitHub.

2. **Stock ticker (`stocks` feed).** A new feed type that shows per-symbol price
   + day's % change + a drawn mini price chart, with a `1D 1W 1M 3M` window
   toggle. It lives inside the **Markets** tab. Its data comes from Yahoo's v8
   chart endpoint (no key, pure stdlib).

Everything reuses the existing feedkit architecture (pure model/parse, the
daemon-worker `FeedManager`, canvas drawing). Pure Python 3.12 stdlib, no pip.

## Information architecture

| Section | Feeds (current) | Behavior |
|---|---|---|
| **Global** tab | Guardian World | shown when active |
| **Markets** tab | MarketWatch, CNBC Markets, **Markets tickers** | shown when active |
| **Tech** tab | Hacker News, GH Trending, Ars AI | shown when active (**default**) |
| **Sports** tab | r/reddevils | shown when active |
| **GitHub** (pinned) | Notifications, My PRs, Review requests, Assigned | **always** visible, below the active tab |

- **News feeds** = feed types `rss` / `json` / `text` / `stocks`. Each carries a
  `tab` field placing it in one of the four tabs.
- **Pinned feeds** = feed types `github` / `notifications` / `search`. These are
  *type-identified* (no `tab` needed) and always render in the pinned GitHub
  section, in config order.
- The four tabs are a **fixed, hardcoded set** (fixed keys, labels, and order:
  Global → Markets → Tech → Sports). A news feed with a missing/unknown `tab` is
  coerced to `global`. (Custom/user-defined tabs are a future follow-up.)

### Layout mock (220 px wide)

```
┌────────────────────────────┐
│ CPU  12%        ▁▂▃▅        │
│ RAM  38%        ▂▂▃▃        │   metrics header (old header ⟳ removed)
│         14:32:07           │
├────────────────────────────┤
│ Global Markets [Tech] Sports ⟳│  tab bar: active highlighted + NEWS refresh
│ Hacker News                   │
│  • headline…                  │   (active tab's feeds)
│ GH Trending                   │
│  • repo…                      │
│ Ars AI                        │
│  • headline…                  │
├────────────────────────────┤
│ GitHub                      ⟳ │  pinned section header + GITHUB refresh
│ Notifications 🔔 3            │
│ My PRs (2)                    │
│  ⇄ repo #34 · @me             │
│ Review requests (1)           │
│ Assigned (0)                  │
└────────────────────────────┘
```

When **Markets** is active, its body is MarketWatch, CNBC Markets, then the
Markets tickers tile (config order):

```
│ Global [Markets] Tech Sports ⟳│
│ MarketWatch                   │
│  • headline…                  │
│ CNBC Markets                  │
│  • headline…                  │
│ Markets  1D 1W [1M] 3M        │   stocks tile w/ range toggle
│  SPY   746.77 ▼1.3%           │
│  ▁▂▃▂▁                        │
│  META  563.29 ▲0.1%           │
│  ▂▃▃▄▅                        │
```

## Config schema

### News feeds gain a `tab`

```json
{ "type": "rss", "title": "Hacker News", "url": "…", "tab": "tech" }
```
`tab` ∈ `global` / `markets` / `tech` / `sports`; missing/unknown → `global`.
GitHub-family feeds ignore `tab`.

### New `hud.default_tab`

```json
"hud": { "...": "...", "default_tab": "tech" }
```
The tab shown on launch. Coerced to a valid key; missing → `tech`. The active
tab is **session state** (see below) and resets to `default_tab` on restart.

### Stocks feed

```json
{ "type": "stocks", "title": "Markets",
  "symbols": ["SPY", "META", "GOOGL", "AMZN", "NFLX"],
  "range": "1mo", "tab": "markets" }
```
- `symbols`: 1–10 tickers; each upper-cased and stripped to `[A-Z0-9.^-]`,
  empties dropped, list capped at 10; a feed with no usable symbol → invalid
  (renders an error tile, never crashes).
- `range`: initial Yahoo range; one of `1d`/`5d`/`1mo`/`3mo`; else → `1mo`.
- `interval` (poll seconds): default 300, floor 120, ceiling 86400 (same as the
  `search`/`notifications` feeds). Distinct from the Yahoo *bar* interval below.
- `title` default `"Markets"`; `tab` default `markets` is **not** assumed — like
  any news feed a missing tab → `global`, so config must set `"tab": "markets"`.

### This feature writes nothing to config

Range and active-tab are session state; nothing here calls `config.save`/
`config.update`. (No config-clobber risk, no need to restart sibling toys after
this lands.)

## Stocks data source (verified)

Yahoo v8 chart, one request per symbol:
```
https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}?range={range}&interval={interval}&includePrePost=false
```
Verified live 2026-06-30 with the feedkit **default** UA `Toybox-WebFeed/1.0`:
HTTP 200, ~3.3 KB (SPY 1mo/1d). **No key, no custom header.**

- `chart.result[0].meta.regularMarketPrice` → price.
- `chart.result[0].meta.chartPreviousClose` → prior close; day change =
  `(price - prevClose)/prevClose*100`. (`meta.previousClose` is a fallback.)
- `chart.result[0].indicators.quote[0].close` → close series (may contain
  `null` → filtered).
- Bad/delisted symbol → HTTP **404** with `result: null`, already mapped by the
  fetch layer to `no access`; the parser also guards null/empty `result`.

The **% change is always the day's move** (`regularMarketPrice` vs
`chartPreviousClose`), independent of the selected chart window. The window only
changes the *shape* drawn (the `close` series).

### Range → (Yahoo range, bar interval)

| Toggle | stored `range` | `interval` | ~points |
|---|---|---|---|
| 1D | `1d`  | `5m`  | ~79 |
| 1W | `5d`  | `30m` | ~65 |
| 1M | `1mo` | `1d`  | ~21 |
| 3M | `3mo` | `1d`  | ~63 |

## Architecture (per file)

### `feedkit/model.py` (pure)

- `_VALID_TYPES` += `"stocks"`.
- `Quote = namedtuple("Quote", ["symbol", "price", "change_pct", "series"])`
  (`price`, `change_pct` floats; `series` `list[float]`, may be empty).
- Stock constants: `STOCK_RANGES = {"1d":"5m","5d":"30m","1mo":"1d","3mo":"1d"}`,
  `STOCK_RANGE_ORDER = ("1d","5d","1mo","3mo")`,
  `STOCK_RANGE_LABELS = {"1d":"1D","5d":"1W","1mo":"1M","3mo":"3M"}`,
  `DEFAULT_STOCK_RANGE = "1mo"`.
- Tab constants: `NEWS_TABS = (("global","Global"),("markets","Markets"),
  ("tech","Tech"),("sports","Sports"))` (ordered key/label pairs),
  `DEFAULT_TAB = "tech"`; helper `coerce_tab(value)` → a valid key (default
  `"global"` for feeds; used by `normalize_feed`) and `coerce_default_tab(value)`
  → valid key (default `"tech"`; used for `hud.default_tab`).
- `yahoo_chart_url(symbol, range_)` (unknown range → default; percent-encoded)
  and `yahoo_quote_web_url(symbol)` → `https://finance.yahoo.com/quote/{SYMBOL}`.
- `format_quote_line(quote)` via `"%-5s %7.2f %s%.1f%%"` (symbol, price, arrow,
  abs percent) — e.g. `"SPY    746.77 ▼1.3%"`; arrow `▲` when `change_pct >= 0`
  (exactly 0.0 = up/green) else `▼`. Pure, unit-tested.
- `normalize_feed`:
  - For **news** feeds (`rss`/`json`/`text`/`stocks`), record `tab =
    coerce_tab(raw.get("tab"))`.
  - New `stocks` branch (mirrors `search`): interval default 300/floor 120,
    clean/cap symbols, coerce `range`, default title `"Markets"`, set `tab`.
    Never raises.
  - GitHub-family branches unchanged (no `tab`).
- Add `is_news_type(t)` / `is_pinned_type(t)` (or equivalent predicates) so the
  HUD partitions feeds without hardcoding the type lists in two places.

### `feedkit/parse.py` (pure)

- `parse_stock_chart(body, symbol)` → a `Quote` or `None`; **never raises**
  (defensive over untrusted bytes). Price falls back to the last non-null close
  if `regularMarketPrice` is absent; `change_pct` is 0.0 when prevClose is
  missing/zero; `series` is the filtered close list; returns `None` when there's
  no usable price at all.

### `feedkit/manager.py` (glue)

- Dispatch in `_fetch_and_process`: `if feed["type"] == "stocks": return
  self._process_stocks(idx, feed)` (no token).
- `_process_stocks(idx, feed)`: per symbol, a conditional GET (cache key
  `(idx,"stk",symbol)` → `etag`/`lm`/`quote`): `not_modified` reuses the cached
  `Quote` (fresh); `error` keeps the cached `Quote` if any (stale) and records
  the error word; `ok` → `parse_stock_chart`, keep prior on `None`. Tile state:
  `ok` if ≥1 symbol refreshed with no error this cycle; `stale` if any quotes but
  an error occurred; `error` if nothing at all. Returns
  `FeedResult(state, [Quote…], None, error, None)`. (Tile-level freshness is
  deliberately coarse — one flaky symbol dims/annotates the whole tile.)
- `set_stock_range(idx, code)`: session-state range change from the UI thread.
  Under the lock: no-op unless feed `idx` is a valid `stocks` feed and `code` is
  known; else replace `self.feeds[idx]` with a copy carrying the new `range`,
  drop that feed's `(idx,"stk",*)` cache entries and `self._last[idx]` so the
  worker refetches the new range next tick.
- `refresh(indices)`: force a re-fetch of the given feed indices. Under the lock,
  `self._last.pop(idx, None)` for each — the worker then re-issues a **conditional**
  GET on the next tick (a 304 keeps the cached result; a 200 updates it). Cheap,
  no validators dropped. Used by the two HUD refresh controls.

### `hud.pyw` (canvas)

State + constants:
- `self.active_tab` — a tab key, initialized to `model.coerce_default_tab(
  cfg["hud"].get("default_tab"))`; session state (not persisted).
- Stock colors reuse `STATE_HEX`: `STOCK_UP = "#3fb950"`, `STOCK_DOWN =
  "#f85149"`; chart-row height (`STOCK_CHART_H`, ~20 px); toggle segment width.
- **Remove** the old header ⟳ (`_reload_item`, `_reload_box`, `_in_reload`);
  refreshes now live on the tab bar and the GitHub header. The right-click menu's
  **"Reload feeds"** stays (full config reload).

Partitioning (drive off `model` predicates):
- `_news_indices()` → feeds whose type is news-family, in config order.
- `_github_indices()` → feeds whose type is pinned-family, in config order.

Pure helper (module-level, unit-tested):
- `_stock_points(series, x_left, x_right, top, bottom)` → polyline coords scaled
  by the series' own min→max (min→bottom, max→top), spread across `[x_left,
  x_right]`; `[]` for <2 points; flat series → vertical midline. (Like
  `_update_spark` but min/max-scaled since prices aren't 0–100.)

Rendering (`_draw_feeds` restructured):
```
clear items/hits/actions
y = feeds_top
y = _draw_tab_bar(y)                       # four labels (active highlighted) + news ⟳
for idx,feed in news feeds where feed.tab == active_tab:
    y = _draw_tile(idx, feed, y)           # existing per-tile render (incl. stocks)
if no active-tab feeds: draw "no feeds" placeholder
y = _draw_github_header(y)                  # "GitHub" label + github ⟳
for idx,feed in github feeds:
    y = _draw_tile(idx, feed, y)
_resize(y + PAD)
```
- `_draw_tile(idx, feed, y) -> new_y`: the current per-tile drawing logic
  extracted into a method — handles the normal 5-tuple tiles **and** the stocks
  2-tuple (`_draw_stock_tile`). (Refactor of today's `_draw_feeds` loop body;
  `_tile_for(idx, feed)` yields the tile tuple as `_feed_tiles` does now.)
- `_draw_tab_bar(y)`: draw the four labels left→right (active bright, inactive
  dim), each a click zone `("tab", key)`; a ⟳ at the right edge → `("refresh",
  "news")`. Must fit four labels + ⟳ in ~200 px (8–9 pt, tight spacing;
  abbreviate only if measured width overflows). Returns new y.
- `_draw_github_header(y)`: `"GitHub"` label + a ⟳ → `("refresh","github")`.
- `_draw_stock_tile(payload, y) -> new_y`: title at left; `1D 1W 1M 3M` toggle
  right-aligned on the header line (active brighter), each segment a click zone
  `("range", idx, code)`; per `Quote`: line 1 = `format_quote_line(q)` in the
  up/down color; line 2 = the drawn `create_line` polyline (`_stock_points`) in
  the same color; both lines open `yahoo_quote_web_url(q.symbol)`. No quotes →
  `loading…` / `! <error>` (error only when the tile has no quotes, so one bad
  symbol stays quiet). Appends every canvas id to `self._feed_items`.

Click dispatch (`_on_release`): when `_action_at` returns an action, dispatch on
`action[0]`:
- `"tab"` → `_set_active_tab(key)` (set `self.active_tab`, redraw; **no** refetch
  — the worker keeps all feeds current in the background, so switching is instant).
- `"refresh"` → `"news"` → `_refresh_news()`; `"github"` → `_refresh_github()`.
- `"range"` → `_set_stock_range(idx, code)`.
- else → `_do_dismiss(action)` (notifications ✕/✓, unchanged).

Refresh handlers:
- `_refresh_news()`: `manager.refresh(_news_indices())`; drop `feed_state` for
  those; redraw. Refetches **all** news feeds (every tab), no config reload.
- `_refresh_github()`: re-read `github_token` from config and `manager.set_token`
  (so a token fix applies without a full reload); `manager.refresh(
  _github_indices())`; drop `feed_state` for those; redraw.
- `_set_active_tab(key)` / `_set_stock_range(idx, code)` as above.
- The menu **"Reload feeds"** keeps the existing full `_reload_feeds` (reload
  feeds + token), for structural edits (added/removed feeds, changed tabs); the
  current `active_tab` is left as-is.

The feed **Settings** window (`feedkit/settings.py`) is unchanged; tabs/stocks
are configured by editing `config.json` and picking up via reload/restart.

## Data flow

```
config.json feeds
  → normalize_feed → news feeds carry {tab}; stocks carry {symbols, range, tab}
  → FeedManager worker fetches ALL valid feeds on their intervals (tab-agnostic)
     · stocks: _process_stocks → per-symbol yahoo_chart_url → fetch → parse_stock_chart → Quote
  → FeedResult → queue → HUD _drain_feeds → feed_state[idx]
  → _draw_feeds → tab bar (active_tab) + active tab's tiles + pinned GitHub tiles

active tab   : session state, default from hud.default_tab; tab click → redraw only
stock range  : session state per feed; segment click → set_stock_range → refetch → redraw
news ⟳       : refresh(all news) ; github ⟳ : set_token + refresh(all github) ; menu : full reload
```

All feeds keep fetching regardless of the visible tab, so tab switches show
already-fetched data with no network round-trip.

## Error handling

- Bad/delisted symbol → 404 → `no access`; symbol omitted; only if the whole
  tile is empty does `! no access` show.
- Offline/timeout → last-known quotes retained + drawn (`stale`); no cache →
  `! offline`.
- Unparseable 200 → `parse_stock_chart` → `None`; prior quote retained; `bad
  data` (shown only when the tile is otherwise empty).
- An empty tab shows a `no feeds` placeholder (tab bar still drawn).
- No token needed for news or stocks; the GitHub section keeps its existing
  `no github_token` handling.

## Layout notes

- Tab bar: fitting `Global Markets Tech Sports` + ⟳ in ~200 px is tight; use a
  compact font/spacing and only abbreviate if measurement overflows.
- Only one tab renders at a time, so the HUD is **shorter** than today's flat
  list for the news portion — the tallest tab (Tech: 3 feeds; Markets: 2 feeds +
  the tickers) plus the always-on GitHub section sets the height. The 5-symbol
  Markets tickers tile adds ~190 px only while Markets is active. The HUD
  auto-resizes (`_resize`) and clamps to the screen.

## Testing (TDD; step-level detail belongs in the plan)

- `tests/test_feed_model.py`: `yahoo_chart_url`; `format_quote_line`;
  `coerce_tab`/`coerce_default_tab`; `normalize_feed` for stocks (symbols
  clean/cap, range coercion, interval, title) and for the `tab` field on news
  feeds (valid, missing → global, unknown → global); `is_news_type`/
  `is_pinned_type` classification.
- `tests/test_feed_parse.py`: `parse_stock_chart` (normal; null closes filtered;
  `result:null` → None; missing price → last-close fallback; missing/zero
  prevClose → 0.0; garbage → None, never raises).
- `tests/test_feed_manager.py`: `_process_stocks` (all-ok; one symbol errors,
  others ok → stale retained; `not_modified` reuse; all-fail-no-cache → error);
  `set_stock_range` (updates range, clears cache+last, refetch on next
  `_run_once`; ignores unknown code / non-stocks idx); `refresh(indices)` (drops
  `_last` for exactly those indices so they become due, leaves others alone).
- `tests/test_smoke_hud.py`: renders the four tab labels; only the active tab's
  feeds are drawn while the GitHub section is always drawn; clicking a tab label
  changes `active_tab` and re-renders (no refetch); the news ⟳ calls
  `manager.refresh` with the news indices; the GitHub ⟳ re-reads the token and
  calls `manager.refresh` with the github indices; a `stocks` feed in the Markets
  tab renders a quote line + a drawn chart line + the range toggle, and clicking
  a segment calls `set_stock_range`; `_stock_points` edge cases (empty, single,
  flat, monotonic) as a direct unit test; `default_tab` selects the initial tab.

## Config migration (applied as part of the build)

Add `"tab"` to each existing news feed (Guardian→`global`; MarketWatch,
CNBC→`markets`; Hacker News, GH Trending, Ars AI→`tech`; r/reddevils→`sports`),
add the `stocks` feed (tab `markets`), and add `"default_tab": "tech"` to `hud`.
Because the code defaults gracefully (missing tab → global, missing default_tab
→ tech), the HUD keeps working before/without these edits; they just place feeds
correctly. `config.json` is gitignored and holds the live token — edits are
scoped additions, never a rewrite, and the token is never echoed.

## Global constraints (carried into the plan)

- Pure Python 3.12 **stdlib only — no pip / third-party, ever**.
- Tests: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path>` from repo root (bare `python` is a broken stub).
- Default urllib TLS, **never weakened**; only `http`/`https` reach the browser
  (`is_web_url` gate) — stock/quote click targets are https literals.
- This feature performs **no config writes** (range + active tab are session
  state), so no sibling-toy restart is required after it lands.
- Commit trailer exactly: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Network access only via the Bash tool.
