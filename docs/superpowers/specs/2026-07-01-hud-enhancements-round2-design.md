# HUD Enhancements — Round 2 Design

**Status:** Approved design (brainstorming complete). Next: implementation plan.

**Goal:** Add six independent enhancements to the Toybox HUD (`hud.pyw`): a
schedule "what am I doing now" tile driven by an Excel file, a now-playing
progress bar + track title, a weather tile, a one-row disk-free sensor,
add/remove of stock tickers from the settings window, and edge-peek window
docking.

**Architecture:** Reuse the existing seams. Pure, defensive logic lives in
small stdlib modules (`schedkit/`, `winkit/`, `feedkit/`) that never raise;
Tk/ctypes/WinRT glue is thin and swallows every failure so the HUD can never
crash from a bad file, a dead media session, or an offline network. Web tiles
extend the existing `feedkit` model/parse/manager/tile pipeline; local sensors
and window behavior extend `hud.pyw` and `winkit/`.

**Tech Stack:** Python 3.12 standard library only. `tkinter` (canvas HUD),
`urllib` (HTTP, keyless), `zipfile` + `xml.etree.ElementTree` (xlsx),
`ctypes` (Win32 + WinRT), `shutil` (disk usage). No third-party packages.

## Global Constraints

- **Pure Python 3.12 stdlib. No pip / third-party packages, ever.**
- **Never weaken urllib's default TLS.** Only `http`/`https` URLs may reach the
  browser (`is_web_url` gate already exists in feedkit).
- **`config.json` is gitignored and holds a live GitHub PAT.** Never echo, log,
  or commit it. All runtime config writes go through `config.update(path, {...})`
  (scoped read-modify-write) so a save can never clobber another toy's keys or
  the HUD's window position.
- **The HUD must never crash from external input.** Every parser returns a
  safe default on malformed data; every ctypes/WinRT/Tk call is guarded.
- **Lightweight:** near-zero idle CPU, tiny RAM. Background polling is
  mtime/interval-gated; no busy loops.
- **Test runner:** `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path>`
  run from the repo root (bare `python` is broken on this machine).
- **Commit trailer, exactly:**
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **After changing any config-save code, restart ALL toys** (hud/clipboard/pet)
  so a stale instance can't re-clobber the shared `config.json` (no backup).

## Existing seams this design reuses

- **Feed types** (`feedkit/model.py`): `_NEWS_TYPES` (tabbed: rss/json/text/stocks)
  vs `_PINNED_TYPES` (github-family). `_VALID_TYPES` gates all. `normalize_feed(raw)`
  returns a per-type dict with `"valid"`. Weather becomes a new news type.
- **Manager** (`feedkit/manager.py`): `_fetch_and_process(idx, feed, token)`
  dispatches by `feed["type"]`; per-type processors do conditional GET with a
  per-key cache and return a `FeedResult`/payload. Weather adds `_process_weather`.
- **Tile rendering** (`hud.pyw`): `_draw_feeds` paints the tab bar, the active
  tab's news tiles, the GitHub header, then pinned tiles. `_draw_stock_tile` /
  `_draw_range_toggle` are the template for weather. Constants: `WIDTH=220`,
  `WIDTH_WIDE=440`, `HEIGHT=134`, `PAD=10`, `ROW_H=22`, `ACCENT="#33d6ff"`.
- **Header rows**: five fixed rows (CPU/RAM/GPU/media/clock+expand) drawn in
  `__init__`/`_relayout_header`, each `ROW_H` tall, `y = PAD + n*ROW_H + ROW_H//2`.
- **Settings** (`feedkit/settings.py`): `_TYPES` drives the Add dropdown;
  `_render_fields` builds per-type entry rows; `_on_add` assembles a raw dict
  and validates via `normalize_feed`; `_persist` does the scoped save.
- **winkit** (`winkit/media.py`): pure-ctypes glue with a "test seam" function
  and blanket try/except. `winkit/nowplaying.py` and `winkit/diskinfo.py` follow
  the same shape.

---

## Feature 1 — Schedule tile ("what am I doing right now")

**What it does:** Reads a user-maintained `.xlsx` timetable and renders a pinned
tile at the top of the feed area showing the task scheduled for the current
moment (or the next upcoming task during a gap).

