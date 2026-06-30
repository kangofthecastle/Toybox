import unittest
from tests.smoke import run_smoke


class TestSmokeHud(unittest.TestCase):
    def test_launches_and_exits_clean(self):
        rc, err = run_smoke("hud.pyw", 1500)
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.strip(), "")


import os
import unittest.mock as mock


class _HudTestBase(unittest.TestCase):
    """Shared base for the in-process Tk Hud tests. setUp stubs the network so the
    worker (started in Hud.__init__) does NO real I/O and is deterministic."""
    def setUp(self):
        import feedkit.fetch as fetchmod
        stub = lambda *a, **k: fetchmod.FetchResult("error", None, None, None, None, "offline")
        patcher = mock.patch.object(fetchmod, "fetch", stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_hud(self, feeds, isolate_cfg=False):
        import tempfile
        import tkinter as tk
        import winkit.window as window
        import config
        import hud as hudmod
        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        cfg = config.defaults()
        cfg["feeds"] = feeds
        root.geometry("%dx%d+100+100" % (hudmod.WIDTH, hudmod.HEIGHT))
        hud = hudmod.Hud(root, cfg)
        if isolate_cfg:                      # never touch the user's real config.json
            hud.CFG_PATH = os.path.join(tempfile.mkdtemp(), "config.json")
        return root, hud


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudFeedRendering(_HudTestBase):
    def test_feeds_grow_window_past_metrics_height(self):
        import hud as hudmod
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud([{"type": "rss", "url": "https://x", "title": "X"}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [Item("Hello headline", "https://example.com/a")], None, None)
            hud._draw_feeds()
            root.update_idletasks()
            height = int(root.geometry().split("x")[1].split("+")[0])
            self.assertGreater(height, hudmod.HEIGHT)      # taller than metrics-only (96)
            self.assertTrue(any(u == "https://example.com/a" for (_, _, u) in hud._hit))
            hud.close()
        finally:
            root.destroy()

    def test_invalid_feed_renders_error_tile(self):
        root, hud = self._make_hud([{"type": "bogus", "title": "Bad"}])
        try:
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("Bad"))
            hud.close()
        finally:
            root.destroy()

    def test_github_tile_is_clickable_and_shows_error(self):
        import feedkit.manager as manager
        from feedkit.model import Status
        root, hud = self._make_hud([{"type": "github", "repo": "o/r", "title": "R"}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [], Status("r ● passing", "success",
                                 "https://github.com/o/r/actions"), "bad token")
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(any(u == "https://github.com/o/r/actions" for (_, _, u) in hud._hit))
            self.assertTrue(hud._feed_has_text("bad token"))   # error surfaced
            hud.close()
        finally:
            root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudClickAndMenu(_HudTestBase):
    def test_click_on_item_returns_url(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud([{"type": "rss", "url": "https://x", "title": "X"}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [Item("Headline", "https://example.com/a")], None, None)
            hud._draw_feeds()
            root.update_idletasks()
            y0, y1, url = hud._hit[0]
            mid = (y0 + y1) // 2
            self.assertEqual(hud._open_at(10, mid), "https://example.com/a")
            self.assertIsNone(hud._open_at(10, 2))          # up in the metrics area
            hud.close()
        finally:
            root.destroy()

    def test_non_http_url_is_never_clickable(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud([{"type": "rss", "url": "https://x", "title": "X"}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [Item("Sneaky", "file:///etc/passwd")], None, None)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertEqual(hud._hit, [])                  # no region registered
            self.assertIsNone(hud._open_at(10, 90))         # nothing opens
            hud.close()
        finally:
            root.destroy()

    def test_menu_has_feed_entries(self):
        root, hud = self._make_hud([])
        try:
            labels = [hud.menu.entrycget(i, "label")
                      for i in range(hud.menu.index("end") + 1)
                      if hud.menu.type(i) == "command"]
            self.assertIn("Feeds…", labels)
            self.assertIn("Reload feeds", labels)
            hud.close()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
