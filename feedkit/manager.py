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

FeedResult = namedtuple("FeedResult", ["state", "items", "status", "error", "badge"],
                        defaults=(None,))


class FeedManager:
    def __init__(self, feeds, token="", fetch_fn=None, poll_interval=1.0, send_fn=None):
        self.feeds = [model.normalize_feed(f) for f in feeds]
        self.token = token or ""
        self._fetch = fetch_fn or fetch_mod.fetch
        self._send = send_fn or fetch_mod.send
        self._poll = poll_interval
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._last = {}      # idx -> elapsed seconds at last fetch
        self._cache = {}     # cache key -> per-source {etag, lm, result/ci/notif}
        self._poll_min = {}  # idx -> server-requested min seconds (X-Poll-Interval)
        self._actions = queue.Queue()  # pending mark-as-read actions (thread-safe)
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
            self._poll_min.clear()
        self._clear_actions()   # drop actions aimed at the now-replaced feed set

    def set_token(self, token):
        with self._lock:
            self.token = token or ""

    def set_stock_range(self, idx, code):
        """UI-thread session-state range change for a stocks feed. No-op unless idx
        is a valid stocks feed and code is a known range. Replaces the feed with a
        copy carrying the new range and drops its (idx,'stk',*) cache + last-fetch
        so the worker refetches the new range next tick."""
        with self._lock:
            if not (0 <= idx < len(self.feeds)):
                return
            feed = self.feeds[idx]
            if not feed.get("valid") or feed.get("type") != "stocks" or code not in model.STOCK_RANGES:
                return
            new = dict(feed)
            new["range"] = code
            self.feeds[idx] = new
            for k in [k for k in self._cache
                      if isinstance(k, tuple) and len(k) == 3 and k[0] == idx and k[1] == "stk"]:
                self._cache.pop(k, None)
            self._last.pop(idx, None)

    def refresh(self, indices):
        """Force a conditional re-fetch of the given feed indices on the next tick
        by dropping their last-fetch time (validators kept -> a 304 reuses cache)."""
        with self._lock:
            for idx in indices:
                self._last.pop(idx, None)

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

    # --- worker ---------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            try:
                self._run_once(time.monotonic() - self._start)
            except Exception:
                pass
            self._stop.wait(self._poll)

    def _run_once(self, now):
        self._process_actions(now)   # apply queued mark-as-read before computing due feeds
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

    def _fetch_and_process(self, idx, feed, token):
        if feed["type"] == "notifications":
            return self._process_notifications(idx, feed, token)
        if feed["type"] == "search":
            return self._process_search(idx, feed, token)
        if feed["type"] == "stocks":
            return self._process_stocks(idx, feed)
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

    def _process_stocks(self, idx, feed):
        """Per-symbol Yahoo chart fetch (no token). Conditional GET per symbol under
        cache key (idx,'stk',symbol) -> {etag, lm, quote}. not_modified reuses the
        cached Quote (fresh); error keeps the cached Quote if any (stale); a 200 is
        parsed, keeping the prior Quote on a None parse. Tile freshness is coarse:
        one flaky symbol dims/annotates the whole tile."""
        range_ = feed["range"]
        quotes = []
        any_error = None
        refreshed = False
        for symbol in feed["symbols"]:
            key = (idx, "stk", symbol)
            with self._lock:
                cache = self._cache.get(key, {})
            res = self._fetch(model.yahoo_chart_url(symbol, range_),
                              etag=cache.get("etag"), last_modified=cache.get("lm"))
            if res.status == "not_modified":
                q = cache.get("quote")
                if q is not None:
                    quotes.append(q)
                    refreshed = True
                continue
            if res.status == "error":
                any_error = res.error
                q = cache.get("quote")
                if q is not None:
                    quotes.append(q)
                continue
            q = parse.parse_stock_chart(res.body, symbol)
            if q is None:
                any_error = any_error or "bad data"
                prev = cache.get("quote")
                if prev is not None:
                    quotes.append(prev)
                continue
            quotes.append(q)
            refreshed = True
            with self._lock:
                self._cache[key] = {"etag": res.etag, "lm": res.last_modified, "quote": q}
        if refreshed and not any_error:
            state = "ok"
        elif quotes:
            state = "stale"
        else:
            state = "error"
        return FeedResult(state, quotes, None, any_error)

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
