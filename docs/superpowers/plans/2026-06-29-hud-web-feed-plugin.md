# HUD Web-Feed Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the System Monitor HUD with a generic, no-LLM web-feed plugin that fetches URL/RSS/Atom/JSON sources (and GitHub CI/notifications) on an interval and renders compact, clickable tiles.

**Architecture:** A new pure-stdlib `feedkit/` package: pure parsing/scheduling/validation in `model.py`+`parse.py`, a thin network layer in `fetch.py`, a single-background-worker `manager.py` bridging to the Tk main loop via a `queue.Queue`, and a `ttk` settings window. `hud.pyw` stacks feed blocks under the existing CPU/RAM/clock rows, hit-tests clicks to open URLs, and owns the manager.

**Tech Stack:** Python 3.12 stdlib only — `tkinter`/`ttk`, `urllib.request`/`urllib.error`/`urllib.parse`, `ssl`, `xml.etree.ElementTree`, `json`, `re`, `email.utils`, `queue`, `threading`, `webbrowser`, `collections`, `os`, `time`.

## Global Constraints

- **Pure Python 3.12 stdlib only. No pip / third-party packages** (no `certifi`, `defusedxml`, `feedparser`, `requests`).
- **Win32 stays in `winkit/`.** The new networked subsystem lives in a new top-level package `feedkit/` (parallel to `petkit/`).
- **Pure logic takes injected values** — no Tk, no `time.*`, no network inside `model.py`/`parse.py` functions. The worker injects `now` and raw `bytes`.
- **TDD** — write the failing test first, run it, watch it fail for the right reason, then write minimal code.
- **Test runner (verbatim):** `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe` (bare `python` is the broken MS-Store stub, exit 49). Tests use `unittest`. Run one module with `-m unittest tests.<module> -v`.
- **Tk-touching tests** must be guarded with `@unittest.skipUnless(os.name == "nt", "Windows only")` and build a real `tk.Tk()` root (see `tests/test_smoke_pet.py`).
- **`config.json` is gitignored.** **Commit only the steps the plan says to commit**, each with trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- TLS verification is **never** disabled. Only `http`/`https` URLs are ever opened.
- GitHub request headers are mandatory: `User-Agent: Toybox-WebFeed/1.0`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, plus `Authorization: Bearer <token>` when a token exists.

## File Structure

| File | Responsibility |
|------|----------------|
| `config.py` (modify) | Add top-level `"feeds": []` and `"hud"."github_token": ""` to `DEFAULTS`. |
| `feedkit/__init__.py` (create) | Empty package marker. |
| `feedkit/model.py` (create) | PURE: `Item`/`Status` types; `strip_control_chars`, `truncate`, `build_conditional_headers`; GitHub URL/header builders; `normalize_feed`; `due_feeds`. |
| `feedkit/parse.py` (create) | PURE: `parse_rss`, `parse_json`, `parse_text`, `parse_check_runs`, `parse_notifications`, `compose_github_status`. |
| `feedkit/fetch.py` (create) | NETWORK (thin): `FetchResult`, `fetch()`, `_error_word()`. |
| `feedkit/manager.py` (create) | GLUE: `FeedResult`, `FeedManager` (one daemon worker + queue + per-type fetch/parse orchestration). |
| `feedkit/settings.py` (create) | GUI: `FeedSettingsWindow` (ttk.Notebook), modeled on `petkit/settings.py`. |
| `hud.pyw` (modify) | Build/own the manager; render feed blocks; drain loop; click-to-open; menu items. |
| `tests/test_config.py` (modify) | Defaults + roundtrip for `feeds`/`github_token`. |
| `tests/test_feed_model.py` (create) | `model.py` unit tests. |
| `tests/test_feed_parse.py` (create) | `parse.py` unit tests with captured fixtures. |
| `tests/test_feed_fetch.py` (create) | `fetch.py` tests via a localhost `http.server` + pure `_error_word`. |
| `tests/test_feed_manager.py` (create) | `FeedManager` orchestration with injected `fetch_fn` (no real thread/network). |
| `tests/test_smoke_hud.py` (existing) | Must still pass (offline-safe with `feeds: []`). |

---

### Task 1: config — add `feeds` and `github_token` defaults

**Files:**
- Modify: `config.py:8-20` (the `DEFAULTS` dict)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `config.DEFAULTS["feeds"] == []` (top-level list) and `config.DEFAULTS["hud"]["github_token"] == ""`. `config.load` preserves a provided `feeds` list and coerces a non-string `github_token` back to `""`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (after `test_clipboard_layout_non_string_falls_back`, before `if __name__`):

```python
    def test_feeds_default_is_empty_list(self):
        self.assertEqual(config.defaults()["feeds"], [])

    def test_github_token_default_is_empty_string(self):
        self.assertEqual(config.defaults()["hud"]["github_token"], "")

    def test_feeds_list_roundtrip(self):
        cfg = config.defaults()
        cfg["feeds"] = [{"type": "rss", "url": "https://x/y", "title": "X"}]
        config.save(self.path, cfg)
        self.assertEqual(config.load(self.path)["feeds"],
                         [{"type": "rss", "url": "https://x/y", "title": "X"}])

    def test_feeds_non_list_falls_back_to_empty(self):
        self._write({"feeds": "nope"})
        self.assertEqual(config.load(self.path)["feeds"], [])

    def test_github_token_non_string_falls_back(self):
        self._write({"hud": {"github_token": 123}})
        self.assertEqual(config.load(self.path)["hud"]["github_token"], "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_config -v`
Expected: the 5 new tests FAIL (KeyError `'feeds'` / `'github_token'`).

- [ ] **Step 3: Add the defaults**

In `config.py`, change the `DEFAULTS` dict so the `hud` section gains `github_token` and a top-level `feeds` key is added:

```python
DEFAULTS = {
    "hud": {"x": 40, "y": 40, "alpha": 0.85, "locked": False, "github_token": ""},
    "clipboard": {"max_items": 30, "hotkey": ["ctrl", "shift", "V"],
                  "x": None, "y": None, "capture": True, "layout": "columns"},
    "pet": {"x": None, "y": None, "sensitivity": 1.6, "floor": 0.02,
            "smoothing": 0.4, "idle_fps": 8, "active_fps": 30, "zoom": 4,
            "petting": True, "catnap": True, "greeter": True,
            "nap_after_s": 120, "away_after_s": 300,
            "focus_min": 25, "break_min": 5, "reminders": True,
            "nudges": True, "nudge_min": 50,
            "pin": True, "carry": True},
    "startup": {"hud": False, "clipboard": False, "pet": False},
    "feeds": [],
}
```

(`_coerce` already passes a `list` default through when the loaded value is a list, and falls back to `[]` otherwise; a `str` default coerces non-strings back to `""`. No change to `config.py` logic is needed.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_config -v`
Expected: all tests PASS (output pristine).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "$(printf 'Feeds: add config defaults (feeds list + hud.github_token)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 2: feedkit/model — data types, text & header helpers, GitHub URL/header builders

**Files:**
- Create: `feedkit/__init__.py` (empty)
- Create: `feedkit/model.py`
- Test: `tests/test_feed_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces (all pure):
  - `Item = namedtuple("Item", ["text", "url"])` (url may be `None`)
  - `Status = namedtuple("Status", ["text", "state", "url"])` (state ∈ `success`/`failure`/`pending`/`none`)
  - `strip_control_chars(s) -> str`
  - `truncate(s, n) -> str`
  - `build_conditional_headers(etag, last_modified) -> dict`
  - `is_web_url(url) -> bool` (True only for `http://`/`https://`)
  - `github_ci_url(repo, branch) -> str`
  - `github_notifications_url() -> str` (carries `?per_page=50`)
  - `github_headers(token) -> dict`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_feed_model.py`:

```python
import unittest
import feedkit.model as model


class TestTextHelpers(unittest.TestCase):
    def test_strip_control_chars_removes_controls_and_collapses_ws(self):
        self.assertEqual(model.strip_control_chars("a\x00b\tc\n  d"), "ab c d")

    def test_strip_control_chars_none_and_empty(self):
        self.assertEqual(model.strip_control_chars(None), "")
        self.assertEqual(model.strip_control_chars(""), "")

    def test_truncate_short_unchanged(self):
        self.assertEqual(model.truncate("hello", 10), "hello")

    def test_truncate_long_adds_ellipsis(self):
        self.assertEqual(model.truncate("hello world", 8), "hello w…")

    def test_truncate_tiny_budget(self):
        self.assertEqual(model.truncate("hello", 1), "…")


class TestConditionalHeaders(unittest.TestCase):
    def test_both_present(self):
        self.assertEqual(
            model.build_conditional_headers('W/"abc"', "Mon, 01 Jan 2026 00:00:00 GMT"),
            {"If-None-Match": 'W/"abc"', "If-Modified-Since": "Mon, 01 Jan 2026 00:00:00 GMT"})

    def test_none_present(self):
        self.assertEqual(model.build_conditional_headers(None, None), {})

    def test_only_etag(self):
        self.assertEqual(model.build_conditional_headers('"x"', None), {"If-None-Match": '"x"'})


class TestGithubBuilders(unittest.TestCase):
    def test_ci_url_plain_branch(self):
        self.assertEqual(
            model.github_ci_url("kangofthecastle/Toybox", "main"),
            "https://api.github.com/repos/kangofthecastle/Toybox/commits/main/check-runs?per_page=100")

    def test_ci_url_encodes_slash_in_branch(self):
        self.assertEqual(
            model.github_ci_url("o/r", "feature/x"),
            "https://api.github.com/repos/o/r/commits/feature%2Fx/check-runs?per_page=100")

    def test_notifications_url_has_per_page(self):
        self.assertEqual(model.github_notifications_url(),
                         "https://api.github.com/notifications?per_page=50")

    def test_headers_without_token_have_no_authorization(self):
        h = model.github_headers("")
        self.assertEqual(h["User-Agent"], "Toybox-WebFeed/1.0")
        self.assertEqual(h["Accept"], "application/vnd.github+json")
        self.assertEqual(h["X-GitHub-Api-Version"], "2022-11-28")
        self.assertNotIn("Authorization", h)

    def test_headers_with_token_have_bearer(self):
        h = model.github_headers("ghp_secret")
        self.assertEqual(h["Authorization"], "Bearer ghp_secret")


class TestIsWebUrl(unittest.TestCase):
    def test_http_and_https_allowed(self):
        self.assertTrue(model.is_web_url("http://x/y"))
        self.assertTrue(model.is_web_url("https://x/y"))
        self.assertTrue(model.is_web_url("HTTPS://X/Y"))

    def test_other_schemes_and_junk_rejected(self):
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,x",
                    "ftp://x", "", None, 123):
            self.assertFalse(model.is_web_url(bad), bad)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'feedkit'`.

- [ ] **Step 3: Create the package and the helpers**

Create `feedkit/__init__.py` (empty file).

Create `feedkit/model.py`:

```python
"""Pure feed helpers: data types, text sanitizing, conditional-request headers,
and GitHub URL/header builders. No network, no Tk, no clock -- the worker injects
``now`` and raw bytes. Everything here is deterministic and unit-testable."""
from collections import namedtuple
import re
import urllib.parse

