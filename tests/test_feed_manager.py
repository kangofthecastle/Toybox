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
