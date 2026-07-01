import unittest
import json
import feedkit.parse as parse
import feedkit.model as model


RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>HN</title><link>https://news.ycombinator.com/</link>
  <item><title>First story</title><link>https://example.com/a</link>
    <pubDate>Mon, 29 Jun 2026 01:44:40 +0000</pubDate></item>
  <item><title>Second story</title><link>https://example.com/b</link></item>
  <item><title>Third</title><link>https://example.com/c</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <title>repo releases</title>
  <entry>
    <title>v7.1</title>
    <updated>2026-06-14T14:58:38Z</updated>
    <link rel="alternate" type="text/html" href="https://github.com/o/r/releases/tag/v7.1"/>
    <media:thumbnail url="x"/>
  </entry>
  <entry>
    <title>v7.0</title>
    <link href="https://github.com/o/r/releases/tag/v7.0"/>
  </entry>
</feed>"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns="http://purl.org/rss/1.0/"
         xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <channel rdf:about="https://ex/"><title>Old feed</title>
    <items><rdf:Seq><rdf:li rdf:resource="https://example.com/r"/></rdf:Seq></items></channel>
  <item rdf:about="https://example.com/r">
    <title>RDF item</title><link>https://example.com/r</link></item>
</rdf:RDF>"""

EVIL = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [ <!ENTITY lol "lol"> ]>
<rss version="2.0"><channel><item><title>&lol;</title></item></channel></rss>"""


class TestParseRss(unittest.TestCase):
    def test_rss_titles_and_links(self):
        items = parse.parse_rss(RSS, 3)
        self.assertEqual([i.text for i in items], ["First story", "Second story", "Third"])
        self.assertEqual(items[0].url, "https://example.com/a")

    def test_rss_respects_item_cap(self):
        self.assertEqual(len(parse.parse_rss(RSS, 2)), 2)

    def test_atom_title_and_href_attribute(self):
        items = parse.parse_rss(ATOM, 5)
        self.assertEqual([i.text for i in items], ["v7.1", "v7.0"])
        self.assertEqual(items[0].url, "https://github.com/o/r/releases/tag/v7.1")
        self.assertEqual(items[1].url, "https://github.com/o/r/releases/tag/v7.0")

    def test_rdf_rss_1_0_items(self):
        items = parse.parse_rss(RDF, 5)
        self.assertEqual([i.text for i in items], ["RDF item"])
        self.assertEqual(items[0].url, "https://example.com/r")

    def test_doctype_rejected(self):
        with self.assertRaises(ValueError):
            parse.parse_rss(EVIL, 3)

    def test_malformed_xml_raises(self):
        with self.assertRaises(Exception):
            parse.parse_rss(b"<rss><channel", 3)


class TestParseJson(unittest.TestCase):
    DOC = b'{"data": {"items": [{"title": "A", "html_url": "https://x/a"}, ' \
          b'{"title": "B", "html_url": "https://x/b"}, {"title": "C"}]}}'

    def test_walks_path_and_maps_fields(self):
        items = parse.parse_json(self.DOC, "data.items",
                                 {"text": "title", "url": "html_url"}, 2)
        self.assertEqual([i.text for i in items], ["A", "B"])
        self.assertEqual(items[0].url, "https://x/a")

    def test_missing_url_field_is_none(self):
        items = parse.parse_json(self.DOC, "data.items",
                                 {"text": "title", "url": "html_url"}, 3)
        self.assertIsNone(items[2].url)        # third item has no html_url

    def test_path_to_nonlist_returns_empty(self):
        self.assertEqual(parse.parse_json(self.DOC, "data", {"text": "x"}, 3), [])

    def test_numeric_path_segment_indexes_list(self):
        doc = b'{"rows": [{"v": "first"}, {"v": "second"}]}'
        items = parse.parse_json(doc, "rows.1", {"text": "v"}, 3)
        self.assertEqual(items, [])            # rows.1 is a dict, not a list -> empty


class TestParseText(unittest.TestCase):
    def test_regex_first_group(self):
        items = parse.parse_text(b"status: OK\nfoo", "text/plain", r"status:\s*(\w+)", 1, url="https://s")
        self.assertEqual(items[0].text, "OK")
        self.assertEqual(items[0].url, "https://s")

    def test_no_regex_returns_first_lines(self):
        items = parse.parse_text(b"one\n\n two \nthree\nfour", "text/plain", None, 2)
        self.assertEqual([i.text for i in items], ["one", "two"])

    def test_regex_no_match(self):
        items = parse.parse_text(b"nothing here", None, r"(\d+)", 1)
        self.assertEqual(items[0].text, "(no match)")

    def test_decode_respects_charset(self):
        body = "café".encode("latin-1")
        items = parse.parse_text(body, "text/plain; charset=latin-1", None, 1)
        self.assertEqual(items[0].text, "café")

    def test_regex_no_group_returns_whole_match(self):
        items = parse.parse_text(b"version=1.2.3", None, r"\d+\.\d+\.\d+", 1)
        self.assertEqual(items[0].text, "1.2.3")


