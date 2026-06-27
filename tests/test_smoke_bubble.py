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


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestMeowChime(unittest.TestCase):
    def test_meow_asset_is_pcm_wav(self):
        import wave
        import petkit.bubble as B
        with wave.open(B._MEOW, "rb") as w:
            self.assertEqual(w.getcomptype(), "NONE")   # PCM -> winsound-playable
            self.assertGreater(w.getnframes(), 0)

    def test_chime_true_meows_without_raising(self):
        import winkit.window as W
        import petkit.bubble as B
        W.enable_dpi_awareness()
        root = tk.Tk(); root.overrideredirect(True)
        root.geometry("170x170+100+100"); root.update()
        try:
            bubble = B.Bubble(root)
            bubble.say("meow", secs=1, chime=True)       # plays the async meow once
            root.update()
            bubble.destroy()
        finally:
            root.destroy()