### Sheet format (from the user's real timetable)

A time-grid: a title row, then a header row whose first cell is `Time` and whose
following cells are dated weekday columns (`Mon Jun 29`, `Tue Jun 30`, …). Each
subsequent row has an explicit time **range** in column A (`7:45–8:45`,
`8:45–12:00`, `1:00–3:00`) and one task per day-column. Placeholder cells
(`—`, `-`, blank) mean "nothing scheduled."

### Modules

New package `schedkit/` (mirrors `feedkit`/`winkit`):

- **`schedkit/xlsx.py`** — minimal, defensive `.xlsx` reader. `.xlsx`/`.xlsm`
  only (a zip of XML); legacy binary `.xls` is unsupported.
  - `read_workbook(path) -> dict[str, list[list[object]]]`: sheet name →
    dense 2D grid (rows of cells; each cell `str`/`float`/`None`).
  - Reads `xl/sharedStrings.xml` (string table), `xl/workbook.xml` +
    `xl/_rels/workbook.xml.rels` (sheet names → part paths), each
    `xl/worksheets/sheetN.xml`. Cell decode: `t="s"` → shared string by index;
    `t="str"`/`t="inlineStr"` → inline text; otherwise numeric → `float`
    (Excel stores dates/times as serial numbers). Sparse cells fill with `None`
    by column letter (`A`→0, `B`→1, …, `AA`→26).
  - Never raises: a bad/locked/missing file → `{}`.

- **`schedkit/model.py`** — pure schedule logic.
  - `parse_schedule(workbook) -> Schedule`: for each sheet, find the header row
    (col A text lowercased == `"time"`); map each following day-column to a
    date; parse each block row's range and per-day tasks.
    - **Date columns:** a header cell that is a numeric serial → real date
      (Excel epoch 1899-12-30). A text header (`"Mon Jun 29"`) → parse month+day
      (+ weekday if present). Matching "today" uses (month, day) and, when a
      weekday name is present, requires the weekday to agree — avoids year
      ambiguity in text headers and disambiguates multi-week workbooks.
    - **Time ranges:** split col A on en/em-dash/hyphen/"to". Parse each side as
      12-hour `H[:MM]`. **am/pm inference:** walk rows top-down tracking a
      running clock; if a parsed time would go backwards, add 12h (rolls into
      PM). Correctly resolves `12:00`→noon then `1:00`→13:00.
  - `Schedule.at(now: datetime) -> Slot`: locate the sheet+column whose date ==
    `now.date()`; among its blocks, return the block with `start <= now < end`
    and a non-placeholder task → `Slot(kind="now", start, end, task)`. Else the
    next block today with a real task → `Slot(kind="next", start, …, task)`.
    Else `Slot(kind="none")`.

### HUD integration

- A daemon thread stats the configured file's mtime every ~30 s; on change (or
  first run) it re-reads + re-parses and stores the `Schedule` behind a lock.
  The parse is milliseconds and infrequent — negligible idle cost.
- Each draw tick computes `schedule.at(now)` (cheap) and renders a **pinned tile
  at the very top of the feed column**, above the tab bar, always visible
  regardless of active tab. Layout: a small `▸`/clock glyph + the task, or
  `→ HH:MM  <task>` for a `next` slot; `none` → the tile is hidden.
- Long tasks truncate with the existing `_fit` ellipsis and reuse the existing
  hover-marquee. Clicking does nothing (no URL).

### Config

`hud.schedule.path` — absolute path to the `.xlsx`. Absent/empty → tile hidden.
(Optional `hud.schedule.enabled` bool, default true when a path is set.)

### Error handling

Missing/locked/garbage file → last-good schedule retained; if none, tile hidden.
No date column matches today → tile hidden. Never crashes the HUD.

### Testing

Build tiny `.xlsx` fixtures programmatically (zip the minimal XML) in tests:
- `xlsx.py`: shared strings, inline strings, numeric cells, sparse rows,
  multi-sheet; garbage zip → `{}`.
- `model.py`: header-row detection; range parsing incl. the noon wrap
  (`12:00–1:00` → 12:00–13:00); date-column matching by serial and by text;
  `at()` returning now/next/none across times of day; placeholder handling.

