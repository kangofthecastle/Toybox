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
class TestPetPhase4PinCarry(unittest.TestCase):
    def test_cat_has_pin_carry_objects_and_ticks(self):
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
            self.assertTrue(hasattr(cat, "pinset"))
            self.assertIsInstance(cat.hwnd, int)
            self.assertNotEqual(cat.hwnd, 0)
            # A drop holds the files; releasing clears the held list.
            cat._on_files_dropped(["C:\\a.txt", "C:\\b.txt"])
            self.assertEqual(cat._held, ["C:\\a.txt", "C:\\b.txt"])
            cat._release_held()
            self.assertEqual(cat._held, [])
            cat.tick()                # one tick must run with the new wiring
            cat.close()               # tears down poller/target/pins cleanly
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