Item = namedtuple("Item", ["text", "url"])            # url may be None
Status = namedtuple("Status", ["text", "state", "url"])  # state: success/failure/pending/none

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/__init__.py feedkit/model.py tests/test_feed_model.py
git commit -m "$(printf 'Feeds: feedkit.model types + text/header/github-url helpers\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 3: feedkit/model — `normalize_feed` + `due_feeds`

**Files:**
- Modify: `feedkit/model.py` (append)
- Test: `tests/test_feed_model.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces (pure):
  - `normalize_feed(raw: dict) -> dict` — never raises; always returns a dict carrying `valid: bool`, `error: str|None`, `type`, `title`, and (when valid) the type-specific keys. Invalid feeds keep a usable `title` so the HUD can render an error tile.
  - `due_feeds(feeds, last_fetch, now, stagger=2.0) -> list[int]` — indices of *valid* feeds due to fetch. `now` and `last_fetch[i]` are **seconds since the manager started** (monotonic-relative). First fetch is staggered by `i * stagger` seconds.

Normalized dict shape per valid type:
- `rss`: `{type,title,items,interval,url,valid,error}`
- `json`: `+ path, fields={"text":..,"url":..}`
- `text`: `+ url, regex (str|None)`
- `github`: `{type,title,interval,repo,branch,show,valid,error}` (no `items`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feed_model.py` (before `if __name__`):

```python
class TestNormalizeFeed(unittest.TestCase):
    def test_rss_minimal_fills_defaults(self):
        f = model.normalize_feed({"type": "rss", "url": "https://news.ycombinator.com/rss"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["type"], "rss")
        self.assertEqual(f["items"], 3)
        self.assertEqual(f["interval"], 300)            # floor for non-github
        self.assertEqual(f["title"], "news.ycombinator.com")  # derived from host

    def test_items_clamped_and_interval_floored(self):
        f = model.normalize_feed({"type": "rss", "url": "https://x/y", "items": 99, "interval": 5})
        self.assertEqual(f["items"], 10)                # clamped 1..10
        self.assertEqual(f["interval"], 300)            # floored

    def test_unknown_type_invalid_but_titled(self):
        f = model.normalize_feed({"type": "weather", "title": "Sky"})
        self.assertFalse(f["valid"])
        self.assertIn("unknown type", f["error"])
        self.assertEqual(f["title"], "Sky")

    def test_rss_missing_url_invalid(self):
        f = model.normalize_feed({"type": "rss"})
        self.assertFalse(f["valid"])
        self.assertIn("url", f["error"])

    def test_rss_non_http_scheme_invalid(self):
        f = model.normalize_feed({"type": "rss", "url": "file:///etc/passwd"})
        self.assertFalse(f["valid"])

    def test_json_requires_path_and_fields_text(self):
        self.assertFalse(model.normalize_feed(
            {"type": "json", "url": "https://x", "fields": {"text": "t"}})["valid"])  # no path
        self.assertFalse(model.normalize_feed(
            {"type": "json", "url": "https://x", "path": "a", "fields": {"url": "u"}})["valid"])  # no text
        ok = model.normalize_feed(
            {"type": "json", "url": "https://x", "path": "a.b", "fields": {"text": "t", "url": "u"}})
        self.assertTrue(ok["valid"])
        self.assertEqual(ok["path"], "a.b")
        self.assertEqual(ok["fields"], {"text": "t", "url": "u"})

    def test_text_regex_optional(self):
        f = model.normalize_feed({"type": "text", "url": "https://x"})
        self.assertTrue(f["valid"])
        self.assertIsNone(f["regex"])
        g = model.normalize_feed({"type": "text", "url": "https://x", "regex": "(\\d+)"})
        self.assertEqual(g["regex"], "(\\d+)")

    def test_github_minimal(self):
        f = model.normalize_feed({"type": "github", "repo": "kangofthecastle/Toybox"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["branch"], "main")
        self.assertEqual(f["show"], ["ci", "notifications"])
        self.assertEqual(f["interval"], 120)            # github floor
        self.assertEqual(f["title"], "Toybox")

    def test_github_bad_repo_invalid(self):
        self.assertFalse(model.normalize_feed({"type": "github", "repo": "no-slash"})["valid"])

    def test_github_show_filtered(self):
        f = model.normalize_feed({"type": "github", "repo": "o/r", "show": ["ci", "bogus"]})
        self.assertEqual(f["show"], ["ci"])

    def test_non_dict_input(self):
        self.assertFalse(model.normalize_feed("nope")["valid"])


class TestDueFeeds(unittest.TestCase):
    def _valid(self, interval):
        return {"valid": True, "interval": interval}

    def test_first_pass_staggered(self):
        feeds = [self._valid(300), self._valid(300), self._valid(300)]
        # at now=1s only feed 0 (stagger 0) is due; feed 1 wants >=2s, feed 2 >=4s.
        self.assertEqual(model.due_feeds(feeds, {}, 1.0, stagger=2.0), [0])
        self.assertEqual(model.due_feeds(feeds, {}, 5.0, stagger=2.0), [0, 1, 2])

    def test_interval_gating(self):
        feeds = [self._valid(300)]
        self.assertEqual(model.due_feeds(feeds, {0: 100.0}, 350.0), [])   # 250s < 300
        self.assertEqual(model.due_feeds(feeds, {0: 100.0}, 400.0), [0])  # 300s >= 300

    def test_invalid_feeds_skipped(self):
        feeds = [{"valid": False, "error": "x"}, self._valid(300)]
        self.assertEqual(model.due_feeds(feeds, {}, 10.0), [1])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model.TestNormalizeFeed tests.test_feed_model.TestDueFeeds -v`
Expected: FAIL with `AttributeError: module 'feedkit.model' has no attribute 'normalize_feed'`.

- [ ] **Step 3: Implement `normalize_feed` and `due_feeds`**

Append to `feedkit/model.py`:

```python
_VALID_TYPES = ("rss", "json", "text", "github")
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _coerce_int(value, default, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: all PASS (the whole module, including Task 2's tests).

- [ ] **Step 5: Commit**

```bash
git add feedkit/model.py tests/test_feed_model.py
git commit -m "$(printf 'Feeds: feedkit.model normalize_feed + due_feeds scheduling\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 4: feedkit/parse — `parse_rss` (RSS 2.0 + Atom 1.0, DOCTYPE guard)

**Files:**
- Create: `feedkit/parse.py`
- Test: `tests/test_feed_parse.py`

**Interfaces:**
- Consumes: `feedkit.model.Item`, `strip_control_chars`, `truncate`.
- Produces: `parse_rss(body: bytes, items: int) -> list[Item]`. Detects root (`rss`/`RDF` → RSS, `feed` → Atom); RSS link is element **text**, Atom link is the `rel="alternate"` `<link>` **href** attribute; matches children by local-name so foreign namespaces don't break extraction. Raises `ValueError` if the payload contains a `DOCTYPE`/`ENTITY` declaration (entity-expansion guard).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_feed_parse.py`:

```python
import unittest
import feedkit.parse as parse


RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>HN</title><link>https://news.ycombinator.com/</link>
  <item><title>First story</title><link>https://example.com/a</link>
    <pubDate>Mon, 29 Jun 2026 01:44:40 +0000</pubDate></item>
  <item><title>Second story</title><link>https://example.com/b</link></item>
  <item><title>Third</title><link>https://example.com/c</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <title>repo releases</title>
  <entry>
    <title>v7.1</title>
    <updated>2026-06-14T14:58:38Z</updated>
    <link rel="alternate" type="text/html" href="https://github.com/o/r/releases/tag/v7.1"/>
    <media:thumbnail url="x"/>
  </entry>
  <entry>
    <title>v7.0</title>
    <link href="https://github.com/o/r/releases/tag/v7.0"/>
  </entry>
</feed>"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns="http://purl.org/rss/1.0/"
         xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <channel rdf:about="https://ex/"><title>Old feed</title>
    <items><rdf:Seq><rdf:li rdf:resource="https://example.com/r"/></rdf:Seq></items></channel>
  <item rdf:about="https://example.com/r">
    <title>RDF item</title><link>https://example.com/r</link></item>
</rdf:RDF>"""

EVIL = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [ <!ENTITY lol "lol"> ]>
<rss version="2.0"><channel><item><title>&lol;</title></item></channel></rss>"""


class TestParseRss(unittest.TestCase):
    def test_rss_titles_and_links(self):
        items = parse.parse_rss(RSS, 3)
        self.assertEqual([i.text for i in items], ["First story", "Second story", "Third"])
        self.assertEqual(items[0].url, "https://example.com/a")

    def test_rss_respects_item_cap(self):
        self.assertEqual(len(parse.parse_rss(RSS, 2)), 2)

    def test_atom_title_and_href_attribute(self):
        items = parse.parse_rss(ATOM, 5)
        self.assertEqual([i.text for i in items], ["v7.1", "v7.0"])
        self.assertEqual(items[0].url, "https://github.com/o/r/releases/tag/v7.1")
        self.assertEqual(items[1].url, "https://github.com/o/r/releases/tag/v7.0")

    def test_rdf_rss_1_0_items(self):
        items = parse.parse_rss(RDF, 5)
        self.assertEqual([i.text for i in items], ["RDF item"])
        self.assertEqual(items[0].url, "https://example.com/r")

    def test_doctype_rejected(self):
        with self.assertRaises(ValueError):
            parse.parse_rss(EVIL, 3)

    def test_malformed_xml_raises(self):
        with self.assertRaises(Exception):
            parse.parse_rss(b"<rss><channel", 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'feedkit.parse'`.

