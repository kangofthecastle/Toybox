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


class TestFormatClock(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(nowplaying.format_clock(0), "0:00")

    def test_seconds_pad(self):
        self.assertEqual(nowplaying.format_clock(5), "0:05")

    def test_minutes_seconds(self):
        self.assertEqual(nowplaying.format_clock(83), "1:23")

    def test_ten_minutes(self):
        self.assertEqual(nowplaying.format_clock(600), "10:00")

    def test_truncates_fraction(self):
        self.assertEqual(nowplaying.format_clock(83.9), "1:23")

    def test_hours(self):
        self.assertEqual(nowplaying.format_clock(3661), "1:01:01")

    def test_exact_hour(self):
        self.assertEqual(nowplaying.format_clock(3600), "1:00:00")

    def test_negative_is_zero(self):
        self.assertEqual(nowplaying.format_clock(-30), "0:00")

    def test_bad_input_is_zero(self):
        self.assertEqual(nowplaying.format_clock(None), "0:00")


class TestSeekTargetSeconds(unittest.TestCase):
    def test_left_edge_is_zero(self):
        self.assertAlmostEqual(nowplaying.seek_target_seconds(40, 40, 200, 120.0), 0.0)

    def test_right_edge_is_duration(self):
        self.assertAlmostEqual(nowplaying.seek_target_seconds(200, 40, 200, 120.0), 120.0)

    def test_midpoint_is_half(self):
        self.assertAlmostEqual(nowplaying.seek_target_seconds(120, 40, 200, 120.0), 60.0)

    def test_left_of_bar_clamps_to_zero(self):
        self.assertAlmostEqual(nowplaying.seek_target_seconds(10, 40, 200, 120.0), 0.0)

    def test_right_of_bar_clamps_to_duration(self):
        self.assertAlmostEqual(nowplaying.seek_target_seconds(999, 40, 200, 120.0), 120.0)

    def test_nonpositive_duration_is_zero(self):
        self.assertEqual(nowplaying.seek_target_seconds(120, 40, 200, 0.0), 0.0)

    def test_degenerate_span_is_zero(self):
        self.assertEqual(nowplaying.seek_target_seconds(120, 200, 200, 120.0), 0.0)

    def test_bad_input_is_zero(self):
        self.assertEqual(nowplaying.seek_target_seconds(None, None, None, None), 0.0)


class TestNowPlayingRecord(unittest.TestCase):
    def test_fields_in_order(self):
        s = nowplaying.NowPlaying("t", "a", "playing", 1.0, 2.0, 3.0)
        self.assertEqual(s.title, "t")
        self.assertEqual(s.artist, "a")
        self.assertEqual(s.status, "playing")
        self.assertEqual(s.position_s, 1.0)
        self.assertEqual(s.duration_s, 2.0)
        self.assertEqual(s.sampled_at, 3.0)


class TestReadSmoke(unittest.TestCase):
    def test_read_never_raises_and_is_well_shaped(self):
        # On any machine: returns None or a valid NowPlaying, and never raises.
        s = nowplaying.read()
        if s is not None:
            self.assertIsInstance(s, nowplaying.NowPlaying)
            self.assertIn(s.status, ("playing", "paused", "stopped"))
            self.assertIsInstance(s.title, str)
            self.assertIsInstance(s.artist, str)
            self.assertGreaterEqual(s.position_s, 0.0)
            self.assertGreaterEqual(s.duration_s, 0.0)
            self.assertIsInstance(s.sampled_at, float)

    def test_read_is_idempotent_no_raise(self):
        # Calling twice (re-entrant RoInitialize path) must also never raise.
        nowplaying.read()
        nowplaying.read()


class TestSeekSmoke(unittest.TestCase):
    def test_seek_never_raises_and_returns_bool(self):
        # On any machine (no session / no timeline / WinRT missing): returns a
        # bool and never raises. Cannot assert an effect without live playback.
        self.assertIsInstance(nowplaying.seek(30.0), bool)

    def test_seek_bad_input_returns_false(self):
        self.assertIs(nowplaying.seek(None), False)


class TestMarqueeScrollMax(unittest.TestCase):
    def test_fits_is_zero(self):
        self.assertEqual(nowplaying.marquee_scroll_max(100, 200), 0)

    def test_exact_fit_is_zero(self):
        self.assertEqual(nowplaying.marquee_scroll_max(200, 200), 0)

    def test_overflow_is_the_difference(self):
        self.assertEqual(nowplaying.marquee_scroll_max(260, 200), 60)

    def test_bad_input_is_zero(self):
        self.assertEqual(nowplaying.marquee_scroll_max(None, None), 0)


class TestMarqueeStep(unittest.TestCase):
    def test_static_when_max_not_positive(self):
        self.assertEqual(nowplaying.marquee_step(0, 0, 0), (0, 0))
        self.assertEqual(nowplaying.marquee_step(7, -3, 5), (0, 0))

    def test_advances_by_step_from_start(self):
        self.assertEqual(nowplaying.marquee_step(0, 100, 0), (2, 0))

    def test_custom_step(self):
        self.assertEqual(nowplaying.marquee_step(0, 100, 0, step=5), (5, 0))

    def test_clamps_at_end_and_arms_pause(self):
        self.assertEqual(nowplaying.marquee_step(99, 100, 0), (100, 10))

    def test_pause_counts_down_without_moving(self):
        self.assertEqual(nowplaying.marquee_step(100, 100, 10), (100, 9))

    def test_wraps_to_start_not_bounce(self):
        # At the end with the pause elapsed: JUMP to 0 (a bounce would give 98).
        self.assertEqual(nowplaying.marquee_step(100, 100, 0), (0, 10))

    def test_full_cycle_reaches_end_then_wraps_never_reverses(self):
        offset, pause, max_off = 0, 0, 20
        seen = []
        for _ in range(80):
            offset, pause = nowplaying.marquee_step(offset, max_off, pause)
            seen.append(offset)
        self.assertIn(max_off, seen)                      # scrolled to the end
        i = seen.index(max_off)
        j = i
        while j < len(seen) and seen[j] == max_off:
            j += 1                                        # skip the brief end pause
        self.assertLess(j, len(seen), "expected motion after the end pause")
        self.assertEqual(seen[j], 0)                      # wraps to start (bounce => 18)
        self.assertTrue(all(o >= 0 for o in seen))        # never runs backwards past 0


if __name__ == "__main__":
    unittest.main()
