"""Regression: copying a row from the panel must ALSO broadcast the text to LAN
peers (the Mac), not just set the local clipboard.

The capture poll loop is the only thing that calls node.local_change(), and it
fires on a clipboard-sequence bump. A panel re-copy advances that baseline via
absorb_seq() so the poller won't re-add the item to history -- but that also hid
the copy from the sync broadcast. mark_local_copy() closes that gap: it pushes
the text to peers, then absorbs the sequence.
"""
import importlib.util
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLIP_PATH = os.path.join(ROOT, "clipboard.pyw")

_LOAD_ERR = None
tk = None
clipboard = None
clip_store = None
config = None
try:
    import tkinter as tk  # noqa: E402
    import clip_store  # noqa: E402
    import config  # noqa: E402

    _spec = importlib.util.spec_from_file_location("clipboard_mod_sync", CLIP_PATH)
    clipboard = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(clipboard)
except Exception as exc:  # pragma: no cover - environment dependent
    _LOAD_ERR = exc


class _FakeNode:
    def __init__(self):
        self.changes = []

    def local_change(self, text):
        self.changes.append(text)


class _AppState:
    """Minimal stand-in carrying only what mark_local_copy touches, so the method
    can be exercised as an unbound function without building a real Tk app."""
    def __init__(self, node):
        self.node = node
        self.absorbed = 0

    def absorb_seq(self):
        self.absorbed += 1


@unittest.skipUnless(_LOAD_ERR is None, "clipboard.pyw unavailable: %r" % (_LOAD_ERR,))
class TestMarkLocalCopy(unittest.TestCase):
    def test_broadcasts_to_node_then_absorbs(self):
        node = _FakeNode()
        st = _AppState(node)
        clipboard.ClipboardApp.mark_local_copy(st, "hello world")
        self.assertEqual(node.changes, ["hello world"])   # sent to peers
        self.assertEqual(st.absorbed, 1)                   # poller baseline advanced

    def test_no_node_just_absorbs(self):
        st = _AppState(None)
        clipboard.ClipboardApp.mark_local_copy(st, "x")    # must not raise
        self.assertEqual(st.absorbed, 1)


class _FakeApp:
    def __init__(self, root, store, cfg):
        self.root = root
        self.store = store
        self.cfg = cfg
        self.icon_visible = True
        self.saved = 0
        self.marked = []

    def save_cfg(self):
        self.saved += 1

    def mark_local_copy(self, text):
        self.marked.append(text)

    def absorb_seq(self):
        pass


@unittest.skipUnless(_LOAD_ERR is None, "Tk/clipboard.pyw unavailable: %r" % (_LOAD_ERR,))
class TestCopyBroadcasts(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="clipsync_")
        fav_path = os.path.join(self.tmpdir, "favorites.json")
        self.root = tk.Tk()
        self.root.withdraw()
        self.store = clip_store.ClipStore(30, fav_path)
        self.store.add("hello", 1000.0)
        self.app = _FakeApp(self.root, self.store, config.defaults())
        self.panel = None

    def tearDown(self):
        if self.panel is not None:
            try:
                self.panel.win.destroy()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build(self):
        self.panel = clipboard.ClipPanel(self.app)
        self.panel.win.geometry("632x420+0+0")
        self.panel.win.update_idletasks()
        self.panel.win.update()

    def test_copy_and_close_routes_through_mark_local_copy(self):
        self.app.cfg["clipboard"]["pin"] = False
        self._build()
        self.panel._copy_and_close("hello")
        self.assertEqual(self.app.marked, ["hello"])   # copy reached the sync path


if __name__ == "__main__":
    unittest.main()
