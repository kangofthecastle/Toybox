# tests/test_pins.py
import unittest
from petkit.pins import PinSet


class TestPinSet(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.pins = PinSet(lambda hwnd, on: self.calls.append((hwnd, on)) or True)

    def test_toggle_pins_then_unpins(self):
        self.assertTrue(self.pins.toggle(100))     # now pinned
        self.assertTrue(self.pins.is_pinned(100))
        self.assertEqual(self.calls[-1], (100, True))
        self.assertFalse(self.pins.toggle(100))    # now unpinned
        self.assertFalse(self.pins.is_pinned(100))
        self.assertEqual(self.calls[-1], (100, False))

    def test_tracks_multiple(self):
        self.pins.toggle(1)
        self.pins.toggle(2)
        self.assertEqual(self.pins.pinned(), {1, 2})

    def test_unpin_all_clears_and_calls_off(self):
        self.pins.toggle(1)
        self.pins.toggle(2)
        self.calls.clear()
        self.pins.unpin_all()
        self.assertEqual(self.pins.pinned(), set())
        self.assertEqual(sorted(c[0] for c in self.calls), [1, 2])
        self.assertTrue(all(c[1] is False for c in self.calls))


if __name__ == "__main__":
    unittest.main()
