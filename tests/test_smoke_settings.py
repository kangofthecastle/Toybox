import os
import unittest


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestSettingsWindow(unittest.TestCase):
    def _make_cat(self):
        import tkinter as tk
        import winkit.window as window
        import config
        import pet as petmod
        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("%dx%d+120+120" % (petmod.WIN, petmod.WIN))
        canvas = tk.Canvas(root, width=petmod.WIN, height=petmod.WIN,
                           bg=window.KEY_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        root.update()
        return root, petmod.Cat(root, canvas, config.defaults())

    def test_open_build_all_tabs_and_close(self):
        import petkit.settings as settings
        root, cat = self._make_cat()
        try:
            win = settings.SettingsWindow(cat)
            win.open()
            self.assertIsNotNone(win.win)
            # Exercise the dynamic refresh paths with a pending reminder + the
            # focus-saver, none of which should raise.
            cat.reminders.add("ping", 9999999999)
            win._refresh_reminders()
            win._refresh_pins()
            win._focus_var.set("30"); win._break_var.set("7"); win._on_save_focus()
            self.assertEqual(cat.cfg["pet"]["focus_min"], 30)
            # Add via structured fields ("in 5 min").
            win._mode_var.set("in"); win._amount_var.set("5"); win._unit_var.set("min")
            win._msg_var.set("water"); win._on_add_reminder()
            self.assertTrue(any(i["text"] == "water" for i in cat.reminders.pending()))
            win.open("Pin")               # re-open selects a tab, no second window
            win.close()
            self.assertIsNone(win.win)
            win.open()                    # reopening recreates cleanly
            self.assertIsNotNone(win.win)
            win.close()
            cat.close()
        finally:
            root.destroy()
