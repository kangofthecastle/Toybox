"""GUI test: the header pin toggle. When on, copying a row keeps the panel open
(instead of closing it); the toggle reads from / writes to clipboard.pin so it
persists. Same skip-guarded harness as the other clip-panel GUI tests.
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

    _spec = importlib.util.spec_from_file_location("clipboard_mod_p", CLIP_PATH)
    clipboard = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(clipboard)
except Exception as exc:  # pragma: no cover - environment dependent
    _LOAD_ERR = exc


class _FakeApp:
    def __init__(self, root, store, cfg):
        self.root = root
        self.store = store
        self.cfg = cfg
        self.icon_visible = True
        self.saved = 0

    def save_cfg(self):
        self.saved += 1

    def mark_local_copy(self, text):
        pass

    def absorb_seq(self):
        pass


@unittest.skipUnless(_LOAD_ERR is None, "Tk/clipboard.pyw unavailable: %r" % (_LOAD_ERR,))
class TestClipPanelPin(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="clippin_")
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

    def test_copy_closes_when_unpinned(self):
        self.app.cfg["clipboard"]["pin"] = False
        self._build()
        self.panel._copy_and_close("hello")
        self.assertFalse(self.panel.win.winfo_exists())

    def test_copy_keeps_panel_open_when_pinned(self):
        self.app.cfg["clipboard"]["pin"] = True
        self._build()
        self.panel._copy_and_close("hello")
        self.assertTrue(self.panel.win.winfo_exists())

    def test_keep_open_survives_focus_out(self):
        # the gear "keep open" setting (separate from the header pin) keeps the
        # panel alive when focus leaves it (clicking away, moving it around)
        self.app.cfg["clipboard"]["keep_open"] = True
        self._build()
        self.panel.win.focus_get = lambda: None   # force "focus left the app"
        self.panel._on_focus_out(None)
        self.assertTrue(self.panel.win.winfo_exists())

    def test_focus_out_closes_when_keep_open_off(self):
        self.app.cfg["clipboard"]["keep_open"] = False
        self._build()
        self.panel.win.focus_get = lambda: None
        self.panel._on_focus_out(None)
        self.assertFalse(self.panel.win.winfo_exists())

    def test_header_pin_does_not_affect_focus_out(self):
        # header pin governs copy-behaviour only; on its own it must NOT keep the
        # panel open on focus loss (that is the separate keep_open setting)
        self.app.cfg["clipboard"]["pin"] = True
        self.app.cfg["clipboard"]["keep_open"] = False
        self._build()
        self.panel.win.focus_get = lambda: None
        self.panel._on_focus_out(None)
        self.assertFalse(self.panel.win.winfo_exists())

    def test_toggle_keep_open_persists(self):
        self.app.cfg["clipboard"]["keep_open"] = False
        self._build()
        self.panel._toggle_keep_open()
        self.assertIs(self.app.cfg["clipboard"]["keep_open"], True)
        self.assertGreaterEqual(self.app.saved, 1)

    def test_toggle_pin_persists_and_renders(self):
        self.app.cfg["clipboard"]["pin"] = False
        self._build()
        self.panel._toggle_pin()
        self.assertIs(self.app.cfg["clipboard"]["pin"], True)
        self.assertGreaterEqual(self.app.saved, 1)
        self.assertEqual(self.panel.pin_lbl.cget("bg"), clipboard.SEL_BG)
        self.panel._toggle_pin()
        self.assertIs(self.app.cfg["clipboard"]["pin"], False)
        self.assertEqual(self.panel.pin_lbl.cget("bg"), clipboard.PANEL_BG)


if __name__ == "__main__":
    unittest.main()