---

## Feature 2 — Now-playing progress bar + track title

**What it does:** Reads the current system media session and renders a progress
bar plus a `title — artist` line under the existing media buttons. Today
`winkit/media.py` only *sends* media keys and reads no state, so this needs a
new reader.

### Module — `winkit/nowplaying.py`

- **`read() -> NowPlaying | None`** — a WinRT/SMTC read via `ctypes`, fully
  guarded (any failure → `None`). Returns
  `NowPlaying(title, artist, status, position_s, duration_s, sampled_at)`
  where `status` ∈ {`playing`,`paused`,`stopped`}, times in seconds,
  `sampled_at` a monotonic timestamp.
  - Flow: `RoInitialize(MULTITHREADED)` once → `RoGetActivationFactory` for
    `Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager`
    (statics iface) → `RequestAsync()` and poll the `IAsyncOperation` status to
    completion (bounded) → `GetResults()` (cache the manager) →
    `get_CurrentSession()` (null → nothing playing) → `GetTimelineProperties()`
    (synchronous: `Position`/`StartTime`/`EndTime`, 100 ns ticks) →
    `GetPlaybackInfo()` (PlaybackStatus enum: 4=Playing, 5=Paused) →
    `GetMediaProperties()` (async, polled: `Title`, `Artist` HSTRINGs →
    Python via `WindowsGetStringRawBuffer`). All COM/HSTRING refs released.
  - All WinRT calls happen on one MTA daemon thread (apartment consistency).

- **Pure helpers (unit-tested):**
  - `progress_fraction(position_s, duration_s) -> float` in `[0,1]` (0 when
    duration ≤ 0).
  - `advance(position_s, elapsed_s, status) -> float`: while `playing`, add
    elapsed wall-clock; else hold. Lets the UI animate smoothly between reads.
  - `format_track(title, artist) -> str`: `"title — artist"`, trimmed; title
    only when artist empty; `""` when both empty.

### HUD integration

- A daemon thread calls `read()` every ~2–3 s and stores the latest sample.
- Each draw tick advances the displayed position with `advance(...)` from
  `sampled_at`, so the bar is smooth without frequent WinRT calls.
- Render under the media buttons: a `title — artist` line (marquee if long) and
  a thin (~3 px) progress bar filled to `progress_fraction` in `ACCENT`. When
  nothing is playing, both render blank.
- **Layout:** reserve fixed space for the now-playing line + bar (stable layout,
  no jumpiness when playback starts/stops). `HEIGHT` and the media/clock row
  offsets shift down accordingly; the width-expand relayout is updated to match.

### Error handling

`read()` returns `None` on any failure (no session, WinRT unavailable, COM
error); the row renders blank. Never raises, never blocks the UI thread.

### Testing

Pure helpers get full TDD (`progress_fraction` clamping, `advance` play/pause,
`format_track` variants). The ctypes reader gets a smoke test: importing the
module and calling `read()` returns `None` or a well-formed `NowPlaying` and
never raises, on any machine.

---

## Feature 3 — Weather tile

**What it does:** A `stocks`-style tile showing current temperature, day
high/low, and a temperature sparkline with a `Today / 3D / 7D` range toggle,
from keyless Open-Meteo.

### feedkit changes

- **`model.py`:** add `"weather"` to `_NEWS_TYPES` and `_VALID_TYPES`.
  `normalize_feed` gains a `weather` branch: `city` (non-empty str, required),
  `units` (`"fahrenheit"`/`"celsius"`, default `fahrenheit`), `range`
  (`today`/`3d`/`7d`, default `today`), `interval` (default 1800, floor 600).
  URL builders:
  - `openmeteo_geocode_url(city)` →
    `https://geocoding-api.open-meteo.com/v1/search?name=<city>&count=1&language=en&format=json`
  - `openmeteo_forecast_url(lat, lon, units, range_)` →
    `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&current=temperature_2m&hourly=temperature_2m&daily=temperature_2m_max,temperature_2m_min&temperature_unit=<f|c>&timezone=auto&forecast_days=<1|3|7>`
  - Ranges: `today` → hourly series for today; `3d`/`7d` → daily max/min series.
