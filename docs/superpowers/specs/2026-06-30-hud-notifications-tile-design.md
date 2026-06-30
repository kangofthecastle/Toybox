# HUD Notifications Tile — Design

> Extends the web-feed plugin (`feedkit/`) with a new global GitHub notifications
> feed type that renders an **actionable, 2-line-per-item** tile in the HUD.

**Goal:** Add a dedicated `notifications` feed type that shows the authenticated
user's unread GitHub notifications **across all repos** as a glanceable, clickable
list — type glyph, repo, number, reason, and age per item — not just a count.

**Architecture:** A new feed `type` ("notifications") reusing the existing
`feedkit` worker/queue/render pipeline. Pure classification + URL derivation in
`model.py`; a pure `parse_notification_items` in `parse.py`; a `_process_notifications`
worker method in `manager.py`; a 2-line render path in `hud.pyw`. No new module.

**Tech Stack:** Python 3.12 stdlib only (urllib, json, datetime, tkinter). Reuses
`model.github_notifications_url()`, `model.github_headers()`, `feedkit.fetch.fetch`,
and the existing `timeago.format_ago` helper.

## Global Constraints

- **Pure Python 3.12 stdlib ONLY.** No pip / third-party packages ever (no
  `requests`, `certifi`, `defusedxml`). Network via `urllib` only.
- **TLS verification is NEVER weakened.**
- **Only http/https URLs may ever be opened.** `model.is_web_url` is the single
  gate, already enforced in `_register_hit` (hud.pyw:266) and `_open_at` (hud.pyw:325).
  Every URL this feature produces MUST be an `https://github.com/...` literal.
- Win32 glue stays in `winkit/` (not touched here).
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Test runner: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`.
- **Existing single-line feeds (rss/json/text/github) must remain byte-for-byte
  unchanged in behavior.** Backward compatibility is a hard requirement.

---

## 1. Config schema

A new feed dict shape (added to the user's `config.json` `feeds` list):

```jsonc
// Global, all-repos GitHub notifications. No url/repo. Uses hud.github_token.
{"type":"notifications", "title":"Notifications", "items":5, "interval":300}
```

- `items` → int clamped **1..10, default 5** (max items rendered; the header badge
  still shows the true unread total).
- `interval` → int seconds, **default 300, floor 120** (GitHub's polling guidance;
  see §7). No `url`, `repo`, `branch`, `show`.
- Requires a **classic PAT** in `hud.github_token` with scope `notifications`
  (+ `repo` for private-repo notifications). With no token the tile renders an
  explanatory error line (§6).

## 2. Canonical tables (single source of truth)

These resolve the contradictions the research surfaced. Implement EXACTLY these.

### 2a. `subject.type` → glyph

Every glyph below is from the set the user confirmed renders crisply in Consolas 9
(`⇄ ◉ 💬 🏷 ⚑`). No untested glyph ships.

| subject.type | glyph | codepoint |
|---|---|---|
| PullRequest | ⇄ | U+21C4 |
| Issue | ◉ | U+25C9 |
| Discussion | 💬 | U+1F4AC |
| Release | 🏷 | U+1F3F7 |
| CheckSuite | ⚑ | U+2691 |
| WorkflowRun | ⚑ | U+2691 |
| Commit | ◉ | U+25C9 |
| RepositoryVulnerabilityAlert | ⚑ | U+2691 |
| SecurityAdvisory | ⚑ | U+2691 |
| RepositoryDependabotAlertsThread | ⚑ | U+2691 |
| *(any other / unknown)* | ◉ | U+25C9 |

### 2b. `reason` → label (≤8 chars) and urgency tier

| reason | label | urgency |
|---|---|---|
| review_requested | review | high |
| mention | @you | high |
| team_mention | @team | high |
| assign | assign | high |
| author | author | high |
| approval_requested | approve | high |
| security_alert | security | high |
| comment | comment | normal |
| state_change | update | normal |
| ci_activity | CI | normal |
| manual | manual | normal |
| invitation | invite | normal |
| push | push | normal |
| subscribed | watch | low |
| your_activity | you | low |
| security_advisory_credit | credit | low |
| member_feature_requested | feature | low |
| *(unknown)* | `reason.replace("_"," ")[:8]` | low |

### 2c. urgency → color (all from the existing HUD palette, hud.pyw:36-52)

| urgency | color | constant |
|---|---|---|
| high | `#d29922` | `STATE_HEX["pending"]` (amber — "needs you") |
| normal | `#c8c8d4` | `FEED_FG` |
| low | `#6a6a78` | `FEED_DIM` |
| *(stale/error override)* | `#6a6a78` | `FEED_DIM` — dims the whole tile |

