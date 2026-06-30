# HUD Notifications Tile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated `notifications` feed type that renders the authenticated user's unread GitHub notifications across all repos as a glanceable, clickable, 2-line-per-item HUD tile (glyph · repo · #num · reason | age, then title) — not just a count.

**Architecture:** A new feed `type` ("notifications") reusing the existing `feedkit` worker/queue/render pipeline. Pure classification + URL derivation and a new `NotifItem` type live in `feedkit/model.py`; a pure `parse_notification_items` in `feedkit/parse.py`; a `_process_notifications` worker method in `feedkit/manager.py`; a 2-line render path in `hud.pyw`. No new module is created. The single-line render path and all existing feed types are left byte-for-byte unchanged in behavior.

**Tech Stack:** Python 3.12 stdlib only (urllib, json, datetime, tkinter). Reuses `model.github_notifications_url()`, `model.github_headers()`, `feedkit.fetch.fetch`, and the existing `timeago.format_ago` helper.

**Spec:** `docs/superpowers/specs/2026-06-30-hud-notifications-tile-design.md` (the canonical tables in §2 are the single source of truth — implement them exactly).

## Global Constraints

- **Pure Python 3.12 stdlib ONLY.** No pip / third-party packages ever (no `requests`, `certifi`, `defusedxml`, `feedparser`). Network via `urllib` only.
- **TLS verification is NEVER weakened.**
- **Only http/https URLs may ever be opened.** `model.is_web_url` is the single gate, already enforced in `_register_hit` (hud.pyw:270) and `_open_at` (hud.pyw:325). Every URL this feature produces MUST be an `https://github.com/...` literal.
- **Existing single-line feeds (rss/json/text/github) must remain byte-for-byte unchanged in behavior.** Backward compatibility is a hard requirement. `FeedResult` and `FetchResult` gain trailing fields with defaults so every existing positional construction is unaffected.
- Win32 glue stays in `winkit/` (not touched here).
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Test runner: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`. Tests run from the repo root via `-m unittest`.
- Token: classic PAT, stored only in gitignored `config.json` (or the `TOYBOX_GITHUB_TOKEN` env var), masked in the UI, never logged. Mark-as-read is **out of scope** — clicking opens the thread on github.com.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `timeago.py` | Humanize elapsed seconds | Add a weeks bucket to `format_ago` |
| `feedkit/model.py` | Pure types/helpers/validation | Add `NotifItem`, classifier helpers (`glyph_for`/`reason_label`/`urgency_for`/`notification_url`), and `normalize_feed` support for `"notifications"` |
| `feedkit/parse.py` | Pure response parsers | Add `parse_notification_items` (the existing count `parse_notifications` stays) |
| `feedkit/fetch.py` | Thin networked GET | Add `poll_interval` field, read `X-Poll-Interval` on 200 |
| `feedkit/manager.py` | Worker/queue/cache glue | Add `FeedResult.badge`, `_process_notifications`, dispatch, and `X-Poll-Interval` honoring |
| `hud.pyw` | Tk overlay + feed rendering | Add the 2-line notifications render path (constants, helpers, `_feed_tiles` branch, `_draw_feeds` dispatch) |
| `feedkit/settings.py` | Feed Settings window | Add `"notifications"` to the type list, fields spec, and `_on_add` |

Tasks are ordered so each task's dependencies are already complete: 1 (timeago) and the model/parse/fetch primitives precede the manager that consumes them, which precedes the renderer.

---

### Task 1: timeago weeks bucket

**Files:**
- Modify: `timeago.py:4-13`
- Test: `tests/test_timeago.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `format_ago(elapsed_seconds)` now returns `"Nw"` for elapsed ≥ 604800 s (1 week); behavior < 1 week is unchanged (`"just now"`/`"Nm"`/`"Nh"`/`"Nd"`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_timeago.py` inside `class TestFormatAgo` (after `test_days`):

```python
    def test_weeks(self):
        self.assertEqual(format_ago(604800), "1w")      # exactly one week
        self.assertEqual(format_ago(1209600), "2w")     # two weeks
        self.assertEqual(format_ago(3024000), "5w")     # five weeks

    def test_days_to_weeks_boundary(self):
        self.assertEqual(format_ago(604799), "6d")      # just under a week stays days
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_timeago -v`
Expected: FAIL — `format_ago(604800)` returns `"7d"`, not `"1w"`.

- [ ] **Step 3: Implement the weeks bucket**

In `timeago.py`, replace the final `return` line of `format_ago`:

```python
    if s < 86400:
        return "%dh" % int(s // 3600)
    if s < 604800:
        return "%dd" % int(s // 86400)
    return "%dw" % int(s // 604800)
```

(Replaces the single trailing `return "%dd" % int(s // 86400)`. The docstring may be updated to mention `'Nw'`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_timeago -v`
Expected: PASS — all `TestFormatAgo` tests including the existing days/hours/minutes/just-now.

- [ ] **Step 5: Commit**

```bash
git add timeago.py tests/test_timeago.py
git commit -m "feat(timeago): add weeks bucket to format_ago"
```

---

### Task 2: model.py — NotifItem, classifiers, and normalize_feed support

**Files:**
- Modify: `feedkit/model.py` — add `NotifItem` after `Item` (model.py:9); add classifier dicts + helpers near the other `github_*` helpers (after model.py:79); add `"notifications"` to `_VALID_TYPES` (model.py:82); add a `normalize_feed` branch (between model.py:145 and model.py:147)
- Test: `tests/test_feed_model.py`

**Interfaces:**
- Consumes: `is_web_url` (existing), `_coerce_int` (existing).
- Produces:
  - `NotifItem = namedtuple("NotifItem", ["glyph","repo","number","reason_label","urgency","updated_at","title","url"])`
  - `glyph_for(subject_type) -> str`
  - `reason_label(reason) -> str` (≤8 chars)
  - `urgency_for(reason) -> "high"|"normal"|"low"`
  - `notification_url(subject_type, subject_url, repo_full) -> str` (always `https://github.com/...`)
  - `normalize_feed({"type":"notifications", ...})` → valid dict with `items` (1..10, default 5), `interval` (default 300, floor 120), `title` (default "Notifications"), no `url`/`repo`.

- [ ] **Step 1: Write the failing classifier + NotifItem tests**

Add to `tests/test_feed_model.py` (new class, after `TestGithubBuilders`):

```python
class TestNotifClassifiers(unittest.TestCase):
    def test_glyph_known_and_unknown(self):
        self.assertEqual(model.glyph_for("PullRequest"), "⇄")   # ⇄
        self.assertEqual(model.glyph_for("Issue"), "◉")         # ◉
        self.assertEqual(model.glyph_for("Discussion"), "\U0001f4ac")  # 💬
        self.assertEqual(model.glyph_for("Release"), "\U0001f3f7")     # 🏷
        self.assertEqual(model.glyph_for("CheckSuite"), "⚑")      # ⚑
        self.assertEqual(model.glyph_for("WorkflowRun"), "⚑")
        self.assertEqual(model.glyph_for("Commit"), "◉")
        self.assertEqual(model.glyph_for("Nonsense"), "◉")        # default ◉

    def test_reason_label_known_and_unknown(self):
        self.assertEqual(model.reason_label("review_requested"), "review")
        self.assertEqual(model.reason_label("mention"), "@you")
        self.assertEqual(model.reason_label("ci_activity"), "CI")
        self.assertEqual(model.reason_label("weird_reason_x"), "weird re")  # _->space, [:8]
        self.assertEqual(model.reason_label(""), "")

    def test_urgency_tiers(self):
        self.assertEqual(model.urgency_for("review_requested"), "high")
        self.assertEqual(model.urgency_for("mention"), "high")
        self.assertEqual(model.urgency_for("comment"), "normal")
        self.assertEqual(model.urgency_for("push"), "normal")
        self.assertEqual(model.urgency_for("subscribed"), "low")
        self.assertEqual(model.urgency_for("your_activity"), "low")
        self.assertEqual(model.urgency_for("totally_unknown"), "low")

    def test_url_pull_request(self):
        self.assertEqual(
            model.notification_url("PullRequest", "https://api.github.com/repos/o/r/pulls/34", "o/r"),
            "https://github.com/o/r/pull/34")

    def test_url_issue_identity(self):
        self.assertEqual(
            model.notification_url("Issue", "https://api.github.com/repos/o/r/issues/5", "o/r"),
            "https://github.com/o/r/issues/5")

    def test_url_commit(self):
        self.assertEqual(
            model.notification_url("Commit", "https://api.github.com/repos/o/r/commits/abc123", "o/r"),
            "https://github.com/o/r/commit/abc123")

    def test_url_security_advisory(self):
        self.assertEqual(
            model.notification_url("SecurityAdvisory",
                "https://api.github.com/repos/o/r/security-advisories/GHSA-x", "o/r"),
            "https://github.com/o/r/security/advisories/GHSA-x")

    def test_url_check_suite_to_actions(self):
        self.assertEqual(
            model.notification_url("CheckSuite",
                "https://api.github.com/repos/o/r/check-suites/9", "o/r"),
            "https://github.com/o/r/actions")

    def test_url_null_falls_back_to_subpage(self):
        self.assertEqual(model.notification_url("Issue", None, "o/r"),
                         "https://github.com/o/r/issues")

    def test_url_non_repos_url_falls_back(self):
        self.assertEqual(
            model.notification_url("Discussion",
                "https://api.github.com/organizations/1/team/2/discussions/3", "o/r"),
            "https://github.com/o/r/discussions")

    def test_url_empty_repo_is_inbox(self):
        self.assertEqual(model.notification_url("Issue", None, ""),
                         "https://github.com/notifications")

    def test_url_unknown_type_repo_root(self):
        self.assertEqual(model.notification_url("Mystery", None, "o/r"),
                         "https://github.com/o/r")

    def test_every_url_is_web_url(self):
        cases = [
            ("PullRequest", "https://api.github.com/repos/o/r/pulls/1", "o/r"),
            ("Issue", None, "o/r"),
            ("CheckSuite", "https://api.github.com/repos/o/r/check-suites/2", "o/r"),
            ("Mystery", None, ""),
            ("Discussion", "https://api.github.com/organizations/x", "o/r"),
            ("RepositoryInvitation", None, "o/r"),
        ]
        for st, su, rf in cases:
            self.assertTrue(model.is_web_url(model.notification_url(st, su, rf)),
                            (st, su, rf))

    def test_notifitem_shape(self):
        it = model.NotifItem("g", "o/r", "#1", "review", "high", 1.0, "t",
                             "https://github.com/o/r")
        self.assertEqual(it.glyph, "g")
        self.assertEqual(it.urgency, "high")
        self.assertEqual(it.updated_at, 1.0)
        self.assertEqual(it._fields,
            ("glyph", "repo", "number", "reason_label", "urgency",
             "updated_at", "title", "url"))
```

Also add notifications cases to the **existing** `class TestNormalizeFeed` (after `test_items_lower_clamp`):

```python
    def test_notifications_minimal(self):
        f = model.normalize_feed({"type": "notifications"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["type"], "notifications")
        self.assertEqual(f["items"], 5)
        self.assertEqual(f["interval"], 300)
        self.assertEqual(f["title"], "Notifications")
        self.assertNotIn("url", f)
        self.assertNotIn("repo", f)

    def test_notifications_items_clamped(self):
        self.assertEqual(model.normalize_feed({"type": "notifications", "items": 99})["items"], 10)
        self.assertEqual(model.normalize_feed({"type": "notifications", "items": 0})["items"], 1)

    def test_notifications_interval_floor_120(self):
        self.assertEqual(model.normalize_feed({"type": "notifications", "interval": 5})["interval"], 120)
        self.assertEqual(model.normalize_feed({"type": "notifications", "interval": 600})["interval"], 600)

    def test_notifications_custom_title(self):
        self.assertEqual(model.normalize_feed({"type": "notifications", "title": "Inbox"})["title"], "Inbox")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: FAIL — `AttributeError: module 'feedkit.model' has no attribute 'glyph_for'` (and `NotifItem`, etc.).

- [ ] **Step 3: Add `NotifItem` after `Item`**

In `feedkit/model.py`, immediately after line 9 (`Item = namedtuple(...)`):

```python
NotifItem = namedtuple("NotifItem",
    ["glyph", "repo", "number", "reason_label", "urgency", "updated_at", "title", "url"])
# urgency is the tier string "high"/"normal"/"low" -- the HUD maps it to a palette
# color. number is a display token ("#34" or ""). updated_at is a float unix
# timestamp (0.0 when the API value was missing/unparseable).
```

- [ ] **Step 4: Add the classifier dicts + helpers**

In `feedkit/model.py`, after `github_headers` (after line 79) and before `_VALID_TYPES` (line 82):

```python
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
```

- [ ] **Step 5: Add `"notifications"` to `_VALID_TYPES`**

In `feedkit/model.py:82`:

```python
_VALID_TYPES = ("rss", "json", "text", "github", "notifications")
```

- [ ] **Step 6: Add the `normalize_feed` notifications branch**

In `feedkit/model.py`, insert between line 145 (`return out` ending the rss/json/text block) and line 147 (`# github`):

```python

    if ftype == "notifications":
        # default 300 / floor 120 differs from the generic floor=300 line above,
        # so set interval here explicitly. No url/repo required; never raises.
        out["items"] = _coerce_int(raw.get("items"), 5, 1, 10)
        out["interval"] = _coerce_int(raw.get("interval"), 300, 120, 86400)
        out["title"] = title or "Notifications"
        return out
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: PASS — new classifier/url/normalize tests plus every existing `TestNormalizeFeed`/`TestGithubBuilders`/`TestIsWebUrl` test.

- [ ] **Step 8: Commit**

```bash
git add feedkit/model.py tests/test_feed_model.py
git commit -m "feat(feedkit): NotifItem, notification classifiers, and notifications feed validation"
```

---

### Task 3: parse.py — parse_notification_items

**Files:**
- Modify: `feedkit/parse.py` — add `import datetime` and `import feedkit.model as model` (top of file); add `_parse_ts` + `parse_notification_items` after `parse_notifications` (parse.py:157). The existing `parse_notifications` count function STAYS.
- Test: `tests/test_feed_parse.py`

**Interfaces:**
- Consumes: `model.NotifItem`, `model.glyph_for`, `model.reason_label`, `model.urgency_for`, `model.notification_url` (Task 2); existing `_clean` helper.
- Produces: `parse_notification_items(body, max_items) -> (list[NotifItem], int_total)`. `total` is the count of all unread threads on the page (drives the badge); the list is capped at `max_items`.

- [ ] **Step 1: Write the failing parser tests**

Add `import json` to the top of `tests/test_feed_parse.py` (it currently imports only `unittest` and `feedkit.parse`), add `import feedkit.model as model`, and append this class (after `TestComposeGithubStatus`):

```python
def _notif(**over):
    n = {"id": "1", "unread": True, "reason": "mention",
         "updated_at": "2026-06-29T00:00:00Z",
         "subject": {"title": "Hello", "type": "Issue",
                     "url": "https://api.github.com/repos/o/r/issues/7"},
         "repository": {"full_name": "o/r"}}
    n.update(over)
    return n


class TestParseNotificationItems(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(parse.parse_notification_items(b"[]", 5), ([], 0))

    def test_non_list_json(self):
        self.assertEqual(parse.parse_notification_items(b'{"message":"Bad creds"}', 5), ([], 0))

    def test_basic_issue(self):
        items, total = parse.parse_notification_items(json.dumps([_notif()]).encode(), 5)
        self.assertEqual(total, 1)
        it = items[0]
        self.assertEqual(it.glyph, model.glyph_for("Issue"))
        self.assertEqual(it.repo, "o/r")
        self.assertEqual(it.number, "#7")
        self.assertEqual(it.reason_label, "@you")
        self.assertEqual(it.urgency, "high")
        self.assertEqual(it.title, "Hello")
        self.assertEqual(it.url, "https://github.com/o/r/issues/7")
        self.assertGreater(it.updated_at, 0)

    def test_null_subject_url_does_not_raise(self):
        n = _notif(subject={"title": "Invite", "type": "RepositoryInvitation", "url": None})
        items, total = parse.parse_notification_items(json.dumps([n]).encode(), 5)
        self.assertEqual(total, 1)
        self.assertEqual(items[0].number, "")
        self.assertTrue(model.is_web_url(items[0].url))

    def test_missing_subject_and_repository(self):
        items, total = parse.parse_notification_items(
            json.dumps([{"unread": True, "reason": "subscribed"}]).encode(), 5)
        self.assertEqual(total, 1)
        self.assertEqual(items[0].repo, "")
        self.assertEqual(items[0].url, "https://github.com/notifications")
        self.assertEqual(items[0].glyph, "◉")           # default ◉

    def test_unknown_subject_type_default_glyph(self):
        n = _notif(subject={"title": "x", "type": "Wat", "url": None})
        items, _ = parse.parse_notification_items(json.dumps([n]).encode(), 5)
        self.assertEqual(items[0].glyph, "◉")

    def test_pull_request_number_and_url(self):
        n = _notif(subject={"title": "PR", "type": "PullRequest",
                            "url": "https://api.github.com/repos/o/r/pulls/34"})
        items, _ = parse.parse_notification_items(json.dumps([n]).encode(), 5)
        self.assertEqual(items[0].number, "#34")
        self.assertEqual(items[0].url, "https://github.com/o/r/pull/34")

    def test_non_digit_last_segment_has_no_number(self):
        n = _notif(subject={"title": "rel", "type": "Release",
                            "url": "https://api.github.com/repos/o/r/releases/tags/v1.2"})
        items, _ = parse.parse_notification_items(json.dumps([n]).encode(), 5)
        self.assertEqual(items[0].number, "")

    def test_bad_updated_at_is_zero(self):
        items, _ = parse.parse_notification_items(json.dumps([_notif(updated_at="nope")]).encode(), 5)
        self.assertEqual(items[0].updated_at, 0.0)

    def test_missing_updated_at_is_zero(self):
        n = _notif()
        del n["updated_at"]
        items, _ = parse.parse_notification_items(json.dumps([n]).encode(), 5)
        self.assertEqual(items[0].updated_at, 0.0)

    def test_max_items_caps_render_but_total_counts_all(self):
        arr = [_notif(id=str(i)) for i in range(8)]
        items, total = parse.parse_notification_items(json.dumps(arr).encode(), 3)
        self.assertEqual(len(items), 3)
        self.assertEqual(total, 8)

    def test_read_filtered_out(self):
        arr = [_notif(), _notif(unread=False)]
        items, total = parse.parse_notification_items(json.dumps(arr).encode(), 5)
        self.assertEqual(total, 1)
        self.assertEqual(len(items), 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: FAIL — `AttributeError: module 'feedkit.parse' has no attribute 'parse_notification_items'`.

- [ ] **Step 3: Add the imports**

At the top of `feedkit/parse.py`, add `import datetime` (with the other stdlib imports, after `import json`) and `import feedkit.model as model` (after the existing `from feedkit.model import ...` line):

```python
import datetime
import json
import re
import xml.etree.ElementTree as ET

import feedkit.model as model
from feedkit.model import Item, Status, strip_control_chars, truncate
```

- [ ] **Step 4: Add `_parse_ts` and `parse_notification_items`**

In `feedkit/parse.py`, after `parse_notifications` (after line 157) and before `compose_github_status`:

```python
def _parse_ts(s):
    """ISO-8601 timestamp (e.g. '2026-06-29T00:00:00Z') -> float unix seconds.
    Returns 0.0 for None/missing/unparseable values (the HUD renders no age)."""
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, AttributeError):
        return 0.0


def parse_notification_items(body, max_items):
    """Parse a /notifications response into (list[NotifItem], total_unread).
    total counts every unread thread on the page (drives the badge); the list is
    capped at max_items. Defensive against null subject.url and missing keys."""
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
        suburl = subj.get("url") or ""              # JSON null -> "" (NOT .get(k,"") -> None)
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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: PASS — new `TestParseNotificationItems` plus every existing parse test (`TestParseNotifications` count tests included — that function is untouched).

- [ ] **Step 6: Commit**

```bash
git add feedkit/parse.py tests/test_feed_parse.py
git commit -m "feat(feedkit): parse_notification_items into NotifItem list + total"
```

---

### Task 4: fetch.py — honor X-Poll-Interval

**Files:**
- Modify: `feedkit/fetch.py` — add `poll_interval` as a trailing `FetchResult` field with a default; read `X-Poll-Interval` on the 200 path.
- Test: `tests/test_feed_fetch.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `FetchResult` gains a 7th field `poll_interval` (int|None, default None). Set from the `X-Poll-Interval` response header on a 200 (None if absent/non-int). All existing 6-positional-arg `FetchResult(...)` constructions are unaffected.

- [ ] **Step 1: Write the failing fetch tests**

In `tests/test_feed_fetch.py`, add two paths to `_Handler.do_GET` (before the trailing `else`):

```python
        elif self.path == "/poll":
            self.send_response(200)
            self.send_header("X-Poll-Interval", "90")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"[]")
        elif self.path == "/pollbad":
            self.send_response(200)
            self.send_header("X-Poll-Interval", "soon")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"[]")
```

Add these tests to `class TestFetch` (after `test_connection_refused_is_offline`):

```python
    def test_poll_interval_parsed_on_200(self):
        r = fetch.fetch(self._url("/poll"))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.poll_interval, 90)

    def test_poll_interval_none_when_absent(self):
        r = fetch.fetch(self._url("/etag"))
        self.assertIsNone(r.poll_interval)

    def test_poll_interval_none_when_non_int(self):
        r = fetch.fetch(self._url("/pollbad"))
        self.assertIsNone(r.poll_interval)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_fetch -v`
Expected: FAIL — `AttributeError: 'FetchResult' object has no attribute 'poll_interval'`.

- [ ] **Step 3: Add the `poll_interval` field with a default**

In `feedkit/fetch.py:13-14`, replace the `FetchResult` definition:

```python
FetchResult = namedtuple(
    "FetchResult",
    ["status", "body", "content_type", "etag", "last_modified", "error", "poll_interval"],
    defaults=(None,))
```

- [ ] **Step 4: Read `X-Poll-Interval` on the 200 path**

In `feedkit/fetch.py`, add a small helper above `fetch` (after `_error_word`):

```python
def _poll_interval(response):
    """The server's requested minimum seconds between polls (GitHub's
    X-Poll-Interval), or None when absent / non-integer."""
    try:
        return int(response.headers.get("X-Poll-Interval"))
    except (TypeError, ValueError):
        return None
```

Then, in `fetch`, change the success-path construction (fetch.py:50-52) to pass it as the trailing arg:

```python
            return FetchResult("ok", body, response.headers.get("Content-Type"),
                               response.headers.get("ETag"),
                               response.headers.get("Last-Modified"), None,
                               _poll_interval(response))
```

(The 304 and error constructions are left as-is; their `poll_interval` defaults to None.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_fetch -v`
Expected: PASS — new poll-interval tests plus every existing fetch test (`test_ok_returns_body_and_etag`, `test_conditional_304`, etc.).

- [ ] **Step 6: Commit**

```bash
git add feedkit/fetch.py tests/test_feed_fetch.py
git commit -m "feat(feedkit): parse X-Poll-Interval into FetchResult.poll_interval"
```

---

### Task 5: manager.py — notifications worker + badge + poll-min honoring

**Files:**
- Modify: `feedkit/manager.py` — add `badge` to `FeedResult` (manager.py:15); add `self._poll_min = {}` to `__init__` (after manager.py:29); clear it in `set_feeds` (manager.py:52-56); apply the poll-min override in `_run_once` (manager.py:71-86); dispatch notifications in `_fetch_and_process` (manager.py:88-90); add `_process_notifications`.
- Test: `tests/test_feed_manager.py`

**Interfaces:**
- Consumes: `parse.parse_notification_items` (Task 3), `model.github_notifications_url`/`model.github_headers` (existing), `FetchResult.poll_interval` (Task 4).
- Produces: `FeedResult` gains a 5th field `badge` (int|None, default None) = the true unread total on success. `_process_notifications(idx, feed, token) -> FeedResult`. `self._poll_min` (idx → server-requested min seconds) gates re-fetch via `_run_once`.

- [ ] **Step 1: Write the failing manager tests**

Add to `tests/test_feed_manager.py` (after `class TestProcessGithub`). Note the helpers `_ok`/`_err`/`_nm` at the top of the file already build 6-positional-arg `FetchResult`s (poll_interval defaults to None):

```python
class TestProcessNotifications(unittest.TestCase):
    NOTIF = (b'[{"id":"1","unread":true,"reason":"mention",'
             b'"updated_at":"2026-06-29T00:00:00Z",'
             b'"subject":{"title":"Fix bug","type":"Issue",'
             b'"url":"https://api.github.com/repos/o/r/issues/5"},'
             b'"repository":{"full_name":"o/r"}}]')
    TWO = (b'[{"id":"1","unread":true,"reason":"mention","subject":'
           b'{"type":"Issue","title":"a","url":null},"repository":{"full_name":"o/r"}},'
           b'{"id":"2","unread":true,"reason":"author","subject":'
           b'{"type":"PullRequest","title":"b","url":null},"repository":{"full_name":"o/r"}}]')

    def test_no_token_is_error(self):
        m = manager.FeedManager([{"type": "notifications"}], token="",
                                fetch_fn=lambda u, **k: _ok(b"[]"))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")
        self.assertEqual(result.error, "no github_token")
        self.assertIsNone(result.badge)

    def test_success_badge_is_total(self):
        m = manager.FeedManager([{"type": "notifications", "items": 5}], token="ghp_x",
                                fetch_fn=lambda u, **k: _ok(self.TWO))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.badge, 2)
        self.assertEqual(len(result.items), 2)

    def test_304_reuses_cached(self):
        responses = [_ok(self.NOTIF), _nm()]
        m = manager.FeedManager([{"type": "notifications"}], token="ghp_x",
                                fetch_fn=lambda u, **k: responses.pop(0))
        m._run_once(0.0)
        m._last.clear()
        m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.badge, 1)             # reused from cache

    def test_error_after_success_is_stale_with_badge(self):
        responses = [_ok(self.NOTIF), _err("offline")]
        m = manager.FeedManager([{"type": "notifications"}], token="ghp_x",
                                fetch_fn=lambda u, **k: responses.pop(0))
        m._run_once(0.0)
        m._last.clear()
        m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.error, "offline")
        self.assertEqual(result.badge, 1)
        self.assertEqual(len(result.items), 1)

    def test_error_first_time_is_error(self):
        m = manager.FeedManager([{"type": "notifications"}], token="ghp_x",
                                fetch_fn=lambda u, **k: _err("offline"))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")
        self.assertEqual(result.items, [])
        self.assertIsNone(result.badge)

    def test_bad_data_after_success_is_stale(self):
        responses = [_ok(self.NOTIF), _ok(b"not json{")]
        m = manager.FeedManager([{"type": "notifications"}], token="ghp_x",
                                fetch_fn=lambda u, **k: responses.pop(0))
        m._run_once(0.0)
        m._last.clear()
        m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.error, "bad data")
        self.assertEqual(result.badge, 1)

    def test_x_poll_interval_delays_next_due(self):
        # X-Poll-Interval=600 must raise the effective interval above the
        # configured 120s floor, so a fetch at t=300 is suppressed.
        def fake(u, **k):
            return fetch.FetchResult("ok", self.NOTIF, "application/json",
                                     None, None, None, 600)
        m = manager.FeedManager([{"type": "notifications", "interval": 120}],
                                token="ghp_x", fetch_fn=fake)
        m._run_once(0.0)                              # first fetch; stores poll_min=600
        self.assertEqual(len(m.drain()), 1)
        m._run_once(300.0)                            # 300 >= 120 but < 600 -> not due
        self.assertEqual(m.drain(), [])
        m._run_once(601.0)                            # 601 >= 600 -> due
        self.assertEqual(len(m.drain()), 1)


class TestFeedResultBadge(unittest.TestCase):
    def test_badge_defaults_none(self):
        self.assertIsNone(manager.FeedResult("ok", [], None, None).badge)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
Expected: FAIL — `AttributeError: 'FeedResult' object has no attribute 'badge'` / `_process_notifications` not invoked (notifications feed falls into the generic branch and KeyErrors on `feed["url"]`).

- [ ] **Step 3: Add `badge` to `FeedResult`**

In `feedkit/manager.py:15`:

```python
FeedResult = namedtuple("FeedResult", ["state", "items", "status", "error", "badge"],
                        defaults=(None,))
```

- [ ] **Step 4: Track `_poll_min`**

In `FeedManager.__init__`, after `self._cache = {}` (manager.py:29) add:

```python
        self._poll_min = {}  # idx -> server-requested min seconds (X-Poll-Interval)
```

In `set_feeds` (manager.py:52-56), add `self._poll_min.clear()` alongside the existing clears:

```python
    def set_feeds(self, feeds):
        with self._lock:
            self.feeds = [model.normalize_feed(f) for f in feeds]
            self._last.clear()
            self._cache.clear()
            self._poll_min.clear()
```

- [ ] **Step 5: Apply the poll-min override in `_run_once`**

Replace `_run_once` (manager.py:71-86) with:

```python
    def _run_once(self, now):
        # Snapshot shared state under the lock; the blocking fetch runs unlocked so
        # a Settings save (set_feeds/set_token) is never blocked on network I/O.
        with self._lock:
            feeds = list(self.feeds)
            token = self.token
            last = dict(self._last)
            poll_min = dict(self._poll_min)
        # For notifications feeds the server may ask us to poll no faster than
        # X-Poll-Interval; raise the effective interval for the due check only
        # (due_feeds itself stays pure). Indices/order match `feeds`.
        due_view = feeds
        if poll_min:
            due_view = []
            for i, f in enumerate(feeds):
                pm = poll_min.get(i, 0)
                if (pm and f.get("valid") and f.get("type") == "notifications"
                        and pm > f.get("interval", 0)):
                    f = dict(f)
                    f["interval"] = pm
                due_view.append(f)
        for idx in model.due_feeds(due_view, last, now):
            feed = feeds[idx]
            try:
                result = self._fetch_and_process(idx, feed, token)
            except Exception as exc:
                result = FeedResult("error", [], None, str(exc) or "error")
            with self._lock:
                self._last[idx] = now
            self._queue.put((idx, result))
```

- [ ] **Step 6: Dispatch notifications in `_fetch_and_process`**

In `_fetch_and_process` (manager.py:88), add the notifications dispatch before the github branch:

```python
    def _fetch_and_process(self, idx, feed, token):
        if feed["type"] == "notifications":
            return self._process_notifications(idx, feed, token)
        if feed["type"] == "github":
            return self._process_github(idx, feed, token)
        with self._lock:
            cache = self._cache.get(idx, {})
        # ... unchanged ...
```

- [ ] **Step 7: Add `_process_notifications`**

In `feedkit/manager.py`, add this method (e.g. after `_process_github`):

```python
    def _process_notifications(self, idx, feed, token):
        """Global all-repos notifications. Single cache key = idx (one request,
        unlike github's compound ci/notif keys). Stale-on-error/bad-data carries
        the previous items + badge; honors the server's X-Poll-Interval."""
        if not token:
            return FeedResult("error", [], None, "no github_token", None)
        with self._lock:
            cache = self._cache.get(idx, {})
        res = self._fetch(model.github_notifications_url(),
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
            items, total = parse.parse_notification_items(res.body, feed["items"])
        except Exception:
            return FeedResult("stale" if prev else "error",
                              prev.items if prev else [], None, "bad data",
                              prev.badge if prev else None)
        result = FeedResult("ok", items, None, None, total)
        with self._lock:
            self._cache[idx] = {"etag": res.etag, "lm": res.last_modified, "result": result}
            if res.poll_interval:
                self._poll_min[idx] = res.poll_interval
        return result
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
Expected: PASS — new `TestProcessNotifications`/`TestFeedResultBadge` plus every existing manager test (`TestProcessRss`, `TestProcessGithub`, `TestManagerControl` — all construct `FeedResult`/`FetchResult` positionally and are unaffected by the defaulted fields).

- [ ] **Step 9: Commit**

```bash
git add feedkit/manager.py tests/test_feed_manager.py
git commit -m "feat(feedkit): notifications worker, FeedResult.badge, and X-Poll-Interval honoring"
```

---

### Task 6: hud.pyw — 2-line notifications render path

**Files:**
- Modify: `hud.pyw` — add `import timeago` and `import tkinter.font as tkfont` (hud.pyw:13-19); add `URGENCY_HEX` constant + `_repo_short` helper (after hud.pyw:52/58); create a font measurer in `__init__` (after the canvas, ~hud.pyw:95) and add a `_fit_line1` method; add the notifications branch to `_feed_tiles` (before hud.pyw:253); dispatch on row length in `_draw_feeds` (hud.pyw:287-292).
- Test: `tests/test_smoke_hud.py`

**Interfaces:**
- Consumes: `feedmodel.NotifItem` fields (Task 2), `FeedResult.badge` (Task 5), `timeago.format_ago` (Task 1), existing `STATE_HEX`/`FEED_FG`/`FEED_DIM`/`FEED_LINE_H`/`WIDTH`/`PAD`/`_fit`/`_register_hit`.
- Produces: notifications tiles render a 2-line item per `NotifItem` (line 1 = glyph · repo · #num · reason with right-aligned age, colored by urgency; line 2 = title, dim), a `🔔 N` header badge, state lines (no-token / error / inbox-zero), and a `… N more` overflow line. Both lines of an item register the same clickable `https://github.com/...` URL. `len(row)==3` lines keep the existing single-line path byte-for-byte.

- [ ] **Step 1: Write the failing smoke tests**

Add a `_fill_of` helper and a new test class to `tests/test_smoke_hud.py` (after `class TestHudClickAndMenu`). These are Windows-only smoke tests (real Tk):

```python
def _fill_of(hud, needle):
    """Fill color of the first feed canvas item whose text contains needle."""
    for iid in hud._feed_items:
        if needle in hud.canvas.itemcget(iid, "text"):
            return hud.canvas.itemcget(iid, "fill")
    return None


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudNotificationsRendering(_HudTestBase):
    def _item(self, urgency="high", repo="o/app", num="#34", title="Fix the thing",
              url="https://github.com/o/app/pull/34", ts=0.0, glyph="⇄",
              reason="review"):
        from feedkit.model import NotifItem
        return NotifItem(glyph, repo, num, reason, urgency, ts, title, url)

    def test_two_line_item_and_badge(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "Notifications", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._item(repo="o/app", title="Fix the thing")], None, None, 7)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("\U0001f514 7"))      # 🔔 7 header badge
            self.assertTrue(hud._feed_has_text("app"))               # line 1 repo
            self.assertTrue(hud._feed_has_text("Fix the thing"))     # line 2 title
        finally:
            hud.close(); root.destroy()

    def test_item_is_clickable_to_thread(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._item(url="https://github.com/o/app/pull/34")], None, None, 1)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(any(u == "https://github.com/o/app/pull/34"
                                for (_, _, u) in hud._hit))
        finally:
            hud.close(); root.destroy()

    def test_overflow_more_line(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            items = [self._item(num="#%d" % i, url="https://github.com/o/app/issues/%d" % i)
                     for i in range(5)]
            hud.feed_state[0] = manager.FeedResult("ok", items, None, None, 50)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("45 more"))   # 50 total - 5 shown
            self.assertTrue(any(u == "https://github.com/notifications"
                                for (_, _, u) in hud._hit))
        finally:
            hud.close(); root.destroy()

    def test_no_token_state_line(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("error", [], None, "no github_token", None)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("set GitHub token"))
        finally:
            hud.close(); root.destroy()

    def test_inbox_zero(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [], None, None, 0)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("inbox zero"))
        finally:
            hud.close(); root.destroy()

    def test_badge_none_and_zero_do_not_crash(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            for badge in (None, 0):
                hud.feed_state[0] = manager.FeedResult("ok", [], None, None, badge)
                hud._draw_feeds()       # None >= 50 would raise TypeError without the guard
                root.update_idletasks()
                self.assertTrue(hud._feed_has_text("\U0001f514 0"))
        finally:
            hud.close(); root.destroy()

    def test_high_urgency_amber_when_ok_and_dim_when_stale(self):
        import hud as hudmod
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._item(urgency="high", repo="o/app")], None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(_fill_of(hud, "app"), hudmod.STATE_HEX["pending"])  # amber
            hud.feed_state[0] = manager.FeedResult(
                "stale", [self._item(urgency="high", repo="o/app")], None, "offline", 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(_fill_of(hud, "app"), hudmod.FEED_DIM)              # dimmed
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: FAIL — the notifications result has `status is None` and items are `NotifItem`s, so the existing `_feed_tiles` generic path tries `it.text`/`it.url` → `AttributeError` (or the badge/2-line assertions fail).

- [ ] **Step 3: Add imports**

In `hud.pyw`, add `import timeago` (with the other top-level project imports, near hud.pyw:16-19) and `import tkinter.font as tkfont` (next to `import tkinter as tk`, hud.pyw:13):

```python
import tkinter as tk
import tkinter.font as tkfont
```
```python
import config
import webbrowser
import timeago
import feedkit.manager as feedmanager
import feedkit.model as feedmodel
```

- [ ] **Step 4: Add `URGENCY_HEX` and `_repo_short`**

In `hud.pyw`, after `STATE_HEX` (hud.pyw:51-52):

```python
URGENCY_HEX = {"high": STATE_HEX["pending"], "normal": FEED_FG, "low": FEED_DIM}
```

After `_fit` (hud.pyw:58):

```python
def _repo_short(full):
    """Bare repo name (drop the owner/), capped so a long owner can't push the
    reason label off the right edge of the 220px tile."""
    name = (full or "").rsplit("/", 1)[-1]
    return name if len(name) <= 12 else name[:11] + "…"
```

- [ ] **Step 5: Create the font measurer and add `_fit_line1`**

In `Hud.__init__`, after the canvas is packed (after hud.pyw:95 `self.canvas.pack(...)`):

```python
        # Pixel-width measurer for line 1 (emoji glyphs are double-width, so
        # char-count truncation under-budgets and collides with the age).
        self._feed_font_measure = tkfont.Font(root=root, family=FEED_FONT[0], size=FEED_FONT[1])
```

Add this method to the `Hud` class (e.g. just after `_register_hit`, hud.pyw:271):

```python
    def _fit_line1(self, text, age):
        """Truncate line 1 by measured pixel width so it never collides with the
        right-aligned age. Drops trailing chars and appends an ellipsis."""
        m = self._feed_font_measure.measure
        budget = WIDTH - 2 * PAD - m(age) - 8
        if m(text) <= budget:
            return text
        while text and m(text + "…") > budget:
            text = text[:-1]
        return text + "…"
```

- [ ] **Step 6: Add the notifications branch to `_feed_tiles`**

In `_feed_tiles`, insert this branch immediately before the github branch (`if result.status is not None:`, hud.pyw:253):

```python
            if feed["type"] == "notifications":
                badge = result.badge or 0          # badge may be None; None>=50 would crash the drain loop
                header = title + ("  \U0001f514 %s" % ("50+" if badge >= 50 else badge))
                lines = []
                if result.error == "no github_token":
                    lines.append(("! set GitHub token in Settings", None, True))
                elif result.error and not result.items:
                    lines.append(("! " + result.error, None, True))
                elif result.state == "ok" and not result.items:
                    lines.append(("inbox zero", None, True))
                stale = result.state != "ok"
                for it in result.items:
                    color = FEED_DIM if stale else URGENCY_HEX.get(it.urgency, FEED_FG)
                    age = "" if it.updated_at <= 0 else timeago.format_ago(time.time() - it.updated_at)
                    num = (" " + it.number) if it.number else ""
                    line1 = "%s %s%s · %s" % (it.glyph, _repo_short(it.repo), num, it.reason_label)
                    lines.append((line1, it.url, color, it.title, age))
                extra = badge - len(result.items)
                if extra > 0:
                    lines.append(("… %d more" % extra, "https://github.com/notifications", True))
                yield (header, "https://github.com/notifications", FEED_FG, lines)
                continue
```

- [ ] **Step 7: Dispatch on row length in `_draw_feeds`**

Replace the inner line loop in `_draw_feeds` (hud.pyw:287-292) — the existing `for text, url, dim in lines:` block — with:

```python
            for row in lines:
                if len(row) == 3:                      # existing single-line path, unchanged
                    text, url, dim = row
                    lid = c.create_text(PAD + 6, y, anchor="w", text=_fit(text),
                                        fill=(FEED_DIM if dim else FEED_FG), font=FEED_FONT)
                    self._feed_items.append(lid)
                    self._register_hit(y, url)
                    y += FEED_LINE_H
                else:                                  # len == 5: notifications 2-line item
                    line1, url, color, subtitle, age = row
                    l1 = c.create_text(PAD + 6, y, anchor="w",
                                       text=self._fit_line1(line1, age),
                                       fill=color, font=FEED_FONT)
                    self._feed_items.append(l1)
                    if age:
                        aid = c.create_text(WIDTH - PAD, y, anchor="e", text=age,
                                            fill=FEED_DIM, font=FEED_FONT)
                        self._feed_items.append(aid)
                    self._register_hit(y, url)
                    y += FEED_LINE_H
                    l2 = c.create_text(PAD + 12, y, anchor="w", text=_fit(subtitle),
                                       fill=FEED_DIM, font=FEED_FONT)
                    self._feed_items.append(l2)
                    self._register_hit(y, url)         # second band -> whole item opens the thread
                    y += FEED_LINE_H
```

(`_resize` is unchanged — the doubled `y += FEED_LINE_H` already reflects the full rendered height.)

- [ ] **Step 8: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS — new `TestHudNotificationsRendering` plus every existing smoke test (`TestSmokeHud`, `TestHudFeedRendering`, `TestHudClickAndMenu`, `TestFeedSettings`). The `test_launches_and_exits_clean` subprocess smoke must still exit 0 with empty stderr.

- [ ] **Step 9: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): 2-line actionable notifications tile render path"
```

---

### Task 7: settings.py — notifications in the Feed Settings window

**Files:**
- Modify: `feedkit/settings.py` — add `"notifications"` to `_TYPES` (settings.py:13); add a `_render_fields` spec entry (settings.py:77-86); add an `elif` branch to `_on_add` (settings.py:107-125); update the GitHub-tab scope label copy (settings.py:191).
- Test: `tests/test_smoke_hud.py` (the `TestFeedSettings` class)

**Interfaces:**
- Consumes: `model.normalize_feed("notifications")` (Task 2); existing `_add_feed_dict`/`_persist`.
- Produces: the Add-feed type list includes `notifications`; selecting it shows Title/Items/Interval fields (no URL/repo); `_on_add` builds a `{"type":"notifications", ...}` dict with no `url` key.

- [ ] **Step 1: Write the failing settings tests**

Add to the existing `class TestFeedSettings` in `tests/test_smoke_hud.py` (after `test_github_add_row_has_show_controls`):

```python
    def test_notifications_render_fields_has_no_url(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("notifications")
            hud.settings._render_fields()
            self.assertIn("items", hud.settings._fields)
            self.assertIn("interval", hud.settings._fields)
            self.assertNotIn("url", hud.settings._fields)
            self.assertNotIn("repo", hud.settings._fields)
            hud.close()
        finally:
            root.destroy()

    def test_notifications_on_add_builds_no_url_feed(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("notifications")
            hud.settings._render_fields()
            hud.settings._fields["title"].set("Notifications")
            hud.settings._fields["items"].set("7")
            hud.settings._on_add()
            added = hud.cfg["feeds"][-1]
            self.assertEqual(added["type"], "notifications")
            self.assertNotIn("url", added)
            self.assertEqual(added["items"], 7)
            self.assertTrue(hud.manager.feeds[-1]["valid"])
            hud.close()
        finally:
            root.destroy()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestFeedSettings -v`
Expected: FAIL — `_render_fields` raises `KeyError: 'notifications'` (the spec dict has no notifications entry).

- [ ] **Step 3: Add `"notifications"` to `_TYPES`**

In `feedkit/settings.py:13`:

```python
_TYPES = ("rss", "json", "text", "github", "notifications")
```

- [ ] **Step 4: Add the `_render_fields` spec entry**

In the `spec` dict inside `_render_fields` (settings.py:77-86), add a `notifications` key (after the `github` entry):

```python
            "github": [("title", "Title"), ("repo", "owner/name"), ("branch", "Branch"),
                       ("interval", "Interval s")],
            "notifications": [("title", "Title"), ("items", "Items"), ("interval", "Interval s")],
```

- [ ] **Step 5: Add the `_on_add` notifications branch**

In `_on_add` (settings.py:107-125), change the `if ftype == "github": ... else:` to add an `elif`. The notifications branch sets only `items` (no `url`):

```python
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
        elif ftype == "notifications":
            if g("items"):
                raw["items"] = _as_int(g("items"))
        else:
            raw["url"] = g("url")
            if g("items"):
                raw["items"] = _as_int(g("items"))
            if ftype == "json":
                raw["path"] = g("path")
                raw["fields"] = {"text": g("text"), "url": g("urlfield") or None}
            elif ftype == "text" and g("regex"):
                raw["regex"] = g("regex")
```

- [ ] **Step 6: Update the GitHub-tab scope label copy**

In `_build_github_tab` (settings.py:191), update the label text:

```python
        tk.Label(f, text="Classic PAT · scope: notifications (+ repo for private repos)",
                 fg="#555").pack(anchor="w", padx=10)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestFeedSettings -v`
Expected: PASS — new notifications settings tests plus the existing `test_open_add_feed_and_save` and `test_github_add_row_has_show_controls`.

- [ ] **Step 8: Commit**

```bash
git add feedkit/settings.py tests/test_smoke_hud.py
git commit -m "feat(hud): notifications feed type in Feed Settings"
```

---

## Final verification

After all tasks, run the full suite to confirm nothing regressed:

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -v`
Expected: PASS — entire suite green, including the subprocess HUD smoke (`test_launches_and_exits_clean`) exiting 0 with empty stderr.

---

## Self-Review

**1. Spec coverage** (each spec section → task):
- §1 config schema → Task 2 (normalize) + Task 7 (settings UI).
- §2a glyph / §2b reason→label+urgency / §2c urgency→color / §2d URL derivation → Task 2 (model dicts/helpers) + Task 6 (`URGENCY_HEX` color mapping).
- §3 `NotifItem` → Task 2.
- §4 `normalize_feed` → Task 2.
- §5 `parse_notification_items` + `_parse_ts` → Task 3.
- §6 worker `_process_notifications` + `FeedResult.badge` → Task 5.
- §7 X-Poll-Interval (`FetchResult.poll_interval`, `_poll_min`, `_run_once` override) → Task 4 (fetch) + Task 5 (manager).
- §8a `_feed_tiles` branch / §8b `_draw_feeds` dispatch / §8c `_fit_line1` / §8d timeago weeks → Task 6 + Task 1.
- §9 settings → Task 7.
- §10 security (is_web_url invariant) → Task 2 (`test_every_url_is_web_url`) + Task 6 (gates unchanged).
- §11 testing plan → distributed across each task's tests.

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to" — every code and test step contains full literal content.

**3. Type consistency:** `NotifItem` field order is identical in Task 2 (definition), Task 3 (construction), and Task 6 (consumption: `it.glyph/repo/number/reason_label/urgency/updated_at/title/url`). `FeedResult` 5-field shape (`state,items,status,error,badge`) and `FetchResult` 7-field shape (`...,error,poll_interval`) are consistent across manager/fetch/tests. `urgency` strings (`"high"/"normal"/"low"`) match between `_NOTIF_REASONS` (Task 2) and `URGENCY_HEX` keys (Task 6).

**Spec note (§2d vs §12):** The canonical code in §2d is implemented verbatim (it is the declared single source of truth). For a `Release` whose `subject.url` starts with the `/repos/` prefix, §2d returns the tail-derived `https://github.com/o/r/releases/<id>` link (not the `/releases` fallback that §12's prose mentions — that fallback only applies to null/non-`/repos` URLs). The result is always an `is_web_url`-safe `https://github.com/...` link. Flagged at handoff as a minor follow-up if exact Release deep-linking is wanted.