- **`parse.py`:** `parse_geocode(body) -> (lat, lon, name) | None` and
  `parse_weather(body, range_) -> WeatherPayload | None` (current temp, hi, lo,
  numeric series for the sparkline). Defensive on missing keys/short arrays.
- **`manager.py`:** `_process_weather(idx, feed)` — geocode once, caching
  `(lat, lon)` under the feed's cache entry, then conditional-GET the forecast;
  return a payload shaped like the stock tile payload. Geocode failure →
  error tile; forecast failure → last-good (stale) like stocks. UA
  `Toybox-WebFeed/1.0` (no key).

### HUD changes

`_draw_weather_tile(idx, payload, y)` mirrors `_draw_stock_tile`: title +
`72°  H 78°  L 61°` + temperature sparkline + a range toggle drawn with the
existing toggle helper but the weather ranges (`Today/3D/7D`). Clicking the
title opens the Open-Meteo/city page (optional; a web URL if available).

### Config

A feed dict, e.g. `{"type":"weather","title":"Weather","city":"Boston","units":"fahrenheit","range":"today","tab":"global"}`.

### Testing

`parse_geocode` / `parse_weather` (valid + malformed bodies), URL builders,
`normalize_feed` weather branch (units/range/city coercion + invalid rejection),
manager geocode-cache logic (with a fake fetch), tile-render smoke.

---

## Feature 4 — Disk-free sensor row (single row)

**What it does:** One new header row listing free space per fixed drive,
compact: `C 312G   D 1.1T`.

### Module — `winkit/diskinfo.py`

- `fixed_drives() -> list[str]`: enumerate `A:`–`Z:`, keep those whose
  `GetDriveTypeW` == `DRIVE_FIXED` (3) via `ctypes` on `kernel32`. Guarded.
- `usage() -> list[tuple[str, int, int]]`: `(letter, free_bytes, total_bytes)`
  per fixed drive via `shutil.disk_usage`. Guarded per drive.
- **Pure helpers (unit-tested):** `human_bytes(n) -> str` (`312G`, `1.1T`,
  ≤ 4 chars) and `format_disk_row(usages, max_chars) -> str` (packs drives onto
  one line, truncating with `…` if too wide).

### HUD integration

Add a disk row to the header stack (after GPU), refreshed every ~15 s (disk-free
changes slowly; `disk_usage` is fast). `HEIGHT` and downstream row offsets shift
by one `ROW_H`; the width-expand relayout updates to match.

### Testing

`human_bytes` (G/T rounding, width cap), `format_disk_row` (packing +
truncation). `fixed_drives`/`usage` get a smoke test (return a list, never raise).

---

## Feature 5 — Add/remove stock tickers in the settings window

**What it does:** Manage a stock watchlist from the Feed Settings window instead
of hand-editing `config.json`.

### feedkit/settings.py changes

- Add `"stocks"` to `_TYPES` (appears in the Add dropdown).
- `_render_fields`: a `stocks` field spec — `Title`, `Symbols`
  (comma/space-separated codes), `Range` (`1d/5d/1mo/3mo` dropdown),
  `Interval`. `_on_add` builds `{"type":"stocks","symbols":[...],"range":..,"interval":..}`,
  splitting the symbols text into a list; `normalize_feed` enforces the existing
  rules (uppercase, strip to `[A-Z0-9.^-]`, cap 10, reject empty).
- **Edit an existing stocks feed's symbols:** in `_refresh_list`, a stocks feed
  shows its current symbols each with a `✕` (remove that ticker) plus a small
  entry + `+` (append a ticker), persisted via the existing scoped `_persist`.
- **Tab selector for news feeds:** since a stocks/weather feed must land in the
  right tab (e.g. Markets), news-type feeds (`rss/json/text/stocks/weather`)
  gain a `Tab` dropdown (`Global/Markets/Tech/Sports`) in `_render_fields`;
  `_on_add` writes `raw["tab"]`. (Existing feeds without a tab still coerce to
  `global` — unchanged.)

### Pure helper (unit-tested)

`parse_symbols(text) -> list[str]` in `feedkit/model.py`: split on commas/space,
upper-case, strip junk, dedupe preserving order, cap 10. Reused by settings and
covered directly by tests (settings GUI itself stays glue).

