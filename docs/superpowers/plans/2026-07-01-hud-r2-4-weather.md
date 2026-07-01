# Weather Tile Implementation Plan

> For agentic workers: use subagent-driven-development to execute; steps use checkbox syntax.

**Goal:** Add a keyless Open-Meteo "weather" news-feed type to the Toybox HUD: a
city geocodes to (lat, lon), a forecast fetch yields current temperature, day
high/low, and a temperature sparkline, rendered as a `stocks`-style tile with a
`Today / 3D / 7D` range toggle that mirrors the existing stock range toggle.
Units default to fahrenheit and are configurable.

**Architecture:** Reuse the existing feedkit model → parse → manager → tile
pipeline (the same seam stocks use). Pure, deterministic logic (URL builders,
JSON parsers, formatters) lives in `feedkit/model.py` + `feedkit/parse.py` and is
fully unit-tested with synthetic bodies (no network). `feedkit/manager.py` adds a
`_process_weather` processor that geocodes once (caching the coordinates under the
feed's cache entry) then conditional-GETs the forecast, returning a `FeedResult`
whose `items` carry a single `Weather` record. `hud.pyw` adds a `_draw_weather_tile`
(+ its own range toggle) and dispatches to it wherever the stock 2-tuple tile is
chosen. Weather is a tabbed news type, so it flows through `_news_indices`,
tab filtering, and the settings/config seams unchanged.

**Tech Stack:** Python 3.12 standard library only. `urllib` (keyless HTTP),
`json` (parse), `tkinter` canvas (tile render). No third-party packages.

## Global Constraints

- **Pure Python 3.12 stdlib; no third-party packages.**
- **Never weaken urllib's default TLS; only http/https may reach the browser.**
- **`config.json` is gitignored and holds a live GitHub PAT** — never echo, log,
  or commit it; every runtime config write goes through `config.update(path, {...})`
  (scoped read-modify-write) so it cannot clobber another toy's keys.
- **The HUD must never crash on bad external input:** every parser returns a safe
  default; every ctypes/WinRT/Tk call is guarded (try/except).
- **Lightweight:** no busy loops; background polling is mtime/interval-gated.
- **Test runner — use this EXACT command form in every "run the test" step:**
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path> -v`
  run from the repo root. Bare `python` is broken on this machine.
- **Commit trailer, EXACTLY** (every commit step ends with this line):
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## Task 1: model — weather types, URL builders, Weather record, normalize branch

**Files:**
- Modify: `C:\Users\Warren\Toybox\feedkit\model.py`
- Test: `C:\Users\Warren\Toybox\tests\test_feed_model.py`

**Interfaces:**
- Consumes: existing `namedtuple`, `urllib.parse`, `_coerce_int`, `coerce_tab`,
  `is_news_type`, `_VALID_TYPES`.
- Produces:
  - `model.Weather` = `namedtuple("Weather", ["current", "hi", "lo", "series", "unit"])`
  - `model.WEATHER_RANGES: dict[str,int]`, `model.WEATHER_RANGE_ORDER: tuple`,
    `model.WEATHER_RANGE_LABELS: dict`, `model.DEFAULT_WEATHER_RANGE: str`
  - `model.openmeteo_geocode_url(city) -> str`
  - `model.openmeteo_forecast_url(lat, lon, units, range_) -> str`
  - `model.format_weather_line(weather) -> str`
  - `normalize_feed` weather branch; `"weather"` in `_NEWS_TYPES` and `_VALID_TYPES`.

### Steps

- [ ] Step: write the failing test — append this class to `tests\test_feed_model.py`:

```python
class TestWeatherModel(unittest.TestCase):
    def test_weather_is_news_type_and_valid_type(self):
        self.assertTrue(model.is_news_type("weather"))
        self.assertIn("weather", model._VALID_TYPES)

    def test_geocode_url(self):
        self.assertEqual(
            model.openmeteo_geocode_url("Boston"),
            "https://geocoding-api.open-meteo.com/v1/search?name=Boston"
            "&count=1&language=en&format=json")

    def test_geocode_url_encodes_city(self):
        self.assertIn("name=New%20York", model.openmeteo_geocode_url("New York"))

    def test_forecast_url_today_is_one_day(self):
        u = model.openmeteo_forecast_url(42.36, -71.06, "fahrenheit", "today")
        self.assertIn("latitude=42.36", u)
        self.assertIn("longitude=-71.06", u)
        self.assertIn("temperature_unit=fahrenheit", u)
        self.assertIn("forecast_days=1", u)
        self.assertIn("current=temperature_2m", u)
        self.assertIn("hourly=temperature_2m", u)
        self.assertIn("daily=temperature_2m_max,temperature_2m_min", u)
        self.assertIn("timezone=auto", u)

    def test_forecast_url_ranges_map_to_days(self):
        self.assertIn("forecast_days=3",
                      model.openmeteo_forecast_url(1.0, 2.0, "celsius", "3d"))
        self.assertIn("forecast_days=7",
                      model.openmeteo_forecast_url(1.0, 2.0, "celsius", "7d"))

    def test_forecast_url_unknown_range_defaults_today(self):
        self.assertIn("forecast_days=1",
                      model.openmeteo_forecast_url(1.0, 2.0, "celsius", "zzz"))

    def test_forecast_url_unknown_units_defaults_fahrenheit(self):
        self.assertIn("temperature_unit=fahrenheit",
                      model.openmeteo_forecast_url(1.0, 2.0, "kelvin", "today"))

    def test_weather_shape(self):
        w = model.Weather(72.0, 78.0, 61.0, [70.0, 72.0], "°F")
        self.assertEqual(w._fields, ("current", "hi", "lo", "series", "unit"))

    def test_format_weather_line_rounds(self):
        w = model.Weather(72.4, 78.6, 61.2, [70.0, 72.0], "°F")
        self.assertEqual(model.format_weather_line(w),
                         "72°  H 79°  L 61°")

    def test_normalize_minimal_valid(self):
        f = model.normalize_feed({"type": "weather", "city": "Boston", "tab": "global"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["city"], "Boston")
        self.assertEqual(f["units"], "fahrenheit")   # default
        self.assertEqual(f["range"], "today")        # default
        self.assertEqual(f["interval"], 1800)        # default
        self.assertEqual(f["title"], "Weather")      # default title
        self.assertEqual(f["tab"], "global")

    def test_normalize_units_and_range_coerce(self):
        f = model.normalize_feed({"type": "weather", "city": "X",
                                  "units": "celsius", "range": "7d"})
        self.assertEqual(f["units"], "celsius")
        self.assertEqual(f["range"], "7d")

    def test_normalize_bad_units_and_range_default(self):
        f = model.normalize_feed({"type": "weather", "city": "X",
                                  "units": "kelvin", "range": "10y"})
        self.assertEqual(f["units"], "fahrenheit")
        self.assertEqual(f["range"], "today")

    def test_normalize_missing_city_invalid(self):
        f = model.normalize_feed({"type": "weather", "city": "  "})
        self.assertFalse(f["valid"])
        self.assertIn("city", f["error"])
        self.assertEqual(f["title"], "Weather")

    def test_normalize_interval_floor_600(self):
        self.assertEqual(model.normalize_feed(
            {"type": "weather", "city": "X", "interval": 5})["interval"], 600)

    def test_normalize_default_tab_global(self):
        self.assertEqual(model.normalize_feed(
            {"type": "weather", "city": "X"})["tab"], "global")
```

- [ ] Step: run it, expect FAIL — command:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
  Expected failure: `AttributeError: module 'feedkit.model' has no attribute
  'openmeteo_geocode_url'` (and `Weather` / `format_weather_line` /
  `WEATHER_RANGES` missing), plus the normalize tests asserting `valid` for a
  `"weather"` type that is not yet in `_VALID_TYPES`.

- [ ] Step: implement — make these edits to `feedkit\model.py`:

  1. Change the `_NEWS_TYPES` line (currently
     `_NEWS_TYPES = ("rss", "json", "text", "stocks")`) to:

```python
_NEWS_TYPES = ("rss", "json", "text", "stocks", "weather")
```

  2. Change the `_VALID_TYPES` line (currently
     `_VALID_TYPES = ("rss", "json", "text", "github", "notifications", "search", "stocks")`)
     to:

```python
_VALID_TYPES = ("rss", "json", "text", "github", "notifications", "search", "stocks", "weather")
```

  3. Insert this block immediately after the `format_quote_line` function
     (right before the `NEWS_TABS = (...)` definition):

```python
Weather = namedtuple("Weather", ["current", "hi", "lo", "series", "unit"])
# current/hi/lo are floats (temperatures already in the feed's requested unit);
# series is list[float] for the sparkline (hourly for 'today', daily-max for
# multi-day); unit is the API's unit symbol string ("°F"/"°C") or "" when absent.

WEATHER_RANGES = {"today": 1, "3d": 3, "7d": 7}          # range -> forecast_days
WEATHER_RANGE_ORDER = ("today", "3d", "7d")
WEATHER_RANGE_LABELS = {"today": "Today", "3d": "3D", "7d": "7D"}
DEFAULT_WEATHER_RANGE = "today"


def openmeteo_geocode_url(city):
    """Open-Meteo geocoding endpoint for a city name (keyless). count=1 -> the
    single best match; the city is percent-encoded so spaces/punctuation are safe."""
    return ("https://geocoding-api.open-meteo.com/v1/search?name=%s"
            "&count=1&language=en&format=json"
            % urllib.parse.quote(city, safe=""))


def openmeteo_forecast_url(lat, lon, units, range_):
    """Open-Meteo forecast endpoint (keyless). Unknown range -> DEFAULT_WEATHER_RANGE;
    unknown units -> 'fahrenheit'. Requests current temp, an hourly series, and
    daily max/min; forecast_days follows the range (today=1, 3d=3, 7d=7)."""
    days = WEATHER_RANGES.get(range_, WEATHER_RANGES[DEFAULT_WEATHER_RANGE])
    unit = units if units in ("fahrenheit", "celsius") else "fahrenheit"
    return ("https://api.open-meteo.com/v1/forecast"
            "?latitude=%s&longitude=%s"
            "&current=temperature_2m&hourly=temperature_2m"
            "&daily=temperature_2m_max,temperature_2m_min"
            "&temperature_unit=%s&timezone=auto&forecast_days=%d"
            % (lat, lon, unit, days))


def format_weather_line(weather):
    """One-line weather render: '<cur>°  H <hi>°  L <lo>°' with temps rounded to
    whole degrees. Example: '72°  H 78°  L 61°'."""
    return "%d°  H %d°  L %d°" % (
        round(weather.current), round(weather.hi), round(weather.lo))
```

  4. Insert this weather branch in `normalize_feed` immediately after the stocks
     branch (right after the stocks branch's final `return out`, before the
     `# github` comment):

```python
    if ftype == "weather":
        # default 1800 / floor 600 (Open-Meteo is keyless but slow-changing), so
        # set interval explicitly like the stocks/search/notifications branches.
        out["interval"] = _coerce_int(raw.get("interval"), 1800, 600, 86400)
        city = raw.get("city")
        city = city.strip() if isinstance(city, str) else ""
        if not city:
            out.update(valid=False, error="weather feed needs 'city'",
                       title=title or "Weather")
            return out
        out["city"] = city
        units = raw.get("units")
        out["units"] = units if units in ("fahrenheit", "celsius") else "fahrenheit"
        rng = raw.get("range")
        out["range"] = rng if rng in WEATHER_RANGES else DEFAULT_WEATHER_RANGE
        out["title"] = title or "Weather"
        return out
```

- [ ] Step: run it, expect PASS — command:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`

- [ ] Step: commit —

```
git add feedkit/model.py tests/test_feed_model.py
git commit -m "feat(feedkit): weather feed type, Open-Meteo URL builders + Weather record

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: parse — parse_geocode and parse_weather

**Files:**
- Modify: `C:\Users\Warren\Toybox\feedkit\parse.py`
- Test: `C:\Users\Warren\Toybox\tests\test_feed_parse.py`

**Interfaces:**
- Consumes: `json`, existing `_finite_num`, `feedkit.model` (aliased `model`),
  `model.Weather` (from Task 1).
- Produces:
  - `parse.parse_geocode(body) -> (lat: float, lon: float, name: str) | None`
  - `parse.parse_weather(body, range_) -> model.Weather | None`

### Steps

- [ ] Step: write the failing test — append these two classes to
  `tests\test_feed_parse.py`:

```python
class TestParseGeocode(unittest.TestCase):
    def test_valid(self):
        body = json.dumps({"results": [
            {"name": "Boston", "latitude": 42.3584, "longitude": -71.0598}]}).encode()
        self.assertEqual(parse.parse_geocode(body), (42.3584, -71.0598, "Boston"))

    def test_empty_results_is_none(self):
        self.assertIsNone(parse.parse_geocode(json.dumps({"results": []}).encode()))

    def test_missing_results_key_is_none(self):
        self.assertIsNone(parse.parse_geocode(json.dumps({}).encode()))

    def test_non_finite_coords_is_none(self):
        body = json.dumps({"results": [
            {"name": "X", "latitude": "nope", "longitude": 1.0}]}).encode()
        self.assertIsNone(parse.parse_geocode(body))

    def test_missing_name_yields_empty_string(self):
        body = json.dumps({"results": [
            {"latitude": 1.0, "longitude": 2.0}]}).encode()
        self.assertEqual(parse.parse_geocode(body), (1.0, 2.0, ""))

    def test_garbage_is_none(self):
        self.assertIsNone(parse.parse_geocode(b"<<not json>>"))


class TestParseWeather(unittest.TestCase):
    def _today_body(self):
        return json.dumps({
            "current": {"temperature_2m": 72.0},
            "current_units": {"temperature_2m": "°F"},
            "hourly": {"temperature_2m": [70.0, 71.0, 73.0, 72.0]},
            "daily": {"temperature_2m_max": [78.0], "temperature_2m_min": [61.0]},
        }).encode()

    def test_today_uses_hourly_series_and_daily_hilo(self):
        w = parse.parse_weather(self._today_body(), "today")
        self.assertAlmostEqual(w.current, 72.0)
        self.assertAlmostEqual(w.hi, 78.0)
        self.assertAlmostEqual(w.lo, 61.0)
        self.assertEqual(w.series, [70.0, 71.0, 73.0, 72.0])
        self.assertEqual(w.unit, "°F")

    def test_multiday_uses_daily_series_and_range_hilo(self):
        body = json.dumps({
            "current": {"temperature_2m": 55.0},
            "current_units": {"temperature_2m": "°C"},
            "hourly": {"temperature_2m": [1.0, 2.0]},
            "daily": {"temperature_2m_max": [60.0, 65.0, 58.0],
                      "temperature_2m_min": [40.0, 45.0, 38.0]},
        }).encode()
        w = parse.parse_weather(body, "3d")
        self.assertEqual(w.series, [60.0, 65.0, 58.0])   # daily-max series
        self.assertAlmostEqual(w.hi, 65.0)               # max of daily max
        self.assertAlmostEqual(w.lo, 38.0)               # min of daily min

    def test_missing_current_temp_is_none(self):
        body = json.dumps({"current": {}, "daily": {}}).encode()
        self.assertIsNone(parse.parse_weather(body, "today"))

    def test_non_finite_series_values_filtered(self):
        body = json.dumps({
            "current": {"temperature_2m": 50.0},
            "current_units": {"temperature_2m": "°F"},
            "hourly": {"temperature_2m": [50.0, None, "x", 52.0]},
            "daily": {"temperature_2m_max": [55.0], "temperature_2m_min": [45.0]},
        }).encode()
        w = parse.parse_weather(body, "today")
        self.assertEqual(w.series, [50.0, 52.0])         # junk dropped

    def test_missing_units_yields_empty_string(self):
        body = json.dumps({
            "current": {"temperature_2m": 50.0},
            "hourly": {"temperature_2m": [50.0]},
            "daily": {"temperature_2m_max": [55.0], "temperature_2m_min": [45.0]},
        }).encode()
        self.assertEqual(parse.parse_weather(body, "today").unit, "")

    def test_garbage_is_none(self):
        self.assertIsNone(parse.parse_weather(b"<<not json>>", "today"))
```

- [ ] Step: run it, expect FAIL — command:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
  Expected failure: `AttributeError: module 'feedkit.parse' has no attribute
  'parse_geocode'`.

- [ ] Step: implement — insert these two functions into `feedkit\parse.py`
  immediately after `parse_stock_chart` (before `compose_github_status`):

```python
def parse_geocode(body):
    """Parse an Open-Meteo geocoding response into (lat, lon, name), or None.
    NEVER raises. Takes the first result; requires finite lat/lon; name defaults
    to "" when missing."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    try:
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            return None
        r = results[0]
        if not isinstance(r, dict):
            return None
        lat, lon = r.get("latitude"), r.get("longitude")
        if not _finite_num(lat) or not _finite_num(lon):
            return None
        name = r.get("name")
        name = name if isinstance(name, str) and name else ""
        return (float(lat), float(lon), name)
    except Exception:
        return None


def parse_weather(body, range_):
    """Parse an Open-Meteo forecast response into a model.Weather, or None. NEVER
    raises. 'today' -> hourly series + today's daily max/min; '3d'/'7d' -> daily-max
    series + max(daily max)/min(daily min). Non-finite series values are dropped.
    Returns None only when the current temperature is missing/unparseable."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        cur = data.get("current")
        cur = cur if isinstance(cur, dict) else {}
        current = cur.get("temperature_2m")
        if not _finite_num(current):
            return None
        units_map = data.get("current_units")
        unit = ""
        if isinstance(units_map, dict) and isinstance(units_map.get("temperature_2m"), str):
            unit = units_map.get("temperature_2m")
        daily = data.get("daily")
        daily = daily if isinstance(daily, dict) else {}
        dmax = [float(v) for v in (daily.get("temperature_2m_max") or []) if _finite_num(v)]
        dmin = [float(v) for v in (daily.get("temperature_2m_min") or []) if _finite_num(v)]
        if range_ == "today":
            hourly = data.get("hourly")
            hourly = hourly if isinstance(hourly, dict) else {}
            series = [float(v) for v in (hourly.get("temperature_2m") or []) if _finite_num(v)]
            hi = dmax[0] if dmax else (max(series) if series else current)
            lo = dmin[0] if dmin else (min(series) if series else current)
        else:
            series = dmax
            hi = max(dmax) if dmax else current
            lo = min(dmin) if dmin else current
        return model.Weather(float(current), float(hi), float(lo), series, unit)
    except Exception:
        return None
```

- [ ] Step: run it, expect PASS — command:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`

- [ ] Step: commit —

```
git add feedkit/parse.py tests/test_feed_parse.py
git commit -m "feat(feedkit): parse_geocode + parse_weather for Open-Meteo bodies

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: manager — _process_weather, dispatch, set_weather_range

**Files:**
- Modify: `C:\Users\Warren\Toybox\feedkit\manager.py`
- Test: `C:\Users\Warren\Toybox\tests\test_feed_manager.py`

**Interfaces:**
- Consumes: `model.openmeteo_geocode_url`, `model.openmeteo_forecast_url`,
  `model.WEATHER_RANGES` (Task 1), `parse.parse_geocode`, `parse.parse_weather`
  (Task 2), existing `self._fetch`, `self._cache`, `self._lock`, `FeedResult`.
- Produces:
  - `FeedManager._process_weather(idx, feed) -> FeedResult`
    (`.items == [model.Weather]` on success)
  - `FeedManager.set_weather_range(idx, code) -> None`
  - weather dispatch inside `_fetch_and_process`.

### Steps

- [ ] Step: write the failing test — append this class to
  `tests\test_feed_manager.py`:

```python
class TestProcessWeather(unittest.TestCase):
    GEO = json.dumps({"results": [
        {"name": "Boston", "latitude": 42.36, "longitude": -71.06}]}).encode()

    def _forecast(self, current=72.0, hi=78.0, lo=61.0, series=(70.0, 72.0, 74.0)):
        return json.dumps({
            "current": {"temperature_2m": current},
            "current_units": {"temperature_2m": "°F"},
            "hourly": {"temperature_2m": list(series)},
            "daily": {"temperature_2m_max": [hi], "temperature_2m_min": [lo]},
        }).encode()

    FEED = {"type": "weather", "city": "Boston", "units": "fahrenheit",
            "range": "today", "tab": "global"}

    def test_ok_geocode_then_forecast(self):
        def fake(url, **kw):
            if "geocoding-api" in url:
                return _ok(self.GEO)
            return _ok(self._forecast())
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "ok")
        w = result.items[0]
        self.assertAlmostEqual(w.current, 72.0)
        self.assertAlmostEqual(w.hi, 78.0)
        self.assertAlmostEqual(w.lo, 61.0)

    def test_geocode_cached_not_refetched(self):
        geo_calls = {"n": 0}
        def fake(url, **kw):
            if "geocoding-api" in url:
                geo_calls["n"] += 1
                return _ok(self.GEO)
            return _ok(self._forecast())
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        m._last.clear()
        m._run_once(2000.0); m.drain()
        self.assertEqual(geo_calls["n"], 1)          # geocoded once, cached thereafter

    def test_geocode_failure_is_error(self):
        m = manager.FeedManager(
            [self.FEED],
            fetch_fn=lambda u, **k: _err("offline") if "geocoding-api" in u else _ok(b"{}"))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")
        self.assertEqual(result.items, [])

    def test_city_not_found_is_error(self):
        def fake(url, **kw):
            if "geocoding-api" in url:
                return _ok(json.dumps({"results": []}).encode())
            return _ok(self._forecast())
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")

    def test_forecast_failure_after_success_is_stale_retained(self):
        state = {"n": 0}
        def fake(url, **kw):
            if "geocoding-api" in url:
                return _ok(self.GEO)
            state["n"] += 1
            return _ok(self._forecast()) if state["n"] == 1 else _err("offline")
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        m._last.clear()
        m._run_once(2000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.error, "offline")
        self.assertEqual(len(result.items), 1)       # last-good weather retained

    def test_set_weather_range_updates_and_refetches(self):
        urls = []
        def fake(url, **kw):
            urls.append(url)
            if "geocoding-api" in url:
                return _ok(self.GEO)
            return _ok(self._forecast())
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        m.set_weather_range(0, "7d")
        self.assertEqual(m.feeds[0]["range"], "7d")
        m._run_once(2000.0); m.drain()
        self.assertTrue(any("forecast_days=7" in u for u in urls))

    def test_set_weather_range_ignores_unknown_and_nonweather(self):
        m = manager.FeedManager(
            [self.FEED, {"type": "stocks", "symbols": ["SPY"], "range": "1mo"}],
            fetch_fn=lambda u, **k: _ok(self.GEO if "geocoding" in u
                                        else json.dumps({
                "current": {"temperature_2m": 1.0},
                "current_units": {"temperature_2m": "°F"},
                "hourly": {"temperature_2m": [1.0]},
                "daily": {"temperature_2m_max": [2.0], "temperature_2m_min": [0.0]}}).encode()))
        m.set_weather_range(0, "zzz")
        self.assertEqual(m.feeds[0]["range"], "today")   # unknown code -> unchanged
        m.set_weather_range(1, "7d")
        self.assertEqual(m.feeds[1].get("range"), "1mo") # non-weather idx -> unchanged
        m.set_weather_range(99, "7d")                    # out of range -> no crash
```

- [ ] Step: run it, expect FAIL — command:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
  Expected failure: the weather feed falls through `_fetch_and_process` to the
  generic `feed["url"]` branch and raises `KeyError: 'url'` (caught into a
  `FeedResult("error", ...)` with no `Weather` item), so
  `test_ok_geocode_then_forecast` fails on `result.state == "ok"`; and
  `AttributeError: 'FeedManager' object has no attribute 'set_weather_range'`.

- [ ] Step: implement — make these two edits to `feedkit\manager.py`:

  1. Add the weather dispatch in `_fetch_and_process`, immediately after the
     stocks dispatch line (`if feed["type"] == "stocks": return self._process_stocks(idx, feed)`):

```python
        if feed["type"] == "weather":
            return self._process_weather(idx, feed)
```

  2. Add these two methods immediately after `_process_stocks`:

```python
    def _process_weather(self, idx, feed):
        """Geocode the city once (cached under (idx,'geo') so lat/lon survive range
        changes), then conditional-GET the forecast under (idx,'wx') -> {etag, lm,
        result}. Geocode failure / city-not-found -> error tile. Forecast
        not_modified reuses the cached result (fresh); forecast error or bad data
        keeps the last-good Weather (stale) like stocks; no cache -> error."""
        geo_key = (idx, "geo")
        with self._lock:
            coords = self._cache.get(geo_key, {}).get("coords")
        if coords is None:
            gres = self._fetch(model.openmeteo_geocode_url(feed["city"]))
            if gres.status != "ok":
                return FeedResult("error", [], None, gres.error or "geocode failed")
            coords = parse.parse_geocode(gres.body)
            if coords is None:
                return FeedResult("error", [], None, "city not found")
            with self._lock:
                self._cache[geo_key] = {"coords": coords}
        lat, lon, _name = coords
        fx_key = (idx, "wx")
        with self._lock:
            cache = self._cache.get(fx_key, {})
        res = self._fetch(model.openmeteo_forecast_url(lat, lon, feed["units"], feed["range"]),
                          etag=cache.get("etag"), last_modified=cache.get("lm"))
        prev = cache.get("result")
        if res.status == "not_modified":
            return prev or FeedResult("ok", [], None, None)
        if res.status == "error":
            return FeedResult("stale" if prev else "error",
                              prev.items if prev else [], None, res.error)
        weather = parse.parse_weather(res.body, feed["range"])
        if weather is None:
            return FeedResult("stale" if prev else "error",
                              prev.items if prev else [], None, "bad data")
        result = FeedResult("ok", [weather], None, None)
        with self._lock:
            self._cache[fx_key] = {"etag": res.etag, "lm": res.last_modified, "result": result}
        return result

    def set_weather_range(self, idx, code):
        """UI-thread session-state range change for a weather feed. No-op unless idx
        is a valid weather feed and code is a known range. Replaces the feed with a
        copy carrying the new range and drops its (idx,'wx',*) forecast cache +
        last-fetch so the worker refetches the new range next tick. The (idx,'geo')
        geocode cache is kept -- coordinates do not depend on the range."""
        with self._lock:
            if not (0 <= idx < len(self.feeds)):
                return
            feed = self.feeds[idx]
            if not feed.get("valid") or feed.get("type") != "weather" or code not in model.WEATHER_RANGES:
                return
            new = dict(feed)
            new["range"] = code
            self.feeds[idx] = new
            for k in [k for k in self._cache
                      if isinstance(k, tuple) and len(k) == 2 and k[0] == idx and k[1] == "wx"]:
                self._cache.pop(k, None)
            self._last.pop(idx, None)
```

- [ ] Step: run it, expect PASS — command:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`

- [ ] Step: commit —

```
git add feedkit/manager.py tests/test_feed_manager.py
git commit -m "feat(feedkit): _process_weather (cached geocode + forecast) and set_weather_range

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: hud — weather tile render, range toggle, dispatch

**Files:**
- Modify: `C:\Users\Warren\Toybox\hud.pyw`
- Test: `C:\Users\Warren\Toybox\tests\test_smoke_hud.py`

**Interfaces:**
- Consumes: `feedmodel.WEATHER_RANGE_ORDER`, `feedmodel.WEATHER_RANGE_LABELS`,
  `feedmodel.format_weather_line` (Task 1), `manager.set_weather_range` (Task 3),
  existing `_fit`, `_stock_points`, `_register_action`, `_register_hit`,
  `self._feed_font_measure`, constants `PAD/FEED_LINE_H/FEED_TITLE_GAP/FEED_FG/`
  `FEED_DIM/ACCENT/STOCK_CHART_H`.
- Produces:
  - `Hud._draw_weather_tile(idx, payload, y) -> y`
  - `Hud._draw_weather_range_toggle(idx, current, row_y) -> None`
  - `_tile_for` weather branch returning `("weather", payload)`; `_draw_tile`
    dispatch; `_set_stock_range` routes weather feeds to `set_weather_range`.

### Steps

- [ ] Step: write the failing test — append this class to
  `tests\test_smoke_hud.py` (it reuses the module-level `_fill_of` helper):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudWeather(_HudTestBase):
    FEED = {"type": "weather", "title": "Weather", "city": "Boston",
            "units": "fahrenheit", "range": "today", "tab": "global"}

    def _w(self, current=72.0, hi=78.0, lo=61.0, series=(70.0, 72.0, 74.0), unit="°F"):
        from feedkit.model import Weather
        return Weather(current, hi, lo, list(series), unit)

    def test_tile_renders_temps_chart_and_toggle(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "global"
            hud.feed_state[0] = manager.FeedResult("ok", [self._w()], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("Weather"))          # title
            self.assertTrue(hud._feed_has_text("H 78°"))       # hi/lo line
            self.assertTrue(hud._feed_has_text("Today"))            # toggle labels
            self.assertTrue(hud._feed_has_text("7D"))
            self.assertTrue(any(hud.canvas.type(i) == "line" for i in hud._feed_items))  # sparkline
        finally:
            hud.close(); root.destroy()

    def test_range_toggle_click_calls_set_weather_range(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "global"
            calls = []
            hud.manager.set_weather_range = lambda idx, code: calls.append((idx, code))
            hud.feed_state[0] = manager.FeedResult("ok", [self._w()], None, None)
            hud._draw_feeds(); root.update_idletasks()
            hit = None
            for (y0, y1, x0, x1, a) in hud._action_hits:
                if a == ("range", 0, "7d"):
                    hit = (y0, y1, x0, x1); break
            self.assertIsNotNone(hit, "no 7D range zone")
            y0, y1, x0, x1 = hit
            ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
            hud._moved = False; hud._on_release(ev)
            self.assertEqual(calls, [(0, "7d")])
        finally:
            hud.close(); root.destroy()

    def test_stale_tile_dims_line(self):
        import feedkit.manager as manager
        import hud as hudmod
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "global"
            hud.feed_state[0] = manager.FeedResult("stale", [self._w()], None, "offline")
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(_fill_of(hud, "H 78°"), hudmod.FEED_DIM)
        finally:
            hud.close(); root.destroy()

    def test_error_tile_shows_placeholder(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "global"
            hud.feed_state[0] = manager.FeedResult("error", [], None, "city not found")
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("! city not found"))
        finally:
            hud.close(); root.destroy()

    def test_loading_placeholder_when_no_data(self):
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "global"
            hud._draw_feeds(); root.update_idletasks()      # feed_state[0] is None
            self.assertTrue(hud._feed_has_text("loading"))
        finally:
            hud.close(); root.destroy()
```

- [ ] Step: run it, expect FAIL — command:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudWeather -v`
  Expected failure: the weather feed is drawn through the generic 5-tuple tile
  path (no `("weather", payload)` branch yet), so `_feed_has_text("H 78°")` and
  the `("range", 0, "7d")` action zone are absent
  (`AssertionError: no 7D range zone` / `False is not true`).

- [ ] Step: implement — make these four edits to `hud.pyw`:

  1. In `_tile_for`, insert this branch immediately after the stocks branch's
     `return ("stocks", payload)` line:

```python
        if feed.get("valid") and feed["type"] == "weather":
            result = self.feed_state.get(idx)
            payload = {"title": feed.get("title") or feed.get("city") or "Weather",
                       "range": feed["range"],
                       "weather": (result.items[0] if result and result.items else None),
                       "state": result.state if result else "loading",
                       "error": result.error if result else None}
            return ("weather", payload)
```

  2. In `_draw_tile`, replace the 2-tuple dispatch. Change:

```python
        tile = self._tile_for(idx, feed)
        if len(tile) == 2:                       # ("stocks", payload)
            return self._draw_stock_tile(idx, tile[1], y)
        title, title_url, color, lines, header_action = tile
```

  to:

```python
        tile = self._tile_for(idx, feed)
        if len(tile) == 2:                       # ("stocks"/"weather", payload)
            if tile[0] == "weather":
                return self._draw_weather_tile(idx, tile[1], y)
            return self._draw_stock_tile(idx, tile[1], y)
        title, title_url, color, lines, header_action = tile
```

  3. Insert these two methods immediately after `_draw_range_toggle`:

```python
    def _draw_weather_tile(self, idx, payload, y):
        c = self.canvas
        y += FEED_TITLE_GAP
        row_y = y + FEED_LINE_H // 2
        tid = c.create_text(PAD, row_y, anchor="w", text=_fit(payload["title"]),
                            fill=FEED_FG, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        self._draw_weather_range_toggle(idx, payload["range"], row_y)
        y += FEED_LINE_H
        w = payload["weather"]
        if w is None:
            msg = ("! " + payload["error"]) if (payload["state"] != "loading" and payload["error"]) else "loading…"
            lid = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                                text=_fit(msg), fill=FEED_DIM, font=FEED_FONT)
            self._feed_items.append(lid)
            return y + FEED_LINE_H
        stale = payload["state"] in ("stale", "error")
        color = FEED_DIM if stale else ACCENT
        lid = c.create_text(PAD + 6, y + FEED_LINE_H // 2, anchor="w",
                            text=_fit(feedmodel.format_weather_line(w)),
                            fill=(FEED_DIM if stale else FEED_FG), font=FEED_FONT)
        self._feed_items.append(lid)
        y += FEED_LINE_H
        pts = _stock_points(w.series, PAD + 6, self.width - PAD, y + 2, y + STOCK_CHART_H - 2)
        if pts:
            bottom = y + STOCK_CHART_H - 2
            poly = c.create_polygon(*(pts + [pts[-2], bottom, pts[0], bottom]),
                                    fill=color, stipple="gray25", outline="")
            self._feed_items.append(poly)
            ln = c.create_line(*pts, fill=color, width=1)
            self._feed_items.append(ln)
        y += STOCK_CHART_H
        return y

    def _draw_weather_range_toggle(self, idx, current, row_y):
        c = self.canvas
        x = self.width - PAD
        for code in reversed(feedmodel.WEATHER_RANGE_ORDER):     # draw right->left; 7D rightmost
            label = feedmodel.WEATHER_RANGE_LABELS[code]
            active = (code == current)
            tid = c.create_text(x, row_y, anchor="e", text=label,
                                fill=(FEED_FG if active else FEED_DIM), font=FEED_FONT)
            self._feed_items.append(tid)
            w = self._feed_font_measure.measure(label)
            self._register_action(row_y, x - w, x, ("range", idx, code))
            if active:
                uy = row_y + FEED_LINE_H // 2 - 1
                ul = c.create_rectangle(x - w, uy, x, uy + 2, fill=ACCENT, outline="")
                self._feed_items.append(ul)
            x -= w + 6
```

  4. Replace `_set_stock_range` so weather feeds route to `set_weather_range`
     (the `("range", idx, code)` action is shared by both tile kinds; codes never
     overlap). Change:

```python
    def _set_stock_range(self, idx, code):
        self.manager.set_stock_range(idx, code)
        self.feed_state.pop(idx, None)
        self._draw_feeds()
```

  to:

```python
    def _set_stock_range(self, idx, code):
        feeds = self.manager.feeds
        ftype = feeds[idx].get("type") if 0 <= idx < len(feeds) else None
        if ftype == "weather":
            self.manager.set_weather_range(idx, code)
        else:
            self.manager.set_stock_range(idx, code)
        self.feed_state.pop(idx, None)
        self._draw_feeds()
```

- [ ] Step: run it, expect PASS — commands:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudWeather -v`
  then the full HUD smoke suite to catch regressions in the shared range dispatch:
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`

- [ ] Step: commit —

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): weather tile render + Today/3D/7D range toggle

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the executor

- This plan touches NO header/feed-layout rows in `hud.pyw` (no new `ROW_H`
  offsets, no `HEIGHT` change): the weather tile flows through the existing feed
  column exactly like the stock tile, so it composes with sibling features that
  do shift the header layout.
- Weather is a tabbed news type: it appears in `_news_indices`, obeys the active
  tab, and needs no changes to `_github_indices`, tab filtering, or the settings
  window for this feature. A settings-window Add form for weather is out of scope
  here (config-dict driven, per the spec's Feature 3 config example).
- After merging, if any config-save code changed elsewhere in the session,
  restart ALL toys (hud/clipboard/pet) so a stale instance can't re-clobber the
  shared `config.json` (no backup).
