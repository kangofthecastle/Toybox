import json
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
        self.assertEqual(len(result.items), 2)


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


class TestFeedResultBadge(unittest.TestCase):
    def test_badge_defaults_none(self):
        self.assertIsNone(manager.FeedResult("ok", [], None, None).badge)


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


class TestStockRangeAndRefresh(unittest.TestCase):
    def _chart(self, price=100.0, prev=99.0, closes=(98.0, 100.0)):
        return json.dumps({"chart": {"result": [{
            "meta": {"regularMarketPrice": price, "chartPreviousClose": prev},
            "indicators": {"quote": [{"close": list(closes)}]}}], "error": None}}).encode()

    def test_set_stock_range_updates_and_refetches(self):
        urls = []
        def fake(url, **kw):
            urls.append(url); return _ok(self._chart())
        feed = {"type": "stocks", "symbols": ["SPY"], "range": "1mo", "tab": "markets"}
        m = manager.FeedManager([feed], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        self.assertIn("range=1mo", urls[0])
        m.set_stock_range(0, "1d")
        self.assertEqual(m.feeds[0]["range"], "1d")
        self.assertNotIn(0, m._last)                          # last-fetch dropped -> due next tick
        self.assertFalse(any(isinstance(k, tuple) and len(k) == 3 and k[0] == 0 and k[1] == "stk"
                             for k in m._cache))              # stk cache cleared
        m._run_once(5.0)
        self.assertTrue(any("range=1d" in u for u in urls[1:]))   # refetched with new range

    def test_set_stock_range_ignores_unknown_code_and_nonstocks(self):
        feed = {"type": "stocks", "symbols": ["SPY"], "range": "1mo", "tab": "markets"}
        rss = {"type": "rss", "url": "https://x"}
        m = manager.FeedManager([feed, rss], fetch_fn=lambda u, **k: _ok(self._chart()))
        m.set_stock_range(0, "zzz")
        self.assertEqual(m.feeds[0]["range"], "1mo")          # unknown code -> unchanged
        m.set_stock_range(1, "1d")
        self.assertNotIn("range", m.feeds[1])                 # non-stocks idx -> unchanged
        m.set_stock_range(99, "1d")                           # out of range -> no crash

    def test_refresh_drops_last_for_given_indices_only(self):
        a = {"type": "rss", "url": "https://a"}
        b = {"type": "rss", "url": "https://b"}
        m = manager.FeedManager([a, b], fetch_fn=lambda u, **k: _ok(RSS))
        m._run_once(4.0); m.drain()
        self.assertIn(0, m._last); self.assertIn(1, m._last)
        m.refresh([0])
        self.assertNotIn(0, m._last)
        self.assertIn(1, m._last)


class TestProcessStocks(unittest.TestCase):
    def _chart(self, price, prev, closes):
        return json.dumps({"chart": {"result": [{
            "meta": {"regularMarketPrice": price, "chartPreviousClose": prev},
            "indicators": {"quote": [{"close": list(closes)}]}}], "error": None}}).encode()

    FEED = {"type": "stocks", "symbols": ["SPY", "META"], "range": "1mo", "tab": "markets"}

    def test_all_ok_two_quotes(self):
        def fake(url, **kw):
            if "chart/SPY" in url:
                return _ok(self._chart(746.77, 756.0, [740.0, 745.0, 746.77]))
            return _ok(self._chart(563.29, 562.0, [560.0, 561.0, 563.29]))
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "ok")
        self.assertEqual([q.symbol for q in result.items], ["SPY", "META"])
        self.assertAlmostEqual(result.items[0].price, 746.77)

    def test_one_symbol_error_after_success_is_stale_retained(self):
        state = {"n": 0}
        def fake(url, **kw):
            if "chart/SPY" in url:
                return _ok(self._chart(746.77, 756.0, [740.0, 746.77]))
            state["n"] += 1
            return _ok(self._chart(563.29, 562.0, [560.0, 563.29])) if state["n"] == 1 else _err("offline")
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        m._last.clear()
        m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.error, "offline")
        self.assertEqual(len(result.items), 2)                # META retained from cache

    def test_not_modified_reuses_quote(self):
        responses = [_ok(self._chart(746.77, 756.0, [740.0, 746.77])), _nm()]
        m = manager.FeedManager([{"type": "stocks", "symbols": ["SPY"], "range": "1mo"}],
                                fetch_fn=lambda u, **k: responses.pop(0))
        m._run_once(0.0); m.drain()
        m._last.clear()
        m._run_once(1000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "ok")
        self.assertAlmostEqual(result.items[0].price, 746.77)

    def test_all_fail_no_cache_is_error(self):
        m = manager.FeedManager([{"type": "stocks", "symbols": ["SPY"], "range": "1mo"}],
                                fetch_fn=lambda u, **k: _err("offline"))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")
        self.assertEqual(result.items, [])
        self.assertEqual(result.error, "offline")


