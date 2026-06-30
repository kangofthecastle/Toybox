# HUD Web-Feed Plugin — Design

**Date:** 2026-06-29
**Status:** Approved (brainstorming complete)
**Toy:** HUD (`hud.pyw`)

## Overview

Extend the System Monitor HUD with a **web-feed plugin**: a generic engine that
fetches a URL / RSS / Atom / JSON source (or queries the GitHub API) on an
interval, parses it with no LLM involvement, and renders the result as a compact,
glanceable tile stacked below the existing CPU/RAM/clock rows. Feed items are
clickable (open in the default browser). Feeds are managed through a Settings
window. Everything is pure Python 3.12 standard library — **no pip, no
third-party packages, ever.**

This is the first of two HUD-expansion subsystems. A separate later spec covers
**local sensor tiles** (GPU usage, disk free space). CPU/GPU temperature and fan
speed are explicitly out of scope for the project: they require MSR reads through
a signed kernel driver, which the no-pip / no-driver constraint forbids.

## Goals

- A reusable fetch-on-interval engine with four parser adapters: `rss`
  (RSS 2.0 + Atom 1.0), `json` (path + field map), `text` (first lines / regex),
  and `github` (CI check-run status + unread-notification count).
- Network I/O on a single background worker thread; the Tk main loop never
  blocks. Results cross the thread boundary through a `queue.Queue` drained by an
  `after()` loop.
- Click an item → open its URL via `webbrowser`.
- A Settings UI (ttk.Notebook, modeled on `petkit/settings.py`) to add / edit /
  remove feeds and set the GitHub token; changes apply without restart.
- Pure parsing/scheduling logic isolated into testable modules with no network
  and no Tk; the network surface kept thin.

## Non-Goals (v1)

- GPU / disk / CPU-temp / GPU-temp / fan-speed sensors (separate spec; temp/fan
  infeasible under the constraints).
- Scrolling or pagination of tiles in the HUD (overflow beyond the screen-clamped
  height is dropped).
- Following `check-runs` pagination beyond the first 100 (first-100
  approximation; the truncation is logged once, see Open Risks).
- Notification pagination beyond the first page (unread count caps at 50 → render
  `50+`).
- Write actions (mark notifications read, etc.), HTML/image rendering, full
  article view, GitHub *trending* (no official API).

## Global Constraints

- **Pure Python 3.12 stdlib only.** Allowed: `tkinter`, `ctypes`, `winreg`,
  `winsound`, `wave`, `json`, `math`, `urllib.request`, `urllib.parse`,
  `urllib.error`, `ssl`, `xml.etree.ElementTree`, `email.utils`, `datetime`,
  `re`, `queue`, `threading`, `webbrowser`, `os`, `time`, `collections`. **No
  pip / third-party packages (including `certifi`, `defusedxml`, `feedparser`,
  `requests`).**
- **Win32 stays in `winkit/`.** Networking is stdlib, not Win32, so the new
  subsystem lives in a new `feedkit/` package (parallel to `petkit/`), not in
  `winkit/`.
- **Pure logic takes injected values** — no Tk, no `time.*`, no network inside
  the pure parser/model functions. The worker passes in `now` and raw bytes.
- **TDD** — failing test first, watched to fail, then minimal code.
- **Test runner:** `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`
  (bare `python` is the broken MS-Store stub, exit 49).
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **`config.json` is gitignored** (along with favorites.json/reminders.json/
  toybox.log/.superpowers/). Commit only when asked.
- TLS verification is **never** disabled. Only `http`/`https` URLs are opened.

## Architecture

### Module layout

```
feedkit/
  __init__.py
  model.py      # PURE  — Item/Status types; normalize_feed(); due_feeds();
  #                       build_conditional_headers(); strip_control_chars();
  #                       truncate(); is_web_url(); GitHub URL/header builders.
  parse.py      # PURE  — parse_rss / parse_json / parse_text;
  #                       parse_check_runs (reduce) / parse_notifications (count);
  #                       compose_github_status(). No network, no Tk.
  fetch.py      # NET   — fetch(): urllib + ssl GET with conditional headers,
  #                       timeout, size cap, 304/error taxonomy. Thin.
  manager.py    # GLUE  — FeedManager: one daemon worker thread + queue;
  #                       _run_once() orchestration -> _fetch_and_process()/
  #                       _process_github() (injected fetch_fn, unit-testable);
  #                       start()/stop()/drain()/set_feeds()/set_token().
  settings.py   # GUI   — FeedSettingsWindow (ttk.Notebook), like petkit/settings.py.
hud.pyw         # renders feed blocks under the metrics; click-to-open; menu;
                # owns FeedManager + the settings window.
config.py       # DEFAULTS gains top-level "feeds": [] and "hud"."github_token": "".
tests/
  test_feed_model.py   # normalize_feed, due_feeds, header builders, text helpers
  test_feed_parse.py   # all parsers + reductions + malformed/DOCTYPE/missing inputs
  test_feed_manager.py # process_feed/process_github with injected FetchResults
  test_smoke_hud.py    # (existing) still launches clean with feeds: []
```

