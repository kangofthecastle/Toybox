# HUD Search Feed (My PRs / Reviews / Assigned) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `search` feed type so the HUD can show the user's own open PRs, PRs awaiting their review, and issues/PRs assigned to them — things GitHub notifications never surface.

**Architecture:** A new `search` feed type backed by GitHub's `/search/issues` API, fetched with the existing `github_token`. Results parse into the existing `NotifItem` rows and render through the existing two-line notification row path with **no dismiss action** (search results are not threads). The user adds one feed per bucket; Settings offers the three queries as presets.

**Tech Stack:** Python 3.12 standard library only (tkinter, urllib, json) — no third-party packages. Mirrors the existing `feedkit` package: pure `model.py`/`parse.py`, glue `manager.py`, ttk `settings.py`, canvas `hud.pyw`.

## Global Constraints

- **Pure Python 3.12 stdlib only. No pip / third-party ever** (no requests, certifi, defusedxml, feedparser).
- **TLS verification is never weakened.** Reuse `model.github_headers(token)`; never pass a custom SSL context.
- **Only http/https URLs may reach the browser.** The HUD's `_register_hit` already gates on `feedmodel.is_web_url`; parsed item URLs that are not http/https must be `""`.
- **Test runner:** `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path> -v`, run from the repo root `C:\Users\Warren\Toybox`. Bare `python` is a broken MS-Store stub — always use the full path.
- **Commit only the files a task names.** End every commit message with exactly:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Branch:** `hud-notifications-tile` (this feature reuses the notification row renderer that lives only on this branch).
- **The reason field on a search row is the author login `@login`.** Draft PRs render dim (low urgency); everything else normal.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `feedkit/model.py` | Pure data types, URL/header builders, feed validation | Add `github_search_url`, `github_search_web_url`; add `"search"` to `_VALID_TYPES`; add a `search` branch to `normalize_feed`. |
| `feedkit/parse.py` | Pure response parsers | Add `parse_search_items(body, max_items) -> (list[NotifItem], total)`. |
| `feedkit/manager.py` | Worker thread: fetch → parse → queue | Add `_process_search` and dispatch it from `_fetch_and_process`. |
| `hud.pyw` | Canvas rendering + click routing | Add a `search` branch to `_feed_tiles` (reuses the existing 6-tuple row path; no new draw code). |
| `feedkit/settings.py` | Feed settings window | Add `"search"` type, its field spec, a preset menu + `_apply_search_preset`, and an `_on_add` branch. |
| `tests/test_feed_model.py` | model unit tests | Add URL-builder + `normalize_feed` search tests. |
| `tests/test_feed_parse.py` | parse unit tests | Add `parse_search_items` tests. |
| `tests/test_feed_manager.py` | manager unit tests | Add `TestProcessSearch`. |
| `tests/test_smoke_hud.py` | HUD smoke tests | Add `TestHudSearchRendering`; add settings tests to `TestHudClickAndMenu`. |

Task order: **1 (model) → 2 (parse) → 3 (manager) → 4 (hud) → 5 (settings)**. Every later task depends on Task 1; Task 3 also depends on Task 2.

---

### Task 1: model — search URL builders + feed validation

**Files:**
- Modify: `feedkit/model.py` (add two builders after `github_mark_all_read_url`; extend `_VALID_TYPES`; add a `search` branch in `normalize_feed`)
- Test: `tests/test_feed_model.py` (add to `TestGithubBuilders` and `TestNormalizeFeed`)

**Interfaces:**
- Consumes: `GITHUB_API` constant, `urllib.parse`, `_coerce_int`, `is_web_url` (all already in `model.py`).
- Produces:
  - `github_search_url(query, per_page) -> str`
  - `github_search_web_url(query) -> str`
  - `normalize_feed({"type":"search", ...})` returns a dict with `valid`, `query`, `items`, `interval`, `title`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_model.py`, inside `class TestGithubBuilders`:

```python
    def test_search_url_encodes_query(self):
        self.assertEqual(
            model.github_search_url("is:open is:pr author:@me", 5),
            "https://api.github.com/search/issues?q=is%3Aopen%20is%3Apr%20author%3A%40me"
            "&sort=updated&order=desc&per_page=5")

    def test_search_web_url_is_browser_url(self):
        url = model.github_search_web_url("is:open is:pr author:@me")
        self.assertEqual(
            url,
            "https://github.com/search?q=is%3Aopen%20is%3Apr%20author%3A%40me&type=issues")
        self.assertTrue(model.is_web_url(url))
