# HUD Notifications Dismiss Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user mark one notification (`✕`) or all notifications (`✓`) read directly from the HUD tile, via GitHub's notifications API, with optimistic UI that reconciles on the next fetch.

**Architecture:** `NotifItem` carries the api thread URL; a new `fetch.send(url, method, headers)` does the bodyless PATCH/PUT; the `FeedManager` gains an action queue drained on the worker thread (the only code touching the network) that force-refetches on success and restores on failure; `hud.pyw` draws `✕`/`✓` glyphs with x-aware click zones, applies the change optimistically, and dispatches to the manager. The browser open-path is untouched — the api URL is never opened.

**Tech Stack:** Python 3.12 stdlib only (urllib, json, tkinter). Reuses `feedkit` model/parse/fetch/manager and the notifications tile from `2026-06-30-hud-notifications-tile-design.md`.

**Spec:** `docs/superpowers/specs/2026-06-30-hud-notifications-dismiss-design.md` (§2 UX and §3–§7 are the source of truth).

## Global Constraints

- **Pure Python 3.12 stdlib ONLY.** No pip / third-party packages. Network via `urllib` only.
- **TLS verification is NEVER weakened.** `send` uses the default verifying context, like `fetch`.
- **Only http/https URLs may ever be opened in a browser.** `model.is_web_url` is the single gate at `_register_hit` (hud.pyw:302) and `_open_at` (hud.pyw:391). The `api.github.com` `thread_url` / `PUT /notifications` endpoint is used ONLY by the authenticated API client and is NEVER passed to `webbrowser.open`. Dismiss/mark-all hit records carry an *action*, not a URL.
- **Existing behavior is preserved.** Non-notifications feeds (rss/json/text/github) and the single-line render path stay byte-for-byte unchanged. `NotifItem` gains a trailing defaulted field so existing positional constructions keep working.
- **Mark-all confirms; per-item does not.** Mark-all is effectively irreversible in bulk (GitHub has no bulk mark-unread).
- Win32 glue stays in `winkit/` (not touched here).
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Test runner: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`, run from the repo root via `-m unittest`.
- Token: classic PAT (the `notifications` scope already grants write), in gitignored `config.json`/env, masked, never logged.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `feedkit/model.py` | Pure types/helpers | `NotifItem` gains trailing `thread_url`; add `github_mark_all_read_url()` |
| `feedkit/parse.py` | Pure parsers | `parse_notification_items` sets `thread_url = n.get("url") or ""` |
| `feedkit/fetch.py` | Thin network I/O | add `SendResult` + `send(url, method, headers)` (GET path untouched) |
| `feedkit/manager.py` | Worker/queue glue | action queue, `mark_read`/`mark_all_read`, `_do_action`, drain in `_run_once`, `send_fn` injection |
| `hud.pyw` | Tk overlay | `✕`/`✓` glyphs, x-aware action zones, optimistic update, confirm dialog, click dispatch |

Tasks are ordered so each task's dependencies are already complete: model/parse/fetch primitives precede the manager that consumes them; the manager and the render precede the click dispatch that wires them together.

---

### Task 1: model.py — `NotifItem.thread_url` + mark-all URL

**Files:**
- Modify: `feedkit/model.py:12-13` (NotifItem) and after `github_notifications_url` (model.py:69-72)
- Test: `tests/test_feed_model.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `NotifItem` field order is now `(glyph, repo, number, reason_label, urgency, updated_at, title, url, thread_url)` with `thread_url` defaulting to `""` (so existing 8-arg positional constructions keep working).
  - `github_mark_all_read_url() -> "https://api.github.com/notifications"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_model.py`, inside `class TestNotifClassifiers` (after `test_notifitem_shape`):

```python
    def test_notifitem_thread_url_defaults_empty(self):
        it = model.NotifItem("g", "o/r", "#1", "review", "high", 1.0, "t",
                             "https://github.com/o/r")
        self.assertEqual(it.thread_url, "")
        self.assertEqual(it._fields[-1], "thread_url")

    def test_notifitem_thread_url_set(self):
        it = model.NotifItem("g", "o/r", "#1", "review", "high", 1.0, "t",
                             "https://github.com/o/r",
                             "https://api.github.com/notifications/threads/9")
        self.assertEqual(it.thread_url,
                         "https://api.github.com/notifications/threads/9")
```

Add to `class TestGithubBuilders`:

```python
    def test_github_mark_all_read_url(self):
        self.assertEqual(model.github_mark_all_read_url(),
                         "https://api.github.com/notifications")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: FAIL — `AttributeError: 'NotifItem' object has no attribute 'thread_url'` and `module 'feedkit.model' has no attribute 'github_mark_all_read_url'`.

- [ ] **Step 3: Add the `thread_url` field**

Replace `feedkit/model.py:12-13`:

```python
NotifItem = namedtuple("NotifItem",
    ["glyph", "repo", "number", "reason_label", "urgency", "updated_at", "title",
     "url", "thread_url"],
    defaults=("",))