This matches repo conventions: pure helpers isolated and tested (like
`sysmetrics.py`, `petkit/reminders.py`), GUI glue thin (`settings.py` like the
cat's), Win32 untouched in `winkit/`.

### Data flow

1. **Startup.** `hud.pyw` loads cfg, resolves the token (env first, see Token
   storage), builds `FeedManager(feeds, token)`, calls `start()` (spawns the
   daemon worker), and schedules `after(250, self._drain_feeds)`.
2. **Worker thread** (never touches Tk): loop every ~1 s — `due =
   model.due_feeds(feeds, last_fetch, now())`; for each due feed build the
   request(s), call `fetch.fetch(...)`, run `_fetch_and_process`/`_process_github`,
   `queue.put((idx, FeedResult))`, update `last_fetch[idx]` and the ETag/
   Last-Modified cache. Each feed wrapped in `try/except` — one failure can't
   stop the others or the loop. Obeys a stop `Event`.
3. **Main (Tk) thread.** `_drain_feeds()` pops everything from the queue
   (non-blocking) into `self.feed_state[idx]`, recomputes the window height,
   redraws changed blocks, stores per-line hit-regions, reschedules
   `after(250)`.
4. **Click.** `<ButtonRelease-1>` with `_moved == False` → hit-test against line
   regions → `webbrowser.open(url, new=2)` for `http`/`https` URLs.
5. **Settings.** Right-click → "Feeds…" opens the singleton window; saving
   validates via `model.normalize_feed`, writes cfg, `config.save`, and calls
   `manager.set_feeds(...)` (thread-safe swap). "Reload feeds" re-reads cfg.
6. **Close.** `manager.stop()` sets the Event; the daemon worker exits.

## Feed model & config schema

`config.py` `DEFAULTS` gains a top-level `"feeds": []` and `"hud"` gains
`"github_token": ""`. The existing `_coerce`/`_deep_merge` already pass lists and
strings through unchanged. The feed dicts inside the list are **opaque to
config.py** (it only type-checks known leaf keys), so each is re-validated by
`model.normalize_feed`.

### Config shapes (per feed type)

```jsonc
// RSS 2.0 or Atom 1.0 (HN, GitHub releases/commits/tags .atom, blogs, changelogs)
{"type":"rss",  "title":"HN",  "url":"https://news.ycombinator.com/rss", "items":3, "interval":600}

// JSON: walk dot-path to a list, map fields per item
{"type":"json", "title":"…", "url":"…", "path":"data.items",
 "fields":{"text":"title","url":"html_url"}, "items":3, "interval":600}

// Plain text: first capture group of regex, else first non-empty lines
{"type":"text", "title":"Status", "url":"…", "regex":"(?i)status:\\s*(\\w+)", "items":1, "interval":900}

// GitHub: CI check-run status + unread-notification count (REST API)
{"type":"github", "title":"Toybox", "repo":"kangofthecastle/Toybox", "branch":"main",
 "show":["ci","notifications"], "interval":120}
```

### `model.normalize_feed(raw: dict) -> dict`

Always returns a dict (never raises); on an invalid feed it returns the dict with
`valid=False` and a human `error` string so the HUD can render an error tile that
still shows the title. Normalization rules:

- `type` must be one of `rss`/`json`/`text`/`github`; otherwise `valid=False`,
  `error="unknown type '<x>'"`.
- `title` → str, default derived from url/repo or `"feed"`.
- `items` → int clamped to `1..10` (default 3; ignored for `github`).
- `interval` → int seconds, floored: `github` ≥ 120, others ≥ 300, hard floor 30.
- `rss`/`json`/`text` require a non-empty `url` (`http`/`https` scheme) else
  invalid. `json` requires `path` (str) and `fields` (dict with at least
  `text`). `github` requires `repo` matching `owner/name`; `branch` default
  `"main"`; `show` default `["ci","notifications"]`.
- Output dict carries every key with defaults filled, plus `valid`/`error`.

### `model.due_feeds(feeds, last_fetch, now, stagger=2.0) -> list[int]`

Pure. Returns indices where `now - last_fetch.get(i, -inf) >= interval`. On the
very first pass (`last_fetch` empty) it staggers initial fetches by
`i * stagger` seconds so all feeds don't fire on the same tick.

### Text & header helpers (pure)

- `strip_control_chars(s) -> str` — remove C0/C1 control chars except none kept;
  collapse whitespace runs to single spaces.
- `truncate(s, n) -> str` — to `n` chars with a trailing `…`.
- `build_conditional_headers(etag, last_modified) -> dict` — `{"If-None-Match":
  etag}` and/or `{"If-Modified-Since": last_modified}` when present (echo weak
  validators `W/"…"` verbatim).
- GitHub URL/header builders (pure strings):
  - `github_ci_url(repo, branch) -> str` →
    `https://api.github.com/repos/{repo}/commits/{quote(branch)}/check-runs?per_page=100`.
  - `github_notifications_url() -> str` → `https://api.github.com/notifications?per_page=50` (so the unread count can reach the "50+" threshold).
  - `is_web_url(url) -> bool` → True only for `http`/`https` (the single gate on what may be opened in a browser).
  - `github_headers(token) -> dict` →
    `{"User-Agent":"Toybox-WebFeed/1.0", "Accept":"application/vnd.github+json",
    "X-GitHub-Api-Version":"2022-11-28"}` plus `"Authorization": "Bearer "+token`
    when `token`.

### Data types

```python
Item   = namedtuple("Item",   ["text", "url"])            # url may be None
Status = namedtuple("Status", ["text", "state", "url"])   # state in success/failure/pending/none
```

## Parsers (`feedkit/parse.py`, pure)

All parsers run output text through `strip_control_chars` + `truncate`. All
return `[]` / safe defaults on malformed input rather than raising, **except**
the XML-safety guard which rejects hostile payloads (see Error handling).

### `parse_rss(body: bytes, items: int) -> list[Item]`

1. **XML-safety guard:** if the payload contains a `DOCTYPE` or `ENTITY`
   declaration, refuse (`raise ValueError("unsafe XML")`). Legitimate RSS/Atom
   never need them; this blocks entity-expansion ("billion laughs") attacks,
   since `xml.etree.ElementTree` is vulnerable and the size cap doesn't bound
   in-memory expansion.
2. `root = ET.fromstring(body)`; `tag = root.tag.split('}')[-1]`.
3. **RSS** (`tag == 'rss'` or `'RDF'`): `items = root.find('channel').findall('item')`;
   per item `title = findtext('title')`, `url = findtext('link')` (URL is element
   **text**).
4. **Atom** (`tag == 'feed'`): ns `{http://www.w3.org/2005/Atom}`;
   `entries = root.findall(ns+'entry')`; `title = findtext(ns+'title')`;
   `url` = the `<link>` whose `rel` is `alternate` or absent, then `.get('href')`
   (URL is an **attribute**).
5. Match child elements by local-name (`child.tag.split('}')[-1]`) so extra
   namespaces (`dc:`, `content:`, `media:`) don't break extraction. Take the
   first `items`.

### `parse_json(body, path, fields, items) -> list[Item]`

`json.loads`; walk `path` (dot-separated keys; integer-looking segments index
lists) to a list; per element `text = element.get(fields['text'])`,
`url = element.get(fields['url'])` when present. Missing keys → blank text / None
url, never crash. Take first `items`.

### `parse_text(body, content_type, regex, items) -> list[Item]`

Decode using the charset from `content_type` (fallback `utf-8`,
`errors="replace"`). If `regex` is given, return one `Item` with the first
capture group (or whole match). Else return the first `items` non-empty lines.
URL is the source `url` (passed by the worker) or None.

### GitHub adapter

- `parse_check_runs(body: bytes) -> str` → one of `none`/`pending`/`success`/
  `failure`:
  - parse JSON, read `check_runs` (array).
  - empty → `none`.
  - any run `status != "completed"` → `pending`.
  - all completed → `success` iff every `conclusion ∈ {success, neutral,
    skipped}`; otherwise `failure` (any of `failure, timed_out, action_required,
    cancelled, stale`).
- `parse_notifications(body: bytes) -> int` → `len(json.loads(body))` (the
  endpoint returns unread-only by default), defensively filtering
  `unread == true`.
- `compose_github_status(repo, branch, ci_state, notif_count, ci_shown=True) -> Status`:
  - `state` = `ci_state` (`success`/`failure`/`pending`/`none`).
  - `text` = `"<repo-name> ● <ci-word>"` (passing/failing/pending/—) when `ci_shown`,
    else just `"<repo-name>"`; plus `"  🔔 N"` (or `"50+"`) when `notif_count` is not None.
  - `url` = `https://github.com/{repo}/actions` when `ci_shown`, else
    `https://github.com/notifications` (notifications-only tile). The HUD makes this
    URL the click target of the github tile's header line (http/https only).

**Worker orchestration for a `github` feed.** CI (`check-runs`) is fetched when
`"ci"` is in `show` (anonymous is fine for a public repo). The notifications
call **requires a token** — when `"notifications"` is in `show` *and* a token is
resolved, fetch `/notifications` and pass its count; **with no token, skip the
notifications call** and pass `notif_count = None` (CI-only tile, no error). If
`show` has neither, the feed is invalid at `normalize_feed`. Each of the (up to
two) API calls carries its own ETag cache entry.
- The HUD maps `state` → hex + glyph: `success` `#3fb950` ●, `failure` `#f85149`
  ●, `pending` `#d29922` ●, `none` `#6a6a78` ●.

## Fetch / transport (`feedkit/fetch.py`, network, thin)

```python
FetchResult = namedtuple("FetchResult",
    ["status", "body", "content_type", "etag", "last_modified", "error"])
# status in {"ok", "not_modified", "error"}

def fetch(url, headers=None, etag=None, last_modified=None,
          timeout=12, max_bytes=1_000_000) -> FetchResult: ...
```

Verified behavior (Python 3.12.10 / OpenSSL 3.0.16 on Windows 10):

- **TLS:** `urllib.request.urlopen` uses `ssl.create_default_context()`, which
  calls `load_default_certs()` reading the Windows **CA + ROOT** stores. **No
  certifi.** `verify_mode=CERT_REQUIRED`, `check_hostname=True`; never disabled.
- **Headers:** always set an explicit `User-Agent` (default urllib UA can get a
  403 from GitHub). Merge caller `headers` + `build_conditional_headers`.
- **No `Accept-Encoding`** sent → identity bytes (urllib does not auto-
  decompress).
- **304 detection:** a conditional request that is unchanged makes `urlopen`
  **raise** `urllib.error.HTTPError` with `.code == 304` (not return a response).
  Catch it → `status="not_modified"`, `body=None`.
- **Timeout & size cap:** `urlopen(req, timeout=timeout)`; `body = r.read(max_bytes+1)`;
  if `len(body) > max_bytes` → `status="error"`, `error="too large"`.
- **Error taxonomy** (caught in this order):
  1. `HTTPError` with `.code == 304` → `not_modified`.
  2. other `HTTPError` → `error`, message from code (`403`→"rate-limited / bad
     token" — inspect `x-ratelimit-remaining`; `404`→"no access"; `401`→"bad
     token").
  3. `URLError` whose `.reason` is an `ssl.SSLError` (e.g.
     `SSLCertVerificationError`) → `error`, "cert error".
  4. other `(URLError, TimeoutError)` → `error`, "offline" (a *read* timeout
     raises a bare `TimeoutError` not wrapped in URLError — both must be
     caught).
- On `ok`: return new `etag` (`r.headers.get("ETag")`), `last_modified`
  (`r.headers.get("Last-Modified")`), and `content_type`.

## GitHub specifics (verified against official docs)

- **CI status:** `GET /repos/{owner}/{repo}/commits/{branch}/check-runs?per_page=100`.
  The branch name resolves to HEAD server-side (no separate SHA lookup); percent-
  encode a `branch` containing `/`. The **legacy combined `/status` endpoint does
  NOT reflect GitHub Actions** — check-runs is mandatory. Reduce client-side
  (see `parse_check_runs`). No single pre-combined rollup endpoint exists.
- **Notifications:** `GET /notifications` (unread-only by default; page cap 50).
- **Auth model:** a **classic** PAT only (fine-grained PATs are unsupported for
  notifications and unreliable for checks). Scopes: `notifications` (required for
  the notifications feature) plus `repo` **only** for private-repo CI. Public-
  repo CI works with **no token**.
- **Rate limits / cadence:** unauthenticated 60/hr per IP; authenticated
  5,000/hr. Default `github` interval 120 s (= 30 req/hr per tile). Use ETag
  conditional requests: an **authenticated** 304 is free against the limit;
  **anonymous** 304s still count (see Open Risks). The 120 s `github` interval
  floor already exceeds GitHub's `X-Poll-Interval` minimum (≈60 s), so the header
  is **not** dynamically honored in v1 (non-goal); a server-raised value above
  120 s is the only unhandled case.

### Token storage (decision)

Resolve the token from `os.environ["TOYBOX_GITHUB_TOKEN"]` **first**; if unset,
fall back to the optional `cfg["hud"]["github_token"]` (written by the Settings
"GitHub" tab; `config.json` is gitignored). The Settings tab labels the active
source. Rationale: a classic `repo`-scoped PAT grants read/write to all repos, so
it stays off disk by default while still allowing the UI path. Two documented
ways to shrink the blast radius: use only the narrow `notifications` scope (skip
private CI), or make the watched repo public (CI then needs no token at all). The
token is never logged.

## HUD rendering & interaction (`hud.pyw`)

- **Layout.** Width stays 220 px. Below the existing CPU/RAM/clock rows, each
  feed renders a **block**: a header line (feed title; for `github`, the colored
  ● + CI word + `🔔 N`) then up to `items` truncated item lines. The window
  `HEIGHT` is recomputed from stacked content and clamped to the screen work
  area; content beyond the clamp is dropped.
- **Canvas item strategy.** Metrics keep their persistent items (1 Hz). Feed
  blocks **recreate their text items on update** (low churn — minutes apart).
  Each rendered item line is tagged with its `(y0, y1, url)` for hit-testing.
- **Failure rendering.** A feed in `error`/`stale` state shows its last-good
  lines dimmed with a small `!` and the taxonomy word ("offline", "rate-
  limited", "bad token", "no access", "cert error", "too large").
- **Click-to-open.** `_on_release` (when `not self._moved`) hit-tests the release
  point against stored line regions; a hit on a line with an `http`/`https` URL
  calls `webbrowser.open(url, new=2)`. Drag and the right-click menu are
  unchanged.
- **Menu additions** (above the existing opacity/lock/close): **"Feeds…"** (open
  settings), **"Reload feeds"**, separator.
- **Drain loop.** `after(250, self._drain_feeds)`; `_drain_feeds` applies
  `manager.drain()` updates and reschedules.
- **Close.** `Hud` calls `manager.stop()` on window destroy.

## Settings UI (`feedkit/settings.py`)

A singleton `FeedSettingsWindow` (a `ttk.Notebook` `Toplevel`), modeled on
`petkit/settings.py` (guards every `after()`/refresh against `TclError`, reused as
a singleton, reads/writes the live cfg, calls back into the HUD for actions):

- **"Feeds" tab.** A list of configured feeds (title + type + ✕ remove) over an
  "Add" row: a type dropdown (`rss`/`json`/`text`/`github`) that reveals the
  type-specific fields (`url`; or `repo`/`branch`/`show` for github; `path` +
  `fields` for json; `regex` for text), plus `items` and `interval`. "Save"
  validates via `model.normalize_feed`, writes `cfg["feeds"]`, calls
  `config.save`, and `manager.set_feeds(...)`.
- **"GitHub" tab.** A token entry (writes `cfg["hud"]["github_token"]`), a one-
  line scope hint ("classic PAT; `notifications` scope, plus `repo` for private-
  repo CI"), a label showing the active token source (env var vs config), and a
  "Test" button that performs a single `/notifications` request and reports
  `OK (N unread)` / `rate-limited` / `bad token` / `offline`.

## Error handling & security

- **XML safety:** `parse_rss` rejects any payload with a `DOCTYPE`/`ENTITY`
  declaration before parsing (no `defusedxml` available). Oversized payloads are
  rejected by the fetch size cap.
- **Isolation:** every per-feed fetch+parse is wrapped in `try/except` in the
  worker; one feed's failure → its tile shows stale/error, the others and the
  loop are unaffected.
- **Rendering safety:** GET only; remote text rendered as plain text with control
  chars stripped and lines truncated; only `http`/`https` URLs are opened.
- **Secret handling:** token resolved env-first, never written to disk unless the
  user pastes it into the Settings field, never logged.

## Testing strategy (TDD)

- **`test_feed_model.py`** (pure): `normalize_feed` for each type incl. invalid
  (unknown type, missing url/path/fields/repo, out-of-range items/interval);
  `due_feeds` (first-pass stagger, interval gating); `build_conditional_headers`;
  `strip_control_chars`/`truncate`; GitHub URL/header builders (incl. branch with
  `/` percent-encoding and token-present vs absent).
- **`test_feed_parse.py`** (pure, captured fixtures): `parse_rss` on real HN RSS
  and GitHub `.atom` bytes (title + correct URL accessor for each format),
  namespaced Atom, malformed XML, and the DOCTYPE/ENTITY rejection;
  `parse_json` with nested path + missing fields; `parse_text` regex vs lines;
  `parse_check_runs` reduction table (empty→none, in_progress→pending,
  all-success→success, neutral/skipped→success, failure/timed_out→failure);
  `parse_notifications` count; `compose_github_status` text/state/url.
- **`test_feed_manager.py`**: `_run_once` (calling `_fetch_and_process`/
  `_process_github`) driven by an injected `fetch_fn` returning canned
  `FetchResult`s (ok / not_modified / error) — no real thread or network;
  verifies a 304 keeps prior items, an error after success yields `stale`, a 200
  with unparseable bytes also yields `stale` (`bad data`), no-token skips
  notifications, and `ok` dispatches to the right parser. `set_feeds` swap clears
  the cache under the lock.
- **`test_smoke_hud.py`** (existing + new Tk-construction tests): the existing
  smoke test still launches clean and exits with `feeds: []`; `hud.pyw` skips
  `manager.start()` under `_smoke_ms()` so the smoke run does no network
  regardless of the local `config.json`. The new in-process Tk tests stub
  `feedkit.fetch.fetch` (offline) and isolate `CFG_PATH` to a temp dir.
- `fetch.py` is the only network-only / integration surface and is kept thin;
  it is not unit-tested against the live network.

## Open risks (call out in the plan)

1. **Anonymous 304s still count** against the 60/hr per-IP limit (the exemption
   requires an `Authorization` header). Several token-less `api.github.com` tiles
   at a short interval can exhaust 60/hr. Mitigation: provide a token, or keep
   anonymous API tiles few/slow. Prefer the unauthenticated `.atom` feeds for
   "what's new" (no API budget) and reserve the API for CI/notifications.
2. **Fine-grained PATs don't work** for notifications (classic-only) or reliably
   for checks. The Settings hint must say "classic PAT."
3. **Windows ROOT store is populated on demand** (CryptoAPI auto-root update); on
   offline/locked-down machines a public root may be absent → `CERTIFICATE_
   VERIFY_FAILED`. Surface as a distinct "cert error" tile, never a crash.
4. **check-runs pagination:** repos with >100 checks compute overall state from a
   partial set. v1 uses the first 100 and logs the truncation once.
5. **Legacy `/status` `pending` when `total_count == 0`** means "no legacy CI,"
   not real pending — only relevant if a future version merges `/status`; v1 does
   not use it.
6. **RSS `<link>` text vs Atom `<link href>`** is the classic broken-link trap;
   the parser uses the format-specific accessor and the `rel="alternate"` Atom
   link.
7. **Date parsing** of nonstandard `pubDate`/`updated` must fall back gracefully
   (sort to bottom / keep item) rather than drop or raise.
8. **Classic `repo` PAT is broad** — document the blast radius; env-var-first
   storage; never logged.

## References (verified 2026-06-29)

- GitHub Checks (check-runs): https://docs.github.com/en/rest/checks/runs
- GitHub Commit statuses (why it misses Actions):
  https://docs.github.com/en/rest/commits/statuses
- GitHub Notifications: https://docs.github.com/en/rest/activity/notifications
- GitHub rate limits & conditional-request exemption:
  https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api
- GitHub API versions / required headers:
  https://docs.github.com/en/rest/using-the-rest-api/getting-started-with-the-rest-api
- Python `ssl` (Windows cert store via `load_default_certs`):
  https://docs.python.org/3.12/library/ssl.html
- Python `urllib.request` (304 → HTTPError, timeout, size cap):
  https://docs.python.org/3.12/library/urllib.request.html
- Python `xml.etree.ElementTree` (entity-expansion vulnerability):
  https://docs.python.org/3/library/xml.etree.elementtree.html
- Python `webbrowser`: https://docs.python.org/3.12/library/webbrowser.html
- Hacker News RSS: https://news.ycombinator.com/rss ; alternatives:
  https://hnrss.github.io/
- GitHub per-repo Atom feeds: `https://github.com/{owner}/{repo}/releases.atom`
  (also `commits/{branch}.atom`, `tags.atom`)
