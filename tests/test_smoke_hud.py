import unittest
from tests.smoke import run_smoke


class TestSmokeHud(unittest.TestCase):
    def test_launches_and_exits_clean(self):
        rc, err = run_smoke("hud.pyw", 1500)
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.strip(), "")


import os
import unittest.mock as mock


def hud_mid_x():
    import hud as hudmod
    return hudmod.WIDTH // 2


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
            hud.active_tab = "global"  # rss without explicit tab defaults to global
            hud._draw_feeds()
            root.update_idletasks()
            height = int(root.geometry().split("x")[1].split("+")[0])
            self.assertGreater(height, hudmod.HEIGHT)      # taller than metrics-only (96)
            self.assertTrue(any(u == "https://example.com/a" for (_, _, u) in hud._hit))
            hud.close()
        finally:
            root.destroy()

    def test_invalid_feed_renders_error_tile(self):
        # invalid rss (missing url) is a news-type feed with tab="global"
        root, hud = self._make_hud([{"type": "rss", "title": "Bad"}])
        try:
            hud.active_tab = "global"  # rss without explicit tab defaults to global
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
            hud.active_tab = "global"  # rss without explicit tab defaults to global
            hud._draw_feeds()
            root.update_idletasks()
            y0, y1, url = hud._hit[0]
            mid = (y0 + y1) // 2
            self.assertEqual(hud._open_at(10, mid), "https://example.com/a")
            self.assertIsNone(hud._open_at(10, 2))          # up in the metrics area
            hud.close()
        finally:
            root.destroy()

    def test_click_events_bound_to_canvas_only(self):
        # Regression: binding the mouse events to BOTH root and the canvas makes a
        # single canvas click fire _on_release twice (a canvas's bindtags include
        # its toplevel), which opened the URL in two browser tabs. The events must
        # be bound to the canvas only.
        root, hud = self._make_hud([])
        try:
            for seq in ("<ButtonRelease-1>", "<Button-1>", "<B1-Motion>", "<Button-3>"):
                self.assertEqual(hud.root.bind(seq), "", "%s must not be bound on root" % seq)
                self.assertNotEqual(hud.canvas.bind(seq), "", "%s must be bound on canvas" % seq)
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

    def test_reload_glyph_rendered(self):
        root, hud = self._make_hud([])
        try:
            texts = [hud.canvas.itemcget(i, "text") for i in hud.canvas.find_all()
                     if hud.canvas.type(i) == "text"]
            self.assertIn("⟳", texts)                    # visible reload control
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

    def test_search_render_fields_has_query(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("search")
            hud.settings._render_fields()
            self.assertIn("query", hud.settings._fields)
            self.assertIn("items", hud.settings._fields)
            self.assertNotIn("url", hud.settings._fields)
            self.assertNotIn("repo", hud.settings._fields)
            hud.close()
        finally:
            root.destroy()

    def test_search_preset_fills_query(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("search")
            hud.settings._render_fields()
            hud.settings._apply_search_preset("My open PRs")
            self.assertEqual(hud.settings._fields["query"].get(),
                             "is:open is:pr author:@me")
            hud.close()
        finally:
            root.destroy()

    def test_search_on_add_builds_query_feed(self):
        root, hud = self._make_hud([], isolate_cfg=True)
        try:
            hud._open_feed_settings()
            hud.settings._type_var.set("search")
            hud.settings._render_fields()
            hud.settings._fields["title"].set("My PRs")
            hud.settings._fields["query"].set("is:open is:pr author:@me")
            hud.settings._fields["items"].set("5")
            hud.settings._on_add()
            added = hud.cfg["feeds"][-1]
            self.assertEqual(added["type"], "search")
            self.assertEqual(added["query"], "is:open is:pr author:@me")
            self.assertEqual(added["items"], 5)
            self.assertTrue(hud.manager.feeds[-1]["valid"])
            hud.close()
        finally:
            root.destroy()


def _fill_of(hud, needle):
    """Fill color of the first feed canvas item whose text contains needle.
    Non-text items (e.g. chart polylines) are silently skipped."""
    for iid in hud._feed_items:
        try:
            if needle in hud.canvas.itemcget(iid, "text"):
                return hud.canvas.itemcget(iid, "fill")
        except Exception:
            pass
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


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudScopedSave(_HudTestBase):
    def test_save_does_not_clobber_feeds_or_token(self):
        """A HUD window-position save must NOT wipe feeds / github_token even
        when the HUD's in-memory config is stale-empty -- the live-config
        clobber bug: the old whole-file save rewrote every key, so a drag
        overwrote disk feeds/token with the empty values loaded at startup."""
        import tempfile
        import config
        import hud as hudmod
        # disk already holds feeds + a token (written by the settings window or a
        # hand edit) that THIS HUD never loaded into its in-memory cfg
        path = os.path.join(tempfile.mkdtemp(), "config.json")
        seed = config.defaults()
        seed["feeds"] = [{"type": "rss", "url": "https://x/y", "title": "X"}]
        seed["hud"]["github_token"] = "ghp_keepme"
        config.save(path, seed)
        root, hud = self._make_hud([])               # in-memory feeds/token are empty (stale)
        orig = hudmod.CFG_PATH
        hudmod.CFG_PATH = path                        # _save writes via the module global
        try:
            self.assertEqual(hud.cfg["feeds"], [])               # precondition: stale memory
            self.assertEqual(hud.cfg["hud"]["github_token"], "")
            hud.cfg["hud"]["x"] = 777                             # a drag moved the window
            hud.cfg["hud"]["y"] = 555
            hud._save()
            saved = config.load(path)
            self.assertEqual(saved["hud"]["x"], 777)             # our own key persisted
            self.assertEqual(saved["hud"]["y"], 555)
            self.assertEqual(saved["feeds"],                     # NOT clobbered
                             [{"type": "rss", "url": "https://x/y", "title": "X"}])
            self.assertEqual(saved["hud"]["github_token"], "ghp_keepme")  # NOT clobbered
        finally:
            hudmod.CFG_PATH = orig
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudSearchRendering(_HudTestBase):
    FEED = {"type": "search", "title": "My PRs",
            "query": "is:open is:pr author:@me", "items": 5}

    def _item(self, repo="o/app", num="#34", title="Fix the thing",
              url="https://github.com/o/app/pull/34", urgency="normal",
              glyph="⇄", label="@me", ts=0.0):
        from feedkit.model import NotifItem
        return NotifItem(glyph, repo, num, label, urgency, ts, title, url)

    def test_renders_rows_and_count(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._item()], None, None, 3)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("(3)"))          # header count
            self.assertTrue(hud._feed_has_text("app"))          # line 1 repo
            self.assertTrue(hud._feed_has_text("Fix the thing"))  # line 2 title
        finally:
            hud.close(); root.destroy()

    def test_item_clickable_and_no_dismiss(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [self._item()], None, None, 1)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(any(u == "https://github.com/o/app/pull/34"
                                for (_, _, u) in hud._hit))
            # search rows have no ✕; tab bar adds tab/refresh zones so check for absence
            # of per-item dismiss ("one"/"all") actions specifically
            self.assertFalse(any(a[0] in ("one", "all")
                                 for (_, _, _, _, a) in hud._action_hits))
        finally:
            hud.close(); root.destroy()

    def test_header_and_overflow_link_to_web_search(self):
        import feedkit.manager as manager
        import feedkit.model as model
        root, hud = self._make_hud([self.FEED])
        try:
            items = [self._item(num="#%d" % i, url="https://github.com/o/app/pull/%d" % i)
                     for i in range(5)]
            hud.feed_state[0] = manager.FeedResult("ok", items, None, None, 12)
            hud._draw_feeds(); root.update_idletasks()
            web = model.github_search_web_url("is:open is:pr author:@me")
            self.assertTrue(hud._feed_has_text("7 more"))       # 12 total - 5 shown
            self.assertTrue(any(u == web for (_, _, u) in hud._hit))
        finally:
            hud.close(); root.destroy()

    def test_no_token_line(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.feed_state[0] = manager.FeedResult("error", [], None, "no github_token", None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("set GitHub token"))
        finally:
            hud.close(); root.destroy()

    def test_none_open(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [], None, None, 0)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("none open"))
        finally:
            hud.close(); root.destroy()

    def test_stale_items_render_dim(self):
        import feedkit.manager as manager
        import hud as hudmod
        root, hud = self._make_hud([self.FEED])
        try:
            hud.feed_state[0] = manager.FeedResult(
                "stale", [self._item(repo="o/app")], None, "offline", 3)
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(_fill_of(hud, "app"), hudmod.FEED_DIM)
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudGpuRow(_HudTestBase):
    def _texts(self, hud):
        return [hud.canvas.itemcget(i, "text") for i in hud.canvas.find_all()
                if hud.canvas.type(i) == "text"]

    def test_gpu_row_shows_percent(self):
        root, hud = self._make_hud([])
        try:
            hud.gpu = 42.0
            hud._draw()
            self.assertIn("42", hud.canvas.itemcget(hud._gpu_text, "text"))
        finally:
            hud.close(); root.destroy()

    def test_gpu_row_degrades_when_none(self):
        root, hud = self._make_hud([])
        try:
            import hud as hudmod
            hud.gpu = None
            hud._draw()
            self.assertEqual(hud.canvas.itemcget(hud._gpu_text, "text"), "GPU  --%")
            self.assertEqual(hud.canvas.itemcget(hud._gpu_text, "fill"), hudmod.DIM)
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudMediaRow(_HudTestBase):
    def _texts(self, hud):
        return [hud.canvas.itemcget(i, "text") for i in hud.canvas.find_all()
                if hud.canvas.type(i) == "text"]

    def test_media_glyphs_rendered(self):
        root, hud = self._make_hud([])
        try:
            texts = self._texts(hud)
            for g in ("⏮", "⏯", "⏭"):
                self.assertIn(g, texts)
        finally:
            hud.close(); root.destroy()

    def test_media_clicks_call_controls_in_order(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            calls = []
            with mock.patch.object(hudmod.media, "prev_track", lambda: calls.append("prev")), \
                 mock.patch.object(hudmod.media, "play_pause", lambda: calls.append("playpause")), \
                 mock.patch.object(hudmod.media, "next_track", lambda: calls.append("next")):
                for (x0, x1, y0, y1, key) in hud._media_hits:
                    ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
                    hud._moved = False
                    hud._on_release(ev)
            self.assertEqual(calls, ["prev", "playpause", "next"])
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudStocks(_HudTestBase):
    FEED = {"type": "stocks", "title": "Markets", "symbols": ["SPY", "META"],
            "range": "1mo", "tab": "markets"}

    def _q(self, symbol="SPY", price=746.77, change=-1.3, series=(740.0, 745.0, 746.77)):
        from feedkit.model import Quote
        return Quote(symbol, price, change, list(series))

    def test_tile_renders_quote_chart_and_toggle(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult("ok", [self._q()], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("SPY"))                       # quote line
            self.assertTrue(hud._feed_has_text("1M"))                        # toggle labels
            self.assertTrue(hud._feed_has_text("3M"))
            self.assertTrue(any(hud.canvas.type(i) == "line" for i in hud._feed_items))  # chart polyline
            self.assertTrue(any(u == "https://finance.yahoo.com/quote/SPY" for (_, _, u) in hud._hit))
        finally:
            hud.close(); root.destroy()

    def test_up_and_down_colors(self):
        import feedkit.manager as manager, hud as hudmod
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._q(symbol="DN", change=-1.3), self._q(symbol="UP", change=0.5)], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(_fill_of(hud, "DN"), hudmod.STOCK_DOWN)
            self.assertEqual(_fill_of(hud, "UP"), hudmod.STOCK_UP)
        finally:
            hud.close(); root.destroy()

    def test_range_toggle_click_calls_set_stock_range(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            calls = []
            hud.manager.set_stock_range = lambda idx, code: calls.append((idx, code))
            hud.feed_state[0] = manager.FeedResult("ok", [self._q()], None, None)
            hud._draw_feeds(); root.update_idletasks()
            hit = None
            for (y0, y1, x0, x1, a) in hud._action_hits:
                if a == ("range", 0, "1d"):
                    hit = (y0, y1, x0, x1); break
            self.assertIsNotNone(hit, "no 1D range zone")
            y0, y1, x0, x1 = hit
            ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
            hud._moved = False; hud._on_release(ev)
            self.assertEqual(calls, [(0, "1d")])
        finally:
            hud.close(); root.destroy()

    def test_stale_tile_dims_quote_to_feed_dim(self):
        import feedkit.manager as manager
        import hud as hudmod
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult(
                "stale", [self._q(symbol="SPY", change=0.5)], None, "offline")
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(_fill_of(hud, "SPY"), hudmod.FEED_DIM)
        finally:
            hud.close(); root.destroy()

    def test_error_tile_shows_error_placeholder(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult("error", [], None, "offline")
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("! offline"))
        finally:
            hud.close(); root.destroy()

    def test_loading_placeholder_when_no_quotes(self):
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud._draw_feeds(); root.update_idletasks()          # feed_state[0] is None
            self.assertTrue(hud._feed_has_text("loading"))
        finally:
            hud.close(); root.destroy()

    def test_chart_has_filled_polygon(self):
        import feedkit.manager as manager
        root, hud = self._make_hud([self.FEED])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult(
                "ok", [self._q(series=(740.0, 745.0, 742.0, 748.0))], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(any(hud.canvas.type(i) == "polygon" for i in hud._feed_items),
                            "no filled chart polygon")
            self.assertTrue(any(hud.canvas.type(i) == "line" and len(hud.canvas.coords(i)) > 4
                                for i in hud._feed_items),
                            "chart polyline (a line with >2 points) still drawn on top")
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudTabs(_HudTestBase):
    def _feeds(self):
        return [
            {"type": "rss", "url": "https://t", "title": "TechFeed", "tab": "tech"},
            {"type": "rss", "url": "https://g", "title": "GlobalFeed", "tab": "global"},
            {"type": "github", "repo": "o/r", "title": "Repo"},
        ]

    def _click(self, hud, pred):
        for (y0, y1, x0, x1, a) in hud._action_hits:
            if pred(a):
                ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
                hud._moved = False
                hud._on_release(ev)
                return a
        return None

    def test_four_tab_labels_render(self):
        root, hud = self._make_hud([])
        try:
            hud._draw_feeds(); root.update_idletasks()
            for label in ("Global", "Markets", "Tech", "Sports"):
                self.assertTrue(hud._feed_has_text(label), label)
        finally:
            hud.close(); root.destroy()

    def test_only_active_tab_feeds_drawn_github_always(self):
        import feedkit.manager as manager
        from feedkit.model import Item, Status
        root, hud = self._make_hud(self._feeds())
        try:
            hud.feed_state[0] = manager.FeedResult("ok", [Item("techline", "https://x/t")], None, None)
            hud.feed_state[1] = manager.FeedResult("ok", [Item("globalline", "https://x/g")], None, None)
            hud.feed_state[2] = manager.FeedResult("ok", [], Status("Repo passing", "success",
                                                                    "https://github.com/o/r/actions"), None)
            hud.active_tab = "tech"
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("TechFeed"))
            self.assertFalse(hud._feed_has_text("GlobalFeed"))   # other tab hidden
            self.assertTrue(hud._feed_has_text("Repo"))          # github always
        finally:
            hud.close(); root.destroy()

    def test_default_tab_selects_initial_tab(self):
        import tkinter as tk
        import config, hud as hudmod
        root = tk.Tk(); root.overrideredirect(True)
        cfg = config.defaults(); cfg["feeds"] = []
        cfg["hud"]["default_tab"] = "markets"
        root.geometry("%dx%d+100+100" % (hudmod.WIDTH, hudmod.HEIGHT))
        hud = hudmod.Hud(root, cfg)
        try:
            self.assertEqual(hud.active_tab, "markets")
        finally:
            hud.close(); root.destroy()

    def test_tab_click_changes_active_tab_no_refetch(self):
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            calls = []
            hud.manager.refresh = lambda idxs: calls.append(list(idxs))
            hud._draw_feeds(); root.update_idletasks()
            self._click(hud, lambda a: a == ("tab", "global"))
            self.assertEqual(hud.active_tab, "global")
            self.assertEqual(calls, [])                          # switching does not refetch
            self.assertTrue(hud._feed_has_text("GlobalFeed"))
        finally:
            hud.close(); root.destroy()

    def test_news_refresh_calls_manager_refresh_with_news_indices(self):
        root, hud = self._make_hud(self._feeds())
        try:
            calls = []
            hud.manager.refresh = lambda idxs: calls.append(list(idxs))
            hud._draw_feeds(); root.update_idletasks()
            self._click(hud, lambda a: a == ("refresh", "news"))
            self.assertEqual(calls, [[0, 1]])                    # the two rss feeds
        finally:
            hud.close(); root.destroy()

    def test_github_refresh_rereads_token_and_refreshes_github(self):
        import config
        root, hud = self._make_hud(self._feeds(), isolate_cfg=True)
        try:
            seed = config.defaults(); seed["hud"]["github_token"] = "ghp_new"
            config.save(hud.CFG_PATH, seed)
            os.environ.pop("TOYBOX_GITHUB_TOKEN", None)          # ensure cfg wins
            tok, ref = [], []
            hud.manager.set_token = lambda t: tok.append(t)
            hud.manager.refresh = lambda idxs: ref.append(list(idxs))
            hud._draw_feeds(); root.update_idletasks()
            self._click(hud, lambda a: a == ("refresh", "github"))
            self.assertEqual(tok, ["ghp_new"])                  # token re-read from config
            self.assertEqual(ref, [[2]])                        # the github feed index
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestStockPoints(unittest.TestCase):
    def test_empty_and_single_return_empty(self):
        import hud as hudmod
        self.assertEqual(hudmod._stock_points([], 0, 30, 0, 20), [])
        self.assertEqual(hudmod._stock_points([5.0], 0, 30, 0, 20), [])

    def test_flat_series_is_midline(self):
        import hud as hudmod
        pts = hudmod._stock_points([5.0, 5.0, 5.0], 0, 20, 0, 20)
        self.assertTrue(all(abs(y - 10.0) < 1e-9 for y in pts[1::2]))

    def test_monotonic_scales_min_bottom_max_top(self):
        import hud as hudmod
        pts = hudmod._stock_points([1.0, 2.0, 3.0, 4.0], 0, 30, 0, 20)
        self.assertEqual(pts[0], 0)      # x_left
        self.assertEqual(pts[1], 20)     # min -> bottom
        self.assertEqual(pts[-2], 30)    # x_right
        self.assertEqual(pts[-1], 0)     # max -> top


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudPartition(_HudTestBase):
    def test_news_and_github_indices(self):
        feeds = [
            {"type": "rss", "url": "https://a", "title": "A", "tab": "tech"},
            {"type": "github", "repo": "o/r", "title": "R"},
            {"type": "stocks", "symbols": ["SPY"], "range": "1mo", "tab": "markets"},
            {"type": "notifications", "title": "N"},
        ]
        root, hud = self._make_hud(feeds)
        try:
            self.assertEqual(hud._news_indices(), [0, 2])
            self.assertEqual(hud._github_indices(), [1, 3])
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudAccents(_HudTestBase):
    def _accent_rects(self, hud):
        import hud as hudmod
        return [i for i in hud._feed_items
                if hud.canvas.type(i) == "rectangle"
                and hud.canvas.itemcget(i, "fill") == hudmod.ACCENT]

    def test_active_tab_has_accent_underline(self):
        root, hud = self._make_hud([])
        try:
            hud.active_tab = "tech"
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(self._accent_rects(hud), "no accent underline for active tab")
        finally:
            hud.close(); root.destroy()

    def test_github_divider_line_drawn(self):
        import hud as hudmod
        feeds = [{"type": "github", "repo": "o/r", "title": "Repo"}]
        root, hud = self._make_hud(feeds)
        try:
            hud._draw_feeds(); root.update_idletasks()
            spans = []
            for i in hud._feed_items:
                if hud.canvas.type(i) == "line":
                    x0, _y0, x1, _y1 = hud.canvas.coords(i)
                    spans.append((x0, x1))
            self.assertTrue(any(x0 <= hudmod.PAD + 1 and x1 >= hudmod.WIDTH - hudmod.PAD - 1
                                for x0, x1 in spans), "no full-width divider before GitHub")
        finally:
            hud.close(); root.destroy()

    def test_active_range_segment_has_accent(self):
        import feedkit.manager as manager
        from feedkit.model import Quote
        feed = {"type": "stocks", "title": "Markets", "symbols": ["SPY"], "range": "1mo", "tab": "markets"}
        root, hud = self._make_hud([feed])
        try:
            hud.active_tab = "markets"
            hud.feed_state[0] = manager.FeedResult("ok", [Quote("SPY", 1.0, 0.5, [1.0, 2.0])], None, None)
            hud._draw_feeds(); root.update_idletasks()
            import hud as hudmod
            right = [i for i in self._accent_rects(hud)
                     if (hud.canvas.coords(i)[0] + hud.canvas.coords(i)[2]) / 2 > hudmod.WIDTH // 2]
            self.assertTrue(right, "no accent underline for the right-aligned active range segment")
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudFitPx(_HudTestBase):
    def test_fit_px_unit(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            m = hud._feed_font_measure.measure
            short = "hi"
            self.assertEqual(hud._fit_px(short, hudmod.PAD + 6), short)     # fits -> unchanged
            long = "x" * 300
            out = hud._fit_px(long, hudmod.PAD + 6)
            self.assertTrue(out.endswith("…"))                             # truncated + marker
            self.assertLessEqual(m(out), hudmod.WIDTH - hudmod.PAD - (hudmod.PAD + 6))
        finally:
            hud.close(); root.destroy()

    def test_long_item_line_gets_ellipsis(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        feeds = [{"type": "rss", "url": "https://x", "title": "T", "tab": "tech"}]
        root, hud = self._make_hud(feeds)
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult(
                "ok", [Item("This is a very long headline that will not fit inside the width", "https://x/a")],
                None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("…"))                       # ellipsis rendered
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudHover(_HudTestBase):
    def _evt(self, x, y):
        return type("E", (), {"x": x, "y": y})()

    def _feeds(self):
        return [{"type": "rss", "url": "https://t", "title": "TechFeed", "tab": "tech"}]

    def _first_hit_point(self, hud):
        y0, y1, _url = hud._hit[0]
        return (hud_mid_x(), (y0 + y1) // 2)

    def test_hover_over_row_creates_highlight(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult("ok", [Item("line one", "https://t/a")], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._hit, "expected a clickable row")
            y0, y1, _u = hud._hit[0]
            hud._on_motion(self._evt(60, (y0 + y1) // 2))
            self.assertIsNotNone(hud._hover_item)
            self.assertEqual(hud.canvas.type(hud._hover_item), "rectangle")
        finally:
            hud.close(); root.destroy()

    def test_leave_clears_highlight(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult("ok", [Item("line one", "https://t/a")], None, None)
            hud._draw_feeds(); root.update_idletasks()
            y0, y1, _u = hud._hit[0]
            hud._on_motion(self._evt(60, (y0 + y1) // 2))
            self.assertIsNotNone(hud._hover_item)
            hud._on_leave(self._evt(0, 0))
            self.assertIsNone(hud._hover_item)
        finally:
            hud.close(); root.destroy()

    def test_hover_over_empty_space_no_highlight(self):
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            hud._draw_feeds(); root.update_idletasks()
            hud._on_motion(self._evt(5, 100000))                 # far below everything
            self.assertIsNone(hud._hover_item)
        finally:
            hud.close(); root.destroy()

    def test_highlight_survives_redraw(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud(self._feeds())
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult("ok", [Item("line one", "https://t/a")], None, None)
            hud._draw_feeds(); root.update_idletasks()
            y0, y1, _u = hud._hit[0]
            hud._on_motion(self._evt(60, (y0 + y1) // 2))
            self.assertIsNotNone(hud._hover_item)
            hud._draw_feeds(); root.update_idletasks()             # 250ms-loop style redraw
            self.assertIsNotNone(hud._hover_item)                  # re-established, no flicker-to-none
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudExpand(_HudTestBase):
    def test_toggle_changes_width_and_geometry(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            self.assertEqual(hud.width, hudmod.WIDTH)
            hud._toggle_width(); root.update_idletasks()
            self.assertEqual(hud.width, hudmod.WIDTH_WIDE)
            self.assertEqual(root.winfo_width(), hudmod.WIDTH_WIDE)
            hud._toggle_width(); root.update_idletasks()
            self.assertEqual(hud.width, hudmod.WIDTH)
            self.assertEqual(root.winfo_width(), hudmod.WIDTH)
        finally:
            hud.close(); root.destroy()

    def test_expand_button_is_header_control_not_on_tabbar(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._draw_feeds(); root.update_idletasks()
            # no ("width",) action zone remains on the tab bar
            self.assertFalse(any(a == ("width",) for (_a, _b, _c, _d, a) in hud._action_hits))
            # a grey (FG) expand glyph exists as a persistent header item
            self.assertEqual(hud.canvas.itemcget(hud._expand_text, "fill"), hudmod.FG)
            self.assertEqual(hud.canvas.itemcget(hud._expand_text, "text"), hudmod.EXPAND_GLYPH)
        finally:
            hud.close(); root.destroy()

    def test_click_in_expand_box_toggles_width(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            x0, y0, x1, y1 = hud._expand_box
            ev = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
            hud._moved = False
            hud._on_release(ev); root.update_idletasks()
            self.assertEqual(hud.width, hudmod.WIDTH_WIDE)   # a real click toggled it
            hud._moved = False
            # after widening, the box moved to the new right edge; recompute and click again
            x0, y0, x1, y1 = hud._expand_box
            ev2 = type("E", (), {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2})()
            hud._on_release(ev2); root.update_idletasks()
            self.assertEqual(hud.width, hudmod.WIDTH)        # toggled back
        finally:
            hud.close(); root.destroy()

    def test_relayout_recenters_header(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._toggle_width(); root.update_idletasks()
            cx = hud.canvas.coords(hud._clock_text)[0]
            self.assertEqual(cx, hudmod.WIDTH_WIDE // 2)         # clock recentered when wide
        finally:
            hud.close(); root.destroy()

    def test_wide_reduces_truncation(self):
        root, hud = self._make_hud([])
        try:
            text = "A moderately long headline that overflows here"
            narrow = hud._fit_px(text, 16)
            hud._toggle_width()
            wide = hud._fit_px(text, 16)
            self.assertTrue(narrow.endswith("…"))                # truncated when narrow
            self.assertEqual(wide, text)                         # full text fits when wide
        finally:
            hud.close(); root.destroy()

    def test_media_row_above_clock_row(self):
        root, hud = self._make_hud([])
        try:
            media_y = hud.canvas.coords(hud._media_play)[1]
            clock_y = hud.canvas.coords(hud._clock_text)[1]
            self.assertLess(media_y, clock_y)                # media on top, clock underneath
            self.assertEqual(hud.canvas.coords(hud._expand_text)[1], clock_y)  # expand shares clock row
        finally:
            hud.close(); root.destroy()

    def test_media_stays_above_clock_after_toggle(self):
        root, hud = self._make_hud([])
        try:
            hud._toggle_width(); root.update_idletasks()
            self.assertLess(hud.canvas.coords(hud._media_play)[1],
                            hud.canvas.coords(hud._clock_text)[1])   # order preserved when wide
        finally:
            hud.close(); root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudMarquee(_HudTestBase):
    def _evt(self, x, y):
        return type("E", (), {"x": x, "y": y})()

    def _long_feed(self):
        return [{"type": "rss", "url": "https://t", "title": "T", "tab": "tech"}]

    def _draw_long(self, hud, root):
        import feedkit.manager as manager
        from feedkit.model import Item
        hud.active_tab = "tech"
        hud.feed_state[0] = manager.FeedResult(
            "ok", [Item("This headline is far too long to fit within the narrow hud width for sure",
                        "https://t/a")], None, None)
        hud._draw_feeds(); root.update_idletasks()

    def test_draw_feeds_and_close_while_marquee_active_no_crash(self):
        # Regression: _draw_feeds deletes the marquee's canvas item, then calls
        # _stop_marquee -> canvas.coords(deleted) == [] -> [1] IndexError crash.
        root, hud = self._make_hud(self._long_feed())
        try:
            self._draw_long(hud, root)
            rec = hud._scroll_lines[0]
            hud._on_motion(self._evt(60, (rec["y0"] + rec["y1"]) // 2))
            self.assertIsNotNone(hud._marquee)
            hud._draw_feeds()                 # deletes items then _stop_marquee -> must not raise
            root.update_idletasks()
            self.assertIsNone(hud._marquee)   # cleared, not left stale
            hud.close()                       # must not re-crash on a stale marquee
        finally:
            root.destroy()

    def test_drain_without_new_data_does_not_redraw(self):
        root, hud = self._make_hud(self._long_feed())
        try:
            calls = []
            orig = hud._draw_feeds
            hud._draw_feeds = lambda: (calls.append(1), orig())[1]
            hud.manager.drain = lambda: []
            hud._drain_feeds()
            self.assertEqual(calls, [])                          # no new data -> no redraw
            import feedkit.manager as manager
            from feedkit.model import Item
            hud.manager.drain = lambda: [(0, manager.FeedResult("ok", [Item("x", "https://t/x")], None, None))]
            hud._drain_feeds()
            self.assertEqual(calls, [1])                         # new data -> one redraw
        finally:
            if hud._drain_after:
                root.after_cancel(hud._drain_after)
            hud.close(); root.destroy()

    def test_hover_truncated_line_scrolls_by_pixels(self):
        root, hud = self._make_hud(self._long_feed())
        try:
            self._draw_long(hud, root)
            self.assertTrue(hud._scroll_lines, "expected a truncated (scrollable) line")
            rec = hud._scroll_lines[0]
            hud._on_motion(self._evt(60, (rec["y0"] + rec["y1"]) // 2))
            self.assertIsNotNone(hud._marquee)
            self.assertEqual(hud.canvas.itemcget(rec["item"], "text"), rec["full"])   # full text shown
            x_before = hud.canvas.coords(rec["item"])[0]
            for _ in range(4):
                hud._marquee_step()
            x_after = hud.canvas.coords(rec["item"])[0]
            self.assertLess(x_after, x_before)              # scrolled left by pixels
        finally:
            hud._stop_marquee()
            hud.close(); root.destroy()

    def test_leave_stops_marquee_and_restores(self):
        root, hud = self._make_hud(self._long_feed())
        try:
            self._draw_long(hud, root)
            rec = hud._scroll_lines[0]
            truncated = hud.canvas.itemcget(rec["item"], "text")
            base_x = hud.canvas.coords(rec["item"])[0]
            hud._on_motion(self._evt(60, (rec["y0"] + rec["y1"]) // 2))
            for _ in range(4):
                hud._marquee_step()
            hud._on_leave(self._evt(0, 0))
            self.assertIsNone(hud._marquee)
            self.assertEqual(hud.canvas.itemcget(rec["item"], "text"), truncated)   # text restored
            self.assertAlmostEqual(hud.canvas.coords(rec["item"])[0], base_x, delta=0.5)  # x restored
        finally:
            hud.close(); root.destroy()

    def test_hover_short_line_no_marquee(self):
        import feedkit.manager as manager
        from feedkit.model import Item
        root, hud = self._make_hud(self._long_feed())
        try:
            hud.active_tab = "tech"
            hud.feed_state[0] = manager.FeedResult("ok", [Item("short", "https://t/s")], None, None)
            hud._draw_feeds(); root.update_idletasks()
            self.assertEqual(hud._scroll_lines, [])             # nothing truncated
            for y0, y1, _u in hud._hit:
                hud._on_motion(self._evt(60, (y0 + y1) // 2))
            self.assertIsNone(hud._marquee)                     # short line never scrolls
        finally:
            hud.close(); root.destroy()


if __name__ == "__main__":
    unittest.main()
