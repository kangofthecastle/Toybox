import http.server
import threading
import unittest
import urllib.error

import feedkit.fetch as fetch


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/etag":
            if self.headers.get("If-None-Match") == '"v1"':
                self.send_response(304); self.end_headers(); return
            self.send_response(200)
            self.send_header("ETag", '"v1"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        elif self.path == "/big":
            self.send_response(200); self.end_headers()
            self.wfile.write(b"x" * 5000)
        elif self.path == "/boom":
            self.send_response(403)
            self.send_header("X-RateLimit-Remaining", "0")
            self.end_headers()
        elif self.path == "/boom2":
            self.send_response(403)
            self.send_header("X-RateLimit-Remaining", "57")
            self.end_headers()
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
        else:
            self.send_response(404); self.end_headers()


class TestFetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.t.join(timeout=1)

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def test_ok_returns_body_and_etag(self):
        r = fetch.fetch(self._url("/etag"))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.body, b'{"ok": true}')
        self.assertEqual(r.etag, '"v1"')
        self.assertIn("application/json", r.content_type)

    def test_conditional_304(self):
        r = fetch.fetch(self._url("/etag"), etag='"v1"')
        self.assertEqual(r.status, "not_modified")
        self.assertIsNone(r.body)
        self.assertEqual(r.etag, '"v1"')

    def test_size_cap(self):
        r = fetch.fetch(self._url("/big"), max_bytes=1000)
        self.assertEqual(r.status, "error")
        self.assertEqual(r.error, "too large")

    def test_http_403_with_zero_quota_is_rate_limited(self):
        r = fetch.fetch(self._url("/boom"))
        self.assertEqual(r.status, "error")
        self.assertEqual(r.error, "rate-limited")

    def test_http_403_with_quota_left_is_bad_token(self):
        r = fetch.fetch(self._url("/boom2"))
        self.assertEqual(r.error, "bad token")
        self.assertEqual(r.status, "error")

    def test_connection_refused_is_offline(self):
        r = fetch.fetch("http://127.0.0.1:9/never", timeout=1)
        self.assertEqual(r.status, "error")
        self.assertEqual(r.error, "offline")

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


class TestErrorWord(unittest.TestCase):
    def test_403_rate_limited_when_quota_zero(self):
        e = urllib.error.HTTPError("u", 403, "m", {"x-ratelimit-remaining": "0"}, None)
        self.assertEqual(fetch._error_word(e), "rate-limited")

    def test_403_bad_token_when_quota_remains_or_absent(self):
        e1 = urllib.error.HTTPError("u", 403, "m", {"x-ratelimit-remaining": "57"}, None)
        e2 = urllib.error.HTTPError("u", 403, "m", {}, None)
        self.assertEqual(fetch._error_word(e1), "bad token")
        self.assertEqual(fetch._error_word(e2), "bad token")

    def test_other_http_codes(self):
        mk = lambda code: urllib.error.HTTPError("u", code, "m", {}, None)
        self.assertEqual(fetch._error_word(mk(401)), "bad token")
        self.assertEqual(fetch._error_word(mk(404)), "no access")

    def test_cert_error(self):
        import ssl
        e = urllib.error.URLError(ssl.SSLCertVerificationError("bad cert"))
        self.assertEqual(fetch._error_word(e), "cert error")

    def test_generic_urlerror_offline(self):
        self.assertEqual(fetch._error_word(urllib.error.URLError("down")), "offline")

    def test_bare_timeout_is_offline(self):
        self.assertEqual(fetch._error_word(TimeoutError()), "offline")


if __name__ == "__main__":
    unittest.main()
