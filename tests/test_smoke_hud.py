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

    def test_open_at_rechecks_scheme_on_planted_hit(self):
        root, hud = self._make_hud([{"type": "rss", "url": "https://x", "title": "X"}])
        try:
            hud._hit = [(80, 95, "file:///etc/passwd")]   # planted, bypassing _register_hit
            self.assertIsNone(hud._open_at(10, 88))        # _open_at re-checks is_web_url
            hud.close()
        finally:
            root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestFeedSettings(_HudTestBase):
    def test_open_add_feed_and_save(self):
        # isolate_cfg points hud.CFG_PATH at a temp file so saving never touches
        # the user's real config.json.
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            self.assertIsNotNone(hud.settings.win)
            # Add an rss feed programmatically through the window's helper.
            hud.settings._add_feed_dict({"type": "rss", "url": "https://x/y", "title": "X"})
            self.assertEqual(hud.cfg["feeds"][-1]["url"], "https://x/y")
            self.assertEqual(hud.manager.feeds[-1].get("url"), "https://x/y")
            # Test button reports a status (offline here, since fetch is stubbed).
            hud.settings._on_test_token()
            self.assertEqual(hud.settings._token_status.get(), "offline")
            hud._open_feed_settings()                 # singleton: still one window
            hud.close()                               # closes settings too
        finally:
            root.destroy()

    def test_github_add_row_has_show_controls(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("github")
            hud.settings._render_fields()
            # CI + Notifications checkbuttons exist and default to on.
            self.assertEqual(hud.settings._show_ci.get(), 1)
            self.assertEqual(hud.settings._show_notif.get(), 1)
            hud.close()
        finally:
            root.destroy()

    def test_notifications_render_fields_has_no_url(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("notifications")
            hud.settings._render_fields()
            self.assertIn("items", hud.settings._fields)
            self.assertIn("interval", hud.settings._fields)
            self.assertNotIn("url", hud.settings._fields)
            self.assertNotIn("repo", hud.settings._fields)
            hud.close()
        finally:
            root.destroy()

    def test_notifications_on_add_builds_no_url_feed(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("notifications")
            hud.settings._render_fields()
            hud.settings._fields["title"].set("Notifications")
            hud.settings._fields["items"].set("7")
            hud.settings._on_add()
            added = hud.cfg["feeds"][-1]
            self.assertEqual(added["type"], "notifications")
            self.assertNotIn("url", added)
            self.assertEqual(added["items"], 7)
            self.assertTrue(hud.manager.feeds[-1]["valid"])
            hud.close()
        finally:
            root.destroy()


def _fill_of(hud, needle):
    """Fill color of the first feed canvas item whose text contains needle."""
    for iid in hud._feed_items:
        if needle in hud.canvas.itemcget(iid, "text"):
            return hud.canvas.itemcget(iid, "fill")
    return None


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudNotificationsRendering(_HudTestBase):
    def _item(self, urgency="high", repo="o/app", num="#34", title="Fix the thing",
              url="https://github.com/o/app/pull/34", ts=0.0, glyph="⇄",
              reason="review"):
        from feedkit.model import NotifItem
        return NotifItem(glyph, repo, num, reason, urgency, ts, title, url)

    def test_two_line_item_and_badge(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "Notifications", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._item(repo="o/app", title="Fix the thing")], None, None, 7)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("\U0001f514 7"))      # 🔔 7 header badge
            self.assertTrue(hud._feed_has_text("app"))               # line 1 repo
            self.assertTrue(hud._feed_has_text("Fix the thing"))     # line 2 title
        finally:
            hud.close(); root.destroy()

    def test_item_is_clickable_to_thread(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._item(url="https://github.com/o/app/pull/34")], None, None, 1)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(any(u == "https://github.com/o/app/pull/34"
                                for (_, _, u) in hud._hit))
        finally:
            hud.close(); root.destroy()

    def test_overflow_more_line(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            items = [self._item(num="#%d" % i, url="https://github.com/o/app/issues/%d" % i)
                     for i in range(5)]
            hud.feed_state[0] = manager.FeedResult("ok", items, None, None, 50)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("45 more"))   # 50 total - 5 shown
            self.assertTrue(any(u == "https://github.com/notifications"
                                for (_, _, u) in hud._hit))
        finally:
            hud.close(); root.destroy()

    def test_no_token_state_line(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("error", [], None, "no github_token", None)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("set GitHub token"))
        finally:
            hud.close(); root.destroy()

    def test_inbox_zero(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [], None, None, 0)
            hud._draw_feeds()
            root.update_idletasks()
            self.assertTrue(hud._feed_has_text("inbox zero"))
        finally:
            hud.close(); root.destroy()

    def test_badge_none_and_zero_do_not_crash(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            for badge in (None, 0):
                hud.feed_state[0] = manager.FeedResult("ok", [], None, None, badge)
                hud._draw_feeds()       # None >= 50 would raise TypeError without the guard
                root.update_idletasks()
                self.assertTrue(hud._feed_has_text("\U0001f514 0"))
        finally:
            hud.close(); root.destroy()

    def test_high_urgency_amber_when_ok_and_dim_when_stale(self):
        import hud as hudmod
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._item(urgency="high", repo="o/app")], None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(_fill_of(hud, "app"), hudmod.STATE_HEX["pending"])  # amber
            hud.feed_state[0] = manager.FeedResult(
                "stale", [self._item(urgency="high", repo="o/app")], None, "offline", 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(_fill_of(hud, "app"), hudmod.FEED_DIM)              # dimmed
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudNotificationsDismiss(_HudTestBase):
    def _ditem(self, thread_url="https://api.github.com/notifications/threads/7",
               url="https://github.com/o/app/issues/7", repo="o/app", title="T"):
        from feedkit.model import NotifItem
        return NotifItem("◉", repo, "#7", "@you", "high", 0.0, title, url, thread_url)

    def test_dismiss_glyph_and_zone_registered(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("✕"))   # ✕ per-item
            self.assertTrue(hud._feed_has_text("✓"))   # ✓ header mark-all
            ones = [a for (_, _, _, _, a) in hud._action_hits if a[0] == "one"]
            alls = [a for (_, _, _, _, a) in hud._action_hits if a[0] == "all"]
            self.assertEqual(ones[0],
                             ("one", 0, "https://api.github.com/notifications/threads/7"))
            self.assertEqual(alls[0], ("all", 0))
        finally:
            hud.close(); root.destroy()

    def test_item_without_thread_url_has_no_dismiss(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem(thread_url="")],
                                                   None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertFalse(any(a[0] == "one" for (_, _, _, _, a) in hud._action_hits))
            self.assertFalse(hud._feed_has_text("✕"))
        finally:
            hud.close(); root.destroy()

    def test_dismiss_zone_x_is_right_edge(self):
        import hud as hudmod
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            one = [(x0, x1) for (_, _, x0, x1, a) in hud._action_hits if a[0] == "one"][0]
            self.assertEqual(one, (hudmod.WIDTH - hudmod.PAD - hudmod.ACTION_ZONE_W, hudmod.WIDTH))
        finally:
            hud.close(); root.destroy()

    def _click(self, hud, kind):
        """Synthesize a plain click at the center of the first action zone of `kind`."""
        for (y0, y1, x0, x1, a) in hud._action_hits:
            if a[0] == kind:
                ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
                hud._moved = False
                hud._on_release(ev)
                return a
        return None

    def test_dismiss_one_optimistic_and_enqueues(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        hud.manager.stop()                         # deterministic _actions inspection
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 3)
            hud._draw_feeds(); root.update_idletasks()
            self._click(hud, "one")
            self.assertEqual(len(hud.feed_state[0].items), 0)   # optimistically removed
            self.assertEqual(hud.feed_state[0].badge, 2)        # 3 - 1
            self.assertEqual(hud.manager._actions.get_nowait(),
                             ("one", 0, "https://api.github.com/notifications/threads/7"))
        finally:
            hud.close(); root.destroy()

    def test_mark_all_confirm_yes_clears_and_enqueues(self):
        import feedkit.manager as manager
        import tkinter.messagebox as tkmsg
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        hud.manager.stop()
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 8)
            hud._draw_feeds(); root.update_idletasks()
            with mock.patch.object(tkmsg, "askyesno", lambda *a, **k: True):
                self._click(hud, "all")
            self.assertEqual(len(hud.feed_state[0].items), 0)
            self.assertEqual(hud.feed_state[0].badge, 0)
            self.assertEqual(hud.manager._actions.get_nowait(), ("all", 0, None))
        finally:
            hud.close(); root.destroy()

    def test_mark_all_confirm_no_does_nothing(self):
        import feedkit.manager as manager
        import tkinter.messagebox as tkmsg
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        hud.manager.stop()
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._ditem()], None, None, 8)
            hud._draw_feeds(); root.update_idletasks()
            with mock.patch.object(tkmsg, "askyesno", lambda *a, **k: False):
                self._click(hud, "all")
            self.assertEqual(len(hud.feed_state[0].items), 1)   # unchanged
            self.assertEqual(hud.feed_state[0].badge, 8)
            self.assertTrue(hud.manager._actions.empty())       # nothing enqueued
        finally:
            hud.close(); root.destroy()

    def test_failed_dismiss_shows_dismiss_failed_line(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([{"type": "notifications", "title": "N", "items": 5}])
        try:
            # the manager restores a "stale"/"dismiss failed" result that re-attaches
            # the full cached items (badge restored) when a mark-as-read call fails
            hud.feed_state[0] = manager.FeedResult(
                "stale", [self._ditem()], None, "dismiss failed", 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("! dismiss failed"))  # banner shown despite items present
            self.assertTrue(hud._feed_has_text("app"))               # restored item still rendered (repo short of o/app)
        finally:
            hud.close(); root.destroy()


if __name__ == "__main__":
    unittest.main()