```

(The trailing `defaults=("",)` keeps every existing 8-positional-arg construction working; `thread_url` is the api.github.com thread URL used only for mark-as-read, never for the browser.)

- [ ] **Step 4: Add `github_mark_all_read_url`**

In `feedkit/model.py`, immediately after `github_notifications_url` (after model.py:72):

```python


def github_mark_all_read_url():
    # PUT here marks every notification thread read (no query string, unlike the
    # GET notifications URL). Used only by the authenticated API client.
    return "%s/notifications" % GITHUB_API
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_model -v`
Expected: PASS — new tests plus every existing `TestNotifClassifiers`/`TestGithubBuilders`/`TestNormalizeFeed` test (the defaulted field leaves the existing `test_notifitem_shape` 8-arg construction valid).

- [ ] **Step 6: Commit**

```bash
git add feedkit/model.py tests/test_feed_model.py
git commit -m "feat(feedkit): NotifItem.thread_url + github_mark_all_read_url"
```

---

### Task 2: parse.py — carry `thread_url`

**Files:**
- Modify: `feedkit/parse.py:189-198` (the `model.NotifItem(...)` construction in `parse_notification_items`)
- Test: `tests/test_feed_parse.py`

**Interfaces:**
- Consumes: `NotifItem.thread_url` (Task 1).
- Produces: each parsed `NotifItem` carries `thread_url = n.get("url") or ""` (the notification's top-level api thread URL; `""` when absent/null).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_parse.py`, inside `class TestParseNotificationItems`:

```python
    def test_thread_url_carried_from_top_level_url(self):
        n = _notif(url="https://api.github.com/notifications/threads/42")
        items, _ = parse.parse_notification_items(json.dumps([n]).encode(), 5)
        self.assertEqual(items[0].thread_url,
                         "https://api.github.com/notifications/threads/42")

    def test_thread_url_missing_is_empty(self):
        items, _ = parse.parse_notification_items(
            json.dumps([{"unread": True, "reason": "subscribed"}]).encode(), 5)
        self.assertEqual(items[0].thread_url, "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: FAIL — `test_thread_url_carried_from_top_level_url` asserts `""` (current default) != the expected URL.

- [ ] **Step 3: Set `thread_url` in the construction**

In `feedkit/parse.py`, change the `model.NotifItem(...)` call in `parse_notification_items` (parse.py:189-198) to add the trailing kwarg:

```python
        out.append(model.NotifItem(
            glyph=model.glyph_for(stype),
            repo=repo,
            number=number,
            reason_label=model.reason_label(reason),
            urgency=model.urgency_for(reason),
            updated_at=_parse_ts(n.get("updated_at")),
            title=_clean(subj.get("title") or ""),
            url=model.notification_url(stype, subj.get("url"), repo),
            thread_url=n.get("url") or "",   # api thread URL; "" when absent (never browser-opened)
        ))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_parse -v`
Expected: PASS — new tests plus every existing `TestParseNotificationItems` test.

- [ ] **Step 5: Commit**

```bash
git add feedkit/parse.py tests/test_feed_parse.py
git commit -m "feat(feedkit): parse_notification_items carries thread_url"
```

---

### Task 3: fetch.py — `send()` write path

**Files:**
- Modify: `feedkit/fetch.py` — add `SendResult` after `FetchResult` (fetch.py:16) and `send` after `fetch` (end of file); add `do_PATCH`/`do_PUT` to the test handler
- Test: `tests/test_feed_fetch.py`

**Interfaces:**
- Consumes: existing `_error_word`, `_DEFAULT_UA`.
- Produces: `SendResult = namedtuple("SendResult", ["status", "code", "error"], defaults=(None, None))` and `send(url, method, headers=None, timeout=12) -> SendResult`. `status="ok"` for any 2xx; `status="error"` with the same error word taxonomy as `fetch` otherwise.

- [ ] **Step 1: Write the failing tests**

In `tests/test_feed_fetch.py`, add these two methods to `class _Handler` (after `do_GET`):

```python
    def do_PATCH(self):
        if self.path == "/thread":
            self.send_response(205); self.end_headers()
        elif self.path == "/forbidden":
            self.send_response(401); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    def do_PUT(self):
        if self.path == "/notifications":
            self.send_response(202); self.end_headers()
        else:
            self.send_response(404); self.end_headers()
