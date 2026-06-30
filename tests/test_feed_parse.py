import unittest
import feedkit.parse as parse


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


if __name__ == "__main__":
    unittest.main()
