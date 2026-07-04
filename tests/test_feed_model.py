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

    def test_search_url_encodes_query(self):
        self.assertEqual(
            model.github_search_url("is:open is:pr author:@me", 5),
            "https://api.github.com/search/issues?q=is%3Aopen%20is%3Apr%20author%3A%40me"
            "&sort=updated&order=desc&per_page=5")

    def test_search_web_url_is_browser_url(self):
        url = model.github_search_web_url("is:open is:pr author:@me")
        self.assertEqual(
            url,
            "https://github.com/search?q=is%3Aopen%20is%3Apr%20author%3A%40me&type=issues")
        self.assertTrue(model.is_web_url(url))

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
        f = model.normalize_feed({"type": "podcast", "title": "Sky"})
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

    def test_search_minimal_valid(self):
        f = model.normalize_feed({"type": "search", "query": "is:open is:pr author:@me"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["query"], "is:open is:pr author:@me")
        self.assertEqual(f["items"], 5)
        self.assertEqual(f["interval"], 300)
        self.assertEqual(f["title"], "Search")

    def test_search_missing_query_invalid(self):
        self.assertFalse(model.normalize_feed({"type": "search"})["valid"])
        blank = model.normalize_feed({"type": "search", "query": "   "})
        self.assertFalse(blank["valid"])
        self.assertEqual(blank["error"], "search feed needs 'query'")

    def test_search_interval_floor_120(self):
        self.assertEqual(
            model.normalize_feed({"type": "search", "query": "x", "interval": 5})["interval"], 120)
        self.assertEqual(
            model.normalize_feed({"type": "search", "query": "x", "interval": 600})["interval"], 600)

    def test_search_items_clamped(self):
        self.assertEqual(
            model.normalize_feed({"type": "search", "query": "x", "items": 99})["items"], 10)
        self.assertEqual(
            model.normalize_feed({"type": "search", "query": "x", "items": 0})["items"], 1)

    def test_search_custom_title_and_strips_query(self):
        f = model.normalize_feed({"type": "search", "query": "  is:open  ", "title": "My PRs"})
        self.assertEqual(f["title"], "My PRs")
        self.assertEqual(f["query"], "is:open")


class TestNormalizeStocksAndTab(unittest.TestCase):
    def test_news_feeds_get_tab(self):
        self.assertEqual(model.normalize_feed(
            {"type": "rss", "url": "https://x/y", "tab": "tech"})["tab"], "tech")
        self.assertEqual(model.normalize_feed(
            {"type": "rss", "url": "https://x/y"})["tab"], "global")          # missing -> global
        self.assertEqual(model.normalize_feed(
            {"type": "rss", "url": "https://x/y", "tab": "nope"})["tab"], "global")  # unknown -> global

    def test_invalid_news_feed_still_has_tab(self):
        f = model.normalize_feed({"type": "rss", "tab": "markets"})            # missing url -> invalid
        self.assertFalse(f["valid"])
        self.assertEqual(f["tab"], "markets")

    def test_pinned_feeds_have_no_tab(self):
        self.assertNotIn("tab", model.normalize_feed({"type": "notifications"}))
        self.assertNotIn("tab", model.normalize_feed({"type": "github", "repo": "o/r"}))

    def test_stocks_minimal_valid(self):
        f = model.normalize_feed({"type": "stocks", "symbols": ["spy", "META"],
                                  "range": "1d", "tab": "markets"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["symbols"], ["SPY", "META"])                       # upper-cased
        self.assertEqual(f["range"], "1d")
        self.assertEqual(f["tab"], "markets")
        self.assertEqual(f["interval"], 300)                                  # default
        self.assertEqual(f["title"], "Markets")                              # default title

    def test_stocks_cleans_and_caps_symbols(self):
        f = model.normalize_feed({"type": "stocks",
                                  "symbols": ["a b!", "", 5, "BRK-B", "^GSPC"] + ["X%d" % i for i in range(20)]})
        self.assertEqual(f["symbols"][:4], ["AB", "BRK-B", "^GSPC", "X0"])    # junk stripped, non-str dropped
        self.assertLessEqual(len(f["symbols"]), 10)                          # capped at 10

    def test_stocks_no_usable_symbol_invalid(self):
        f = model.normalize_feed({"type": "stocks", "symbols": ["", "!!", 3]})
        self.assertFalse(f["valid"])
        self.assertIn("symbols", f["error"])
        self.assertEqual(f["title"], "Markets")                              # titled for the error tile

    def test_stocks_bad_range_defaults(self):
        self.assertEqual(model.normalize_feed(
            {"type": "stocks", "symbols": ["SPY"], "range": "10y"})["range"], "1mo")

    def test_stocks_interval_floor_120(self):
        self.assertEqual(model.normalize_feed(
            {"type": "stocks", "symbols": ["SPY"], "interval": 5})["interval"], 120)

    def test_stocks_default_tab_global_when_missing(self):
        self.assertEqual(model.normalize_feed(
            {"type": "stocks", "symbols": ["SPY"]})["tab"], "global")         # like any news feed


class TestTabsAndTypes(unittest.TestCase):
    def test_news_tabs_order_and_labels(self):
        self.assertEqual([k for k, _ in model.NEWS_TABS],
                         ["global", "markets", "tech", "sports"])
        self.assertEqual(dict(model.NEWS_TABS)["markets"], "Markets")

    def test_coerce_tab_valid_and_default_global(self):
        self.assertEqual(model.coerce_tab("markets"), "markets")
        self.assertEqual(model.coerce_tab("nope"), "global")
        self.assertEqual(model.coerce_tab(None), "global")

    def test_coerce_default_tab_valid_and_default_tech(self):
        self.assertEqual(model.coerce_default_tab("global"), "global")
        self.assertEqual(model.coerce_default_tab("bogus"), "tech")
        self.assertEqual(model.coerce_default_tab(None), "tech")

    def test_is_news_type(self):
        for t in ("rss", "json", "text", "stocks"):
            self.assertTrue(model.is_news_type(t), t)
        for t in ("github", "notifications", "search", "?", None):
            self.assertFalse(model.is_news_type(t), t)

    def test_is_pinned_type(self):
        for t in ("github", "notifications", "search"):
            self.assertTrue(model.is_pinned_type(t), t)
        for t in ("rss", "json", "text", "stocks", "?", None):
            self.assertFalse(model.is_pinned_type(t), t)


class TestStockPrimitives(unittest.TestCase):
    def test_quote_shape(self):
        q = model.Quote("SPY", 746.77, -1.3, [1.0, 2.0])
        self.assertEqual(q._fields, ("symbol", "price", "change_pct", "series"))
        self.assertEqual(q.symbol, "SPY")

    def test_chart_url_maps_range_to_interval(self):
        self.assertEqual(
            model.yahoo_chart_url("SPY", "1mo"),
            "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
            "?range=1mo&interval=1d&includePrePost=false")
        self.assertIn("range=1d&interval=5m", model.yahoo_chart_url("SPY", "1d"))
        self.assertIn("range=5d&interval=30m", model.yahoo_chart_url("SPY", "5d"))
        self.assertIn("range=3mo&interval=1d", model.yahoo_chart_url("SPY", "3mo"))

    def test_chart_url_unknown_range_falls_back_to_default(self):
        self.assertIn("range=1mo&interval=1d", model.yahoo_chart_url("SPY", "zzz"))

    def test_chart_url_percent_encodes_symbol(self):
        self.assertIn("/chart/%5EGSPC?", model.yahoo_chart_url("^GSPC", "1mo"))

    def test_quote_web_url_is_browser_url(self):
        u = model.yahoo_quote_web_url("SPY")
        self.assertEqual(u, "https://finance.yahoo.com/quote/SPY")
        self.assertTrue(model.is_web_url(u))

    def test_format_quote_line_down(self):
        q = model.Quote("SPY", 746.77, -1.3, [])
        self.assertEqual(model.format_quote_line(q), "SPY    746.77 ▼1.3%")

    def test_format_quote_line_up_and_zero(self):
        self.assertTrue(model.format_quote_line(model.Quote("META", 563.29, 0.14, [])).endswith("△0.1%"))
        self.assertIn("△", model.format_quote_line(model.Quote("X", 1.0, 0.0, [])))  # 0.0 -> up


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


class TestWeatherModel(unittest.TestCase):
    def test_weather_is_not_news_type_but_is_valid(self):
        self.assertFalse(model.is_news_type("weather"))   # always-shown, not tab-scoped
        self.assertIn("weather", model._VALID_TYPES)

    def test_geocode_url(self):
        self.assertEqual(
            model.openmeteo_geocode_url("Boston"),
            "https://geocoding-api.open-meteo.com/v1/search?name=Boston"
            "&count=1&language=en&format=json")

    def test_geocode_url_encodes_city(self):
        self.assertIn("name=New%20York", model.openmeteo_geocode_url("New York"))

    def test_forecast_url_today_is_one_day(self):
        u = model.openmeteo_forecast_url(42.36, -71.06, "fahrenheit", "today")
        self.assertIn("latitude=42.36", u)
        self.assertIn("longitude=-71.06", u)
        self.assertIn("temperature_unit=fahrenheit", u)
        self.assertIn("forecast_days=1", u)
        self.assertIn("current=temperature_2m", u)
        self.assertIn("hourly=temperature_2m", u)
        self.assertIn("daily=temperature_2m_max,temperature_2m_min", u)
        self.assertIn("timezone=auto", u)

    def test_forecast_url_ranges_map_to_days(self):
        self.assertIn("forecast_days=3",
                      model.openmeteo_forecast_url(1.0, 2.0, "celsius", "3d"))
        self.assertIn("forecast_days=7",
                      model.openmeteo_forecast_url(1.0, 2.0, "celsius", "7d"))

    def test_forecast_url_unknown_range_defaults_today(self):
        self.assertIn("forecast_days=1",
                      model.openmeteo_forecast_url(1.0, 2.0, "celsius", "zzz"))

    def test_forecast_url_unknown_units_defaults_fahrenheit(self):
        self.assertIn("temperature_unit=fahrenheit",
                      model.openmeteo_forecast_url(1.0, 2.0, "kelvin", "today"))

    def test_weather_shape(self):
        w = model.Weather(72.0, 78.0, 61.0, [70.0, 72.0], "°F")
        self.assertEqual(w._fields,
                         ("current", "hi", "lo", "series", "unit",
                          "code", "feels", "humidity", "wind", "precip"))

    def test_weather_new_fields_default_when_omitted(self):
        # Backward-compat: the 5-arg positional construction still works and the
        # richer fields fall to unknown sentinels.
        w = model.Weather(72.0, 78.0, 61.0, [70.0], "°F")
        self.assertEqual(w.code, -1)
        self.assertIsNone(w.feels)
        self.assertIsNone(w.humidity)
        self.assertIsNone(w.wind)
        self.assertIsNone(w.precip)

    def test_forecast_url_requests_richer_current_and_daily(self):
        u = model.openmeteo_forecast_url(1.0, 2.0, "fahrenheit", "today")
        self.assertIn("weather_code", u)
        self.assertIn("apparent_temperature", u)
        self.assertIn("relative_humidity_2m", u)
        self.assertIn("wind_speed_10m", u)
        self.assertIn("precipitation_probability_max", u)
        self.assertIn("wind_speed_unit=mph", u)          # imperial pairs with mph

    def test_forecast_url_celsius_uses_kmh_wind(self):
        u = model.openmeteo_forecast_url(1.0, 2.0, "celsius", "today")
        self.assertIn("wind_speed_unit=kmh", u)

    def test_weather_glyph_and_label_buckets(self):
        self.assertEqual((model.weather_glyph(0), model.weather_label(0)),
                         ("☀", "Clear"))            # ☀ clear
        self.assertEqual(model.weather_label(2), "Partly")
        self.assertEqual(model.weather_label(3), "Cloudy")
        self.assertEqual(model.weather_label(48), "Fog")
        self.assertEqual(model.weather_label(63), "Rain")
        self.assertEqual(model.weather_label(81), "Showers")
        self.assertEqual(model.weather_label(75), "Snow")
        self.assertEqual(model.weather_label(95), "Storm")

    def test_weather_glyph_unknown_is_empty(self):
        self.assertEqual(model.weather_glyph(-1), "")
        self.assertEqual(model.weather_label(999), "")
        self.assertEqual(model.weather_glyph(None), "")

    def test_format_weather_current_temp_and_condition(self):
        w = model.Weather(72.4, 78.0, 61.0, [], "°F", code=0)
        self.assertEqual(model.format_weather_current(w), "72°  Clear")

    def test_format_weather_current_omits_unknown_condition(self):
        w = model.Weather(72.4, 78.0, 61.0, [], "°F")   # code defaults to -1
        self.assertEqual(model.format_weather_current(w), "72°")

    def test_format_weather_hilo_rounds(self):
        w = model.Weather(72.4, 78.6, 61.2, [], "°F")
        self.assertEqual(model.format_weather_hilo(w), "H 79°  L 61°")

    def test_format_weather_hilo_appends_feels(self):
        w = model.Weather(72.0, 78.0, 61.0, [], "°F", feels=52.6)
        self.assertEqual(model.format_weather_hilo(w), "H 78°  L 61°  Feels 53°")

    def test_format_weather_detail_present_fields(self):
        w = model.Weather(72.0, 78.0, 61.0, [], "°F",
                          humidity=72, wind=9.4, precip=10)
        self.assertEqual(model.format_weather_detail(w),
                         "Hum 72%   Wind 9mph   Rain 10%")

    def test_format_weather_detail_celsius_wind_unit(self):
        w = model.Weather(20.0, 24.0, 15.0, [], "°C", wind=14.6)
        self.assertEqual(model.format_weather_detail(w), "Wind 15km/h")

    def test_format_weather_detail_empty_when_no_fields(self):
        w = model.Weather(72.0, 78.0, 61.0, [], "°F")
        self.assertEqual(model.format_weather_detail(w), "")

    def test_normalize_minimal_valid(self):
        f = model.normalize_feed({"type": "weather", "city": "Boston", "tab": "global"})
        self.assertTrue(f["valid"])
        self.assertEqual(f["city"], "Boston")
        self.assertEqual(f["units"], "fahrenheit")   # default
        self.assertEqual(f["range"], "today")        # default
        self.assertEqual(f["interval"], 1800)        # default
        self.assertEqual(f["title"], "Weather")      # default title
        self.assertNotIn("tab", f)                   # always-shown, not tab-scoped

    def test_normalize_units_and_range_coerce(self):
        f = model.normalize_feed({"type": "weather", "city": "X",
                                  "units": "celsius", "range": "7d"})
        self.assertEqual(f["units"], "celsius")
        self.assertEqual(f["range"], "7d")

    def test_normalize_bad_units_and_range_default(self):
        f = model.normalize_feed({"type": "weather", "city": "X",
                                  "units": "kelvin", "range": "10y"})
        self.assertEqual(f["units"], "fahrenheit")
        self.assertEqual(f["range"], "today")

    def test_normalize_missing_city_invalid(self):
        f = model.normalize_feed({"type": "weather", "city": "  "})
        self.assertFalse(f["valid"])
        self.assertIn("city", f["error"])
        self.assertEqual(f["title"], "Weather")

    def test_normalize_interval_floor_600(self):
        self.assertEqual(model.normalize_feed(
            {"type": "weather", "city": "X", "interval": 5})["interval"], 600)

    def test_normalize_weather_has_no_tab(self):
        # weather is always-shown, not tab-scoped, so it carries no tab key.
        f = model.normalize_feed({"type": "weather", "city": "X"})
        self.assertTrue(f["valid"])
        self.assertNotIn("tab", f)


class TestParseSymbols(unittest.TestCase):
    def test_splits_on_commas_and_spaces_uppercases(self):
        self.assertEqual(model.parse_symbols("spy, meta nvda"), ["SPY", "META", "NVDA"])

    def test_strips_junk_chars_keeps_allowed(self):
        self.assertEqual(model.parse_symbols("brk-b ^gspc a@b!"), ["BRK-B", "^GSPC", "AB"])

    def test_dedupes_preserving_first_seen_order(self):
        self.assertEqual(model.parse_symbols("aapl AAPL msft aapl"), ["AAPL", "MSFT"])

    def test_caps_at_ten(self):
        syms = model.parse_symbols(" ".join("S%d" % i for i in range(20)))
        self.assertEqual(len(syms), 10)
        self.assertEqual(syms[0], "S0")
        self.assertEqual(syms[-1], "S9")

    def test_empty_and_non_str_return_empty(self):
        self.assertEqual(model.parse_symbols(""), [])
        self.assertEqual(model.parse_symbols("   ,  "), [])
        self.assertEqual(model.parse_symbols(None), [])
        self.assertEqual(model.parse_symbols(123), [])


if __name__ == "__main__":
    unittest.main()
