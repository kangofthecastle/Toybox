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


if __name__ == "__main__":
    unittest.main()
