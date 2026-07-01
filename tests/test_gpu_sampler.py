import os
import unittest


@unittest.skipUnless(os.name == "nt", "Windows only (PDH ctypes)")
class TestGpuSampler(unittest.TestCase):
    def test_sample_returns_float_or_none_and_never_raises(self):
        import winkit.metrics as metrics
        s = metrics.GpuSampler()
        for _ in range(2):                 # first is the baseline, second reads
            v = s.sample()
            self.assertTrue(v is None or isinstance(v, float))
            if isinstance(v, float):
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 100.0)


if __name__ == "__main__":
    unittest.main()