> **No red "CI failed" tier.** The `/notifications` payload carries no CI
> conclusion (only `subject.type/title/url`), so pass/fail is unknowable without an
> extra per-thread API call. Dropped as infeasible.

### 2d. `subject.url` (an api.github.com URL, possibly null) → github.com browser URL

A **pure** function `model.notification_url(subject_type, subject_url, repo_full)`:

```
PREFIX = "https://api.github.com/repos/"
repo_base = "https://github.com/" + repo_full        # repo_full = "owner/name"

if not repo_full:                       return "https://github.com/notifications"
if subject_url and subject_url.startswith(PREFIX):
    tail = subject_url[len(PREFIX):]                  # "owner/name/pulls/34"
    if subject_type == "PullRequest":   tail = tail.replace("/pulls/", "/pull/", 1)
    elif subject_type == "Commit":      tail = tail.replace("/commits/", "/commit/", 1)
    elif subject_type == "SecurityAdvisory":
                                        tail = tail.replace("/security-advisories/", "/security/advisories/", 1)
    elif subject_type == "CheckSuite":  return repo_base + "/actions"   # no web page for suite id
    return "https://github.com/" + tail
# null url, or a non-/repos url (e.g. TeamDiscussion /organizations/...): safe fallback subpage
FALLBACK = {"PullRequest":"/pulls", "Issue":"/issues", "Discussion":"/discussions",
            "Release":"/releases", "CheckSuite":"/actions", "WorkflowRun":"/actions",
            "Commit":"/commits", "RepositoryVulnerabilityAlert":"/security/dependabot",
            "SecurityAdvisory":"/security/advisories",
            "RepositoryDependabotAlertsThread":"/security/dependabot"}
return repo_base + FALLBACK.get(subject_type, "")
```

**Invariant:** the result ALWAYS begins `https://github.com/` ⇒ `is_web_url` is
always True. The renderer still gates through `is_web_url` (defense in depth). PR
and Issue (the overwhelming majority) get exact deep links; exotic/null cases fall
back to a safe repo subpage rather than a dead api URL or a crash.

## 3. Data type (`feedkit/model.py`)

Add immediately after `Item` (model.py:9):

```python
NotifItem = namedtuple("NotifItem",
    ["glyph", "repo", "number", "reason_label", "urgency", "updated_at", "title", "url"])
# urgency is the tier string "high"/"normal"/"low" — the HUD maps it to a palette
# color (§2c). number is a display token: "#34", "" (kept pure of presentation hex).
# updated_at is a float unix timestamp (0.0 if the API value was missing/unparseable).
```

> **Decision: a NEW namedtuple, not extending `Item`.** `Item` has 2 fields; adding
> 6 would break every existing unpack/attribute site. A distinct `NotifItem` lets the
> renderer branch on tuple length, leaving every `Item` path provably untouched.

Pure helpers (also in `model.py`, near the other `github_*` helpers):
`glyph_for(subject_type)`, `reason_label(reason)`, `urgency_for(reason)`,
`notification_url(...)` (§2d) — driven by module-level dicts/frozensets matching §2a–2c.

## 4. `normalize_feed` (`feedkit/model.py:102`)

- Add `"notifications"` to `_VALID_TYPES` (model.py:82).
- Add a branch (after the rss/json/text `return out` at model.py:145, before the
  github block):

```python
if ftype == "notifications":
    out["items"] = _coerce_int(raw.get("items"), 5, 1, 10)
    out["interval"] = _coerce_int(raw.get("interval"), 300, 120, 86400)  # default 300, floor 120
    out["title"] = title or "Notifications"
    return out
```

> Note: the generic interval line (model.py:119-120) uses `default == floor`. For
> notifications the default (300) differs from the floor (120), so set `interval`
> **inside** this branch (do not rely on the generic line). No url/repo required;
> never raises.

## 5. Parser (`feedkit/parse.py`)

Add `parse_notification_items(body, max_items) -> tuple[list[NotifItem], int]`
**after** the existing `parse_notifications` count function (parse.py:151) — which
**stays** (it is still used by the github tile; do not rename/remove it).