- [ ] **Step 3: Create `feedkit/parse.py` with `parse_rss`**

```python
"""Pure feed/response parsers: RSS/Atom XML, JSON, plain text, and GitHub
check-runs/notifications. No network, no Tk. Output text is sanitized and
truncated so hostile remote content can't corrupt the canvas or blow out the
layout. parse_rss refuses DOCTYPE/ENTITY payloads (xml.etree is vulnerable to
entity-expansion and there is no stdlib defusedxml)."""
import json
import re
import xml.etree.ElementTree as ET

from feedkit.model import Item, Status, strip_control_chars, truncate

_ATOM = "{http://www.w3.org/2005/Atom}"
_DOCTYPE = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)
_LINE_MAX = 64


def _local(tag):
    """Local element name with any '{namespace}' prefix stripped."""
    return tag.rsplit("}", 1)[-1]


def _clean(text, n=_LINE_MAX):
    return truncate(strip_control_chars(text or ""), n)


def _child_text(parent, local):
    for child in parent:
        if _local(child.tag) == local:
            return child.text
    return None


def _atom_link(entry):
    """The entry's alternate HTML link href (fall back to the first href present)."""
    fallback = None
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = child.get("href")
        if not href:
            continue
        if child.get("rel") in (None, "alternate"):
            return href.strip()
        if fallback is None:
            fallback = href.strip()
    return fallback


def parse_rss(body, items):
    if _DOCTYPE.search(body or b""):
        raise ValueError("unsafe XML (DOCTYPE/ENTITY rejected)")
    root = ET.fromstring(body)
    tag = _local(root.tag)
    out = []
    if tag in ("rss", "RDF"):
        # Match items by local-name anywhere under the root: RSS 2.0 nests <item>
        # inside <channel>, but RSS 1.0/RDF makes <item> a direct child of <rdf:RDF>
        # (and namespaces every tag), so a namespace-exact channel/item lookup
        # silently returns nothing. iter() + local-name handles both.
        for node in root.iter():
            if _local(node.tag) != "item":
                continue
            url = _child_text(node, "link")
            out.append(Item(_clean(_child_text(node, "title")), url.strip() if url else None))
            if len(out) >= items:
                break
    elif tag == "feed":
        for entry in root.findall(_ATOM + "entry"):
            out.append(Item(_clean(_child_text(entry, "title")), _atom_link(entry)))
            if len(out) >= items:
                break
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/parse.py tests/test_feed_parse.py
git commit -m "$(printf 'Feeds: feedkit.parse parse_rss (RSS+Atom, DOCTYPE guard)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 5: feedkit/parse — `parse_json` + `parse_text`

**Files:**
- Modify: `feedkit/parse.py` (append)
- Test: `tests/test_feed_parse.py` (append)

**Interfaces:**
- Consumes: same module helpers.
- Produces:
  - `parse_json(body: bytes, path: str, fields: dict, items: int) -> list[Item]` — `json.loads`, walk the dot-path (numeric segments index lists) to a list, map `fields["text"]`/`fields["url"]` per element. Missing keys → blank/`None`, never raises on shape.
  - `parse_text(body: bytes, content_type: str|None, regex: str|None, items: int, url=None) -> list[Item]` — decode by charset (fallback utf-8/replace); `regex` → first capture group (or whole match) as one Item; else first `items` non-empty lines.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feed_parse.py` (before `if __name__`):

```python
class TestParseJson(unittest.TestCase):
    DOC = b'{"data": {"items": [{"title": "A", "html_url": "https://x/a"}, ' \
          b'{"title": "B", "html_url": "https://x/b"}, {"title": "C"}]}}'

    def test_walks_path_and_maps_fields(self):
        items = parse.parse_json(self.DOC, "data.items",
                                 {"text": "title", "url": "html_url"}, 2)
        self.assertEqual([i.text for i in items], ["A", "B"])
        self.assertEqual(items[0].url, "https://x/a")

    def test_missing_url_field_is_none(self):
        items = parse.parse_json(self.DOC, "data.items",
                                 {"text": "title", "url": "html_url"}, 3)
        self.assertIsNone(items[2].url)        # third item has no html_url

    def test_path_to_nonlist_returns_empty(self):
        self.assertEqual(parse.parse_json(self.DOC, "data", {"text": "x"}, 3), [])

    def test_numeric_path_segment_indexes_list(self):
        doc = b'{"rows": [{"v": "first"}, {"v": "second"}]}'
        items = parse.parse_json(doc, "rows.1", {"text": "v"}, 3)
        self.assertEqual(items, [])            # rows.1 is a dict, not a list -> empty


class TestParseText(unittest.TestCase):
    def test_regex_first_group(self):
        items = parse.parse_text(b"status: OK\nfoo", "text/plain", r"status:\s*(\w+)", 1, url="https://s")
        self.assertEqual(items[0].text, "OK")
        self.assertEqual(items[0].url, "https://s")

    def test_no_regex_returns_first_lines(self):
        items = parse.parse_text(b"one\n\n two \nthree\nfour", "text/plain", None, 2)
        self.assertEqual([i.text for i in items], ["one", "two"])

    def test_regex_no_match(self):
        items = parse.parse_text(b"nothing here", None, r"(\d+)", 1)
        self.assertEqual(items[0].text, "(no match)")

    def test_decode_respects_charset(self):
        body = "café".encode("latin-1")
        items = parse.parse_text(body, "text/plain; charset=latin-1", None, 1)
        self.assertEqual(items[0].text, "café")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse.TestParseJson tests.test_feed_parse.TestParseText -v`
Expected: FAIL with `AttributeError: module 'feedkit.parse' has no attribute 'parse_json'`.

- [ ] **Step 3: Implement `parse_json` and `parse_text`**

Append to `feedkit/parse.py`:

```python
def _walk(data, path):
    node = data
    for seg in path.split("."):
        if isinstance(node, list) and seg.isdigit():
            idx = int(seg)
            node = node[idx] if 0 <= idx < len(node) else None
        elif isinstance(node, dict):
            node = node.get(seg)
        else:
            return None
        if node is None:
            return None
    return node


def parse_json(body, path, fields, items):
    node = _walk(json.loads(body), path)
    if not isinstance(node, list):
        return []
    text_key = fields.get("text")
    url_key = fields.get("url")
    out = []
    for element in node:
        if not isinstance(element, dict):
            continue
        text = element.get(text_key) if text_key else None
        url = element.get(url_key) if url_key else None
        out.append(Item(_clean("" if text is None else str(text)),
                        url if isinstance(url, str) and url else None))
        if len(out) >= items:
            break
    return out


def _decode(body, content_type):
    charset = "utf-8"
    if content_type and "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=", 1)[1].split(";")[0].strip().strip("\"'") or "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def parse_text(body, content_type, regex, items, url=None):
    text = _decode(body, content_type)
    if regex:
        match = re.search(regex, text)
        if not match:
            return [Item(_clean("(no match)"), url)]
        value = match.group(1) if match.groups() else match.group(0)
        return [Item(_clean(value), url)]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [Item(_clean(ln), url) for ln in lines[:items]]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/parse.py tests/test_feed_parse.py
git commit -m "$(printf 'Feeds: feedkit.parse parse_json + parse_text\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 6: feedkit/parse — GitHub `parse_check_runs` + `parse_notifications` + `compose_github_status`

**Files:**
- Modify: `feedkit/parse.py` (append)
- Test: `tests/test_feed_parse.py` (append)

**Interfaces:**
- Consumes: `feedkit.model.Status`.
- Produces:
  - `parse_check_runs(body: bytes) -> str` → `none`/`pending`/`success`/`failure`. Empty list → `none`; any `bad` conclusion → `failure` (dominates); else any run not `completed` → `pending`; else `success` (every conclusion ∈ {success, neutral, skipped}).
  - `parse_notifications(body: bytes) -> int` → count of unread threads (array length; defensively counts `unread != false`).
  - `compose_github_status(repo, branch, ci_state, notif_count, ci_shown=True) -> Status` → tile header text (`name ● word` + `🔔 N`/`50+`), `state=ci_state`; `url=.../actions` when `ci_shown`, else `.../notifications`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feed_parse.py` (before `if __name__`):

