import unittest

import winkit.nowplaying as nowplaying


class TestProgressFraction(unittest.TestCase):
    def test_zero_duration_is_zero(self):
        self.assertEqual(nowplaying.progress_fraction(10.0, 0.0), 0.0)

    def test_negative_duration_is_zero(self):
        self.assertEqual(nowplaying.progress_fraction(10.0, -5.0), 0.0)

    def test_quarter(self):
        self.assertAlmostEqual(nowplaying.progress_fraction(30.0, 120.0), 0.25)

    def test_clamps_over_one(self):
        self.assertEqual(nowplaying.progress_fraction(200.0, 120.0), 1.0)

    def test_negative_position_is_zero(self):
        self.assertEqual(nowplaying.progress_fraction(-3.0, 120.0), 0.0)

    def test_bad_input_is_zero(self):
        self.assertEqual(nowplaying.progress_fraction(None, None), 0.0)


class TestAdvance(unittest.TestCase):
    def test_playing_adds_elapsed(self):
        self.assertAlmostEqual(nowplaying.advance(30.0, 5.0, "playing"), 35.0)

    def test_paused_holds(self):
        self.assertAlmostEqual(nowplaying.advance(30.0, 5.0, "paused"), 30.0)

    def test_stopped_holds(self):
        self.assertAlmostEqual(nowplaying.advance(30.0, 5.0, "stopped"), 30.0)

    def test_negative_elapsed_ignored(self):
        self.assertAlmostEqual(nowplaying.advance(30.0, -5.0, "playing"), 30.0)

    def test_never_negative(self):
        self.assertEqual(nowplaying.advance(-10.0, 0.0, "paused"), 0.0)

    def test_bad_input(self):
        self.assertEqual(nowplaying.advance(None, None, "playing"), 0.0)


class TestFormatTrack(unittest.TestCase):
    def test_title_and_artist(self):
        self.assertEqual(nowplaying.format_track("Song", "Band"), "Song — Band")

    def test_title_only(self):
        self.assertEqual(nowplaying.format_track("Song", ""), "Song")

    def test_artist_only(self):
        self.assertEqual(nowplaying.format_track("", "Band"), "Band")

    def test_both_empty(self):
        self.assertEqual(nowplaying.format_track("", ""), "")

    def test_none_inputs(self):
        self.assertEqual(nowplaying.format_track(None, None), "")

    def test_trims_whitespace(self):
        self.assertEqual(nowplaying.format_track("  Song ", " Band "), "Song — Band")


class TestNowPlayingRecord(unittest.TestCase):
    def test_fields_in_order(self):
        s = nowplaying.NowPlaying("t", "a", "playing", 1.0, 2.0, 3.0)
        self.assertEqual(s.title, "t")
        self.assertEqual(s.artist, "a")
        self.assertEqual(s.status, "playing")
        self.assertEqual(s.position_s, 1.0)
        self.assertEqual(s.duration_s, 2.0)
        self.assertEqual(s.sampled_at, 3.0)


if __name__ == "__main__":
    unittest.main()
