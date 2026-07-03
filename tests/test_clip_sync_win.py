import unittest

import clip_sync_win


class FakeStore:
    def __init__(self):
        self.added = []

    def add(self, text, ts):
        self.added.append((text, ts))


class TestSyncEnabled(unittest.TestCase):
    def _cfg(self, sync, passphrase):
        return {"clipboard": {"sync": sync, "sync_passphrase": passphrase}}

    def test_enabled_requires_flag_and_passphrase(self):
        self.assertTrue(clip_sync_win.sync_enabled(self._cfg(True, "pw")))

    def test_disabled_when_flag_off(self):
        self.assertFalse(clip_sync_win.sync_enabled(self._cfg(False, "pw")))

    def test_disabled_when_passphrase_empty(self):
        self.assertFalse(clip_sync_win.sync_enabled(self._cfg(True, "")))

    def test_missing_keys_are_safe(self):
        self.assertFalse(clip_sync_win.sync_enabled({"clipboard": {}}))
        self.assertFalse(clip_sync_win.sync_enabled({}))


class TestMakeApply(unittest.TestCase):
    def test_apply_sets_clipboard_absorbs_and_records(self):
        events = []
        store = FakeStore()
        apply = clip_sync_win.make_apply(
            set_clipboard=lambda t: events.append(("set", t)),
            store=store,
            absorb=lambda: events.append(("absorb", None)),
            now=lambda: 42.0)
        apply("from peer")
        # order matters: write the clipboard, THEN absorb the sequence bump
        self.assertEqual(events, [("set", "from peer"), ("absorb", None)])
        self.assertEqual(store.added, [("from peer", 42.0)])

    def test_apply_survives_store_failure(self):
        class Boom:
            def add(self, *a):
                raise RuntimeError("nope")
        events = []
        apply = clip_sync_win.make_apply(
            set_clipboard=lambda t: events.append("set"),
            store=Boom(),
            absorb=lambda: events.append("absorb"),
            now=lambda: 1.0)
        apply("x")                              # must not raise
        self.assertEqual(events, ["set", "absorb"])


class TestBuildNode(unittest.TestCase):
    def test_returns_none_when_disabled(self):
        cfg = {"clipboard": {"sync": False, "sync_passphrase": "pw"}}
        self.assertIsNone(clip_sync_win.build_node(cfg, lambda t: None))

    def test_builds_node_when_enabled(self):
        cfg = {"clipboard": {"sync": True, "sync_passphrase": "pw"}}
        node = clip_sync_win.build_node(cfg, lambda t: None,
                                        instance_id="X", udp_port=55210, tcp_port=55211)
        self.assertIsNotNone(node)
        self.assertEqual(node._instance_id, "X")   # did not start(); no sockets bound


class TestStartNode(unittest.TestCase):
    def test_none_passes_through(self):
        self.assertIsNone(clip_sync_win.start_node(None))

    def test_started_node_returned(self):
        class N:
            def __init__(self): self.started = False
            def start(self): self.started = True
        n = N()
        self.assertIs(clip_sync_win.start_node(n), n)
        self.assertTrue(n.started)

    def test_bind_failure_drops_to_none(self):
        class N:
            def start(self): raise OSError("addr in use")
        self.assertIsNone(clip_sync_win.start_node(N()))