```python
class TestParseCheckRuns(unittest.TestCase):
    def _body(self, runs):
        import json as _j
        return _j.dumps({"total_count": len(runs), "check_runs": runs}).encode()

    def test_empty_is_none(self):
        self.assertEqual(parse.parse_check_runs(self._body([])), "none")

    def test_all_success(self):
        runs = [{"status": "completed", "conclusion": "success"},
                {"status": "completed", "conclusion": "skipped"}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "success")

    def test_in_progress_is_pending(self):
        runs = [{"status": "completed", "conclusion": "success"},
                {"status": "in_progress", "conclusion": None}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "pending")

    def test_incomplete_dominates_even_with_a_failure(self):
        # Spec rule: any not-completed run -> pending, regardless of an already
        # failed sibling (a re-run in progress shows amber, not red).
        runs = [{"status": "in_progress", "conclusion": None},
                {"status": "completed", "conclusion": "failure"}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "pending")

    def test_all_completed_with_a_failure_is_failure(self):
        runs = [{"status": "completed", "conclusion": "success"},
                {"status": "completed", "conclusion": "failure"}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "failure")

    def test_timed_out_is_failure(self):
        runs = [{"status": "completed", "conclusion": "timed_out"}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "failure")


class TestParseNotifications(unittest.TestCase):
    def test_counts_array_length(self):
        body = b'[{"id":"1","unread":true},{"id":"2","unread":true}]'
        self.assertEqual(parse.parse_notifications(body), 2)

    def test_filters_read(self):
        body = b'[{"id":"1","unread":true},{"id":"2","unread":false}]'
        self.assertEqual(parse.parse_notifications(body), 1)

    def test_non_list_is_zero(self):
        self.assertEqual(parse.parse_notifications(b'{"message":"Bad creds"}'), 0)


class TestComposeGithubStatus(unittest.TestCase):
    def test_ci_and_notifications(self):
        s = parse.compose_github_status("kangofthecastle/Toybox", "main", "success", 3)
        self.assertEqual(s.state, "success")
        self.assertIn("Toybox", s.text)
        self.assertIn("passing", s.text)
        self.assertIn("3", s.text)
        self.assertEqual(s.url, "https://github.com/kangofthecastle/Toybox/actions")

    def test_no_notifications_omits_bell(self):
        s = parse.compose_github_status("o/r", "main", "failure", None)
        self.assertIn("failing", s.text)
        self.assertNotIn("\U0001f514", s.text)

    def test_fifty_plus(self):
        s = parse.compose_github_status("o/r", "main", "none", 50)
        self.assertIn("50+", s.text)

    def test_notifications_only_points_at_notifications(self):
        s = parse.compose_github_status("o/r", "main", "none", 4, ci_shown=False)
        self.assertEqual(s.url, "https://github.com/notifications")
        self.assertNotIn("●", s.text)        # no CI glyph when CI isn't shown
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse.TestParseCheckRuns tests.test_feed_parse.TestParseNotifications tests.test_feed_parse.TestComposeGithubStatus -v`
Expected: FAIL with `AttributeError: ... has no attribute 'parse_check_runs'`.

- [ ] **Step 3: Implement the GitHub parsers**

Append to `feedkit/parse.py`:

```python
_GOOD_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
_CI_WORD = {"success": "passing", "failure": "failing", "pending": "pending", "none": "—"}


def parse_check_runs(body):
    """Reduce a check-runs response to one of none/pending/success/failure, per
    the spec's order: empty -> none; ANY run not completed -> pending (a re-run
    in progress shows amber even if a sibling already failed); all completed ->
    success iff every conclusion is success/neutral/skipped, else failure."""
    data = json.loads(body)
    runs = data.get("check_runs") if isinstance(data, dict) else None
    if not runs:
        return "none"
    if any(run.get("status") != "completed" for run in runs):
        return "pending"
    if all(run.get("conclusion") in _GOOD_CONCLUSIONS for run in runs):
        return "success"
    return "failure"


def parse_notifications(body):
    """Count unread notification threads (the endpoint returns unread-only by
    default; we still filter unread != false defensively)."""
    data = json.loads(body)
    if not isinstance(data, list):
        return 0
    return sum(1 for n in data if isinstance(n, dict) and n.get("unread", True))


def compose_github_status(repo, branch, ci_state, notif_count, ci_shown=True):
    """Build the github tile's header Status. When CI is shown the text leads with
    the colored ● + CI word and the click target is the repo's Actions page; a
    notifications-only tile shows just the name and points at /notifications."""
    name = repo.split("/")[-1]
    if ci_shown:
        text = "%s ● %s" % (name, _CI_WORD.get(ci_state, "—"))
        url = "https://github.com/%s/actions" % repo
    else:
        text = name
        url = "https://github.com/notifications"
    if notif_count is not None:
        text += "  \U0001f514 %s" % ("50+" if notif_count >= 50 else notif_count)
    return Status(_clean(text, 40), ci_state, url)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/parse.py tests/test_feed_parse.py
git commit -m "$(printf 'Feeds: feedkit.parse GitHub check-runs/notifications/status\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 7: feedkit/fetch — conditional HTTP GET with 304/timeout/size-cap/error taxonomy

**Files:**
- Create: `feedkit/fetch.py`
- Test: `tests/test_feed_fetch.py`

**Interfaces:**
- Consumes: `feedkit.model.build_conditional_headers`.
- Produces:
  - `FetchResult = namedtuple("FetchResult", ["status","body","content_type","etag","last_modified","error"])`, `status ∈ {"ok","not_modified","error"}`.
  - `fetch(url, headers=None, etag=None, last_modified=None, timeout=12, max_bytes=1_000_000) -> FetchResult`. Sends an explicit `User-Agent` + caller headers + conditional headers; on success returns body (size-capped) + new ETag/Last-Modified; a `304` (raised as `HTTPError`) → `not_modified`; everything else → `error` with a taxonomy word.
  - `_error_word(exc) -> str` (pure helper over an exception instance).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_feed_fetch.py`:

```python
import http.server
import threading
import unittest
import urllib.error

import feedkit.fetch as fetch


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/etag":
            if self.headers.get("If-None-Match") == '"v1"':
                self.send_response(304); self.end_headers(); return
            self.send_response(200)
            self.send_header("ETag", '"v1"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        elif self.path == "/big":
            self.send_response(200); self.end_headers()
            self.wfile.write(b"x" * 5000)
        elif self.path == "/boom":
            self.send_response(403)
            self.send_header("X-RateLimit-Remaining", "0")
            self.end_headers()
        elif self.path == "/boom2":
            self.send_response(403)
            self.send_header("X-RateLimit-Remaining", "57")
            self.end_headers()
        else:
            self.send_response(404); self.end_headers()


class TestFetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.t.join(timeout=1)

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def test_ok_returns_body_and_etag(self):
        r = fetch.fetch(self._url("/etag"))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.body, b'{"ok": true}')
        self.assertEqual(r.etag, '"v1"')
        self.assertIn("application/json", r.content_type)

    def test_conditional_304(self):
        r = fetch.fetch(self._url("/etag"), etag='"v1"')
        self.assertEqual(r.status, "not_modified")
        self.assertIsNone(r.body)

    def test_size_cap(self):
        r = fetch.fetch(self._url("/big"), max_bytes=1000)
        self.assertEqual(r.status, "error")
        self.assertEqual(r.error, "too large")

    def test_http_403_with_zero_quota_is_rate_limited(self):
        r = fetch.fetch(self._url("/boom"))
        self.assertEqual(r.status, "error")
        self.assertEqual(r.error, "rate-limited")

    def test_http_403_with_quota_left_is_bad_token(self):
        r = fetch.fetch(self._url("/boom2"))
        self.assertEqual(r.error, "bad token")

    def test_connection_refused_is_offline(self):
        r = fetch.fetch("http://127.0.0.1:9/never", timeout=1)
        self.assertEqual(r.status, "error")
        self.assertEqual(r.error, "offline")


class TestErrorWord(unittest.TestCase):
    def test_403_rate_limited_when_quota_zero(self):
        e = urllib.error.HTTPError("u", 403, "m", {"x-ratelimit-remaining": "0"}, None)
        self.assertEqual(fetch._error_word(e), "rate-limited")

    def test_403_bad_token_when_quota_remains_or_absent(self):
        e1 = urllib.error.HTTPError("u", 403, "m", {"x-ratelimit-remaining": "57"}, None)
        e2 = urllib.error.HTTPError("u", 403, "m", {}, None)
        self.assertEqual(fetch._error_word(e1), "bad token")
        self.assertEqual(fetch._error_word(e2), "bad token")

    def test_other_http_codes(self):
        mk = lambda code: urllib.error.HTTPError("u", code, "m", {}, None)
        self.assertEqual(fetch._error_word(mk(401)), "bad token")
        self.assertEqual(fetch._error_word(mk(404)), "no access")

    def test_cert_error(self):
        import ssl
        e = urllib.error.URLError(ssl.SSLCertVerificationError("bad cert"))
        self.assertEqual(fetch._error_word(e), "cert error")

    def test_generic_urlerror_offline(self):
        self.assertEqual(fetch._error_word(urllib.error.URLError("down")), "offline")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_fetch -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'feedkit.fetch'`.

- [ ] **Step 3: Create `feedkit/fetch.py`**

```python
"""Thin networked HTTP GET for the feed worker. Conditional requests (ETag /
Last-Modified), a socket timeout, a response size cap, and an error taxonomy that
maps every failure to a short tile word. Verified on Python 3.12 / Windows: the
stdlib default TLS context verifies against the Windows cert store (no certifi),
and a 304 is RAISED as HTTPError(code=304) rather than returned."""
import ssl
import urllib.error
import urllib.request
from collections import namedtuple

from feedkit.model import build_conditional_headers

FetchResult = namedtuple(
    "FetchResult", ["status", "body", "content_type", "etag", "last_modified", "error"])

_DEFAULT_UA = "Toybox-WebFeed/1.0"


def _error_word(exc):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 403:
            # 403 with exhausted quota = rate limit; otherwise a bad/under-scoped
            # token or missing User-Agent (GitHub returns 403 for both).
            try:
                remaining = exc.headers.get("x-ratelimit-remaining")
            except Exception:
                remaining = None
            return "rate-limited" if remaining == "0" else "bad token"
        return {401: "bad token", 404: "no access"}.get(exc.code, "http %d" % exc.code)
    if isinstance(exc, urllib.error.URLError):
        if isinstance(getattr(exc, "reason", None), ssl.SSLError):
            return "cert error"
        return "offline"
    if isinstance(exc, TimeoutError):
        return "offline"
    return "error"


def fetch(url, headers=None, etag=None, last_modified=None, timeout=12, max_bytes=1_000_000):
    request_headers = {"User-Agent": _DEFAULT_UA}
    if headers:
        request_headers.update(headers)
    request_headers.update(build_conditional_headers(etag, last_modified))
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                return FetchResult("error", None, None, None, None, "too large")
            return FetchResult("ok", body, response.headers.get("Content-Type"),
                               response.headers.get("ETag"),
                               response.headers.get("Last-Modified"), None)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return FetchResult("not_modified", None, None, etag, last_modified, None)
        return FetchResult("error", None, None, None, None, _error_word(exc))
    except (urllib.error.URLError, TimeoutError) as exc:
        return FetchResult("error", None, None, None, None, _error_word(exc))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_fetch -v`