```

Add to `tests/test_feed_model.py`, inside `class TestNormalizeFeed`:

```python
    def test_search_minimal_valid(self):
        f = model.normalize_feed({"type": "search", "query": "is:open is:pr author:@me"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["query"], "is:open is:pr author:@me")
        self.assertEqual(f["items"], 5)
        self.assertEqual(f["interval"], 300)
        self.assertEqual(f["title"], "Search")

    def test_search_missing_query_invalid(self):
        self.assertFalse(model.normalize_feed({"type": "search"})["valid"])
        blank = model.normalize_feed({"type": "search", "query": "   "})
        self.assertFalse(blank["valid"])
        self.assertEqual(blank["error"], "search feed needs 'query'")

    def test_search_interval_floor_120(self):
        self.assertEqual(
            model.normalize_feed({"type": "search", "query": "x", "interval": 5})["interval"], 120)
        self.assertEqual(
            model.normalize_feed({"type": "search", "query": "x", "interval": 600})["interval"], 600)

    def test_search_items_clamped(self):
        self.assertEqual(
            model.normalize_feed({"type": "search", "query": "x", "items": 99})["items"], 10)
        self.assertEqual(
            model.normalize_feed({"type": "search", "query": "x", "items": 0})["items"], 1)

    def test_search_custom_title_and_strips_query(self):
        f = model.normalize_feed({"type": "search", "query": "  is:open  ", "title": "My PRs"})
        self.assertEqual(f["title"], "My PRs")
        self.assertEqual(f["query"], "is:open")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: FAIL — `AttributeError: module 'feedkit.model' has no attribute 'github_search_url'`, and the normalize tests fail because `search` is an unknown type.

- [ ] **Step 3: Add the URL builders**

In `feedkit/model.py`, immediately after the `github_mark_all_read_url` function:

```python
def github_search_url(query, per_page):
    """Issue/PR search endpoint, newest-updated first. `query` is the raw GitHub
    search expression (e.g. 'is:open is:pr author:@me'); it is percent-encoded."""
    return "%s/search/issues?q=%s&sort=updated&order=desc&per_page=%d" % (
        GITHUB_API, urllib.parse.quote(query), per_page)


def github_search_web_url(query):
    """github.com search UI for `query` (covers issues and PRs). Used as the
    click target for a search tile's header and its '… N more' overflow line."""
    return "https://github.com/search?q=%s&type=issues" % urllib.parse.quote(query)
```

- [ ] **Step 4: Add `"search"` to the valid types**

In `feedkit/model.py`, change the `_VALID_TYPES` tuple:

```python
_VALID_TYPES = ("rss", "json", "text", "github", "notifications", "search")
```

- [ ] **Step 5: Add the `search` branch to `normalize_feed`**

In `feedkit/model.py`, inside `normalize_feed`, immediately after the `if ftype == "notifications":` block returns and **before** the `# github` comment, insert:

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: PASS (all new tests green, no existing tests broken).

- [ ] **Step 7: Commit**

```bash
git add feedkit/model.py tests/test_feed_model.py
git commit -m "$(cat <<'EOF'
feat(feedkit): search feed URL builders + validation

github_search_url / github_search_web_url and a 'search' feed type in
normalize_feed (raw query, items 1-10, interval floor 120 / default 300).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: parse — `parse_search_items`

**Files:**
- Modify: `feedkit/parse.py` (add `_SEARCH_REPO_PREFIX` constant + `parse_search_items`)
- Test: `tests/test_feed_parse.py` (add `class TestParseSearchItems`)

**Interfaces:**
- Consumes: `model.glyph_for`, `model.is_web_url`, `model.NotifItem`, `_parse_ts`, `_clean` (all already in `parse.py` / imported there).
- Produces: `parse_search_items(body, max_items) -> (list[NotifItem], int)`.
  - A `NotifItem` for each result: `glyph` = `⇄` for PRs (item has a `pull_request` dict) else `◉`; `repo` from `repository_url`; `number` = `"#<n>"`; `reason_label` = `"@<login>"`; `urgency` = `"low"` for draft PRs else `"normal"`; `updated_at` from `updated_at`; `title` cleaned; `url` = `html_url` when http/https else `""`; `thread_url` defaulted to `""`.
  - Second element is `total_count` (falls back to `len(items)` when absent).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_parse.py` (the file already imports `json`, `parse`, and `model`):

```python
def _sr(**over):
    """One /search/issues result item (a PR by default)."""
    it = {"number": 34, "title": "Fix the thing",
          "html_url": "https://github.com/o/app/pull/34",
          "repository_url": "https://api.github.com/repos/o/app",
          "user": {"login": "octocat"},
          "updated_at": "2026-06-29T00:00:00Z",
          "pull_request": {"url": "https://api.github.com/repos/o/app/pulls/34"}}
    it.update(over)
    return it


def _sbody(items, total=None):
    payload = {"items": items}
    if total is not None:
        payload["total_count"] = total
    return json.dumps(payload).encode()


class TestParseSearchItems(unittest.TestCase):
    def test_non_dict_body_is_empty(self):
        self.assertEqual(parse.parse_search_items(b"[]", 5), ([], 0))

    def test_missing_items_is_empty(self):
        self.assertEqual(parse.parse_search_items(b'{"total_count":3}', 5), ([], 0))

    def test_basic_pr(self):
        items, total = parse.parse_search_items(_sbody([_sr()], total=3), 5)
        self.assertEqual(total, 3)
        it = items[0]
        self.assertEqual(it.glyph, model.glyph_for("PullRequest"))
        self.assertEqual(it.repo, "o/app")
        self.assertEqual(it.number, "#34")
        self.assertEqual(it.reason_label, "@octocat")
        self.assertEqual(it.urgency, "normal")
        self.assertEqual(it.title, "Fix the thing")
        self.assertEqual(it.url, "https://github.com/o/app/pull/34")
        self.assertEqual(it.thread_url, "")
        self.assertGreater(it.updated_at, 0)

    def test_issue_uses_issue_glyph(self):
        issue = _sr()
        del issue["pull_request"]
        items, _ = parse.parse_search_items(_sbody([issue]), 5)
        self.assertEqual(items[0].glyph, model.glyph_for("Issue"))

    def test_draft_pr_is_low_urgency(self):
        items, _ = parse.parse_search_items(_sbody([_sr(draft=True)]), 5)
        self.assertEqual(items[0].urgency, "low")

    def test_missing_user_number_html(self):
        bare = {"title": "no metadata", "repository_url": "https://api.github.com/repos/o/app"}
        items, total = parse.parse_search_items(_sbody([bare]), 5)
        self.assertEqual(total, 1)                       # total_count absent -> len(items)
        it = items[0]
        self.assertEqual(it.reason_label, "")
        self.assertEqual(it.number, "")
        self.assertEqual(it.url, "")                     # no html_url -> no click target
        self.assertEqual(it.repo, "o/app")

    def test_total_count_absent_falls_back_to_len(self):
        items, total = parse.parse_search_items(_sbody([_sr(), _sr(number=35)]), 5)
        self.assertEqual(total, 2)

    def test_max_items_caps_list(self):
        items, total = parse.parse_search_items(
            _sbody([_sr(number=i) for i in range(8)], total=8), 3)
        self.assertEqual(len(items), 3)
        self.assertEqual(total, 8)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: FAIL — `AttributeError: module 'feedkit.parse' has no attribute 'parse_search_items'`.

- [ ] **Step 3: Implement `parse_search_items`**

In `feedkit/parse.py`, add the constant near the other module constants (e.g. below `_NOTIF_API_PREFIX` usage — anywhere at module level) and the function after `parse_notification_items`:

```python
_SEARCH_REPO_PREFIX = "https://api.github.com/repos/"


def parse_search_items(body, max_items):
    """Parse a /search/issues response into (list[NotifItem], total_count).
    total_count drives the count shown in the tile title; the list is capped at
    max_items. Defensive against missing keys and non-list items. A result with
    a 'pull_request' object is a PR (⇄); otherwise an issue (◉)."""
    data = json.loads(body)
    items_raw = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items_raw, list):
        return [], 0
    total = data.get("total_count")
    if not isinstance(total, int) or isinstance(total, bool):
        total = len(items_raw)
    out = []
    for it in items_raw[:max_items]:
        if not isinstance(it, dict):
            continue
        is_pr = isinstance(it.get("pull_request"), dict)
        repo_url = it.get("repository_url") or ""
        repo = (repo_url[len(_SEARCH_REPO_PREFIX):]
                if isinstance(repo_url, str) and repo_url.startswith(_SEARCH_REPO_PREFIX)
                else "")
        num = it.get("number")
        number = "#%d" % num if isinstance(num, int) and not isinstance(num, bool) else ""
        user = it.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        label = ("@" + login) if login else ""
        urgency = "low" if (is_pr and it.get("draft")) else "normal"
        html = it.get("html_url")
        out.append(model.NotifItem(
            glyph=model.glyph_for("PullRequest" if is_pr else "Issue"),
            repo=repo,
            number=number,
            reason_label=label,
            urgency=urgency,
            updated_at=_parse_ts(it.get("updated_at")),
            title=_clean(it.get("title") or ""),
            url=html if model.is_web_url(html) else "",
        ))
    return out, total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add feedkit/parse.py tests/test_feed_parse.py
