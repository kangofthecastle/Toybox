import unittest

from beat_detector import BeatDetector


def _settle_silence(d, start=0.0, n=20, dt=0.03):
    t = start
    r = None
    for _ in range(n):
        r = d.update(0.0, t)
        t += dt
    return t, r


class TestBeatDetector(unittest.TestCase):
    def test_silence_never_beats(self):
        d = BeatDetector()
        t = 0.0
        last = None
        for _ in range(50):
            last = d.update(0.0, t)
            self.assertFalse(last["beat"])
            t += 0.03
        self.assertLess(last["envelope"], 0.01)

    def test_onset_after_silence_beats(self):
        d = BeatDetector()
        t, _ = _settle_silence(d)
        r = d.update(0.6, t)
        self.assertTrue(r["beat"])

    def test_below_floor_never_beats(self):
        d = BeatDetector(floor=0.05)
        t, _ = _settle_silence(d)
        r = d.update(0.02, t)  # exceeds avg*sens (avg~0) but is below the floor
        self.assertFalse(r["beat"])

    def test_refractory_blocks_immediate_second_beat(self):
        d = BeatDetector(refractory=0.15)
        t, _ = _settle_silence(d)
        r1 = d.update(0.6, t)
        self.assertTrue(r1["beat"])
        t += 0.05  # still inside refractory window
        r2 = d.update(0.6, t)
        self.assertFalse(r2["beat"])

    def test_sustained_loud_only_beats_on_onset(self):
        d = BeatDetector(refractory=0.15)
        t, _ = _settle_silence(d)
        first = d.update(0.8, t)
        self.assertTrue(first["beat"])
        beats = 0
        for _ in range(30):
            t += 0.03
            if d.update(0.8, t)["beat"]:
                beats += 1
        self.assertEqual(beats, 0)  # steady level produces no further onsets

    def test_new_onset_after_drop_and_refractory(self):
        d = BeatDetector(refractory=0.15)
        t, _ = _settle_silence(d)
        d.update(0.8, t)  # onset beat
        # hold loud briefly, then go quiet long enough for avg to fall
        for _ in range(20):
            t += 0.03
            d.update(0.0, t)
        r = d.update(0.8, t)
        self.assertTrue(r["beat"])

    def test_envelope_rises_with_loudness(self):
        d = BeatDetector()
        t, base = _settle_silence(d)
        low_env = base["envelope"]
        for _ in range(15):
            t += 0.03
            r = d.update(0.7, t)
        self.assertGreater(r["envelope"], low_env)
        self.assertGreater(r["envelope"], 0.2)

    def test_envelope_within_unit_range(self):
        d = BeatDetector()
        t = 0.0
        for _ in range(40):
            r = d.update(1.0, t)
            self.assertGreaterEqual(r["envelope"], 0.0)
            self.assertLessEqual(r["envelope"], 1.0)
            t += 0.03


if __name__ == "__main__":
    unittest.main()
