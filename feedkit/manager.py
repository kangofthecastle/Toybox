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