git commit -m "$(cat <<'EOF'
feat(feedkit): parse_search_items for /search/issues

Reduces search results to NotifItem rows (PR vs issue glyph, repo from
repository_url, author login label, draft -> low urgency, html_url click
target gated to http/https) plus the total_count.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: manager — `_process_search` + dispatch

**Files:**
- Modify: `feedkit/manager.py` (add one dispatch line in `_fetch_and_process`; add `_process_search`)
- Test: `tests/test_feed_manager.py` (add `class TestProcessSearch`)

**Interfaces:**
- Consumes: `model.github_search_url` (Task 1), `parse.parse_search_items` (Task 2), `model.github_headers`, the existing `self._fetch`, `self._cache`, `self._lock`, `FeedResult`.
- Produces: a `FeedResult` for a `search` feed — `("error", [], None, "no github_token", None)` with no token; `("ok", items, None, None, total)` on success (badge = total); stale-on-error / bad-data carries previous items + badge, mirroring `_process_notifications`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_manager.py` (it already defines `_ok`, `_err`, `_nm`, and imports `fetch`/`manager`):

```python
class TestProcessSearch(unittest.TestCase):
    PRS = (b'{"total_count":2,"items":['
           b'{"number":34,"title":"a","html_url":"https://github.com/o/r/pull/34",'
           b'"repository_url":"https://api.github.com/repos/o/r","user":{"login":"me"},'
           b'"updated_at":"2026-06-29T00:00:00Z","pull_request":{"url":"x"}},'
           b'{"number":35,"title":"b","html_url":"https://github.com/o/r/pull/35",'
           b'"repository_url":"https://api.github.com/repos/o/r","user":{"login":"me"},'
           b'"updated_at":"2026-06-29T00:00:00Z","pull_request":{"url":"y"}}]}')
    FEED = {"type": "search", "query": "is:open is:pr author:@me", "items": 5}

    def test_no_token_is_error(self):
        m = manager.FeedManager([self.FEED], token="",
                                fetch_fn=lambda u, **k: _ok(b'{"total_count":0,"items":[]}'))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")
        self.assertEqual(result.error, "no github_token")
        self.assertIsNone(result.badge)

    def test_hits_search_endpoint(self):
        seen = []
        def fake(u, **k):
            seen.append(u); return _ok(self.PRS)
        m = manager.FeedManager([self.FEED], token="ghp_x", fetch_fn=fake)
        m._run_once(0.0)
        self.assertIn("/search/issues?q=", seen[0])

    def test_success_badge_is_total(self):
        m = manager.FeedManager([self.FEED], token="ghp_x",
                                fetch_fn=lambda u, **k: _ok(self.PRS))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.badge, 2)
        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.items[0].number, "#34")

    def test_error_after_success_is_stale_with_badge(self):
        responses = [_ok(self.PRS), _err("offline")]
        m = manager.FeedManager([self.FEED], token="ghp_x",
                                fetch_fn=lambda u, **k: responses.pop(0))
        m._run_once(0.0); m._last.clear(); m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.error, "offline")
        self.assertEqual(result.badge, 2)
        self.assertEqual(len(result.items), 2)

    def test_bad_data_after_success_is_stale(self):
        responses = [_ok(self.PRS), _ok(b"not json{")]
        m = manager.FeedManager([self.FEED], token="ghp_x",
                                fetch_fn=lambda u, **k: responses.pop(0))
        m._run_once(0.0); m._last.clear(); m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.error, "bad data")
        self.assertEqual(result.badge, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager.TestProcessSearch -v`
Expected: FAIL — the `search` feed falls through `_fetch_and_process` to the generic path, which has no `feed["url"]`, raising `KeyError: 'url'` (caught and surfaced as an `error` FeedResult, so assertions on `state == "ok"`/`"stale"` fail).

- [ ] **Step 3: Add the dispatch line**

In `feedkit/manager.py`, in `_fetch_and_process`, add the `search` branch directly after the `notifications` branch:

```python
    def _fetch_and_process(self, idx, feed, token):
        if feed["type"] == "notifications":
            return self._process_notifications(idx, feed, token)
        if feed["type"] == "search":
            return self._process_search(idx, feed, token)
        if feed["type"] == "github":
            return self._process_github(idx, feed, token)
```

- [ ] **Step 4: Implement `_process_search`**

In `feedkit/manager.py`, add this method immediately after `_process_notifications`:

```python
    def _process_search(self, idx, feed, token):
        """GitHub /search/issues for a saved query (my PRs / reviews / assigned).
        Single cache key = idx; conditional GET; stale-on-error / bad-data carries
        the previous items + badge, mirroring _process_notifications. Requires a
        token (search of private repos / @me needs auth)."""
        if not token:
            return FeedResult("error", [], None, "no github_token", None)
        with self._lock:
            cache = self._cache.get(idx, {})
        res = self._fetch(model.github_search_url(feed["query"], feed["items"]),
                          headers=model.github_headers(token),
                          etag=cache.get("etag"), last_modified=cache.get("lm"))
        prev = cache.get("result")
        if res.status == "not_modified":
            return prev or FeedResult("ok", [], None, None, 0)
        if res.status == "error":
            return FeedResult("stale" if prev else "error",
                              prev.items if prev else [], None, res.error,
                              prev.badge if prev else None)
        try:
            items, total = parse.parse_search_items(res.body, feed["items"])
        except Exception:
            return FeedResult("stale" if prev else "error",
                              prev.items if prev else [], None, "bad data",
                              prev.badge if prev else None)
        result = FeedResult("ok", items, None, None, total)
        with self._lock:
            self._cache[idx] = {"etag": res.etag, "lm": res.last_modified, "result": result}
        return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
Expected: PASS (the whole manager suite, including the existing tests).

- [ ] **Step 6: Commit**

```bash
git add feedkit/manager.py tests/test_feed_manager.py
git commit -m "$(cat <<'EOF'
feat(feedkit): manager _process_search (token-gated, stale-on-error)

Fetches /search/issues for a saved query and returns NotifItem rows with the
total as the badge; mirrors the notifications path for caching and
stale-on-error/bad-data.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: hud — `_feed_tiles` search branch

**Files:**
- Modify: `hud.pyw` (`_feed_tiles`, insert a `search` branch after the `notifications` branch, before the `github` `if result.status is not None:` block)
- Test: `tests/test_smoke_hud.py` (add `class TestHudSearchRendering`)

**Interfaces:**
- Consumes: `FeedResult` from Task 3 (`state`, `items` of `NotifItem`, `error`, `badge`); `feedmodel.github_search_web_url` (Task 1); existing `_repo_short`, `URGENCY_HEX`, `FEED_FG`, `FEED_DIM`, `timeago`, `time`.
- Produces: per-feed yield `(header, web_url, FEED_FG, lines, None)` where `lines` are existing 6-tuples `(line1, url, color, subtitle, age, dismiss)` with `dismiss=None` (so the existing `_draw_feeds` renders two-line rows with **no ✕** and registers only the open-URL hit). No new draw code, no changes to `_draw_feeds`/`_on_release`/`_action_at`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smoke_hud.py` (the module already imports `os`, `unittest`, and defines `_HudTestBase` with `_make_hud`, plus `hud._feed_has_text` / `hud._hit` / `hud._action_hits`):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudSearchRendering(_HudTestBase):
    FEED = {"type": "search", "title": "My PRs",
            "query": "is:open is:pr author:@me", "items": 5}

    def _item(self, repo="o/app", num="#34", title="Fix the thing",
              url="https://github.com/o/app/pull/34", urgency="normal",
              glyph="⇄", label="@me", ts=0.0):
        from feedkit.model import NotifItem
        return NotifItem(glyph, repo, num, label, urgency, ts, title, url)

    def test_renders_rows_and_count(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._item()], None, None, 3)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("(3)"))          # header count
            self.assertTrue(hud._feed_has_text("app"))          # line 1 repo
            self.assertTrue(hud._feed_has_text("Fix the thing"))  # line 2 title
        finally:
            hud.close(); root.destroy()

    def test_item_clickable_and_no_dismiss(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._item()], None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(any(u == "https://github.com/o/app/pull/34"
                                for (_, _, u) in hud._hit))
            self.assertEqual(hud._action_hits, [])              # search rows have no ✕
        finally:
            hud.close(); root.destroy()

    def test_header_and_overflow_link_to_web_search(self):
        import feedkit.manager as manager
        import feedkit.model as model
        root, hud = self._make_hud([self.FEED])
        try:
            items = [self._item(num="#%d" % i, url="https://github.com/o/app/pull/%d" % i)
                     for i in range(5)]
            hud.feed_state[0] = manager.FeedResult("ok", items, None, None, 12)
            hud._draw_feeds(); root.update_idletasks()
            web = model.github_search_web_url("is:open is:pr author:@me")
            self.assertTrue(hud._feed_has_text("7 more"))       # 12 total - 5 shown
            self.assertTrue(any(u == web for (_, _, u) in hud._hit))
        finally:
            hud.close(); root.destroy()

    def test_no_token_line(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.feed_state[0] = manager.FeedResult("error", [], None, "no github_token", None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("set GitHub token"))
        finally:
            hud.close(); root.destroy()

    def test_none_open(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [], None, None, 0)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("none open"))
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudSearchRendering -v`
Expected: FAIL — with no `search` branch in `_feed_tiles`, the search feed falls into the generic non-github path and renders nothing matching `(3)` / `7 more` / `none open`; `test_renders_rows_and_count` fails first.

- [ ] **Step 3: Add the `search` branch to `_feed_tiles`**

In `hud.pyw`, inside `_feed_tiles`, insert this block immediately after the `notifications` branch's `continue` and **before** the `if result.status is not None:` line:

```python
            if feed["type"] == "search":
                badge = result.badge or 0           # badge may be None
                header = title + ("  (%d)" % badge)
                web = feedmodel.github_search_web_url(feed["query"])
                lines = []
                if result.error == "no github_token":
                    lines.append(("! set GitHub token in Settings", None, True))
                elif result.error and not result.items:
                    lines.append(("! " + result.error, None, True))
                elif result.state == "ok" and not result.items:
                    lines.append(("none open", None, True))
                stale = result.state != "ok"
                for it in result.items:
                    color = FEED_DIM if stale else URGENCY_HEX.get(it.urgency, FEED_FG)
                    age = "" if it.updated_at <= 0 else timeago.format_ago(time.time() - it.updated_at)
                    num = (" " + it.number) if it.number else ""
                    line1 = "%s %s%s · %s" % (it.glyph, _repo_short(it.repo), num, it.reason_label)
                    lines.append((line1, it.url, color, it.title, age, None))
                extra = badge - len(result.items)
                if extra > 0:
                    lines.append(("… %d more" % extra, web, True))
                yield (header, web, FEED_FG, lines, None)
                continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudSearchRendering -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "$(cat <<'EOF'
