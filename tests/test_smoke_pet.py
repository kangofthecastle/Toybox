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


if __name__ == "__main__":
    unittest.main()
