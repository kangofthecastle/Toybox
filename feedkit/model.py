"""Pure feed helpers: data types, text sanitizing, conditional-request headers,
and GitHub URL/header builders. No network, no Tk, no clock -- the worker injects
``now`` and raw bytes. Everything here is deterministic and unit-testable."""
from collections import namedtuple
import math
import re
import urllib.parse

Item = namedtuple("Item", ["text", "url"])            # url may be None
Status = namedtuple("Status", ["text", "state", "url"])  # state: success/failure/pending/none

NotifItem = namedtuple("NotifItem",
    ["glyph", "repo", "number", "reason_label", "urgency", "updated_at", "title",
     "url", "thread_url"],
    defaults=("",))
# urgency is the tier string "high"/"normal"/"low" -- the HUD maps it to a palette
# color. number is a display token ("#34" or ""). updated_at is a float unix
# timestamp (0.0 when the API value was missing/unparseable).

# C0 (except the whitespace we normalize), DEL, and C1 control ranges.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS = re.compile(r"\s+")


def strip_control_chars(s):
    """Drop control characters and collapse all whitespace runs to single spaces."""
    if not s:
        return ""
    return _WS.sub(" ", _CONTROL.sub("", s)).strip()


def truncate(s, n):
    """Truncate to at most ``n`` characters, marking elision with a trailing ellipsis."""
    s = s or ""
    if len(s) <= n:
        return s
    if n <= 1:
        return "…"
    return s[:n - 1].rstrip() + "…"


def build_conditional_headers(etag, last_modified):
    """If-None-Match / If-Modified-Since headers for a conditional GET (echo weak
    validators verbatim). Empty dict when neither validator is cached."""
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


def is_web_url(url):
    """True only for http/https URLs. The single gate on what may be opened in a
    browser -- feed item URLs are attacker-controlled, so file://, javascript:,
    data:, and custom schemes must never reach webbrowser.open."""
    return isinstance(url, str) and url.lower().startswith(("http://", "https://"))


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


NEWS_TABS = (("global", "Global"), ("markets", "Markets"),
             ("tech", "Tech"), ("sports", "Sports"))
DEFAULT_TAB = "tech"
_TAB_KEYS = frozenset(k for k, _ in NEWS_TABS)
_NEWS_TYPES = ("rss", "json", "text", "stocks", "weather")
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


GITHUB_API = "https://api.github.com"


def github_ci_url(repo, branch):
    """check-runs endpoint for repo@branch (covers GitHub Actions; the legacy
    /status endpoint does not). The branch resolves to HEAD server-side; a '/' in
    the ref is percent-encoded."""
    return "%s/repos/%s/commits/%s/check-runs?per_page=100" % (
        GITHUB_API, repo, urllib.parse.quote(branch, safe=""))


def github_notifications_url():
    # per_page=50 so the unread count can actually reach the "50+" render threshold
    # (the API default page size is 30).
    return "%s/notifications?per_page=50" % GITHUB_API


def github_mark_all_read_url():
    # PUT here marks every notification thread read (no query string, unlike the
    # GET notifications URL). Used only by the authenticated API client.
    return "%s/notifications" % GITHUB_API


def github_search_url(query, per_page):
    """Issue/PR search endpoint, newest-updated first. `query` is the raw GitHub
    search expression (e.g. 'is:open is:pr author:@me'); it is percent-encoded."""
    return "%s/search/issues?q=%s&sort=updated&order=desc&per_page=%d" % (
        GITHUB_API, urllib.parse.quote(query), per_page)


def github_search_web_url(query):
    """github.com search UI for `query` (covers issues and PRs). Used as the
    click target for a search tile's header and its '… N more' overflow line."""
    return "https://github.com/search?q=%s&type=issues" % urllib.parse.quote(query)


