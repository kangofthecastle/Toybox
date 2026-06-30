import unittest
import feedkit.model as model


class TestTextHelpers(unittest.TestCase):
    def test_strip_control_chars_removes_controls_and_collapses_ws(self):
        self.assertEqual(model.strip_control_chars("a\x00b\tc\n  d"), "ab c d")

    def test_strip_control_chars_none_and_empty(self):
        self.assertEqual(model.strip_control_chars(None), "")
        self.assertEqual(model.strip_control_chars(""), "")

    def test_truncate_short_unchanged(self):
        self.assertEqual(model.truncate("hello", 10), "hello")

    def test_truncate_long_adds_ellipsis(self):
        self.assertEqual(model.truncate("hello world", 8), "hello w…")

    def test_truncate_tiny_budget(self):
        self.assertEqual(model.truncate("hello", 1), "…")


class TestConditionalHeaders(unittest.TestCase):
    def test_both_present(self):
        self.assertEqual(
            model.build_conditional_headers('W/"abc"', "Mon, 01 Jan 2026 00:00:00 GMT"),
            {"If-None-Match": 'W/"abc"', "If-Modified-Since": "Mon, 01 Jan 2026 00:00:00 GMT"})

    def test_none_present(self):
        self.assertEqual(model.build_conditional_headers(None, None), {})

    def test_only_etag(self):
        self.assertEqual(model.build_conditional_headers('"x"', None), {"If-None-Match": '"x"'})


class TestGithubBuilders(unittest.TestCase):
    def test_ci_url_plain_branch(self):
        self.assertEqual(
            model.github_ci_url("kangofthecastle/Toybox", "main"),
            "https://api.github.com/repos/kangofthecastle/Toybox/commits/main/check-runs?per_page=100")

    def test_ci_url_encodes_slash_in_branch(self):
        self.assertEqual(
            model.github_ci_url("o/r", "feature/x"),
            "https://api.github.com/repos/o/r/commits/feature%2Fx/check-runs?per_page=100")

    def test_notifications_url_has_per_page(self):
        self.assertEqual(model.github_notifications_url(),
                         "https://api.github.com/notifications?per_page=50")

    def test_headers_without_token_have_no_authorization(self):
        h = model.github_headers("")
        self.assertEqual(h["User-Agent"], "Toybox-WebFeed/1.0")
        self.assertEqual(h["Accept"], "application/vnd.github+json")
        self.assertEqual(h["X-GitHub-Api-Version"], "2022-11-28")
        self.assertNotIn("Authorization", h)

    def test_headers_with_token_have_bearer(self):
        h = model.github_headers("ghp_secret")
        self.assertEqual(h["Authorization"], "Bearer ghp_secret")


class TestIsWebUrl(unittest.TestCase):
    def test_http_and_https_allowed(self):
        self.assertTrue(model.is_web_url("http://x/y"))
        self.assertTrue(model.is_web_url("https://x/y"))
        self.assertTrue(model.is_web_url("HTTPS://X/Y"))

    def test_other_schemes_and_junk_rejected(self):
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,x",
                    "ftp://x", "", None, 123):
            self.assertFalse(model.is_web_url(bad), bad)


if __name__ == "__main__":
    unittest.main()