```

Add to `class TestFetch` (after the existing tests):

```python
    def test_send_patch_2xx_is_ok(self):
        r = fetch.send(self._url("/thread"), "PATCH")
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.code, 205)

    def test_send_put_2xx_is_ok(self):
        r = fetch.send(self._url("/notifications"), "PUT")
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.code, 202)

    def test_send_http_error_is_error_word(self):
        r = fetch.send(self._url("/forbidden"), "PATCH")
        self.assertEqual(r.status, "error")
        self.assertEqual(r.code, 401)
        self.assertEqual(r.error, "bad token")

    def test_send_connection_refused_is_offline(self):
        r = fetch.send("http://127.0.0.1:1/x", "PUT")
        self.assertEqual(r.status, "error")
        self.assertEqual(r.error, "offline")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_fetch -v`
Expected: FAIL — `AttributeError: module 'feedkit.fetch' has no attribute 'send'`.

- [ ] **Step 3: Add `SendResult`**

In `feedkit/fetch.py`, immediately after the `FetchResult` definition (after fetch.py:16):

```python

SendResult = namedtuple("SendResult", ["status", "code", "error"], defaults=(None, None))
```

- [ ] **Step 4: Add `send`**

At the end of `feedkit/fetch.py` (after `fetch`):

```python


def send(url, method, headers=None, timeout=12):
    """Fire a bodyless mutating request (PATCH a thread, PUT /notifications) for
    the mark-as-read actions. Any 2xx -> SendResult('ok', code, None); failures
    map through the same taxonomy as fetch(). TLS uses the default verifying
    context (never weakened); no response body is read."""
    request_headers = {"User-Agent": _DEFAULT_UA}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return SendResult("ok", response.status, None)
    except urllib.error.HTTPError as exc:
        return SendResult("error", exc.code, _error_word(exc))
    except (urllib.error.URLError, TimeoutError) as exc:
        return SendResult("error", None, _error_word(exc))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_fetch -v`
Expected: PASS — new send tests plus every existing fetch test.

- [ ] **Step 6: Commit**

```bash
git add feedkit/fetch.py tests/test_feed_fetch.py
git commit -m "feat(feedkit): send() write path for mark-as-read (PATCH/PUT)"
```

---

### Task 4: manager.py — action queue + mark-read worker

**Files:**
- Modify: `feedkit/manager.py` — `__init__` (manager.py:20-32), `set_feeds` (manager.py:54-59), `_run_once` (manager.py:74), add `mark_read`/`mark_all_read`/`_clear_actions`/`_process_actions`/`_do_action`
- Test: `tests/test_feed_manager.py`

**Interfaces:**
- Consumes: `fetch.send` + `fetch.SendResult` (Task 3), `model.github_mark_all_read_url`/`github_headers` (Task 1), `parse.parse_notification_items` + `FeedResult` (existing).
- Produces: `mark_read(idx, thread_url)` enqueues `("one", idx, thread_url)`; `mark_all_read(idx)` enqueues `("all", idx, None)`; the worker drains these at the top of `_run_once`, runs `send` unlocked, and on success force-refetches the feed (cleared etag + dropped `_last`) so it reconciles this tick, or on failure queues a restoring `FeedResult("stale", prev.items, None, "dismiss failed", prev.badge)`. `__init__` gains `send_fn` (default `fetch.send`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feed_manager.py` (after the existing classes). The helpers `_ok`/`_err`/`_nm` at the top of the file already build `FetchResult`s:

```python
def _send_ok():
    return fetch.SendResult("ok", 205, None)


class TestMarkRead(unittest.TestCase):
    N2 = (b'[{"id":"1","unread":true,"reason":"mention",'
          b'"url":"https://api.github.com/notifications/threads/1",'
          b'"subject":{"type":"Issue","title":"a","url":null},"repository":{"full_name":"o/r"}},'
          b'{"id":"2","unread":true,"reason":"author",'
          b'"url":"https://api.github.com/notifications/threads/2",'
          b'"subject":{"type":"Issue","title":"b","url":null},"repository":{"full_name":"o/r"}}]')
    N1 = (b'[{"id":"2","unread":true,"reason":"author",'
          b'"url":"https://api.github.com/notifications/threads/2",'
          b'"subject":{"type":"Issue","title":"b","url":null},"repository":{"full_name":"o/r"}}]')

    def test_mark_read_forces_refetch_and_reconciles(self):
        fetches = [_ok(self.N2), _ok(self.N1)]
        sends = []
        def fake_fetch(u, **k):
            return fetches.pop(0)
        def fake_send(u, method, headers):
            sends.append((u, method)); return _send_ok()
        m = manager.FeedManager([{"type": "notifications", "interval": 300}], token="ghp_x",
                                fetch_fn=fake_fetch, send_fn=fake_send)
        m._run_once(0.0)                       # initial fetch: 2 items, _last[0]=0
        m.drain()
        m.mark_read(0, "https://api.github.com/notifications/threads/1")
        m._run_once(5.0)                       # 5 < 300 normally NOT due; the action forces it
        idx, res = m.drain()[-1]
        self.assertEqual(sends, [("https://api.github.com/notifications/threads/1", "PATCH")])
        self.assertEqual(res.state, "ok")
        self.assertEqual(len(res.items), 1)    # reconciled with the post-dismiss page
        self.assertEqual(res.badge, 1)

    def test_mark_read_failure_restores_with_dismiss_failed(self):
        fetches = [_ok(self.N2)]
        m = manager.FeedManager([{"type": "notifications", "interval": 300}], token="ghp_x",
                                fetch_fn=lambda u, **k: fetches.pop(0),
                                send_fn=lambda u, method, headers: fetch.SendResult("error", None, "offline"))
        m._run_once(0.0); m.drain()            # cache has 2 items
        m.mark_read(0, "https://api.github.com/notifications/threads/1")
        m._run_once(5.0)                       # send fails -> restore, NOT due so no refetch
        idx, res = m.drain()[-1]
        self.assertEqual(res.state, "stale")
        self.assertEqual(res.error, "dismiss failed")
        self.assertEqual(len(res.items), 2)
        self.assertEqual(res.badge, 2)

    def test_mark_all_read_targets_put_endpoint(self):
        fetches = [_ok(self.N2), _ok(b"[]")]
        sends = []
        def fake_send(u, method, headers):
            sends.append((u, method)); return _send_ok()
        m = manager.FeedManager([{"type": "notifications", "interval": 300}], token="ghp_x",
                                fetch_fn=lambda u, **k: fetches.pop(0), send_fn=fake_send)
        m._run_once(0.0); m.drain()
        m.mark_all_read(0)
        m._run_once(5.0)
        idx, res = m.drain()[-1]
        self.assertEqual(sends, [("https://api.github.com/notifications", "PUT")])
        self.assertEqual(res.state, "ok")
        self.assertEqual(res.badge, 0)
        self.assertEqual(len(res.items), 0)

    def test_set_feeds_clears_pending_actions(self):
        sends = []
        m = manager.FeedManager([{"type": "notifications"}], token="ghp_x",
                                fetch_fn=lambda u, **k: _ok(b"[]"),
                                send_fn=lambda u, method, headers: (sends.append(1), _send_ok())[1])
        m.mark_read(0, "https://api.github.com/notifications/threads/1")
        m.set_feeds([{"type": "notifications"}])   # discards the queued action
        m._run_once(0.0)
        self.assertEqual(sends, [])                 # send never called
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
Expected: FAIL — `AttributeError: 'FeedManager' object has no attribute 'mark_read'`.

- [ ] **Step 3: Add `send_fn` + action queue to `__init__`**

In `feedkit/manager.py`, change the `__init__` signature and add two attributes. Replace `manager.py:20` (the `def __init__` line) and add the two lines:

```python
    def __init__(self, feeds, token="", fetch_fn=None, poll_interval=1.0, send_fn=None):
```

After `self._fetch = fetch_fn or fetch_mod.fetch` (manager.py:23) add:

```python
        self._send = send_fn or fetch_mod.send
```

After `self._poll_min = {}` (manager.py:31) add:

```python
        self._actions = queue.Queue()  # pending mark-as-read actions (thread-safe)
```

- [ ] **Step 4: Clear pending actions in `set_feeds`**

Replace `set_feeds` (manager.py:54-59):

```python
    def set_feeds(self, feeds):
        with self._lock:
            self.feeds = [model.normalize_feed(f) for f in feeds]
            self._last.clear()
            self._cache.clear()
            self._poll_min.clear()
        self._clear_actions()   # drop actions aimed at the now-replaced feed set
```

- [ ] **Step 5: Add `mark_read`/`mark_all_read`/`_clear_actions`**

In `feedkit/manager.py`, add after `set_token` (after manager.py:63):

```python

    def mark_read(self, idx, thread_url):
        """Enqueue 'mark this thread read' for the worker (called from the UI)."""
        self._actions.put(("one", idx, thread_url))

    def mark_all_read(self, idx):
        """Enqueue 'mark all notifications read' for the worker."""
        self._actions.put(("all", idx, None))

    def _clear_actions(self):
        try:
            while True:
                self._actions.get_nowait()
        except queue.Empty:
            pass
```

- [ ] **Step 6: Drain actions at the top of `_run_once`**

In `_run_once` (manager.py:74), insert the action-processing call as the very first line of the method body (before the `with self._lock:` snapshot):

```python
    def _run_once(self, now):
        self._process_actions(now)   # apply queued mark-as-read before computing due feeds
        # Snapshot shared state under the lock; the blocking fetch runs unlocked so
        # a Settings save (set_feeds/set_token) is never blocked on network I/O.
        with self._lock:
```

(The rest of `_run_once` is unchanged. Draining actions before the snapshot means a successful action that drops `_last[idx]` makes that feed *due this same tick*, so the reconcile fetch happens immediately.)

- [ ] **Step 7: Add `_process_actions` and `_do_action`**

In `feedkit/manager.py`, add after `_run_once` (after manager.py:103), before `_fetch_and_process`:

```python
    def _process_actions(self, now):
        while True:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                return
            try:
                self._do_action(action, now)
            except Exception:
                pass   # one bad action must not stop the worker loop

    def _do_action(self, action, now):
        """Run one mark-as-read mutation. send() runs UNLOCKED (never hold the lock
        across network I/O). On success, invalidate the feed's cache + drop its
        last-fetch time so the due loop refetches and reconciles this tick. On
        failure, queue a restoring result so the optimistic UI rolls back."""
        kind, idx = action[0], action[1]
        with self._lock:
            token = self.token
        if kind == "one":
            target, method = action[2], "PATCH"
        else:                                   # "all"
            target, method = model.github_mark_all_read_url(), "PUT"
        res = self._send(target, method, model.github_headers(token))
        restore = None
        with self._lock:
            if res.status == "ok":
                entry = self._cache.get(idx, {})
                entry.pop("etag", None)         # force a fresh 200, not a 304
                entry.pop("lm", None)
                self._cache[idx] = entry
                self._last.pop(idx, None)       # force the feed due this tick
            else:
                prev = self._cache.get(idx, {}).get("result")
                restore = FeedResult("stale", prev.items if prev else [], None,
                                     "dismiss failed", prev.badge if prev else None)
        if restore is not None:
            self._queue.put((idx, restore))
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_feed_manager -v`
Expected: PASS — new `TestMarkRead` plus every existing manager test (the new `send_fn` defaults to `fetch.send` and the action queue is empty for non-dismiss tests, so `_process_actions` is a no-op there).

- [ ] **Step 9: Commit**

```bash
git add feedkit/manager.py tests/test_feed_manager.py
git commit -m "feat(feedkit): manager action queue for mark-as-read (force-refetch / restore)"
```

---

### Task 5: hud.pyw — `✕`/`✓` glyphs + x-aware action zones

**Files:**
- Modify: `hud.pyw` — constants after `URGENCY_HEX` (hud.pyw:55); `self._action_hits` in `__init__` (hud.pyw:94); `_register_action`/`_action_at` near `_register_hit` (hud.pyw:302); `_fit_line1` gains `reserve` (hud.pyw:309-318); the `_feed_tiles` yields (hud.pyw:252-300); `_draw_feeds` (hud.pyw:320-359)
- Test: `tests/test_smoke_hud.py`

**Interfaces:**
- Consumes: `NotifItem.thread_url` (Task 1), existing `FeedResult`/render constants.
- Produces: notifications tiles draw a `✕` at the right edge of each dismissable item's line 1 and a `✓` at the right edge of the header; each registers an x-aware action zone via `self._action_hits` (`[(y0,y1,x0,x1,action)]`), readable via `_action_at(x, y)`. `_feed_tiles` now yields 5-tuples `(title, title_url, color, lines, header_action)`; notification item rows are 6-tuples `(line1, url, color, subtitle, age, dismiss_action)`. Open-URL hits and the `is_web_url` gate are unchanged.

- [ ] **Step 1: Write the failing tests**

Add a new class to `tests/test_smoke_hud.py` (after `class TestHudNotificationsRendering`):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudNotificationsDismiss(_HudTestBase):
    def _ditem(self, thread_url="https://api.github.com/notifications/threads/7",
               url="https://github.com/o/app/issues/7", repo="o/app", title="T"):
        from feedkit.model import NotifItem
        return NotifItem("◉", repo, "#7", "@you", "high", 0.0, title, url, thread_url)

    def test_dismiss_glyph_and_zone_registered(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("✕"))   # ✕ per-item
            self.assertTrue(hud._feed_has_text("✓"))   # ✓ header mark-all
            ones = [a for (_, _, _, _, a) in hud._action_hits if a[0] == "one"]
            alls = [a for (_, _, _, _, a) in hud._action_hits if a[0] == "all"]
            self.assertEqual(ones[0],
                             ("one", 0, "https://api.github.com/notifications/threads/7"))
            self.assertEqual(alls[0], ("all", 0))
        finally:
            hud.close(); root.destroy()

    def test_item_without_thread_url_has_no_dismiss(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem(thread_url="")],
                                                   None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertFalse(any(a[0] == "one" for (_, _, _, _, a) in hud._action_hits))
            self.assertFalse(hud._feed_has_text("✕"))
        finally:
            hud.close(); root.destroy()

    def test_dismiss_zone_x_is_right_edge(self):
        import hud as hudmod
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            one = [(x0, x1) for (_, _, x0, x1, a) in hud._action_hits if a[0] == "one"][0]
            self.assertEqual(one, (hudmod.WIDTH - hudmod.PAD - hudmod.ACTION_ZONE_W, hudmod.WIDTH))
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudNotificationsDismiss -v`
Expected: FAIL — `AttributeError: 'Hud' object has no attribute '_action_hits'` (and `module 'hud' has no attribute 'ACTION_ZONE_W'`).

