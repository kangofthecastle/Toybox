"""Regression test: per-section scrollbars must stay inert until content overflows.

The ClipPanel builds each column as a Canvas + inner Frame. When a section's
rows fit inside the column, the horizontal (and vertical) scrollbar should be a
full, non-draggable thumb. The bug: the scrollregion was set to the *content*
bbox (``canvas.bbox("all")``), which is smaller than the viewport when content
fits, so the scrollbar thumb did not fill its trough and the section could be
dragged/scrolled to nowhere. The fix stretches the inner canvas window to at
least the viewport size in both axes and pins the scrollregion to that size, so
``scrollregion == viewport`` exactly when content fits.

We assert two invariants:

1. ``scrollregion`` width/height never drops below the canvas (viewport) size
   when content fits. This is the load-bearing, Tk-version-independent check:
   the scrollbar thumb is computed from ``scrollregion``, so a scrollregion
   smaller than the viewport is precisely the draggable-but-inert-looking bug.
   This is RED on the pre-fix code (bbox -> smaller scrollregion) and GREEN
   after.
2. ``Canvas.xview()`` reports a full thumb ``(0.0, 1.0)`` for fitting content
   and a partial thumb (span < 1.0) for overflowing content. (Note: some Tk
   builds, including this Windows one, already clamp ``xview()`` to (0.0, 1.0)
   for a too-small scrollregion, so on those builds this assertion is GREEN
   both before and after the fix; invariant 1 is what makes the test RED here.)

clipboard.pyw has a .pyw extension, so a normal ``import`` won't find it; we load
it with importlib.util.spec_from_file_location (importing only runs module-level
code, never main()). The whole TestCase is skip-guarded so it stays portable if
Tk or the module can't load (mirroring the existing GUI smoke tests).
"""
import importlib.util
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLIP_PATH = os.path.join(ROOT, "clipboard.pyw")

# Attempt to load Tk and clipboard.pyw up front; if either fails, the whole
# TestCase is skipped rather than erroring on an environment without a display.
_LOAD_ERR = None
tk = None
clipboard = None
clip_store = None
config = None
try:
    import tkinter as tk  # noqa: E402
    import clip_store  # noqa: E402
    import config  # noqa: E402

    _spec = importlib.util.spec_from_file_location("clipboard_mod", CLIP_PATH)
    clipboard = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(clipboard)
except Exception as exc:  # pragma: no cover - environment dependent
    _LOAD_ERR = exc


class _FakeApp:
    """Minimal stand-in for ClipboardApp: just what ClipPanel touches."""

    def __init__(self, root, store, cfg):
        self.root = root
        self.store = store
        self.cfg = cfg
        self.icon_visible = True

    def save_cfg(self):
        pass

    def absorb_seq(self):
        pass


def _scrollregion(canvas):
    """Return the canvas scrollregion as a tuple of 4 floats (0,0,w,h)."""
    raw = canvas.cget("scrollregion")
    if isinstance(raw, str):
        parts = raw.split()
    else:  # Tcl may hand back a tuple of objects
        parts = list(raw)
    return tuple(float(p) for p in parts) if parts else (0.0, 0.0, 0.0, 0.0)


@unittest.skipUnless(_LOAD_ERR is None, "Tk/clipboard.pyw unavailable: %r" % (_LOAD_ERR,))
class TestClipPanelScroll(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="clipscroll_")
        fav_path = os.path.join(self.tmpdir, "favorites.json")
        self.root = tk.Tk()
        self.root.withdraw()
        store = clip_store.ClipStore(30, fav_path)
        self.app = _FakeApp(self.root, store, config.defaults())
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
        # Force a known geometry so the canvases get a realized, laid-out size.
        self.panel.win.geometry("632x420+0+0")
        self.panel.win.update_idletasks()
        self.panel.win.update()
        if self.panel.all_canvas.winfo_width() <= 1:
            self.skipTest("no usable display: canvas not laid out")

    def _refresh(self):
        self.panel.refresh()
        self.panel.win.update_idletasks()
        self.panel.win.update()

    def test_short_content_scrollbar_inert(self):
        # A clearly-short entry that comfortably fits inside the column.
        self.app.store.add("hi", 1000.0)
        self._build()
        self._refresh()
        canvas = self.panel.all_canvas
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        _, _, sr_w, sr_h = _scrollregion(canvas)

        # Invariant 1 (load-bearing / RED before the fix): the scrollregion must
        # not be smaller than the viewport when content fits -- a smaller
        # scrollregion is exactly the inert-but-draggable scrollbar bug.
        self.assertGreaterEqual(
            sr_w, cw,
            "scrollregion width (%s) dropped below the viewport (%s); the "
            "horizontal scrollbar would be draggable for fitting content"
            % (sr_w, cw))
        self.assertGreaterEqual(
            sr_h, ch,
            "scrollregion height (%s) dropped below the viewport (%s); the "
            "vertical scrollbar would be draggable for fitting content"
            % (sr_h, ch))

        # Invariant 2 (as specified): xview reports a full, inert thumb.
        first, last = canvas.xview()
        self.assertEqual(
            (first, last), (0.0, 1.0),
            "short content should leave the horizontal scrollbar inert "
            "(full thumb), got xview=%r" % ((first, last),))

    def test_long_content_enables_horizontal_scroll(self):
        # A clearly-overflowing entry, far wider than the column.
        self.app.store.add("x" * 400, 1000.0)
        self._build()
        self._refresh()
        canvas = self.panel.all_canvas
        first, last = canvas.xview()
        self.assertLess(
            last - first, 1.0,
            "overflowing content should enable horizontal scrolling, "
            "got xview=%r" % ((first, last),))

    @staticmethod
    def _bar_shown(bar):
        """True iff a scrollbar widget is currently shown in its section.

        Prefer the realized mapping state (``winfo_ismapped``); but on builds
        where the test toplevel never realizes mapping (everything reports 0),
        fall back to the grid-management state -- a ``grid_remove``'d widget
        reports ``winfo_manager() == ""`` while a gridded one reports "grid".
        """
        if bar.winfo_ismapped():
            return True
        # Distinguish "hidden because the toplevel isn't mapped" from "hidden
        # because grid_remove() was called": the latter drops grid management.
        return bool(bar.winfo_manager())

    def test_short_content_hides_horizontal_scrollbar(self):
        # The full-width stacked sections fit "hi" horizontally with room to
        # spare -> the horizontal scrollbar should be removed, not just inert.
        self.app.store.add("hi", 1000.0)
        self._build()
        self._refresh()
        hsb = self.panel.all_canvas.hsb
        self.assertFalse(
            self._bar_shown(hsb),
            "short content should hide the horizontal scrollbar; "
            "ismapped=%r manager=%r"
            % (hsb.winfo_ismapped(), hsb.winfo_manager()))

    def test_overflow_content_shows_horizontal_scrollbar(self):
        # A row far wider than the section -> the horizontal scrollbar must
        # appear so the overflow is reachable.
        self.app.store.add("x" * 400, 1000.0)
        self._build()
        self._refresh()
        hsb = self.panel.all_canvas.hsb
        self.assertTrue(
            self._bar_shown(hsb),
            "overflowing content should show the horizontal scrollbar; "
            "ismapped=%r manager=%r"
            % (hsb.winfo_ismapped(), hsb.winfo_manager()))


if __name__ == "__main__":
    unittest.main()
