import os
import unittest


@unittest.skipUnless(os.name == "nt", "Windows only (user32 ctypes)")
class TestMedia(unittest.TestCase):
    def setUp(self):
        import winkit.media as media
        self.media = media
        self.calls = []
        self._orig = media._keybd_event
        media._keybd_event = lambda vk, flags: self.calls.append((vk, flags))
        self.addCleanup(setattr, media, "_keybd_event", self._orig)

    def test_play_pause_taps_playpause_vk_down_then_up(self):
        self.media.play_pause()
        self.assertEqual(self.calls,
                         [(0xB3, 0), (0xB3, self.media.KEYEVENTF_KEYUP)])

    def test_next_track_taps_next_vk(self):
        self.media.next_track()
        self.assertEqual(self.calls,
                         [(0xB0, 0), (0xB0, self.media.KEYEVENTF_KEYUP)])

    def test_prev_track_taps_prev_vk(self):
        self.media.prev_track()
        self.assertEqual(self.calls,
                         [(0xB1, 0), (0xB1, self.media.KEYEVENTF_KEYUP)])


if __name__ == "__main__":
    unittest.main()