Expected: all PASS (the localhost server tests are deterministic and offline).

- [ ] **Step 5: Commit**

```bash
git add feedkit/fetch.py tests/test_feed_fetch.py
git commit -m "$(printf 'Feeds: feedkit.fetch conditional GET with 304/timeout/size-cap\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 8: feedkit/manager — `FeedManager` orchestration (injected fetch, no real network in tests)

**Files:**
- Create: `feedkit/manager.py`
- Test: `tests/test_feed_manager.py`

**Interfaces:**
- Consumes: `feedkit.model` (`normalize_feed`, `due_feeds`, `github_*`), `feedkit.parse` (all parsers), `feedkit.fetch.fetch` + `FetchResult`.
- Produces:
  - `FeedResult = namedtuple("FeedResult", ["state","items","status","error"])`, `state ∈ {"ok","stale","error"}`; `items: list[Item]`; `status: Status|None`.
  - `FeedManager(feeds, token="", fetch_fn=None, poll_interval=1.0)` with:
    - `.feeds` — list of normalized feed dicts (so the HUD can render invalid tiles).
    - `start()` / `stop()` — daemon worker lifecycle.
    - `drain() -> list[(idx, FeedResult)]` — non-blocking queue drain for the Tk thread.
    - `set_feeds(feeds)` / `set_token(token)` — thread-safe swaps.
    - `_run_once(now)` — one scheduling+fetch+parse pass (the unit tests call this directly with an injected `fetch_fn`; no thread, no network).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_feed_manager.py`:

```python
import unittest

import feedkit.fetch as fetch
import feedkit.manager as manager


def _ok(body, etag=None, ct="application/json"):
    return fetch.FetchResult("ok", body, ct, etag, None, None)


def _err(word):
    return fetch.FetchResult("error", None, None, None, None, word)


def _nm():
    return fetch.FetchResult("not_modified", None, None, None, None, None)


RSS = b'<rss version="2.0"><channel><item><title>Hi</title>' \
      b'<link>https://x/a</link></item></channel></rss>'


class TestProcessRss(unittest.TestCase):
    def test_ok_parses_items(self):
        calls = []
        def fake(url, **kw):
            calls.append(url)
            return _ok(RSS, etag='"e1"')
        m = manager.FeedManager([{"type": "rss", "url": "https://x", "items": 3}],
                                fetch_fn=fake)
        m._run_once(0.0)
        updates = m.drain()
        self.assertEqual(len(updates), 1)
        idx, result = updates[0]
        self.assertEqual(idx, 0)
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.items[0].text, "Hi")

    def test_304_keeps_prior_items(self):
        responses = [_ok(RSS, etag='"e1"'), _nm()]
        def fake(url, **kw):
            return responses.pop(0)
        m = manager.FeedManager([{"type": "rss", "url": "https://x"}], fetch_fn=fake)
        m._run_once(0.0)                 # first fetch -> ok, caches items + etag
        m._last.clear()                  # force a second fetch
        m._run_once(1000.0)              # second fetch -> 304
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.items[0].text, "Hi")   # reused from cache

    def test_error_after_success_is_stale(self):
        responses = [_ok(RSS, etag='"e1"'), _err("offline")]
        def fake(url, **kw):
            return responses.pop(0)
        m = manager.FeedManager([{"type": "rss", "url": "https://x"}], fetch_fn=fake)
        m._run_once(0.0)
        m._last.clear()
        m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.error, "offline")
        self.assertEqual(result.items[0].text, "Hi")

    def test_error_first_time_is_error(self):
        m = manager.FeedManager([{"type": "rss", "url": "https://x"}],
                                fetch_fn=lambda url, **kw: _err("offline"))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")
        self.assertEqual(result.items, [])

    def test_bad_data_after_success_is_stale(self):
        # A 200 that returns unparseable bytes (e.g. an HTML error page) must keep
        # the last-good items as 'stale', not wipe the tile.
        responses = [_ok(RSS, etag='"e1"'), _ok(b"<rss><notclosed", etag='"e2"')]
        def fake(url, **kw):
            return responses.pop(0)
        m = manager.FeedManager([{"type": "rss", "url": "https://x"}], fetch_fn=fake)
        m._run_once(0.0)
        m._last.clear()
        m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.items[0].text, "Hi")
        self.assertEqual(result.error, "bad data")


class TestProcessGithub(unittest.TestCase):
    CHECKS = b'{"check_runs":[{"status":"completed","conclusion":"success"}]}'
    NOTIF = b'[{"id":"1","unread":true},{"id":"2","unread":true}]'

    def test_ci_and_notifications_with_token(self):
        def fake(url, **kw):
            if "check-runs" in url:
                return _ok(self.CHECKS)
            return _ok(self.NOTIF)
        m = manager.FeedManager([{"type": "github", "repo": "o/r"}],
                                token="ghp_x", fetch_fn=fake)
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.status.state, "success")
        self.assertIn("2", result.status.text)         # 2 unread

    def test_no_token_skips_notifications(self):
        seen = []
        def fake(url, **kw):
            seen.append(url)
            return _ok(self.CHECKS)
        m = manager.FeedManager([{"type": "github", "repo": "o/r"}],
                                token="", fetch_fn=fake)
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertTrue(all("notifications" not in u for u in seen))
        self.assertEqual(result.status.state, "success")
        self.assertNotIn("\U0001f514", result.status.text)


class TestManagerControl(unittest.TestCase):
    def test_invalid_feed_not_scheduled(self):
        m = manager.FeedManager([{"type": "bogus"}], fetch_fn=lambda url, **kw: _ok(RSS))
        m._run_once(0.0)
        self.assertEqual(m.drain(), [])                 # nothing fetched

    def test_set_feeds_swaps_and_clears_cache(self):
        m = manager.FeedManager([{"type": "rss", "url": "https://a"}],
                                fetch_fn=lambda url, **kw: _ok(RSS))
        m._run_once(0.0)
        m.set_feeds([{"type": "rss", "url": "https://b"}])
        self.assertEqual(m._last, {})
        self.assertEqual(m.feeds[0]["url"], "https://b")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'feedkit.manager'`.

- [ ] **Step 3: Create `feedkit/manager.py`**

```python
"""FeedManager: one daemon worker thread fetches due feeds, parses them, and
pushes (idx, FeedResult) onto a queue the Tk main loop drains. The worker never
touches Tk. Per-feed work is wrapped so one failure can't stop the others. The
fetch function is injectable so the orchestration is unit-tested with no network
and no thread (tests call _run_once directly)."""
import queue
import threading
import time
from collections import namedtuple

import feedkit.fetch as fetch_mod
import feedkit.model as model
import feedkit.parse as parse

FeedResult = namedtuple("FeedResult", ["state", "items", "status", "error"])


class FeedManager:
    def __init__(self, feeds, token="", fetch_fn=None, poll_interval=1.0):
        self.feeds = [model.normalize_feed(f) for f in feeds]
        self.token = token or ""
        self._fetch = fetch_fn or fetch_mod.fetch
        self._poll = poll_interval
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._last = {}      # idx -> elapsed seconds at last fetch
        self._cache = {}     # cache key -> per-source {etag, lm, result/ci/notif}
        self._start = None

    # --- lifecycle ------------------------------------------------------
    def start(self):
        self._start = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="feedworker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)   # deterministic teardown; no lingering worker

    def drain(self):
        out = []
        try:
            while True:
                out.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        return out

    def set_feeds(self, feeds):
        with self._lock:
            self.feeds = [model.normalize_feed(f) for f in feeds]
            self._last.clear()
            self._cache.clear()

    def set_token(self, token):
        with self._lock:
            self.token = token or ""

    # --- worker ---------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            try:
                self._run_once(time.monotonic() - self._start)
            except Exception:
                pass
            self._stop.wait(self._poll)

    def _run_once(self, now):
        # Snapshot shared state under the lock; the blocking fetch runs unlocked so
        # a Settings save (set_feeds/set_token) is never blocked on network I/O.
        with self._lock:
            feeds = list(self.feeds)
            token = self.token
            last = dict(self._last)
        for idx in model.due_feeds(feeds, last, now):
            feed = feeds[idx]
            try:
                result = self._fetch_and_process(idx, feed, token)
            except Exception as exc:
                result = FeedResult("error", [], None, str(exc) or "error")
            with self._lock:
                self._last[idx] = now
            self._queue.put((idx, result))

    def _fetch_and_process(self, idx, feed, token):
        if feed["type"] == "github":
            return self._process_github(idx, feed, token)
        with self._lock:
            cache = self._cache.get(idx, {})
        res = self._fetch(feed["url"], etag=cache.get("etag"),
                          last_modified=cache.get("lm"))
        if res.status == "not_modified":
            return cache.get("result") or FeedResult("ok", [], None, None)
        if res.status == "error":
            prev = cache.get("result")
            return FeedResult("stale" if prev else "error",
                              prev.items if prev else [], None, res.error)
        try:
            items = self._parse_body(feed, res)
        except Exception:
            prev = cache.get("result")    # a 200 with unparseable body keeps last-good
            return FeedResult("stale" if prev else "error",
                              prev.items if prev else [], None, "bad data")
        result = FeedResult("ok", items, None, None)
        with self._lock:
            self._cache[idx] = {"etag": res.etag, "lm": res.last_modified, "result": result}
        return result

    def _parse_body(self, feed, res):
        if feed["type"] == "rss":
            return parse.parse_rss(res.body, feed["items"])
        if feed["type"] == "json":
            return parse.parse_json(res.body, feed["path"], feed["fields"], feed["items"])
        return parse.parse_text(res.body, res.content_type, feed.get("regex"),
                                feed["items"], url=feed["url"])

    def _process_github(self, idx, feed, token):
        repo, branch, show = feed["repo"], feed["branch"], feed["show"]
        headers = model.github_headers(token)
        ci_state, notif, error = "none", None, None
        if "ci" in show:
            key = (idx, "ci")
            with self._lock:
                cache = self._cache.get(key, {})
            res = self._fetch(model.github_ci_url(repo, branch), headers=headers,
                              etag=cache.get("etag"), last_modified=cache.get("lm"))
            if res.status == "ok":
                try:
                    ci_state = parse.parse_check_runs(res.body)
                except Exception:
                    ci_state, error = cache.get("ci", "none"), "bad data"
                else:
                    with self._lock:
                        self._cache[key] = {"etag": res.etag, "lm": res.last_modified, "ci": ci_state}
            elif res.status == "not_modified":
                ci_state = cache.get("ci", "none")
            else:
                error, ci_state = res.error, cache.get("ci", "none")
        # Notifications require a token; with none, skip the call and show CI only.
        if "notifications" in show and token:
            key = (idx, "notif")
            with self._lock:
                cache = self._cache.get(key, {})
            res = self._fetch(model.github_notifications_url(), headers=headers,
                              etag=cache.get("etag"), last_modified=cache.get("lm"))
            if res.status == "ok":
                try:
                    notif = parse.parse_notifications(res.body)
                except Exception:
                    notif, error = cache.get("notif"), error or "bad data"
                else:
                    with self._lock:
                        self._cache[key] = {"etag": res.etag, "lm": res.last_modified, "notif": notif}
            elif res.status == "not_modified":
                notif = cache.get("notif")
            else:
                error = error or res.error
        status = parse.compose_github_status(repo, branch, ci_state, notif, ci_shown=("ci" in show))
        state = "error" if (error and ci_state == "none") else "ok"
        return FeedResult(state, [], status, error)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/manager.py tests/test_feed_manager.py
git commit -m "$(printf 'Feeds: feedkit.manager worker orchestration (queue + per-type)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 9: hud.pyw — render feed blocks, drain loop, window resize, manager wiring

**Files:**
- Modify: `hud.pyw` (constants, `Hud.__init__`, new `_draw_feeds`/`_drain_feeds`/`_resize`/`_feed_tiles`/`_github_token`/`close`, `main`)
- Test: `tests/test_smoke_hud.py` (add a Tk-construction test); `tests/test_smoke_hud.py` smoke must still pass

**Interfaces:**
- Consumes: `feedkit.manager.FeedManager`, `feedkit.model`, `feedkit.parse` (for `Status` typing via results).
- Produces: a `Hud` that builds a `FeedManager`, drains it on a 250 ms loop, and renders feed tiles below the metrics. Per rendered item line it records `(y0, y1, url)` in `self._hit` for Task 10's click handling. `Hud.close()` stops the manager.

This task renders tiles and resizes the window; **clicking is added in Task 10** (so this task's test sets `feed_state` directly and asserts geometry/canvas, with no network).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_smoke_hud.py` (before `if __name__`):