- [ ] **Step 3: Add the glyph + zone constants**

In `hud.pyw`, after `URGENCY_HEX` (hud.pyw:55):

```python
DISMISS_GLYPH = "✕"   # ✕  per-item mark-read
MARKALL_GLYPH = "✓"   # ✓  header mark-all-read
ACTION_ZONE_W = 18         # px hit target at the right edge for ✕ / ✓
```

- [ ] **Step 4: Add the `_action_hits` list**

In `Hud.__init__`, after `self._hit = []` (hud.pyw:94):

```python
        self._action_hits = []    # [(y0,y1,x0,x1,action)] x-aware dismiss/mark-all zones
```

- [ ] **Step 5: Add `_register_action` and `_action_at`**

In `hud.pyw`, immediately after `_register_hit` (after hud.pyw:307):

```python

    def _register_action(self, y, x0, x1, action):
        """Record an x-aware click zone that fires a manager action (mark-read),
        NOT a browser open. Checked before the open-URL hits, so the narrow
        right-edge zone never opens the thread."""
        self._action_hits.append((y - FEED_LINE_H // 2, y + FEED_LINE_H // 2, x0, x1, action))

    def _action_at(self, x, y):
        for y0, y1, x0, x1, action in self._action_hits:
            if y0 <= y <= y1 and x0 <= x <= x1:
                return action
        return None
```

- [ ] **Step 6: Give `_fit_line1` a `reserve` argument**

Replace `_fit_line1` (hud.pyw:309-318):

```python
    def _fit_line1(self, text, age, reserve=0):
        """Truncate line 1 by measured pixel width so it never collides with the
        right-aligned age (and the ✕ glyph when present, via reserve px)."""
        m = self._feed_font_measure.measure
        budget = WIDTH - 2 * PAD - m(age) - 8 - reserve
        if m(text) <= budget:
            return text
        while text and m(text + "…") > budget:
            text = text[:-1]
        return text + "…"
```

- [ ] **Step 7: Add `header_action` to every `_feed_tiles` yield and `dismiss` to notification items**

In `_feed_tiles` (hud.pyw:252-300), make every `yield` produce a 5-tuple. Replace the four non-notifications yields and the whole notifications branch:

The invalid-feed yield (hud.pyw:261):

```python
                yield (title, None, FEED_DIM, [("! " + (feed.get("error") or "invalid"), None, True)], None)
```

The loading yield (hud.pyw:265):

```python
                yield (title, None, FEED_FG, [("loading…", None, True)], None)
```

The notifications branch (replace hud.pyw:267-288 in full):

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
                    dismiss = ("one", idx, it.thread_url) if it.thread_url else None
                    lines.append((line1, it.url, color, it.title, age, dismiss))
                extra = badge - len(result.items)
                if extra > 0:
                    lines.append(("… %d more" % extra, "https://github.com/notifications", True))
                header_action = ("all", idx) if (result.state == "ok" and result.items) else None
                yield (header, "https://github.com/notifications", FEED_FG, lines, header_action)
                continue
```

The github-tile yield (hud.pyw:292):

```python
                yield (result.status.text, result.status.url, color, lines, None)
```

The generic trailing yield (hud.pyw:300):

```python
            yield (title, None, FEED_FG, lines, None)