```python
def parse_notification_items(body, max_items):
    data = json.loads(body)
    if not isinstance(data, list):
        return [], 0
    unread = [n for n in data if isinstance(n, dict) and n.get("unread", True)]
    total = len(unread)
    out = []
    for n in unread[:max_items]:
        subj = n.get("subject") or {}
        stype = subj.get("type") or ""
        repo = (n.get("repository") or {}).get("full_name") or ""
        suburl = subj.get("url") or ""                 # JSON null -> "" (NO .get(k,"") — that keeps None)
        seg = suburl.rsplit("/", 1)[-1] if suburl else ""
        number = "#" + seg if seg.isdigit() else ""
        reason = n.get("reason") or ""
        out.append(model.NotifItem(
            glyph=model.glyph_for(stype),
            repo=repo,
            number=number,
            reason_label=model.reason_label(reason),
            urgency=model.urgency_for(reason),
            updated_at=_parse_ts(n.get("updated_at")),
            title=_clean(subj.get("title") or ""),
            url=model.notification_url(stype, subj.get("url"), repo),
        ))
    return out, total
```

- `_parse_ts(s)`: `datetime.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()`
  wrapped in `try/except (TypeError, ValueError, AttributeError): return 0.0`. (Add
  `import datetime` to parse.py.)
- **Null-url safety:** use `subj.get("url") or ""` (NOT `subj.get("url","")`) —
  `dict.get(k, default)` returns the default only when the key is *missing*, not when
  the value is JSON `null`; `RepositoryInvitation` always has `subject.url == null`.
- `total` (the true unread count on this page) drives the header badge; capped at the
  API's `per_page=50` (the badge renders "50+" at ≥50, §6).

## 6. Worker (`feedkit/manager.py`)

- `FeedResult` (manager.py:15) gains a 5th field with a default so all six existing
  4-arg constructions are unaffected:
  ```python
  FeedResult = namedtuple("FeedResult", ["state","items","status","error","badge"], defaults=(None,))
  ```
- In `_fetch_and_process` (manager.py:88), dispatch **before** the github branch:
  ```python
  if feed["type"] == "notifications":
      return self._process_notifications(idx, feed, token)
  ```