class TestProcessWeather(unittest.TestCase):
    GEO = json.dumps({"results": [
        {"name": "Boston", "latitude": 42.36, "longitude": -71.06}]}).encode()

    def _forecast(self, current=72.0, hi=78.0, lo=61.0, series=(70.0, 72.0, 74.0)):
        return json.dumps({
            "current": {"temperature_2m": current},
            "current_units": {"temperature_2m": "°F"},
            "hourly": {"temperature_2m": list(series)},
            "daily": {"temperature_2m_max": [hi], "temperature_2m_min": [lo]},
        }).encode()

    FEED = {"type": "weather", "city": "Boston", "units": "fahrenheit",
            "range": "today", "tab": "global"}

    def test_ok_geocode_then_forecast(self):
        def fake(url, **kw):
            if "geocoding-api" in url:
                return _ok(self.GEO)
            return _ok(self._forecast())
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "ok")
        w = result.items[0]
        self.assertAlmostEqual(w.current, 72.0)
        self.assertAlmostEqual(w.hi, 78.0)
        self.assertAlmostEqual(w.lo, 61.0)

    def test_geocode_cached_not_refetched(self):
        geo_calls = {"n": 0}
        def fake(url, **kw):
            if "geocoding-api" in url:
                geo_calls["n"] += 1
                return _ok(self.GEO)
            return _ok(self._forecast())
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        m._last.clear()
        m._run_once(2000.0); m.drain()
        self.assertEqual(geo_calls["n"], 1)          # geocoded once, cached thereafter

    def test_geocode_failure_is_error(self):
        m = manager.FeedManager(
            [self.FEED],
            fetch_fn=lambda u, **k: _err("offline") if "geocoding-api" in u else _ok(b"{}"))
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")
        self.assertEqual(result.items, [])

    def test_city_not_found_is_error(self):
        def fake(url, **kw):
            if "geocoding-api" in url:
                return _ok(json.dumps({"results": []}).encode())
            return _ok(self._forecast())
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0)
        idx, result = m.drain()[0]
        self.assertEqual(result.state, "error")

    def test_forecast_failure_after_success_is_stale_retained(self):
        state = {"n": 0}
        def fake(url, **kw):
            if "geocoding-api" in url:
                return _ok(self.GEO)
            state["n"] += 1
            return _ok(self._forecast()) if state["n"] == 1 else _err("offline")
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        m._last.clear()
        m._run_once(2000.0)
        idx, result = m.drain()[-1]
        self.assertEqual(result.state, "stale")
        self.assertEqual(result.error, "offline")
        self.assertEqual(len(result.items), 1)       # last-good weather retained

    def test_set_weather_range_updates_and_refetches(self):
        urls = []
        def fake(url, **kw):
            urls.append(url)
            if "geocoding-api" in url:
                return _ok(self.GEO)
            return _ok(self._forecast())
        m = manager.FeedManager([self.FEED], fetch_fn=fake)
        m._run_once(0.0); m.drain()
        m.set_weather_range(0, "7d")
        self.assertEqual(m.feeds[0]["range"], "7d")
        m._run_once(2000.0); m.drain()
        self.assertTrue(any("forecast_days=7" in u for u in urls))

    def test_set_weather_range_ignores_unknown_and_nonweather(self):
        m = manager.FeedManager(
            [self.FEED, {"type": "stocks", "symbols": ["SPY"], "range": "1mo"}],
            fetch_fn=lambda u, **k: _ok(self.GEO if "geocoding" in u
                                        else json.dumps({
                "current": {"temperature_2m": 1.0},
                "current_units": {"temperature_2m": "°F"},
                "hourly": {"temperature_2m": [1.0]},
                "daily": {"temperature_2m_max": [2.0], "temperature_2m_min": [0.0]}}).encode()))
        m.set_weather_range(0, "zzz")
        self.assertEqual(m.feeds[0]["range"], "today")   # unknown code -> unchanged
        m.set_weather_range(1, "7d")
        self.assertEqual(m.feeds[1].get("range"), "1mo") # non-weather idx -> unchanged
        m.set_weather_range(99, "7d")                    # out of range -> no crash


if __name__ == "__main__":
    unittest.main()
