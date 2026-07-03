"""GUI test: the ALL section has a 'select all' header checkbox that checks /
unchecks every currently-shown ALL row in one click, and reflects the current
selection state (checked only when every shown row is selected).

Loaded like test_clip_panel_scroll: clipboard.pyw has a .pyw extension so it is
imported via importlib; the whole TestCase is skip-guarded so it stays portable
where Tk or a display is unavailable.
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

    _spec = importlib.util.spec_from_file_location("clipboard_mod_sa", CLIP_PATH)
    clipboard = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(clipboard)
except Exception as exc:  # pragma: no cover - environment dependent
    _LOAD_ERR = exc

CHECKED = "☑"     # ☑
UNCHECKED = "☐"   # ☐


class _FakeApp:
    def __init__(self, root, store, cfg):
        self.root = root
        self.store = store
        self.cfg = cfg
        self.icon_visible = True

    def save_cfg(self):
        pass

    def absorb_seq(self):
        pass


@unittest.skipUnless(_LOAD_ERR is None, "Tk/clipboard.pyw unavailable: %r" % (_LOAD_ERR,))
class TestClipPanelSelectAll(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="clipsel_")
        fav_path = os.path.join(self.tmpdir, "favorites.json")
        self.root = tk.Tk()
        self.root.withdraw()
        self.store = clip_store.ClipStore(30, fav_path)
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

    def test_select_all_selects_every_shown_row(self):
        for t, n in (("a", 1.0), ("b", 2.0), ("c", 3.0)):
            self.store.add(t, n)
        self._build()
        self.panel._toggle_select_all()
        self.assertEqual(self.panel._selected, {"a", "b", "c"})
        self.assertEqual(self.panel.select_all_chk.cget("text"), CHECKED)

    def test_select_all_again_clears(self):
        for t, n in (("a", 1.0), ("b", 2.0)):
            self.store.add(t, n)
        self._build()
        self.panel._toggle_select_all()   # all on
        self.panel._toggle_select_all()   # all off
        self.assertEqual(self.panel._selected, set())
        self.assertEqual(self.panel.select_all_chk.cget("text"), UNCHECKED)

    def test_header_checkbox_unchecked_when_only_some_selected(self):
        for t, n in (("a", 1.0), ("b", 2.0)):
            self.store.add(t, n)
        self._build()
        self.panel._selected.add("a")
        self.panel.refresh()
        self.assertEqual(self.panel.select_all_chk.cget("text"), UNCHECKED)

    def test_select_all_noop_when_empty(self):
        self._build()   # nothing copied yet
        self.panel._toggle_select_all()
        self.assertEqual(self.panel._selected, set())
        self.assertEqual(self.panel.select_all_chk.cget("text"), UNCHECKED)


if __name__ == "__main__":
    unittest.main()
