"""GUI test: editing a row updates the store through the panel, keeps the ALL
selection in sync, and the editor popup builds prefilled with the row's text.

The button-click path can't be driven by event_generate on this Tk build (see
test_clip_panel_scroll's mapping note), so the commit logic lives in the
mapping-independent seam _apply_edit, which these tests call directly; the popup
itself is checked only for structure (Toplevel + prefilled Text).
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

    _spec = importlib.util.spec_from_file_location("clipboard_mod_ed", CLIP_PATH)
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


def _descendants(w):
    out = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(_descendants(c))
    return out


@unittest.skipUnless(_LOAD_ERR is None, "Tk/clipboard.pyw unavailable: %r" % (_LOAD_ERR,))
class TestClipPanelEdit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="clipedit_")
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

    def _texts(self):
        return [e["text"] for e in self.store.recent()]

    def test_apply_edit_updates_store(self):
        self.store.add("hello", 1.0)
        self._build()
        self.panel._apply_edit("hello", "world")
        self.assertEqual(self._texts(), ["world"])

    def test_apply_edit_keeps_selection_under_new_text(self):
        self.store.add("a", 1.0)
        self.store.add("b", 2.0)
        self._build()
        self.panel._selected.add("a")
        self.panel._apply_edit("a", "a2")
        self.assertIn("a2", self.panel._selected)
        self.assertNotIn("a", self.panel._selected)

    def test_apply_edit_blank_is_noop(self):
        self.store.add("a", 1.0)
        self._build()
        self.panel._apply_edit("a", "   ")
        self.assertEqual(self._texts(), ["a"])

    def test_editor_popup_builds_prefilled(self):
        self.store.add("hello world", 1.0)
        self._build()
        self.panel._edit("hello world")
        self.panel.win.update_idletasks()
        tops = [w for w in self.panel.win.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertTrue(tops, "editor Toplevel was not created")
        texts = [w for w in _descendants(tops[0]) if isinstance(w, tk.Text)]
        self.assertTrue(texts, "editor has no Text widget")
        self.assertEqual(texts[0].get("1.0", "end-1c"), "hello world")


if __name__ == "__main__":
    unittest.main()