```python
import os
import unittest.mock as mock


class _HudTestBase(unittest.TestCase):
    """Shared base for the in-process Tk Hud tests. setUp stubs the network so the
    worker (started in Hud.__init__) does NO real I/O and is deterministic."""
    def setUp(self):
        import feedkit.fetch as fetchmod
        stub = lambda *a, **k: fetchmod.FetchResult("error", None, None, None, None, "offline")
        patcher = mock.patch.object(fetchmod, "fetch", stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_hud(self, feeds, isolate_cfg=False):
        import tempfile
        import tkinter as tk
        import winkit.window as window
        import config
        import hud as hudmod
        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        cfg = config.defaults()
        cfg["feeds"] = feeds
        root.geometry("%dx%d+100+100" % (hudmod.WIDTH, hudmod.HEIGHT))
        hud = hudmod.Hud(root, cfg)
        if isolate_cfg:                      # never touch the user's real config.json
            hud.CFG_PATH = os.path.join(tempfile.mkdtemp(), "config.json")
        return root, hud


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudFeedRendering(_HudTestBase):
    def test_feeds_grow_window_past_metrics_height(self):
        import hud as hudmod
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud([{"type": "rss", "url": "https://x", "title": "X"}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [Item("Hello headline", "https://example.com/a")], None, None)
            hud._draw_feeds()
            root.update_idletasks()
            height = int(root.geometry().split("x")[1].split("+")[0])
            self.assertGreater(height, hudmod.HEIGHT)      # taller than metrics-only (96)
            self.assertTrue(any(u == "https://example.com/a" for (_, _, u) in hud._hit))
            hud.close()
        finally:
            root.destroy()

    def test_invalid_feed_renders_error_tile(self):
        root, hud = self._make_hud([{"type": "bogus", "title": "Bad"}])
        try:
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("Bad"))
            hud.close()
        finally:
            root.destroy()

    def test_github_tile_is_clickable_and_shows_error(self):
        import feedkit.manager as manager
        from feedkit.model import Status
        root, hud = self._make_hud([{"type": "github", "repo": "o/r", "title": "R"}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [], Status("r ● passing", "success",
                                 "https://github.com/o/r/actions"), "bad token")
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(any(u == "https://github.com/o/r/actions" for (_, _, u) in hud._hit))
            self.assertTrue(hud._feed_has_text("bad token"))   # error surfaced
            hud.close()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: the new feed-rendering tests FAIL (`AttributeError: 'Hud' object has no attribute 'feed_state'`); the existing `TestSmokeHud` still passes.

- [ ] **Step 3: Add feed rendering to `hud.pyw`**

3a. Add imports and layout constants. After the existing `import config` (line 16) add:

```python
import webbrowser
import feedkit.manager as feedmanager
import feedkit.model as feedmodel
```

After the color constants block (after `CLOCK_FONT = ...`, line 39) add:

```python
FEED_FONT = ("Consolas", 9)
FEED_TITLE_FONT = ("Consolas", 9, "bold")
FEED_FG = "#c8c8d4"
FEED_DIM = "#6a6a78"
FEED_LINE_H = 15          # px per feed line
FEED_TITLE_GAP = 4        # px above each feed block
FEED_MAX_CHARS = 30       # truncate any feed text (title or item) to fit 220px
STATE_HEX = {"success": "#3fb950", "failure": "#f85149",
             "pending": "#d29922", "none": "#6a6a78"}


def _fit(text):
    """Truncate any feed line/title to FEED_MAX_CHARS so a long headline or repo
    name can't overflow the 220px width."""
    return text if len(text) <= FEED_MAX_CHARS else text[:FEED_MAX_CHARS - 1] + "…"
```

3b. In `Hud.__init__`, after `self.lock_var = ...` (line 61) add feed state:

```python
        self.CFG_PATH = CFG_PATH  # exposed for the settings window's config.save
        self.feed_state = {}      # idx -> feedmanager.FeedResult
        self._hit = []            # [(y0, y1, url)] for click-to-open (http/https only)
        self._feed_items = []     # canvas item ids to clear on each feed redraw
        self._drain_after = None  # pending after() id so close() can cancel it
        self.settings = None      # FeedSettingsWindow singleton (Task 11)
        token = self._github_token()
        self.manager = feedmanager.FeedManager(cfg.get("feeds", []), token=token)
```

3c. At the end of `__init__`, replace the final two lines:

```python
        self._draw()       # paint something immediately (before first tick)
        self.tick()
```

with:

```python
        self._draw()       # paint something immediately (before first tick)
        self._draw_feeds()
        if not _smoke_ms():
            self.manager.start()   # no worker / no network under smoke launches
        self.tick()
        self._drain_feeds()