- `_process_notifications(idx, feed, token)` (single cache key = `idx`, mirroring
  rss/json/text — only one request, unlike github's compound keys):
  1. **No token:** `return FeedResult("error", [], None, "no github_token", None)` (no
     cache write; `_run_once` still stamps `_last[idx]` so the interval is respected).
  2. Snapshot `cache = self._cache.get(idx, {})` under the lock.
  3. `res = self._fetch(model.github_notifications_url(), headers=model.github_headers(token),
     etag=cache.get("etag"), last_modified=cache.get("lm"))`.
  4. **304 not_modified:** `return cache.get("result") or FeedResult("ok", [], None, None, 0)`.
  5. **error:** `prev = cache.get("result"); return FeedResult("stale" if prev else "error",
     prev.items if prev else [], None, res.error, prev.badge if prev else None)`.
  6. Parse in `try/except` (stale-on-bad-data): on exception
     `return FeedResult("stale" if prev else "error", prev.items if prev else [], None, "bad data", prev.badge if prev else None)`.
  7. **ok:** `items, total = parse.parse_notification_items(res.body, feed["items"])`;
     cache `{"etag":res.etag,"lm":res.last_modified,"result":result}` under lock;
     `return FeedResult("ok", items, None, None, total)`.
- **X-Poll-Interval (§7):** on success, if `res.poll_interval` is set, store it under
  lock in `self._poll_min[idx]`.

## 7. Honoring `X-Poll-Interval`

GitHub returns an `X-Poll-Interval` header (seconds; default 60, raised under load)
and asks clients never to poll faster.

- `FetchResult` (fetch.py:13) gains `poll_interval` (int|None) as a trailing field
  with `defaults=(None,)`; `fetch()` sets it on the 200 path from
  `int(response.headers.get("X-Poll-Interval"))` (guarded; None if absent/non-int).
  All other `FetchResult(...)` constructions keep their positional args.
- `FeedManager.__init__` adds `self._poll_min = {}` (idx → server-requested min).
- `_run_once` (manager.py:71): when building the `feeds` snapshot, for a notifications
  feed with an override use an effective interval `max(feed["interval"], self._poll_min.get(idx, 0))`
  by shallow-copying that feed dict with the bumped `interval` before calling
  `model.due_feeds`. `due_feeds` itself stays pure/unchanged.
- Conditional 304s are free (don't count against the 5000/hr rate limit), so at the
  300s default this is comfortably compliant; the override only matters if the server
  asks us to back off beyond our configured interval.

## 8. Rendering (`hud.pyw`)

### 8a. `_feed_tiles` (hud.pyw:238) — new notifications branch

Insert **before** the github `if result.status is not None:` branch (hud.pyw:253).
When `feed["type"] == "notifications"` and `result is not None`:

- **Header:** `title + ("  \U0001f514 %s" % ("50+" if (result.badge or 0) >= 50 else (result.badge or 0)))`.
  Use `(result.badge or 0)` everywhere — `badge` may be `None` (no-token/304-empty/error
  paths) and `None >= 0` / `None > x` raises `TypeError` that would kill the 250 ms
  `_drain_feeds` loop (it only catches `tk.TclError`).
- **State lines** (3-tuples `(text, url, dim)`, dim=True):
  - no token (`error == "no github_token"`): `("! set GitHub token in Settings", None, True)`.
  - other error with no items: `("! " + result.error, None, True)`.
  - empty inbox (`ok`, 0 items): `("inbox zero", None, True)`.
- **Item lines** (5-tuples `(line1, url, color, subtitle, age)`) for each `NotifItem it`,
  with `stale = result.state != "ok"`. Define `URGENCY_HEX` once as a module-level dict
  in hud.pyw: `{"high": STATE_HEX["pending"], "normal": FEED_FG, "low": FEED_DIM}` (§2c).
  ```
  color    = FEED_DIM if stale else URGENCY_HEX[it.urgency]     # stale dims line 1
  age      = "" if it.updated_at <= 0 else timeago.format_ago(time.time() - it.updated_at)
  line1    = "%s %s%s · %s" % (it.glyph, _repo_short(it.repo),
                               (" " + it.number) if it.number else "", it.reason_label)
  subtitle = it.title                                          # line 2, always drawn FEED_DIM (8b)
  row = (line1, it.url, color, subtitle, age)
  ```
  - `_repo_short(full)`: bare repo name (`full.rsplit("/",1)[-1]`), capped ~12 chars.
  - The only stale cue is line 1 losing its urgency color (→ `FEED_DIM`); line 2 is
    always `FEED_DIM` regardless of state, so it needs no per-state handling.
- **Overflow** (3-tuple): when `(result.badge or 0) > len(result.items)`, append
  `("… %d more" % ((result.badge or 0) - len(result.items)), "https://github.com/notifications", True)`.
  (Beyond 50 unread the count is capped at the single page; documented behavior.)
- Yield `(title_with_badge, "https://github.com/notifications", FEED_FG, lines)`; the
  header itself is clickable to the inbox.

### 8b. `_draw_feeds` (hud.pyw:273) — row-length dispatch

Replace the loop `for text, url, dim in lines:` (hud.pyw:287) with `for row in lines:`
dispatching on `len(row)`:

- **`len(row) == 3`** → the existing path, unchanged: `text, url, dim = row`.
- **`len(row) == 5`** → `line1, url, color, subtitle, age = row`:
  - line 1 left: `create_text(PAD+6, y, anchor="w", text=_fit_line1(line1, age), fill=color, font=FEED_FONT)`.
  - line 1 age (if `age`): `create_text(WIDTH-PAD, y, anchor="e", text=age, fill=FEED_DIM, font=FEED_FONT)`.
  - `_register_hit(y, url)`; `y += FEED_LINE_H`.
  - line 2 title: `create_text(PAD+12, y, anchor="w", text=_fit(subtitle), fill=FEED_DIM, font=FEED_FONT)`.
  - `_register_hit(y, url)` (second adjacent band → the full ~30px item height opens the thread); `y += FEED_LINE_H`.
  - append all created ids to `self._feed_items`.

`_resize` (hud.pyw:295) is **unchanged** — the doubled `y += FEED_LINE_H` already
reflects the full rendered height.

### 8c. Pixel-aware line-1 fit (`_fit_line1`)

Emoji glyphs (💬 🏷) are double-width, so char-count truncation (`_fit`) under-budgets
and the left text can collide with the right-aligned age. Add an HUD-instance
`tkinter.font.Font(font=FEED_FONT)` measurer (create once in `__init__`; add
`import tkinter.font as tkfont`). `_fit_line1(text, age)` truncates `text` (dropping
trailing chars + "…") until `measure(text) <= WIDTH - 2*PAD - measure(age) - 8`. Line 2
keeps the existing char-based `_fit` (no glyphs there).

### 8d. Age helper — extend `timeago.format_ago` (timeago.py:4)

Add a weeks bucket so old notifications don't render as huge day counts:
```python
if s < 604800: return "%dd" % int(s // 86400)
return "%dw" % int(s // 604800)
```
Keep "just now" and negative→"just now". `hud.pyw` calls
`timeago.format_ago(time.time() - it.updated_at)` at draw time (delta-injected, so the
function stays unit-testable; ages stay fresh across the 250 ms drain without
re-fetching). `updated_at <= 0` renders no age (handled in `_feed_tiles`, §8a).

## 9. Settings UI (`feedkit/settings.py`)

- Add `"notifications"` to `_TYPES` (settings.py:13).
- Add to the `_render_fields` spec dict (settings.py:77):
  `"notifications": [("title","Title"), ("items","Items"), ("interval","Interval s")]`
  (no url/repo/branch — the token comes from the GitHub tab).
- `_on_add` (settings.py:101): change `if ftype=="github": … else:` to
  `if … elif ftype=="notifications": …  else: …`. The notifications branch sets only
  `raw["items"]` (if provided); it does **not** set `raw["url"]`.
- The GitHub tab already documents the scope and has a "Test" button hitting
  `/notifications`; update its label to "scope: notifications (+ repo for private repos)".

## 10. Security

- Every URL produced begins `https://github.com/` (§2d invariant) ⇒ passes
  `is_web_url`. Both gates (`_register_hit`, `_open_at`) remain in force as
  defense-in-depth; a null/odd `subject.url` can never reach the browser (it falls
  back to a safe https subpage, and would be re-rejected by the gate regardless).
- Token: classic PAT, stored only in gitignored `config.json` (or
  `TOYBOX_GITHUB_TOKEN` env), masked `show="*"` in the UI, never logged. Sent only to
  `https://api.github.com` over verified TLS.
- **Mark-as-read is out of scope.** Clicking opens the thread on github.com; reading
  it there clears it, and the badge updates on the next poll. We do not PATCH threads.

## 11. Testing plan (TDD; mirrors the existing feedkit suite)

- **test_timeago.py:** weeks bucket (`format_ago(700000) == "9w"`-style), boundary at
  604800; existing days/hours/minutes/just-now still pass.
- **test_feed_model.py:** `NotifItem` shape; `glyph_for` known + unknown→◉;
  `reason_label` known + unknown→`reason[:8]`; `urgency_for` each tier + unknown→low;
  `notification_url`: PR `/pulls/N`→`/pull/N`, Issue identity, Commit
  `/commits/SHA`→`/commit/SHA`, Discussion identity, CheckSuite→`/actions`, null url→
  fallback subpage, non-`/repos/` url→fallback, empty repo→`/notifications`, and that
  **every** output satisfies `is_web_url`; `normalize_feed("notifications")`: valid
  with no url/repo, items clamp 1..10 default 5, interval default 300 floor 120, title
  default "Notifications".
- **test_feed_parse.py:** `parse_notification_items`: empty list→`([],0)`; non-list
  JSON→`([],0)`; **null `subject.url` does not raise**; missing `subject`/`repository`;
  unknown `subject.type`→◉; reason→urgency/label; digit vs non-digit last segment→
  number/""; bad `updated_at`→0.0; `max_items` cap; `total` counts all unread (not the
  cap).
- **test_feed_fetch.py:** `poll_interval` parsed from `X-Poll-Interval` on 200; None
  when header absent/non-int; existing fetch tests unaffected by the new defaulted field.
- **test_feed_manager.py:** `_process_notifications`: no-token→`error`/"no github_token";
  304→reuse cached result; error-with-prev→`stale` carrying `prev.badge`;
  error-no-prev→`error`; bad-data→`stale`; success→`badge == total`; X-Poll-Interval
  override raises the effective interval (next due delayed); `FeedResult.badge`
  defaults to None and existing 4-arg constructions/tests are unaffected.
- **test_smoke_hud.py** (real Tk, `skipUnless nt`): notifications tile renders 2-line
  items; header shows `🔔 N`; `… N more` overflow; clicking an item registers a hit and
  returns its `https://github.com/...` thread url; no-token state shows the "! set
  GitHub token" line; `badge=None` and `badge=0` render without crashing the drain loop;
  a stale result dims the items.

## 12. Open questions from research — resolved

- **WorkflowRun vs CheckSuite, Discussion/TeamDiscussion/Security* subject types:** the
  API doesn't enumerate `subject.type`, so we treat it as open-ended — known values map
  per §2a, everything else falls to ◉, and every type has a safe https fallback URL.
  No behavior depends on an unverified enum.
- **Release numeric-id redirect:** not relied upon — Release links fall back to
  `/releases` (the title already identifies it), avoiding a second API call.
- **`repository.html_url` dependency:** removed — fallback URLs are built from
  `repository.full_name`, which is reliably present.
- **`push` / `your_activity` reasons:** added to §2b (normal / low).
