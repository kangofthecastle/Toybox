"""Real-system integration smoke tests for winkit (run ON Windows 10)."""
import ctypes
import os
import time
import tkinter as tk
import unittest

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestOverlayStyles(unittest.TestCase):
    def test_apply_overlay_sets_layered_and_clickthrough_bits(self):
        import winkit.window as W
        W.enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.geometry("50x50+0+0")
        root.update()
        try:
            hwnd = W.apply_overlay_styles(root, clickthrough=True)
            self.assertIsInstance(hwnd, int)
            getp = getattr(ctypes.windll.user32, "GetWindowLongPtrW",
                           ctypes.windll.user32.GetWindowLongW)
            getp.restype = ctypes.c_void_p
            getp.argtypes = [ctypes.c_void_p, ctypes.c_int]
            ex = int(getp(hwnd, GWL_EXSTYLE) or 0)
            self.assertTrue(ex & WS_EX_LAYERED)
            self.assertTrue(ex & WS_EX_TRANSPARENT)
        finally:
            root.destroy()

    def test_non_clickthrough_is_layered_but_hit_testable(self):
        import winkit.window as W
        W.enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.geometry("50x50+0+0")
        root.update()
        try:
            hwnd = W.apply_overlay_styles(root, clickthrough=False)
            getp = getattr(ctypes.windll.user32, "GetWindowLongPtrW",
                           ctypes.windll.user32.GetWindowLongW)
            getp.restype = ctypes.c_void_p
            getp.argtypes = [ctypes.c_void_p, ctypes.c_int]
            ex = int(getp(hwnd, GWL_EXSTYLE) or 0)
            self.assertTrue(ex & WS_EX_LAYERED)        # still translucent/shaped
            self.assertFalse(ex & WS_EX_TRANSPARENT)   # but clicks land on opaque pixels
        finally:
            root.destroy()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestMetrics(unittest.TestCase):
    def test_cpu_sampler_in_range(self):
        import winkit.metrics as M
        s = M.CpuSampler()
        self.assertEqual(s.sample(), 0.0)  # first call is the baseline
        time.sleep(0.05)
        v = s.sample()
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 100.0)

    def test_ram_percent_in_range(self):
        import winkit.metrics as M
        r = M.ram_percent()
        self.assertGreater(r, 0.0)
        self.assertLessEqual(r, 100.0)


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestInput(unittest.TestCase):
    def test_clipboard_sequence_is_int(self):
        import winkit.input as I
        a = I.clipboard_sequence()
        b = I.clipboard_sequence()
        self.assertIsInstance(a, int)
        self.assertGreaterEqual(a, 0)
        self.assertEqual(a, b)  # stable when nothing is copied between calls

    def test_key_down_returns_bool(self):
        import winkit.input as I
        self.assertIsInstance(I.key_down(0x10), bool)  # shift, almost certainly up


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestAudioMeter(unittest.TestCase):
    def test_read_in_unit_range_then_close(self):
        import winkit.audio as A
        m = A.AudioPeakMeter()
        try:
            for _ in range(3):
                v = m.read()
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)
        finally:
            m.close()

    def test_repeated_construct_close_no_crash(self):
        import winkit.audio as A
        for _ in range(5):
            m = A.AudioPeakMeter()
            try:
                v = m.read()
                self.assertGreaterEqual(v, 0.0)
            finally:
                m.close()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestStartupRegistry(unittest.TestCase):
    NAME = "ToyboxTest__DELETEME"

    def tearDown(self):
        import winkit.startup as S
        S.set_run_at_startup(self.NAME, "x.pyw", False)

    def test_round_trip(self):
        import winkit.startup as S
        self.assertFalse(S.is_run_at_startup(self.NAME))
        S.set_run_at_startup(self.NAME, "x.pyw", True)
        self.assertTrue(S.is_run_at_startup(self.NAME))
        S.set_run_at_startup(self.NAME, "x.pyw", False)
        self.assertFalse(S.is_run_at_startup(self.NAME))


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestTrayConstruct(unittest.TestCase):
    def test_construct_and_close(self):
        import winkit.tray as T
        tray = T.TrayIcon("Toybox test", lambda: [{"label": "Quit", "callback": lambda: None}])
        try:
            self.assertIsInstance(tray.hwnd, int)
            self.assertNotEqual(tray.hwnd, 0)
        finally:
            tray.close()


if __name__ == "__main__":
    unittest.main()
