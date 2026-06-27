import os
import unittest
from tests.smoke import run_smoke


class TestSmokePet(unittest.TestCase):
    def test_launches_and_exits_clean(self):
        rc, err = run_smoke("pet.pyw", 1500)
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.strip(), "")


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPetPhase2Wiring(unittest.TestCase):
    def test_cat_constructs_with_phase2_objects_and_ticks(self):
        import tkinter as tk
        import winkit.window as window
        import config
        import pet as petmod

        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("%dx%d+100+100" % (petmod.WIN, petmod.WIN))
        canvas = tk.Canvas(root, width=petmod.WIN, height=petmod.WIN,
                           bg=window.KEY_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        root.update()
        try:
            cat = petmod.Cat(root, canvas, config.defaults())
            self.assertTrue(hasattr(cat, "bubble"))
            self.assertTrue(hasattr(cat, "nap"))
            self.assertTrue(hasattr(cat, "petting"))
            self.assertTrue(hasattr(cat, "greeter"))
            cat.draw(cat.t0)          # one frame must not crash
            cat.close()
        finally:
            root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPetPhase3FocusReminders(unittest.TestCase):
    def test_cat_has_focus_and_reminder_objects_and_ticks(self):
        import tkinter as tk
        import winkit.window as window
        import config
        import pet as petmod

        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("%dx%d+100+100" % (petmod.WIN, petmod.WIN))
        canvas = tk.Canvas(root, width=petmod.WIN, height=petmod.WIN,
                           bg=window.KEY_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        root.update()
        try:
            cat = petmod.Cat(root, canvas, config.defaults())
            self.assertTrue(hasattr(cat, "pomodoro"))
            self.assertTrue(hasattr(cat, "reminders"))
            self.assertEqual(cat.pomodoro.state, "idle")
            cat.tick()                # one tick must run the focus/reminder paths
            cat.close()
        finally:
            root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPetPhase3Nudge(unittest.TestCase):
    def test_cat_has_nudge_object_and_ticks(self):
        import tkinter as tk
        import winkit.window as window
        import config
        import pet as petmod

        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("%dx%d+100+100" % (petmod.WIN, petmod.WIN))
        canvas = tk.Canvas(root, width=petmod.WIN, height=petmod.WIN,
                           bg=window.KEY_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        root.update()
        try:
            cat = petmod.Cat(root, canvas, config.defaults())
            self.assertTrue(hasattr(cat, "nudger"))
            self.assertFalse(hasattr(cat, "tally"))
            cat.tick()                # one tick must run the nudge path
            cat.close()
        finally:
            root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPetPinAndSupport(unittest.TestCase):
    def _make_cat(self):
        import tkinter as tk
        import winkit.window as window
        import config
        import pet as petmod
        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("%dx%d+100+100" % (petmod.WIN, petmod.WIN))
        canvas = tk.Canvas(root, width=petmod.WIN, height=petmod.WIN,
                           bg=window.KEY_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        root.update()
        return root, petmod.Cat(root, canvas, config.defaults())

    def test_pin_and_support_methods(self):
        root, cat = self._make_cat()
        try:
            self.assertFalse(hasattr(cat, "pin_hotkey"))     # hotkey path removed
            self.assertTrue(hasattr(cat, "pinset"))
            # Carry still works.
            cat._on_files_dropped(["C:\\a.txt", "C:\\b.txt"])
            self.assertEqual(cat._held, ["C:\\a.txt", "C:\\b.txt"])
            cat._release_held()
            self.assertEqual(cat._held, [])
            # Cat-driven pin runs without crashing (no real window under the cat in CI).
            cat._pin_under_cat()
            # Focus minutes write through to the Pomodoro object + config.
            cat._set_focus_minutes(40, 8)
            self.assertEqual(cat.pomodoro.focus_s, 40 * 60)
            self.assertEqual(cat.pomodoro.break_s, 8 * 60)
            self.assertEqual(cat.cfg["pet"]["focus_min"], 40)
            # Flag setter applies + persists; disabling pin releases pins.
            cat._set_cfg_flag("pin", False)
            self.assertFalse(cat.cfg["pet"]["pin"])
            self.assertEqual(cat.pinset.pinned(), set())
            cat.tick()
            cat.close()
        finally:
            root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPetMenuSlim(unittest.TestCase):
    def _make_cat(self):
        import tkinter as tk
        import winkit.window as window
        import config
        import pet as petmod
        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("%dx%d+100+100" % (petmod.WIN, petmod.WIN))
        canvas = tk.Canvas(root, width=petmod.WIN, height=petmod.WIN,
                           bg=window.KEY_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        root.update()
        return root, petmod.Cat(root, canvas, config.defaults())

    def test_menu_has_settings_and_no_checkbuttons(self):
        import time
        root, cat = self._make_cat()
        try:
            m = cat._build_menu(time.monotonic())
            labels, has_check = [], False
            for i in range(m.index("end") + 1):
                t = m.type(i)
                if t == "checkbutton":
                    has_check = True
                elif t == "command":
                    labels.append(m.entrycget(i, "label"))
            self.assertFalse(has_check)                                   # toggles moved to window
            self.assertTrue(any("Settings" in s for s in labels))
            self.assertTrue(any("Pin this window" in s for s in labels))
            cat._open_settings("Focus")
            self.assertIsNotNone(cat.settings.win)
            cat._open_settings()                                         # singleton: still one window
            cat.close()                                                  # closes the settings window too
        finally:
            root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestPetFocusBadge(unittest.TestCase):
    def _make_cat(self):
        import tkinter as tk
        import winkit.window as window
        import config
        import pet as petmod
        window.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=window.KEY_COLOR)
        root.geometry("%dx%d+100+100" % (petmod.WIN, petmod.WIN))
        canvas = tk.Canvas(root, width=petmod.WIN, height=petmod.WIN,
                           bg=window.KEY_COLOR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        root.update()
        return root, petmod.Cat(root, canvas, config.defaults())

    def test_badge_shows_during_focus_and_hides_when_idle(self):
        root, cat = self._make_cat()
        try:
            self.assertTrue(hasattr(cat, "timerbadge"))
            cat._start_focus()
            self.assertEqual(cat.pomodoro.state, "focus")
            cat.tick()                              # one tick with focus running
            self.assertTrue(cat.timerbadge._shown)  # badge became visible
            cat._stop_focus()
            cat.tick()                              # idle tick hides it
            self.assertFalse(cat.timerbadge._shown)
            cat.close()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