class TestParseCheckRuns(unittest.TestCase):
    def _body(self, runs):
        import json as _j
        return _j.dumps({"total_count": len(runs), "check_runs": runs}).encode()

    def test_empty_is_none(self):
        self.assertEqual(parse.parse_check_runs(self._body([])), "none")

    def test_all_success(self):
        runs = [{"status": "completed", "conclusion": "success"},
                {"status": "completed", "conclusion": "skipped"}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "success")

    def test_in_progress_is_pending(self):
        runs = [{"status": "completed", "conclusion": "success"},
                {"status": "in_progress", "conclusion": None}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "pending")

    def test_incomplete_dominates_even_with_a_failure(self):
        # Spec rule: any not-completed run -> pending, regardless of an already
        # failed sibling (a re-run in progress shows amber, not red).
        runs = [{"status": "in_progress", "conclusion": None},
                {"status": "completed", "conclusion": "failure"}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "pending")

    def test_all_completed_with_a_failure_is_failure(self):
        runs = [{"status": "completed", "conclusion": "success"},
                {"status": "completed", "conclusion": "failure"}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "failure")

    def test_timed_out_is_failure(self):
        runs = [{"status": "completed", "conclusion": "timed_out"}]
        self.assertEqual(parse.parse_check_runs(self._body(runs)), "failure")


class TestParseNotifications(unittest.TestCase):
    def test_counts_array_length(self):
        body = b'[{"id":"1","unread":true},{"id":"2","unread":true}]'
        self.assertEqual(parse.parse_notifications(body), 2)

    def test_filters_read(self):
        body = b'[{"id":"1","unread":true},{"id":"2","unread":false}]'
        self.assertEqual(parse.parse_notifications(body), 1)

    def test_non_list_is_zero(self):
        self.assertEqual(parse.parse_notifications(b'{"message":"Bad creds"}'), 0)


class TestComposeGithubStatus(unittest.TestCase):
    def test_ci_and_notifications(self):
        s = parse.compose_github_status("kangofthecastle/Toybox", "main", "success", 3)
        self.assertEqual(s.state, "success")
        self.assertIn("Toybox", s.text)
        self.assertIn("passing", s.text)
        self.assertIn("3", s.text)
        self.assertEqual(s.url, "https://github.com/kangofthecastle/Toybox/actions")

    def test_no_notifications_omits_bell(self):
        s = parse.compose_github_status("o/r", "main", "failure", None)
        self.assertIn("failing", s.text)
        self.assertNotIn("\U0001f514", s.text)

    def test_fifty_plus(self):
        s = parse.compose_github_status("o/r", "main", "none", 50)
        self.assertIn("50+", s.text)

    def test_notifications_only_points_at_notifications(self):
        s = parse.compose_github_status("o/r", "main", "none", 4, ci_shown=False)
        self.assertEqual(s.url, "https://github.com/notifications")
        self.assertNotIn("●", s.text)        # no CI glyph when CI isn't shown


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

    def test_thread_url_carried_from_top_level_url(self):
        n = _notif(url="https://api.github.com/notifications/threads/42")
        items, _ = parse.parse_notification_items(json.dumps([n]).encode(), 5)
        self.assertEqual(items[0].thread_url,
                         "https://api.github.com/notifications/threads/42")

    def test_thread_url_missing_is_empty(self):
        items, _ = parse.parse_notification_items(
            json.dumps([{"unread": True, "reason": "subscribed"}]).encode(), 5)
        self.assertEqual(items[0].thread_url, "")


def _sr(**over):
    """One /search/issues result item (a PR by default)."""
    it = {"number": 34, "title": "Fix the thing",
          "html_url": "https://github.com/o/app/pull/34",
          "repository_url": "https://api.github.com/repos/o/app",
          "user": {"login": "octocat"},
          "updated_at": "2026-06-29T00:00:00Z",
          "pull_request": {"url": "https://api.github.com/repos/o/app/pulls/34"}}
    it.update(over)
    return it


def _sbody(items, total=None):
    payload = {"items": items}
    if total is not None:
        payload["total_count"] = total
    return json.dumps(payload).encode()