def github_headers(token):
    """Mandatory GitHub REST headers. User-Agent is required (urllib's default UA
    gets a 403). Authorization is added only when a token is present."""
    headers = {
        "User-Agent": "Toybox-WebFeed/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


# --- notifications classification (single source of truth; see spec §2) -------
_NOTIF_GLYPHS = {
    "PullRequest": "⇄",                    # ⇄
    "Issue": "◉",                          # ◉
    "Discussion": "\U0001f4ac",                 # 💬
    "Release": "\U0001f3f7",                    # 🏷
    "CheckSuite": "⚑",                     # ⚑
    "WorkflowRun": "⚑",
    "Commit": "◉",
    "RepositoryVulnerabilityAlert": "⚑",
    "SecurityAdvisory": "⚑",
    "RepositoryDependabotAlertsThread": "⚑",
}
_NOTIF_DEFAULT_GLYPH = "◉"                 # ◉

# reason -> (label <=8 chars, urgency tier)
_NOTIF_REASONS = {
    "review_requested": ("review", "high"),
    "mention": ("@you", "high"),
    "team_mention": ("@team", "high"),
    "assign": ("assign", "high"),
    "author": ("author", "high"),
    "approval_requested": ("approve", "high"),
    "security_alert": ("security", "high"),
    "comment": ("comment", "normal"),
    "state_change": ("update", "normal"),
    "ci_activity": ("CI", "normal"),
    "manual": ("manual", "normal"),
    "invitation": ("invite", "normal"),
    "push": ("push", "normal"),
    "subscribed": ("watch", "low"),
    "your_activity": ("you", "low"),
    "security_advisory_credit": ("credit", "low"),
    "member_feature_requested": ("feature", "low"),
}

# subject.type -> repo-relative fallback subpage when the api URL is null/non-/repos
_NOTIF_FALLBACK = {
    "PullRequest": "/pulls",
    "Issue": "/issues",
    "Discussion": "/discussions",
    "Release": "/releases",
    "CheckSuite": "/actions",
    "WorkflowRun": "/actions",
    "Commit": "/commits",
    "RepositoryVulnerabilityAlert": "/security/dependabot",
    "SecurityAdvisory": "/security/advisories",
    "RepositoryDependabotAlertsThread": "/security/dependabot",
}

_NOTIF_API_PREFIX = "https://api.github.com/repos/"


def glyph_for(subject_type):
    """Type glyph for a notification subject. Unknown types -> ◉."""
    return _NOTIF_GLYPHS.get(subject_type, _NOTIF_DEFAULT_GLYPH)


def reason_label(reason):
    """Short (<=8 char) label for a notification reason. Unknown -> the reason
    with underscores spaced, truncated to 8 chars."""
    info = _NOTIF_REASONS.get(reason)
    if info:
        return info[0]
    return (reason or "").replace("_", " ")[:8]


def urgency_for(reason):
    """Urgency tier ('high'/'normal'/'low') for a reason. Unknown -> 'low'."""
    info = _NOTIF_REASONS.get(reason)
    return info[1] if info else "low"


def notification_url(subject_type, subject_url, repo_full):
    """Map a notification's (possibly null) api.github.com subject URL to a
    browser github.com URL. ALWAYS returns an https://github.com/... literal so
    is_web_url is always True; PR/Issue get exact deep links, exotic/null cases
    fall back to a safe repo subpage (never a dead api URL, never a crash)."""
    if not repo_full:
        return "https://github.com/notifications"
    repo_base = "https://github.com/" + repo_full
    if subject_url and subject_url.startswith(_NOTIF_API_PREFIX):
        tail = subject_url[len(_NOTIF_API_PREFIX):]      # "owner/name/pulls/34"
        if subject_type == "PullRequest":
            tail = tail.replace("/pulls/", "/pull/", 1)
        elif subject_type == "Commit":
            tail = tail.replace("/commits/", "/commit/", 1)
        elif subject_type == "SecurityAdvisory":
            tail = tail.replace("/security-advisories/", "/security/advisories/", 1)
        elif subject_type == "CheckSuite":
            return repo_base + "/actions"                # no web page for a suite id
        return "https://github.com/" + tail
    return repo_base + _NOTIF_FALLBACK.get(subject_type, "")


_VALID_TYPES = ("rss", "json", "text", "github", "notifications", "search", "stocks", "weather")
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _coerce_int(value, default, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    # Guard against non-finite floats (NaN, Inf) which int() cannot convert
    if isinstance(value, float) and not math.isfinite(value):
        return default
    return max(lo, min(hi, int(value)))


def _title_from_url(url):
    try:
        return urllib.parse.urlparse(url).netloc or "feed"
    except ValueError:
        return "feed"


def normalize_feed(raw):
    """Validate/coerce one feed dict from config. Never raises. Returns a dict
    with valid/error plus the type-specific keys; invalid feeds keep a title so
    the HUD can still render an error tile."""
    if not isinstance(raw, dict):
        return {"type": "?", "title": "feed", "items": 3, "interval": 600,
                "valid": False, "error": "not an object"}
    ftype = raw.get("type")
    title = raw.get("title")
    title = title.strip() if isinstance(title, str) and title.strip() else None
    out = {"type": ftype, "title": title, "valid": True, "error": None}

    if ftype not in _VALID_TYPES:
        out.update(valid=False, error="unknown type %r" % (ftype,),
                   title=title or "feed", items=3, interval=600)
        return out

    floor = 120 if ftype == "github" else 300
    out["interval"] = _coerce_int(raw.get("interval"), floor, floor, 86400)

    if is_news_type(ftype):
        out["tab"] = coerce_tab(raw.get("tab"))

    if ftype in ("rss", "json", "text"):
        out["items"] = _coerce_int(raw.get("items"), 3, 1, 10)
        url = raw.get("url")
        if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
            out.update(valid=False, error="missing/invalid url", title=title or "feed")
            return out
        out["url"] = url
        out["title"] = title or _title_from_url(url)
        if ftype == "json":
            path = raw.get("path")
            fields = raw.get("fields")
            if not isinstance(path, str) or not path:
                out.update(valid=False, error="json feed needs 'path'")
                return out
            if not isinstance(fields, dict) or not isinstance(fields.get("text"), str):
                out.update(valid=False, error="json feed needs fields.text")
                return out
            out["path"] = path
            out["fields"] = {"text": fields.get("text"),
                             "url": fields.get("url") if isinstance(fields.get("url"), str) else None}
        elif ftype == "text":
            rgx = raw.get("regex")
            out["regex"] = rgx if isinstance(rgx, str) and rgx else None
        return out

    if ftype == "notifications":
        # default 300 / floor 120 differs from the generic floor=300 line above,
        # so set interval here explicitly. No url/repo required; never raises.
        out["items"] = _coerce_int(raw.get("items"), 5, 1, 10)
        out["interval"] = _coerce_int(raw.get("interval"), 300, 120, 86400)
        out["title"] = title or "Notifications"
        return out

    if ftype == "search":
        # floor 120 / default 300 (the search API allows 30 req/min authenticated),
        # so set interval explicitly here like the notifications branch.
        out["items"] = _coerce_int(raw.get("items"), 5, 1, 10)
        out["interval"] = _coerce_int(raw.get("interval"), 300, 120, 86400)
        query = raw.get("query")
        query = query.strip() if isinstance(query, str) else ""
        if not query:
            out.update(valid=False, error="search feed needs 'query'",
                       title=title or "Search")
            return out
        out["query"] = query
        out["title"] = title or "Search"
        return out

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

    # github
    repo = raw.get("repo")
    if not isinstance(repo, str) or not _REPO_RE.match(repo):
        out.update(valid=False, error="github feed needs repo 'owner/name'",
                   title=title or "github")
        return out
    out["repo"] = repo
    branch = raw.get("branch")
    out["branch"] = branch if isinstance(branch, str) and branch else "main"
    show = raw.get("show")
    show = [s for s in show if s in ("ci", "notifications")] if isinstance(show, list) else []
    if not show:
        show = ["ci", "notifications"] if not isinstance(raw.get("show"), list) else None
    if not show:
        out.update(valid=False, error="github 'show' must include ci or notifications",
                   title=title or "github")
        return out
    out["show"] = show
    out["title"] = title or repo.split("/")[-1]
    return out


def due_feeds(feeds, last_fetch, now, stagger=2.0):
    """Indices of valid feeds whose interval has elapsed. ``now`` and the
    ``last_fetch`` values are seconds since the manager started (monotonic). The
    first fetch of feed i is staggered to ``i * stagger`` seconds so they don't
    all fire on the same tick."""
    due = []
    for i, feed in enumerate(feeds):
        if not feed.get("valid"):
            continue
        last = last_fetch.get(i)
        if last is None:
            if now >= i * stagger:
                due.append(i)
        elif now - last >= feed["interval"]:
            due.append(i)
    return due
