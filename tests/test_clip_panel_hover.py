"""GUI test: row icons highlight on hover (brighter background + a semantic
foreground) and restore on leave. Same skip-guarded harness as the other
clip-panel GUI tests.
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

    _spec = importlib.util.spec_from_file_location("clipboard_mod_h", CLIP_PATH)
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

    def save_cfg(self):
        pass

    def absorb_seq(self):
        pass


@unittest.skipUnless(_LOAD_ERR is None, "Tk/clipboard.pyw unavailable: %r" % (_LOAD_ERR,))
class TestClipPanelHover(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="cliphover_")
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

    def _first_row_icons(self):
        self.store.add("hello", 1000.0)
        self.panel = clipboard.ClipPanel(self.app)
        self.panel.win.geometry("632x420+0+0")
        self.panel.win.update_idletasks()
        self.panel.win.update()
        row0 = self.panel.all_inner.winfo_children()[0]
        return {w.cget("text"): w for w in row0.winfo_children()
                if isinstance(w, tk.Label)}

    def _assert_hover(self, icon, expected_fg):
        base_bg = icon.cget("bg")
        icon.event_generate("<Enter>")
        self.panel.win.update()
        self.assertEqual(icon.cget("bg"), clipboard.ICON_HOVER)
        self.assertEqual(icon.cget("fg"), expected_fg)
        icon.event_generate("<Leave>")
        self.panel.win.update()
        self.assertEqual(icon.cget("bg"), base_bg)

    def test_delete_icon_hovers_red(self):
        icons = self._first_row_icons()
        self._assert_hover(icons["✕"], clipboard.DEL_HOVER)

    def test_star_icon_hovers_gold(self):
        icons = self._first_row_icons()
        self._assert_hover(icons["☆"], clipboard.STAR_ON)


if __name__ == "__main__":
    unittest.main()