```

3d. Add these methods to the `Hud` class (after `_update_spark`, before `def main`):

```python
    # --- feeds ------------------------------------------------------------
    def _github_token(self):
        return os.environ.get("TOYBOX_GITHUB_TOKEN") or self.cfg["hud"].get("github_token", "")

    def _drain_feeds(self):
        self._drain_after = None
        for idx, result in self.manager.drain():
            self.feed_state[idx] = result
        try:
            self._draw_feeds()
        except tk.TclError:
            return                                  # window gone; stop the loop
        self._drain_after = self.root.after(250, self._drain_feeds)

    def _feed_tiles(self):
        """Yield (title, title_url, color, lines) per configured feed. title_url is
        the click target for the title line (None for non-github feeds); lines is a
        list of (text, url, dim). Pulls live results from feed_state, falling back
        to a 'loading'/error placeholder. A github tile surfaces result.error even
        when CI itself returned ok (e.g. a bad notifications token)."""
        for idx, feed in enumerate(self.manager.feeds):
            title = feed.get("title") or "feed"
            if not feed.get("valid"):
                yield (title, None, FEED_DIM, [("! " + (feed.get("error") or "invalid"), None, True)])
                continue
            result = self.feed_state.get(idx)
            if result is None:
                yield (title, None, FEED_FG, [("loading…", None, True)])
                continue
            if result.status is not None:                 # github tile
                color = STATE_HEX.get(result.status.state, FEED_DIM)
                lines = [("! " + result.error, None, True)] if result.error else []
                yield (result.status.text, result.status.url, color, lines)
                continue
            dim = result.state in ("stale", "error")
            lines = [(it.text, it.url, dim) for it in result.items]
            if result.error:
                lines = [("! " + result.error, None, True)] + lines
            if not lines:
                lines = [("(empty)", None, True)]
            yield (title, None, FEED_FG, lines)

    def _register_hit(self, y, url):
        """Record a clickable region for the line centered at y -- but ONLY for
        http/https URLs, so attacker-controlled feed content can't launch
        file://, javascript:, data:, or custom-scheme URLs."""
        if url and feedmodel.is_web_url(url):
            self._hit.append((y - FEED_LINE_H // 2, y + FEED_LINE_H // 2, url))

    def _draw_feeds(self):
        c = self.canvas
        for item_id in self._feed_items:
            c.delete(item_id)
        self._feed_items = []
        self._hit = []
        y = PAD + 3 * ROW_H + 4
        for title, title_url, color, lines in self._feed_tiles():
            y += FEED_TITLE_GAP
            tid = c.create_text(PAD, y, anchor="w", text=_fit(title),
                                fill=color, font=FEED_TITLE_FONT)
            self._feed_items.append(tid)
            self._register_hit(y, title_url)            # github header is clickable
            y += FEED_LINE_H
            for text, url, dim in lines:
                lid = c.create_text(PAD + 6, y, anchor="w", text=_fit(text),
                                    fill=(FEED_DIM if dim else FEED_FG), font=FEED_FONT)
                self._feed_items.append(lid)
                self._register_hit(y, url)
                y += FEED_LINE_H
        self._resize(y + PAD)

    def _resize(self, wanted_h):
        sh = self.root.winfo_screenheight()
        new_h = max(HEIGHT, min(int(wanted_h), sh - self.root.winfo_y()))
        if new_h != self.root.winfo_height():
            self.canvas.config(height=new_h)
            self.root.geometry("%dx%d" % (WIDTH, new_h))

    def _feed_has_text(self, needle):
        for item_id in self._feed_items:
            if needle in self.canvas.itemcget(item_id, "text"):
                return True
        return False

    def close(self):
        # Cleanup only -- never destroys the root (mirrors petkit Cat.close). The
        # single root.destroy() is the quit path in main(); close() runs after it
        # (in main's finally) and the tests call close() then destroy() themselves.
        if self._drain_after is not None:
            try:
                self.root.after_cancel(self._drain_after)
            except Exception:
                pass
            self._drain_after = None
        try:
            self.manager.stop()
        except Exception:
            pass
        if getattr(self, "settings", None) is not None:
            self.settings.close()
```

3e. In `main()`, wire `close()` into both quit paths. Replace:

```python
    Hud(root, cfg)
    startup.watch_for_quit("Toybox_hud", root.after, root.destroy)

    ms = _smoke_ms()
    if ms:
        root.after(ms, root.destroy)
    root.mainloop()
```

with:

```python
    hud = Hud(root, cfg)
    startup.watch_for_quit("Toybox_hud", root.after, root.destroy)

    ms = _smoke_ms()
    if ms:
        root.after(ms, root.destroy)
    try:
        root.mainloop()
    finally:
        hud.close()        # cleanup after the single root.destroy() (stops the worker)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: all PASS, including the existing smoke test (with `feeds: []` the worker does nothing — offline-safe).

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "$(printf 'HUD: render web-feed tiles below metrics, drain worker on 250ms loop\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 10: hud.pyw — click-to-open + menu items (Feeds… / Reload feeds)

**Files:**
- Modify: `hud.pyw` (`_on_release`, menu construction, two small handlers)
- Test: `tests/test_smoke_hud.py` (append a Tk test)

**Interfaces:**
- Consumes: `self._hit` (from Task 9), `self.manager.set_feeds`, `webbrowser`.
- Produces: a left-click (no drag) on a feed line with a URL opens it; the right-click menu gains "Feeds…" and "Reload feeds". `_open_at(x, y) -> str|None` returns the URL it would open (testable without launching a browser). `_reload_feeds()` re-reads `cfg["feeds"]` into the manager.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_smoke_hud.py` (before `if __name__`):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudClickAndMenu(_HudTestBase):
    def test_click_on_item_returns_url(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud([{"type": "rss", "url": "https://x", "title": "X"}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [Item("Headline", "https://example.com/a")], None, None)
            hud._draw_feeds()
            root.update_idletasks()
            y0, y1, url = hud._hit[0]
            mid = (y0 + y1) // 2
            self.assertEqual(hud._open_at(10, mid), "https://example.com/a")
            self.assertIsNone(hud._open_at(10, 2))          # up in the metrics area
            hud.close()
        finally:
            root.destroy()

    def test_non_http_url_is_never_clickable(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud([{"type": "rss", "url": "https://x", "title": "X"}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [Item("Sneaky", "file:///etc/passwd")], None, None)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertEqual(hud._hit, [])                  # no region registered
            self.assertIsNone(hud._open_at(10, 90))         # nothing opens
            hud.close()
        finally:
            root.destroy()

    def test_menu_has_feed_entries(self):
        root, hud = self._make_hud([])
        try:
            labels = [hud.menu.entrycget(i, "label")
                      for i in range(hud.menu.index("end") + 1)
                      if hud.menu.type(i) == "command"]
            self.assertIn("Feeds…", labels)
            self.assertIn("Reload feeds", labels)
            hud.close()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudClickAndMenu -v`
Expected: FAIL (`AttributeError: 'Hud' object has no attribute '_open_at'`).

- [ ] **Step 3: Add click handling and menu entries**

3a. Replace the existing `_on_release` method body so a non-drag click can open a feed link:

```python
    def _on_release(self, event):
        if not self._moved:
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
```

3b. Add the hit-test and feed handlers near the other feed methods (after `close`):

```python
    def _open_at(self, x, y):
        for y0, y1, url in self._hit:
            if y0 <= y <= y1:
                return url if feedmodel.is_web_url(url) else None
        return None

    def _open_feed_settings(self):
        import feedkit.settings as feedsettings
        if getattr(self, "settings", None) is None:
            self.settings = feedsettings.FeedSettingsWindow(self)
        self.settings.open()

    def _reload_feeds(self):
        reloaded = config.load(self.CFG_PATH)
        self.cfg["feeds"] = reloaded.get("feeds", [])
        self.cfg["hud"]["github_token"] = reloaded["hud"].get("github_token", "")
        self.feed_state = {}
        self.manager.set_token(self._github_token())
        self.manager.set_feeds(self.cfg["feeds"])
        self._draw_feeds()
```

3c. Insert the new menu commands. In `__init__`, change the menu block from:

```python
        self.menu.add_separator()
        self.menu.add_checkbutton(label="Lock position", variable=self.lock_var,
                                  command=self._toggle_lock)
        self.menu.add_command(label="Close", command=root.destroy)
```

to:

```python
        self.menu.add_separator()
        self.menu.add_command(label="Feeds…", command=self._open_feed_settings)
        self.menu.add_command(label="Reload feeds", command=self._reload_feeds)
        self.menu.add_separator()
        self.menu.add_checkbutton(label="Lock position", variable=self.lock_var,
                                  command=self._toggle_lock)
        self.menu.add_command(label="Close", command=root.destroy)   # mainloop's finally runs hud.close()
```

(`self.settings` and `self.CFG_PATH` were already initialized in Task 9 Step 3b.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: all PASS.

Note: `_open_feed_settings` imports `feedkit.settings`, created in Task 11. The menu test only checks labels and does not invoke it, and `test_smoke_hud` does not open settings, so this task is green without Task 11. The import is inside the method so module load does not require it yet.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "$(printf 'HUD: click feed item to open URL; Feeds.../Reload feeds menu\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 11: feedkit/settings — the Feed Settings window + final wiring

**Files:**
- Create: `feedkit/settings.py`
- Test: `tests/test_smoke_hud.py` (append a Tk test that opens/saves/closes settings)

**Interfaces:**
- Consumes: the host `Hud` (`.root`, `.cfg`, `.manager`, `._github_token`, `._reload_feeds`, `._draw_feeds`), `feedkit.model.normalize_feed`, `config`.
- Produces: `FeedSettingsWindow(hud)` with `open(tab=None)` / `close()`. A singleton `ttk.Notebook` Toplevel: a "Feeds" tab listing/adding/removing feeds, a "GitHub" tab for the token. Saving writes `hud.cfg["feeds"]`, persists via `config.save`, and calls `hud.manager.set_feeds(...)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_smoke_hud.py` (before `if __name__`):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestFeedSettings(_HudTestBase):
    def test_open_add_feed_and_save(self):
        # isolate_cfg points hud.CFG_PATH at a temp file so saving never touches
        # the user's real config.json.
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            self.assertIsNotNone(hud.settings.win)
            # Add an rss feed programmatically through the window's helper.
            hud.settings._add_feed_dict({"type": "rss", "url": "https://x/y", "title": "X"})
            self.assertEqual(hud.cfg["feeds"][-1]["url"], "https://x/y")
            self.assertEqual(hud.manager.feeds[-1].get("url"), "https://x/y")
            # Test button reports a status (offline here, since fetch is stubbed).
            hud.settings._on_test_token()
            self.assertEqual(hud.settings._token_status.get(), "offline")
            hud._open_feed_settings()                 # singleton: still one window
            hud.close()                               # closes settings too
        finally:
            root.destroy()

    def test_github_add_row_has_show_controls(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("github")
            hud.settings._render_fields()
            # CI + Notifications checkbuttons exist and default to on.
            self.assertEqual(hud.settings._show_ci.get(), 1)
            self.assertEqual(hud.settings._show_notif.get(), 1)
            hud.close()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestFeedSettings -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'feedkit.settings'`.

- [ ] **Step 3: Create `feedkit/settings.py`**

```python
"""The HUD's Feed Settings window: a titled, movable Toplevel hosting a
ttk.Notebook with Feeds / GitHub tabs. Built on demand and reused as a singleton;
reads/writes the live cfg and calls back into the Hud. GUI glue only -- the
testable logic lives in feedkit.model. Guards after()/refresh against TclError
like petkit.settings."""
import tkinter as tk
from tkinter import ttk

import config
import feedkit.model as model

_TYPES = ("rss", "json", "text", "github")


class FeedSettingsWindow:
    def __init__(self, hud):
        self.hud = hud
        self.win = None
        self._nb = None
        self._list = None
        self._type_var = None
        self._fields = {}

    # --- lifecycle ------------------------------------------------------
    def open(self, tab=None):
        if self.win is not None:
            try:
                self.win.deiconify(); self.win.lift(); self.win.focus_force()
                return
            except tk.TclError:
                self.win = None
        self._build()

    def close(self):
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None

    def _build(self):
        self.win = tk.Toplevel(self.hud.root)
        self.win.title("HUD · Feeds")
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._nb = ttk.Notebook(self.win)
        self._nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_feeds_tab()
        self._build_github_tab()
        self._refresh_list()

    # --- Feeds tab ------------------------------------------------------
    def _build_feeds_tab(self):
        f = tk.Frame(self._nb)
        self._nb.add(f, text="Feeds")
        self._list = tk.Frame(f)
        self._list.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        tk.Frame(f, height=1, bg="#ccc").pack(fill="x", padx=10, pady=4)
        add = tk.Frame(f); add.pack(anchor="w", padx=10, pady=(2, 10))
        self._type_var = tk.StringVar(value="rss")
        tk.Label(add, text="Add").pack(side="left")
        tk.OptionMenu(add, self._type_var, *_TYPES,
                      command=lambda _=None: self._render_fields()).pack(side="left", padx=4)
        self._fields_frame = tk.Frame(f)
        self._fields_frame.pack(anchor="w", padx=10)
        self._status = tk.StringVar(value="")
        tk.Label(f, textvariable=self._status, fg="#c33").pack(anchor="w", padx=10)
        self._render_fields()

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
        tk.Button(self._fields_frame, text="Add feed", command=self._on_add).pack(anchor="w", pady=4)

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
        else:
            raw["url"] = g("url")
            if g("items"):
                raw["items"] = _as_int(g("items"))
            if ftype == "json":
                raw["path"] = g("path")
                raw["fields"] = {"text": g("text"), "url": g("urlfield") or None}
            elif ftype == "text" and g("regex"):
                raw["regex"] = g("regex")
        norm = model.normalize_feed(raw)
        if not norm.get("valid"):
            self._status.set(norm.get("error") or "invalid feed")
            return
        self._status.set("")
        self._add_feed_dict(raw)

    def _add_feed_dict(self, raw):
        """Append a raw feed dict, persist, and push to the manager. Also used by
        tests to add a feed without driving the widgets."""
        feeds = list(self.hud.cfg.get("feeds", []))
        feeds.append(raw)
        self.hud.cfg["feeds"] = feeds
        self._persist()
        self._refresh_list()

    def _remove(self, index):
        feeds = list(self.hud.cfg.get("feeds", []))
        if 0 <= index < len(feeds):
            del feeds[index]
            self.hud.cfg["feeds"] = feeds
            self._persist()
            self._refresh_list()

    def _persist(self):
        try:
            config.save(self.hud.CFG_PATH, self.hud.cfg)
        except Exception:
            pass
        self.hud.manager.set_token(self.hud._github_token())
        self.hud.manager.set_feeds(self.hud.cfg["feeds"])
        self.hud.feed_state = {}
        self.hud._draw_feeds()

    def _refresh_list(self):
        if self.win is None:
            return
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

    # --- GitHub tab -----------------------------------------------------
    def _build_github_tab(self):
        f = tk.Frame(self._nb)
        self._nb.add(f, text="GitHub")
        import os
        env_set = bool(os.environ.get("TOYBOX_GITHUB_TOKEN"))
        src = "environment (TOYBOX_GITHUB_TOKEN)" if env_set else "this field / config.json"
        tk.Label(f, text="Active token source: " + src, fg="#555").pack(anchor="w", padx=10, pady=(10, 2))
        tk.Label(f, text="Classic PAT · scope: notifications (+ repo for private CI)",
                 fg="#555").pack(anchor="w", padx=10)
        row = tk.Frame(f); row.pack(anchor="w", padx=10, pady=6)
        self._token_var = tk.StringVar(value=self.hud.cfg["hud"].get("github_token", ""))
        tk.Label(row, text="Token").pack(side="left")
        tk.Entry(row, width=30, show="*", textvariable=self._token_var).pack(side="left", padx=4)
        tk.Button(row, text="Save", command=self._on_save_token).pack(side="left")
        tk.Button(row, text="Test", command=self._on_test_token).pack(side="left", padx=4)
        self._token_status = tk.StringVar(value="")
        tk.Label(f, textvariable=self._token_status, fg="#555").pack(anchor="w", padx=10)

    def _on_save_token(self):
        self.hud.cfg["hud"]["github_token"] = self._token_var.get().strip()
        self._persist()

    def _on_test_token(self):
        """One synchronous /notifications request (acceptable for an explicit
        click) reporting OK (N unread) / bad token / rate-limited / offline."""
        import feedkit.fetch as fetch
        import feedkit.parse as parse
        token = self.hud._github_token()
        res = fetch.fetch(model.github_notifications_url(), headers=model.github_headers(token))
        if res.status == "ok":
            try:
                self._token_status.set("OK (%d unread)" % parse.parse_notifications(res.body))
            except Exception:
                self._token_status.set("bad response")
        elif res.status == "not_modified":
            self._token_status.set("OK")
        else:
            self._token_status.set(res.error or "error")


def _as_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return text     # normalize_feed will coerce/reject it
```

3b. `feedkit/settings.py` reads `self.hud.CFG_PATH`, `self.hud._github_token`, `self.hud.manager`, and `self.hud._draw_feeds` — all introduced in Task 9 Step 3. No further `hud.pyw` change is needed here.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: all PASS.

- [ ] **Step 5: Full-suite regression + commit**

Run the whole suite:
`C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -t . -v`
Expected: OK (existing tests + all new feed tests; output pristine).

```bash
git add feedkit/settings.py hud.pyw tests/test_smoke_hud.py
git commit -m "$(printf 'HUD: Feed Settings window (add/remove feeds, GitHub token)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:

| Spec requirement | Task |
|---|---|
| `config.py` `feeds: []` + `hud.github_token` | 1 |
| `Item`/`Status`, text/header helpers, GitHub URL/header builders | 2 |
| `normalize_feed`, `due_feeds` | 3 |
| `parse_rss` (RSS+Atom, DOCTYPE guard) | 4 |
| `parse_json`, `parse_text` | 5 |
| `parse_check_runs`/`parse_notifications`/`compose_github_status` (check-runs reduction; mandatory headers via model) | 6 |
| `fetch.py` (no certifi, 304-as-HTTPError, size cap, timeout, error taxonomy incl. cert error) | 7 |
| `FeedManager` (one worker, queue, conditional caching, github 2-call orchestration, no-token-skips-notifications) | 8 |
| HUD rendering, drain loop, window resize, state→color, click hit-regions (incl. github header) | 9 |
| click-to-open (`webbrowser`, **http/https only** via `model.is_web_url`), menu Feeds…/Reload | 10 |
| Settings UI (ttk.Notebook, Feeds + GitHub tabs incl. show checkboxes + Test button), env-first token | 11 |
| Non-goals (no GPU/disk/temp/fan, no scroll, first-100 checks, no write actions) | honored — none implemented |

Token storage decision (env-first, UI fallback) → `_github_token` (Task 9) + GitHub tab label (Task 11). XML safety → DOCTYPE guard (Task 4). Error taxonomy → `_error_word` (Task 7) surfaced in tiles incl. github (Task 9 `_feed_tiles`). Cadence floors → `normalize_feed` interval floors (Task 3). Offline-safe smoke → Task 9 gates `manager.start()` under `_smoke_ms()`.

**Audit hardening applied** (from the adversarial plan review): the **only-http/https** constraint is now enforced by `model.is_web_url` at hit-registration (Task 9 `_register_hit`) and at `_open_at` (Task 10), with a `file://` rejection test; the in-process Tk tests stub `feedkit.fetch.fetch` (offline base, Task 9) and the settings test isolates `CFG_PATH` to a temp dir; `parse_rss` finds items by local-name (RSS 1.0/RDF, Task 4); a 200 with unparseable bytes keeps last-good as `stale` (Task 8); `_last`/`_cache` are lock-guarded; the github tile renders its error line and a clickable Actions/notifications URL; the GitHub tab has a working **Test** button and CI/Notifications `show` checkboxes; `parse_check_runs` follows the spec's incomplete→pending order. The `X-Poll-Interval` header is intentionally **not** dynamically honored — the 120 s github interval floor already exceeds GitHub's ~60 s minimum (documented non-goal).

**2. Placeholder scan** — no TBD/TODO; every code step shows complete code; no "similar to Task N".

**3. Type consistency** — checked across tasks:
- `Item(text, url)` / `Status(text, state, url)` defined in Task 2, used identically in Tasks 4–6, 8, 9.
- `FetchResult(status, body, content_type, etag, last_modified, error)` defined in Task 7, constructed in tests and consumed in Task 8 with matching field order.
- `FeedResult(state, items, status, error)` defined in Task 8, constructed in Task 9's test and consumed in `_feed_tiles`.
- `normalize_feed` output keys (`valid`, `error`, `type`, `title`, `items`, `interval`, `url`/`repo`/`branch`/`show`/`path`/`fields`/`regex`) — produced in Task 3, consumed in Task 8 (`_parse_body`, `_process_github`), Task 9 (`_feed_tiles`), Task 11 (`_refresh_list`).
- `due_feeds(feeds, last_fetch, now, stagger)` — Task 3; called by `FeedManager._run_once` (Task 8).
- `FeedManager(feeds, token, fetch_fn, poll_interval)`, `.feeds`, `.drain()`, `.set_feeds()`, `.set_token()`, `.start()`, `.stop()`, `._run_once()` — Task 8; used by HUD (Task 9/10) and settings (Task 11).
- `Hud` attributes added in Task 9 (`feed_state`, `_hit`, `manager`, `CFG_PATH`, `_github_token`, `_draw_feeds`, `close`) consumed by Task 10 (`_open_at`, `_reload_feeds`) and Task 11 (`_persist`, `_add_feed_dict`).
- `github_headers`/`github_ci_url`/`github_notifications_url`/`is_web_url` — Task 2; `is_web_url` consumed by Task 9 `_register_hit`/`_draw_feeds` and Task 10 `_open_at`; the github URL builders by Task 8 `_process_github` and Task 11 `_on_test_token`.
- `compose_github_status(..., ci_shown=True)` — Task 6; `ci_shown` passed by Task 8 `_process_github`.
- `_feed_tiles()` yields 4-tuples `(title, title_url, color, lines)` — Task 9; `_draw_feeds` (same task) is the only consumer.
- `FeedSettingsWindow` reads `hud.CFG_PATH`/`hud.manager`/`hud._github_token`/`hud._draw_feeds`/`hud.feed_state` — all set in Task 9 Step 3; `hud.settings` set/cleared by Task 10 `_open_feed_settings` and Task 9 `close`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-29-hud-web-feed-plugin.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, task review (spec + quality) between tasks, then a whole-branch review.
2. **Inline Execution** — execute tasks in this session with checkpoints.