feat(hud): render search feeds (reuses the notification row, no dismiss)

A 'search' branch in _feed_tiles yields the existing two-line item rows with
dismiss=None, a "(N)" count in the header, and header + overflow links to the
github.com search page. No new draw code.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: settings — search type, preset menu, add path

**Files:**
- Modify: `feedkit/settings.py` (add `"search"` to `_TYPES`; a module-level `_SEARCH_PRESETS`; the field spec; a preset `OptionMenu` + `_apply_search_preset`; an `_on_add` branch)
- Test: `tests/test_smoke_hud.py` (add three tests to `class TestHudClickAndMenu`)

**Interfaces:**
- Consumes: `model.normalize_feed` (Task 1), the existing `_fields` dict, `_render_fields`, `_on_add`, `_add_feed_dict`.
- Produces: a `search` type in the Add dropdown with Title / Query / Items / Interval fields and a Preset menu; `_apply_search_preset(name)` sets the Query field; `_on_add` builds `{"type":"search","title":…,"query":…,"items":…}` (and `interval` when provided).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smoke_hud.py`, inside `class TestHudClickAndMenu` (next to `test_notifications_render_fields_has_no_url`):

```python
    def test_search_render_fields_has_query(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("search")
            hud.settings._render_fields()
            self.assertIn("query", hud.settings._fields)
            self.assertIn("items", hud.settings._fields)
            self.assertNotIn("url", hud.settings._fields)
            self.assertNotIn("repo", hud.settings._fields)
            hud.close()
        finally:
            root.destroy()

    def test_search_preset_fills_query(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("search")
            hud.settings._render_fields()
            hud.settings._apply_search_preset("My open PRs")
            self.assertEqual(hud.settings._fields["query"].get(),
                             "is:open is:pr author:@me")
            hud.close()
        finally:
            root.destroy()

    def test_search_on_add_builds_query_feed(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("search")
            hud.settings._render_fields()
            hud.settings._fields["title"].set("My PRs")
            hud.settings._fields["query"].set("is:open is:pr author:@me")
            hud.settings._fields["items"].set("5")
            hud.settings._on_add()
            added = hud.cfg["feeds"][-1]
            self.assertEqual(added["type"], "search")
            self.assertEqual(added["query"], "is:open is:pr author:@me")
            self.assertEqual(added["items"], 5)
            self.assertTrue(hud.manager.feeds[-1]["valid"])
            hud.close()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudClickAndMenu -v`
Expected: FAIL — `search` is not in `_TYPES` and `_render_fields` has no `search` spec (`KeyError`), and `_apply_search_preset` does not exist (`AttributeError`).

- [ ] **Step 3: Add `"search"` to the type list and the presets constant**

In `feedkit/settings.py`, change `_TYPES` and add `_SEARCH_PRESETS` below it:

```python
_TYPES = ("rss", "json", "text", "github", "notifications", "search")

_SEARCH_PRESETS = {
    "My open PRs": "is:open is:pr author:@me",
    "Awaiting my review": "is:open is:pr review-requested:@me",
    "Assigned to me": "is:open assignee:@me",
}
```

- [ ] **Step 4: Add the `search` field spec**

In `feedkit/settings.py`, in `_render_fields`, add a `search` entry to the `spec` dict (alongside `notifications`):

```python
            "search": [("title", "Title"), ("query", "Query"),
                       ("items", "Items"), ("interval", "Interval s")],
```

- [ ] **Step 5: Add the preset menu and `_apply_search_preset`**

In `feedkit/settings.py`, in `_render_fields`, after the `if ftype == "github":` checkbutton block and **before** the final `tk.Button(self._fields_frame, text="Add feed", ...)`, add:

```python
        if ftype == "search":
            prow = tk.Frame(self._fields_frame); prow.pack(anchor="w", pady=1)
            tk.Label(prow, text="Preset", width=10, anchor="w").pack(side="left")
            self._preset_var = tk.StringVar(value="")
            tk.OptionMenu(prow, self._preset_var, *_SEARCH_PRESETS,
                          command=self._apply_search_preset).pack(side="left")
```

Add this method to the `FeedSettingsWindow` class (e.g. after `_render_fields`):

```python
    def _apply_search_preset(self, name):
        """Fill the Query field from a named preset so the GitHub search syntax
        never has to be typed."""
        query = _SEARCH_PRESETS.get(name)
        if query and "query" in self._fields:
            self._fields["query"].set(query)
```

- [ ] **Step 6: Add the `search` branch to `_on_add`**

In `feedkit/settings.py`, in `_on_add`, add an `elif` for `search` before the final `else` (the rss/json/text branch):

```python
        elif ftype == "search":
            raw["query"] = g("query")
            if g("items"):
                raw["items"] = _as_int(g("items"))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudClickAndMenu -v`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -v`
Expected: PASS (all tests; nothing regressed).

- [ ] **Step 9: Commit**

```bash
git add feedkit/settings.py tests/test_smoke_hud.py
git commit -m "$(cat <<'EOF'
feat(settings): add search feed type with query presets

A 'search' type with Title/Query/Items/Interval fields and a Preset menu
(my open PRs / awaiting my review / assigned to me) that fills the query.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage:**
- §3 token (reuse existing, `repo` scope) → no code; covered by reusing `github_headers` in Task 3 and the `no github_token` path (Tasks 3/4). ✅
- §4 `github_search_url`, `github_search_web_url`, `_VALID_TYPES`, `normalize_feed` validation incl. `out["query"]` → Task 1. ✅
- §5 `parse_search_items` (glyph PR/issue, repo, number, author label, draft→low, updated_at, html_url gate, total fallback) → Task 2. ✅
- §6 `_process_search` + dispatch (token-gated, conditional GET, stale-on-error) → Task 3. ✅
- §7 rendering (header count, web-url header link, 6-tuple rows with `dismiss=None`, overflow line, token/empty copy "none open") → Task 4. ✅
- §8 settings (`_TYPES`, field spec, presets, `_apply_search_preset`, `_on_add`) → Task 5. ✅
- §9 testing (model, parse, manager, smoke) → tests in every task. ✅
- §10 out-of-scope items are not implemented. ✅

**2. Placeholder scan:** No TBD/TODO; every code step contains complete code; every test step contains real assertions. ✅

**3. Type consistency:**
- `github_search_url(query, per_page)` and `github_search_web_url(query)` used identically in Tasks 1, 3, 4. ✅
- `parse_search_items(body, max_items) -> (list, int)` produced in Task 2, consumed in Task 3 with `feed["items"]` as `max_items`. ✅
- `NotifItem` built positionally in tests as `NotifItem(glyph, repo, num, label, urgency, ts, title, url)` — matches the field order `glyph, repo, number, reason_label, urgency, updated_at, title, url` with `thread_url` defaulted. ✅
- `FeedResult(state, items, status, error, badge)` used with `badge`=total throughout. ✅
- `_SEARCH_PRESETS` keys (`"My open PRs"`, `"Awaiting my review"`, `"Assigned to me"`) match the spec presets and the Task 5 test. ✅
- Insertion points named precisely (after the `notifications` branch in `_fetch_and_process` and `_feed_tiles`; after `_process_notifications`; before the `# github` block in `normalize_feed`). ✅