class TestParseSearchItems(unittest.TestCase):
    def test_non_dict_body_is_empty(self):
        self.assertEqual(parse.parse_search_items(b"[]", 5), ([], 0))

    def test_missing_items_is_empty(self):
        self.assertEqual(parse.parse_search_items(b'{"total_count":3}', 5), ([], 0))

    def test_basic_pr(self):
        items, total = parse.parse_search_items(_sbody([_sr()], total=3), 5)
        self.assertEqual(total, 3)
        it = items[0]
        self.assertEqual(it.glyph, model.glyph_for("PullRequest"))
        self.assertEqual(it.repo, "o/app")
        self.assertEqual(it.number, "#34")
        self.assertEqual(it.reason_label, "@octocat")
        self.assertEqual(it.urgency, "normal")
        self.assertEqual(it.title, "Fix the thing")
        self.assertEqual(it.url, "https://github.com/o/app/pull/34")
        self.assertEqual(it.thread_url, "")
        self.assertGreater(it.updated_at, 0)

    def test_issue_uses_issue_glyph(self):
        issue = _sr()
        del issue["pull_request"]
        items, _ = parse.parse_search_items(_sbody([issue]), 5)
        self.assertEqual(items[0].glyph, model.glyph_for("Issue"))

    def test_draft_pr_is_low_urgency(self):
        items, _ = parse.parse_search_items(_sbody([_sr(draft=True)]), 5)
        self.assertEqual(items[0].urgency, "low")

    def test_missing_user_number_html(self):
        bare = {"title": "no metadata", "repository_url": "https://api.github.com/repos/o/app"}
        items, total = parse.parse_search_items(_sbody([bare]), 5)
        self.assertEqual(total, 1)                       # total_count absent -> len(items)
        it = items[0]
        self.assertEqual(it.reason_label, "")
        self.assertEqual(it.number, "")
        self.assertEqual(it.url, "")                     # no html_url -> no click target
        self.assertEqual(it.repo, "o/app")

    def test_total_count_absent_falls_back_to_len(self):
        items, total = parse.parse_search_items(_sbody([_sr(), _sr(number=35)]), 5)
        self.assertEqual(total, 2)

    def test_max_items_caps_list(self):
        items, total = parse.parse_search_items(
            _sbody([_sr(number=i) for i in range(8)], total=8), 3)
        self.assertEqual(len(items), 3)
        self.assertEqual(total, 8)


def _chart_body(price=746.77, prev=756.0, closes=(740.0, 745.0, 746.77), result=True):
    if not result:
        return json.dumps({"chart": {"result": None, "error": {"code": "Not Found"}}}).encode()
    return json.dumps({"chart": {"result": [{
        "meta": {"regularMarketPrice": price, "chartPreviousClose": prev},
        "indicators": {"quote": [{"close": list(closes)}]}}], "error": None}}).encode()


class TestParseStockChart(unittest.TestCase):
    def test_normal(self):
        q = parse.parse_stock_chart(_chart_body(), "SPY")
        self.assertEqual(q.symbol, "SPY")
        self.assertAlmostEqual(q.price, 746.77)
        self.assertAlmostEqual(q.change_pct, (746.77 - 756.0) / 756.0 * 100.0)
        self.assertEqual(q.series, [740.0, 745.0, 746.77])

    def test_null_closes_filtered(self):
        q = parse.parse_stock_chart(_chart_body(closes=(740.0, None, 746.77)), "SPY")
        self.assertEqual(q.series, [740.0, 746.77])

    def test_result_null_is_none(self):
        self.assertIsNone(parse.parse_stock_chart(_chart_body(result=False), "SPY"))

    def test_missing_price_uses_last_close(self):
        body = json.dumps({"chart": {"result": [{
            "meta": {"chartPreviousClose": 100.0},
            "indicators": {"quote": [{"close": [98.0, 101.0]}]}}]}}).encode()
        q = parse.parse_stock_chart(body, "X")
        self.assertAlmostEqual(q.price, 101.0)                 # fallback to last close
        self.assertAlmostEqual(q.change_pct, 1.0)             # (101-100)/100*100

    def test_previousclose_fallback_when_chartpreviousclose_absent(self):
        # previousClose should be used when chartPreviousClose is not present.
        body = json.dumps({"chart": {"result": [{
            "meta": {"regularMarketPrice": 101.0, "previousClose": 100.0},
            "indicators": {"quote": [{"close": [100.0, 101.0]}]}}],
            "error": None}}).encode()
        self.assertAlmostEqual(parse.parse_stock_chart(body, "X").change_pct, 1.0)

    def test_missing_prevclose_is_zero_change(self):
        body = json.dumps({"chart": {"result": [{
            "meta": {"regularMarketPrice": 50.0},
            "indicators": {"quote": [{"close": [50.0]}]}}]}}).encode()
        self.assertEqual(parse.parse_stock_chart(body, "X").change_pct, 0.0)

    def test_zero_prevclose_is_zero_change(self):
        self.assertEqual(parse.parse_stock_chart(_chart_body(prev=0.0), "X").change_pct, 0.0)

    def test_garbage_never_raises(self):
        for bad in (b"not json{", b"", b"[]", b'{"chart":{}}', b'{"chart":{"result":[{}]}}'):
            self.assertIsNone(parse.parse_stock_chart(bad, "X"), bad)


if __name__ == "__main__":
    unittest.main()
