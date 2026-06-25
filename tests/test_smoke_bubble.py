import os
import unittest
import tkinter as tk


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestBubble(unittest.TestCase):
    def test_say_shows_and_hides_without_crashing(self):
        import winkit.window as W
        import petkit.bubble as B
        W.enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.geometry("170x170+100+100")
        root.update()
        try:
            bubble = B.Bubble(root)
            bubble.say("purr~", secs=1, chime=False)
            root.update()
            self.assertTrue(bubble.win.winfo_ismapped())
            bubble.say("Welcome back!", secs=1)  # re-say reuses the window
            root.update()
            bubble.destroy()
        finally:
            root.destroy()