```

- [ ] **Step 8: Draw the glyphs + register zones in `_draw_feeds`**

Replace `_draw_feeds` (hud.pyw:320-359) in full:

```python
    def _draw_feeds(self):
        c = self.canvas
        for item_id in self._feed_items:
            c.delete(item_id)
        self._feed_items = []
        self._hit = []
        self._action_hits = []
        y = PAD + 3 * ROW_H + 4
        for title, title_url, color, lines, header_action in self._feed_tiles():
            y += FEED_TITLE_GAP
            tid = c.create_text(PAD, y, anchor="w", text=_fit(title),
                                fill=color, font=FEED_TITLE_FONT)
            self._feed_items.append(tid)
            self._register_hit(y, title_url)            # github/notifications header is clickable
            if header_action is not None:               # notifications: ✓ marks all read
                mk = c.create_text(WIDTH - PAD, y, anchor="e", text=MARKALL_GLYPH,
                                   fill=FEED_DIM, font=FEED_TITLE_FONT)
                self._feed_items.append(mk)
                self._register_action(y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, header_action)
            y += FEED_LINE_H
            for row in lines:
                if len(row) == 3:                      # existing single-line path, unchanged
                    text, url, dim = row
                    lid = c.create_text(PAD + 6, y, anchor="w", text=_fit(text),
                                        fill=(FEED_DIM if dim else FEED_FG), font=FEED_FONT)
                    self._feed_items.append(lid)
                    self._register_hit(y, url)
                    y += FEED_LINE_H
                else:                                  # len == 6: notifications 2-line item
                    line1, url, color, subtitle, age, dismiss = row
                    reserve = ACTION_ZONE_W if dismiss else 0
                    l1 = c.create_text(PAD + 6, y, anchor="w",
                                       text=self._fit_line1(line1, age, reserve),
                                       fill=color, font=FEED_FONT)
                    self._feed_items.append(l1)
                    if age:
                        age_x = WIDTH - PAD - reserve
                        aid = c.create_text(age_x, y, anchor="e", text=age,
                                            fill=FEED_DIM, font=FEED_FONT)
                        self._feed_items.append(aid)
                    if dismiss is not None:
                        xg = c.create_text(WIDTH - PAD, y, anchor="e", text=DISMISS_GLYPH,
                                           fill=FEED_DIM, font=FEED_FONT)
                        self._feed_items.append(xg)
                        self._register_action(y, WIDTH - PAD - ACTION_ZONE_W, WIDTH, dismiss)
                    self._register_hit(y, url)
                    y += FEED_LINE_H
                    l2 = c.create_text(PAD + 12, y, anchor="w", text=_fit(subtitle),
                                       fill=FEED_DIM, font=FEED_FONT)
                    self._feed_items.append(l2)
                    self._register_hit(y, url)         # second band -> whole item opens the thread
                    y += FEED_LINE_H
        self._resize(y + PAD)
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS — new `TestHudNotificationsDismiss` plus every existing smoke test. The existing `TestHudNotificationsRendering` items have `thread_url=""` (the `_item` helper's default), so they render no `✕` and still satisfy their assertions; the subprocess `test_launches_and_exits_clean` still exits 0.

- [ ] **Step 10: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): dismiss ✕ + mark-all ✓ glyphs with x-aware action zones"
```

---

### Task 6: hud.pyw — click dispatch, optimistic update, confirm

**Files:**
- Modify: `hud.pyw` — add `import tkinter.messagebox as tkmsg` (next to `import tkinter.font as tkfont`); `_on_release` (hud.pyw:167-179); add `_do_dismiss`
- Test: `tests/test_smoke_hud.py`

**Interfaces:**
- Consumes: `_action_at` + `self._action_hits` (Task 5), `manager.mark_read`/`mark_all_read` (Task 4), `FeedResult._replace` (namedtuple).
- Produces: a plain (non-drag) click in a dismiss/mark-all zone applies the change optimistically to `feed_state[idx]`, redraws, and enqueues the manager action; mark-all first confirms via `tkmsg.askyesno`. The open-thread path is otherwise unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `class TestHudNotificationsDismiss` (the class from Task 5) in `tests/test_smoke_hud.py`:

```python
    def _click(self, hud, kind):
        """Synthesize a plain click at the center of the first action zone of `kind`."""
        for (y0, y1, x0, x1, a) in hud._action_hits:
            if a[0] == kind:
                ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
                hud._moved = False
                hud._on_release(ev)
                return a
        return None

    def test_dismiss_one_optimistic_and_enqueues(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        hud.manager.stop()                         # deterministic _actions inspection
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 3)
            hud._draw_feeds(); root.update_idletasks()
            self._click(hud, "one")
            self.assertEqual(len(hud.feed_state[0].items), 0)   # optimistically removed
            self.assertEqual(hud.feed_state[0].badge, 2)        # 3 - 1
            self.assertEqual(hud.manager._actions.get_nowait(),
                             ("one", 0, "https://api.github.com/notifications/threads/7"))
        finally:
            hud.close(); root.destroy()

    def test_mark_all_confirm_yes_clears_and_enqueues(self):
        import feedkit.manager as manager
        import tkinter.messagebox as tkmsg
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        hud.manager.stop()
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 8)
            hud._draw_feeds(); root.update_idletasks()
            with mock.patch.object(tkmsg, "askyesno", lambda *a, **k: True):
                self._click(hud, "all")
            self.assertEqual(len(hud.feed_state[0].items), 0)
            self.assertEqual(hud.feed_state[0].badge, 0)
            self.assertEqual(hud.manager._actions.get_nowait(), ("all", 0, None))
        finally:
            hud.close(); root.destroy()

    def test_mark_all_confirm_no_does_nothing(self):
        import feedkit.manager as manager
        import tkinter.messagebox as tkmsg
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        hud.manager.stop()
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 8)
            hud._draw_feeds(); root.update_idletasks()
            with mock.patch.object(tkmsg, "askyesno", lambda *a, **k: False):
                self._click(hud, "all")
            self.assertEqual(len(hud.feed_state[0].items), 1)   # unchanged
            self.assertEqual(hud.feed_state[0].badge, 8)
            self.assertTrue(hud.manager._actions.empty())       # nothing enqueued
        finally:
            hud.close(); root.destroy()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudNotificationsDismiss -v`
Expected: FAIL — clicking the action zone currently falls through to `_open_at` (no dismiss); `feed_state` is unchanged and `_actions` stays empty.

- [ ] **Step 3: Import `messagebox`**

In `hud.pyw`, next to `import tkinter.font as tkfont` (hud.pyw:14):

```python
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as tkmsg
```

- [ ] **Step 4: Dispatch actions in `_on_release`**

Replace `_on_release` (hud.pyw:167-179):

```python
    def _on_release(self, event):
        if not self._moved:
            action = self._action_at(event.x, event.y)   # dismiss/mark-all zone wins over open
            if action is not None:
                self._do_dismiss(action)
                return
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