### Testing

`parse_symbols` variants; `normalize_feed` stocks branch produces a valid feed
from settings-shaped input; a settings smoke test (build window offscreen, add a
stocks feed, assert it persists and validates) following the existing settings
test pattern.

---

## Feature 6 — Edge-peek (dock-to-edge auto-hide)

**What it does:** Drag the HUD near a screen edge to dock it; docked, it hides
mostly off-screen leaving a small lip, and slides fully into view on hover,
sliding back out when the pointer leaves.

### hud.pyw changes

- Session state `self._dock_edge` ∈ {None, left, right, top, bottom} (not
  persisted — matches the existing session-only expand/tab pattern).
- **Pure helpers (unit-tested), module-level in `hud.pyw`:**
  - `edge_for(x, y, w, h, sw, sh, threshold) -> edge | None`: which screen edge
    the window is within `threshold` px of (None if none).
  - `docked_geometry(edge, x, y, w, h, sw, sh, revealed, lip) -> "WxH+X+Y"`:
    the geometry string for a docked window, hidden (leaving `lip` px) or
    revealed (fully on-screen), per edge.
- On drag-release, if `edge_for(...)` returns an edge, dock there and animate to
  hidden. `<Enter>` animates to revealed; `<Leave>` animates back to hidden
  (~120 ms via chained `after`). Dragging away from the edge undocks.
- Screen size from `winfo_screenwidth/height`; single-monitor behavior is the
  target (multi-monitor uses the primary screen dims — acceptable).
- Composes with the width-expand toggle: docking recomputes from the current
  width/height.

### Testing

`edge_for` (each edge, corners, none) and `docked_geometry` (each edge, hidden
vs revealed, lip math) are pure and fully tested. The animation/binding is
smoke-tested offscreen (dock/reveal/undock mutate `_dock_edge` and geometry
without raising).

---

## Config schema — additions (all scoped-save safe)

```jsonc
"hud": {
  "schedule": { "path": "C:/Users/Warren/.../schedule.xlsx" },  // opt; tile hidden if absent
  "weather":  { "units": "fahrenheit" }                          // opt default for weather feeds
}
"feeds": [
  { "type": "weather", "title": "Weather", "city": "Boston",
    "units": "fahrenheit", "range": "today", "tab": "global" },
  { "type": "stocks",  "title": "Markets", "symbols": ["AAPL","NVDA"],
    "range": "1mo", "tab": "markets" }
]
```

Now-playing, disk, and edge-peek need no config (now-playing shows whenever a
session exists; disk is always on; edge-peek is session-only state).

## Non-goals (explicitly out of scope)

- Crypto tickers (dropped by the user — `stocks` could still take `BTC-USD`,
  but nothing crypto-specific is built).
- Google Calendar / OAuth / `.ics` parsing (Excel chosen); writing back to the
  Excel file (read-only).
- Album-art thumbnails; multiple/simultaneous media sessions (current session
  only).
- CPU/GPU temperature, fan speed, network throughput, per-core CPU.
- Persisting edge-dock or expand width across sessions.

## Testing strategy (overall)

- `unittest`, run with the Python 3.12 path above from the repo root.
- Pure logic modules (`schedkit/xlsx`, `schedkit/model`, weather parse/URL,
  `nowplaying` helpers, `diskinfo` helpers, `parse_symbols`, edge-peek geometry)
  are TDD'd to full behavior coverage.
- ctypes/WinRT/Tk glue (`nowplaying.read`, `diskinfo` enumeration, settings
  window, edge-peek animation) gets defensive smoke tests: correct shape, never
  raises, on any machine and with nothing playing / offline.
- Network parsers are tested against synthetic JSON bodies — no live network in
  the test suite.
- `.xlsx` fixtures are generated in-test with `zipfile` (no binary fixtures
  checked in).

## Natural implementation grouping (for the plan)

Six independent features. Suggested build order — light/low-risk first, the two
heavy modules last:

1. Disk-free row  2. Stocks-in-settings (+ tab selector)  3. Edge-peek
4. Weather tile   5. Schedule tile (xlsx)   6. Now-playing (SMTC)

Each is independently testable and shippable; the plan may be split into more
than one document if it grows large.
