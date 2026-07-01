# HUD Search Feed (My PRs / Reviews / Assigned) — Design

**Status:** Approved (2026-06-30)
**Branch:** `hud-notifications-tile`
**Follows:** `2026-06-30-hud-notifications-tile-design.md`, `2026-06-30-hud-notifications-dismiss-design.md`

## 1. Problem

GitHub never raises a notification for your *own* actions, so a PR you opened
yourself never appears in the notifications tile. The user wants the HUD to
surface, at a glance:

- **My open PRs** — `is:open is:pr author:@me`
- **Awaiting my review** — `is:open is:pr review-requested:@me`
- **Assigned to me** — `is:open assignee:@me`

These are not notifications; they are GitHub *search* results. They need their
own feed type.

## 2. Approach

A new **`search`** feed type. Its config carries a raw GitHub search `query`
string. The manager fetches `GET /search/issues?q=…` with the existing
`github_token`, parses the results into `NotifItem` rows, and the HUD renders
them with the **same two-line row** the notifications tile already uses — but
with **no dismiss (✕)** action, because search results are not dismissible
threads. Clicking a row opens the PR/issue in the browser.

The user adds one `search` feed per bucket they want. The three queries above
are offered as **presets** in Settings so the GitHub search syntax never has to
be typed.

**Rejected alternatives:**
- *Fixed `prs` type with an author/review/assigned dropdown* — rigid; every new
  filter ("stuff like that") needs a new enum value and code. The raw-query type
  covers all of them and anything future with one implementation.
- *Folding PRs into the notifications tile* — conflates a different data source
  (search vs. notifications) and mixes non-dismissible rows with dismissible
  notification threads.

## 3. Token

**No new or different token is required.** Search reuses the existing
`hud.github_token` via `model.github_headers(token)` — the same header the
notifications tile sends. The PAT must carry the **`repo` scope** to see PRs in
*private* repos and to resolve `@me`; a notifications-only token returns public
results only. (If private-repo notifications already work, the scope is present.)
With no token the feed renders `! set GitHub token in Settings`, exactly like the
notifications feed.

## 4. Data Model & URL (`feedkit/model.py`)

Add a URL builder:

```python
def github_search_url(query, per_page):
    """Issue/PR search endpoint, newest-updated first. `query` is the raw GitHub
    search expression (e.g. 'is:open is:pr author:@me'); it is percent-encoded."""
    return "%s/search/issues?q=%s&sort=updated&order=desc&per_page=%d" % (
        GITHUB_API, urllib.parse.quote(query), per_page)
```

`per_page` is the feed's `items` (1–10). No new namedtuple — search rows reuse
`NotifItem`. For a search row, `thread_url` stays `""` (its default), which is
what suppresses the ✕.

A companion builder maps a query to its browser search page (for the header and
the "… N more" overflow line):

```python
def github_search_web_url(query):
    """github.com search UI for `query` (covers issues and PRs)."""
    return "https://github.com/search?q=%s&type=issues" % urllib.parse.quote(query)
```

### Validation (`normalize_feed`)

Add `"search"` to `_VALID_TYPES`. A `search` feed validates as:

- `query`: required non-empty string, stored as `out["query"]` (stripped) →
  else `valid=False, error="search feed needs 'query'"`. The manager and HUD
  read `feed["query"]`.
- `items`: `_coerce_int(raw.items, 5, 1, 10)`.
- `interval`: `_coerce_int(raw.interval, 300, 120, 86400)` (floor 120, default 300).
  Search API permits 30 requests/min authenticated, so a 300 s poll is far
  inside budget even with all three feeds.
- `title`: `raw.title` or default `"Search"`.

## 5. Parsing (`feedkit/parse.py`)

```python
def parse_search_items(body, max_items):
    """Parse a /search/issues response into (list[NotifItem], total_count).
    total_count drives the title count; the list is capped at max_items.
    Defensive against missing keys and non-list items."""
```

Per result item in `data["items"]` (a list; `data["total_count"]` an int):

- **glyph** — `model.glyph_for("PullRequest")` (⇄) if the item has a
  `"pull_request"` key, else `model.glyph_for("Issue")` (◉).
- **repo** — derived from `repository_url`
  (`https://api.github.com/repos/owner/name` → `owner/name`); `""` if absent.
- **number** — `"#" + str(item["number"])` when numeric, else `""`.
- **reason_label** — the author login: `"@" + item["user"]["login"]` (used
  as-is; line 1 is pixel-fit by the existing `_fit_line1`, same as notifications,
  so a long login just truncates the line, not the field). `""` if absent.
