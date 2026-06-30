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

    def test_github_mark_all_read_url(self):
        self.assertEqual(model.github_mark_all_read_url(),
                         "https://api.github.com/notifications")

    def test_headers_without_token_have_no_authorization(self):
        h = model.github_headers("")
        self.assertEqual(h["User-Agent"], "Toybox-WebFeed/1.0")
        self.assertEqual(h["Accept"], "application/vnd.github+json")
        self.assertEqual(h["X-GitHub-Api-Version"], "2022-11-28")
        self.assertNotIn("Authorization", h)

    def test_headers_with_token_have_bearer(self):
        h = model.github_headers("ghp_secret")
        self.assertEqual(h["Authorization"], "Bearer ghp_secret")


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
             "updated_at", "title", "url", "thread_url"))

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


class TestIsWebUrl(unittest.TestCase):
    def test_http_and_https_allowed(self):
        self.assertTrue(model.is_web_url("http://x/y"))
        self.assertTrue(model.is_web_url("https://x/y"))
        self.assertTrue(model.is_web_url("HTTPS://X/Y"))

    def test_other_schemes_and_junk_rejected(self):
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,x",
                    "ftp://x", "", None, 123):
            self.assertFalse(model.is_web_url(bad), bad)


class TestNormalizeFeed(unittest.TestCase):
    def test_rss_minimal_fills_defaults(self):
        f = model.normalize_feed({"type": "rss", "url": "https://news.ycombinator.com/rss"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["type"], "rss")
        self.assertEqual(f["items"], 3)
        self.assertEqual(f["interval"], 300)            # floor for non-github
        self.assertEqual(f["title"], "news.ycombinator.com")  # derived from host

    def test_items_clamped_and_interval_floored(self):
        f = model.normalize_feed({"type": "rss", "url": "https://x/y", "items": 99, "interval": 5})
        self.assertEqual(f["items"], 10)                # clamped 1..10
        self.assertEqual(f["interval"], 300)            # floored

    def test_unknown_type_invalid_but_titled(self):
        f = model.normalize_feed({"type": "weather", "title": "Sky"})
        self.assertFalse(f["valid"])
        self.assertIn("unknown type", f["error"])
        self.assertEqual(f["title"], "Sky")

    def test_rss_missing_url_invalid(self):
        f = model.normalize_feed({"type": "rss"})
        self.assertFalse(f["valid"])
        self.assertIn("url", f["error"])

    def test_rss_non_http_scheme_invalid(self):
        f = model.normalize_feed({"type": "rss", "url": "file:///etc/passwd"})
        self.assertFalse(f["valid"])

    def test_json_requires_path_and_fields_text(self):
        self.assertFalse(model.normalize_feed(
            {"type": "json", "url": "https://x", "fields": {"text": "t"}})["valid"])  # no path
        self.assertFalse(model.normalize_feed(
            {"type": "json", "url": "https://x", "path": "a", "fields": {"url": "u"}})["valid"])  # no text
        ok = model.normalize_feed(
            {"type": "json", "url": "https://x", "path": "a.b", "fields": {"text": "t", "url": "u"}})
        self.assertTrue(ok["valid"])
        self.assertEqual(ok["path"], "a.b")
        self.assertEqual(ok["fields"], {"text": "t", "url": "u"})

    def test_text_regex_optional(self):
        f = model.normalize_feed({"type": "text", "url": "https://x"})
        self.assertTrue(f["valid"])
        self.assertIsNone(f["regex"])
        g = model.normalize_feed({"type": "text", "url": "https://x", "regex": "(\\d+)"})
        self.assertEqual(g["regex"], "(\\d+)")

    def test_github_minimal(self):
        f = model.normalize_feed({"type": "github", "repo": "kangofthecastle/Toybox"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["branch"], "main")
        self.assertEqual(f["show"], ["ci", "notifications"])
        self.assertEqual(f["interval"], 120)            # github floor
        self.assertEqual(f["title"], "Toybox")

    def test_github_bad_repo_invalid(self):
        self.assertFalse(model.normalize_feed({"type": "github", "repo": "no-slash"})["valid"])

    def test_github_show_filtered(self):
        f = model.normalize_feed({"type": "github", "repo": "o/r", "show": ["ci", "bogus"]})
        self.assertEqual(f["show"], ["ci"])

    def test_non_dict_input(self):
        self.assertFalse(model.normalize_feed("nope")["valid"])

    def test_non_finite_numbers_fall_back_not_raise(self):
        f = model.normalize_feed({"type": "rss", "url": "https://x/y", "interval": float("nan")})
        self.assertTrue(f["valid"])
        self.assertEqual(f["interval"], 300)        # non-finite -> default floor, no raise
        g = model.normalize_feed({"type": "rss", "url": "https://x/y", "items": float("inf")})
        self.assertEqual(g["items"], 3)             # non-finite -> default, no raise

    def test_github_show_all_invalid_is_invalid(self):
        f = model.normalize_feed({"type": "github", "repo": "o/r", "show": ["bogus", "junk"]})
        self.assertFalse(f["valid"])
        self.assertIn("show", f["error"])

    def test_items_lower_clamp(self):
        f = model.normalize_feed({"type": "rss", "url": "https://x/y", "items": 0})
        self.assertEqual(f["items"], 1)             # clamped up to the 1..10 floor

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


class TestDueFeeds(unittest.TestCase):
    def _valid(self, interval):
        return {"valid": True, "interval": interval}

    def test_first_pass_staggered(self):
        feeds = [self._valid(300), self._valid(300), self._valid(300)]
        # at now=1s only feed 0 (stagger 0) is due; feed 1 wants >=2s, feed 2 >=4s.
        self.assertEqual(model.due_feeds(feeds, {}, 1.0, stagger=2.0), [0])
        self.assertEqual(model.due_feeds(feeds, {}, 5.0, stagger=2.0), [0, 1, 2])

    def test_interval_gating(self):
        feeds = [self._valid(300)]
        self.assertEqual(model.due_feeds(feeds, {0: 100.0}, 350.0), [])   # 250s < 300
        self.assertEqual(model.due_feeds(feeds, {0: 100.0}, 400.0), [0])  # 300s >= 300

    def test_invalid_feeds_skipped(self):
        feeds = [{"valid": False, "error": "x"}, self._valid(300)]
        self.assertEqual(model.due_feeds(feeds, {}, 10.0), [1])


if __name__ == "__main__":
    unittest.main()