- [ ] **Step 5: Add `_do_dismiss`**

In `hud.pyw`, add after `_on_release` (after the new hud.pyw:~183), before `_on_menu`:

```python

    def _do_dismiss(self, action):
        """Optimistically apply a mark-read action to the rendered tile, then hand
        it to the worker. The worker's reconcile (success) or restore (failure)
        result overwrites this optimistic state on the next 250ms drain."""
        kind, idx = action[0], action[1]
        result = self.feed_state.get(idx)
        if kind == "one":
            thread_url = action[2]
            if result is not None:
                remaining = [it for it in result.items if it.thread_url != thread_url]
                self.feed_state[idx] = result._replace(
                    items=remaining, badge=max(0, (result.badge or 0) - 1))
                self._draw_feeds()
            self.manager.mark_read(idx, thread_url)
        elif kind == "all":
            if not tkmsg.askyesno("Mark all read?",
                                  "Mark all notifications as read?", parent=self.root):
                return
            if result is not None:
                self.feed_state[idx] = result._replace(items=[], badge=0)
                self._draw_feeds()
            self.manager.mark_all_read(idx)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v`
Expected: PASS — new dispatch tests plus every existing smoke test (including the subprocess `test_launches_and_exits_clean`).

- [ ] **Step 7: Commit**

```bash
git add hud.pyw tests/test_smoke_hud.py
git commit -m "feat(hud): click-to-dismiss + mark-all (optimistic, confirm dialog)"
```

---

## Final verification

After all tasks, run the full suite:

Run: `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests -v`
Expected: PASS — entire suite green, including the subprocess HUD smoke (`test_launches_and_exits_clean`) exiting 0 with empty stderr.

---

## Self-Review

**1. Spec coverage** (each spec section → task):
- §2 UX (`✕` per item, `✓` header confirm, optimistic, no-`✕` when thread_url empty) → Task 5 (glyphs/zones) + Task 6 (dispatch/optimistic/confirm).
- §3 model (`NotifItem.thread_url`, api-URL isolation) → Task 1 (field) + Task 2 (parser) + Task 5/6 (thread_url only flows to actions, never `_register_hit`).
- §4 network `send` (PATCH/PUT, TLS, taxonomy) → Task 3.
- §5 worker action queue (drain, force-refetch on success, restore on failure, `set_feeds` clears) → Task 4.
- §6 HUD hit-testing (x-aware), optimism, confirm, error line → Tasks 5 + 6 (the `"dismiss failed"` restore from Task 4 renders via the existing notifications error-line path in `_feed_tiles`).
- §7 security (browser open-path only gets `https://github.com/…`; confirm on mark-all; TLS) → Global Constraints + Task 3 + Task 6.
- §8 testing → distributed per task.

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to" — every code and test step has full literal content.

**3. Type consistency:** `NotifItem` 9-field order is identical at definition (Task 1), construction (Task 2), and consumption (`it.thread_url` in Task 5). `SendResult(status, code, error)` is consistent across Task 3 (def) and Task 4 (tests/use). Action tuples are uniform length-3: `("one", idx, thread_url)` / `("all", idx, None)` produced by `mark_read`/`mark_all_read` (Task 4) and consumed by `_do_action` (Task 4) and `_do_dismiss` (Task 6); the render-side `dismiss`/`header_action` payloads (`("one", idx, thread_url)` / `("all", idx)`) are 3- and 2-tuples used only for hit-zone dispatch, and `_do_dismiss` reads them by `action[0]`/`action[1]`/`action[2]` so both shapes work. `_feed_tiles` yields are uniformly 5-tuples; notification item rows are uniformly 6-tuples; `_draw_feeds` dispatches on `len(row) in (3, 6)`.

**Note on the worker thread in dispatch tests:** the in-process `_make_hud` starts the real worker, which drains `self._actions`. Tasks 6's tests call `hud.manager.stop()` before enqueuing so the action queue can be inspected deterministically (they assert enqueue + optimistic state, not worker processing — that is covered by Task 4's `TestMarkRead`).