- **urgency** — `"low"` when the item is a **draft** PR (`item.get("draft")`),
  else `"normal"`. (Draft PRs render dim.)
- **updated_at** — `_parse_ts(item.get("updated_at"))`.
- **title** — `_clean(item.get("title") or "")`.
- **url** — `item.get("html_url")` when it is an http/https URL (already a
  `github.com` link), else `""` (no click target; never a dead/api/exotic URL).
- **thread_url** — omitted (defaults to `""`).

Missing `total_count` falls back to `len(items)`. A non-dict body or missing
`items` list → `([], 0)`.

## 6. Manager (`feedkit/manager.py`)

Add a `"search"` branch to `_fetch_and_process` dispatching to
`_process_search`, modeled exactly on `_process_notifications` (single cache key
= `idx`; conditional GET; stale-on-error / bad-data carries previous
`items` + `badge`):

```python
def _process_search(self, idx, feed, token):
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

The search endpoint may not honor conditional requests; if it always returns
`200`, the parse path runs each poll — still cheap. No `X-Poll-Interval`
handling (that is notifications-specific).

## 7. Rendering (`hud.pyw`)

**No new draw code.** Add a `search` branch to `_feed_tiles`, paralleling the
`notifications` branch but simpler:

- Header: `title + "  (%d)" % (result.badge or 0)` (the match count), click
  target = `model.github_search_web_url(feed["query"])` so clicking the header
  opens the full results on github.com. No `header_action` (nothing to mark-all).
- For each `NotifItem`: yield the existing **6-tuple**
  `(line1, url, color, subtitle, age, dismiss)` with `dismiss=None`:
  - `color` = `FEED_DIM` when stale, else `URGENCY_HEX.get(it.urgency, FEED_FG)`.
  - `line1 = "%s %s%s · %s" % (glyph, _repo_short(repo), num, reason_label)` —
    identical shape to notifications.
  - `subtitle = it.title`, `age` from `it.updated_at`.
- Overflow: when `(result.badge or 0) > len(result.items)`, append a dim
  `("… %d more" % extra, model.github_search_web_url(feed["query"]), True)`
  line (clickable to the full search), mirroring the notifications tile.
- Token/empty states reuse the notifications copy:
  - `no github_token` → `! set GitHub token in Settings`.
  - `result.error and not result.items` → `! <error>`.
  - `state == "ok" and not result.items` → `inbox zero` → use `"none open"`.

Because `dismiss=None`, `_draw_feeds`'s existing `len(row) == 6` path renders
two lines with no ✕ and registers only the open-URL hit. No changes to
`_draw_feeds`, `_on_release`, `_register_action`, or `_action_at`.

## 8. Settings (`feedkit/settings.py`)

- Add `"search"` to `_TYPES`.
- `_render_fields` spec for `search`:
  `[("title","Title"), ("query","Query"), ("items","Items"), ("interval","Interval s")]`.
- A **Preset** `OptionMenu` shown only for the `search` type that writes one of
  the three preset strings into the Query field:
  - `My open PRs` → `is:open is:pr author:@me`
  - `Awaiting my review` → `is:open is:pr review-requested:@me`
  - `Assigned to me` → `is:open assignee:@me`
- `_on_add` builds `{"type":"search", "title":…, "query":…, "items":…, "interval":…}`
  (interval/items only when provided), runs it through `normalize_feed`, and
  rejects on `valid=False` with the error shown in the existing status label.

## 9. Testing

Pure unit tests (no network, no Tk):

- `model.github_search_url` — encodes the query, includes `sort=updated`,
  `order=desc`, and `per_page`.
- `model.github_search_web_url` — encodes the query into a `github.com/search`
  URL and passes `is_web_url`.
- `normalize_feed` (search) — valid query; missing/empty query rejected;
  items/interval coercion and floors; default title.
- `parse_search_items` — a PR result (⇄, repo, `#num`, author label, age, url);
  an issue result (◉); a draft PR → `urgency=="low"`; missing `user`/`number`/
  `html_url` tolerated; empty `items` → `([], 0)`; `total_count` surfaced.
- `manager._process_search` — no-token → `no github_token`; error response with
  a cached `prev` → `stale` carrying prev items + badge; ok response caches and
  returns `total` as badge. Driven via an injected fake `fetch_fn` and
  `_run_once`, like the existing manager tests.
- Smoke test — a `search` feed in config renders rows with no ✕ and a clickable
  open hit.

## 10. Out of Scope (YAGNI)

- Per-PR CI/review status (extra API calls per row).
- Mark-as-read / dismiss for search rows (they are not threads).
- Closed/merged results, pagination beyond `items`, custom sort.
- Auto-creating the three feeds — the user adds the ones they want via presets.
