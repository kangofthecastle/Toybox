"""Unit tests for winkit.display -- the pure orientation math and the DEVMODEW
ctypes layout -- plus petkit.rotate._device_label. The native
EnumDisplaySettings / ChangeDisplaySettingsEx calls need a real GPU and would
physically rotate the screen, so they are exercised by hand, not here."""
import ctypes
import unittest

from winkit import display
from petkit import rotate


class NextOrientation(unittest.TestCase):
    def test_single_step_wraps(self):
        self.assertEqual(display.next_orientation(0), 1)
        self.assertEqual(display.next_orientation(1), 2)
        self.assertEqual(display.next_orientation(2), 3)
        self.assertEqual(display.next_orientation(3), 0)   # wrap 270 -> 0

    def test_multi_step_and_zero(self):
        self.assertEqual(display.next_orientation(2, 2), 0)
        self.assertEqual(display.next_orientation(3, 2), 1)
        self.assertEqual(display.next_orientation(1, 0), 1)
        self.assertEqual(display.next_orientation(0, 4), 0)   # a full turn


class DimensionSwap(unittest.TestCase):
    def test_quarter_turns_swap(self):
        # An odd number of quarter-turns crosses landscape<->portrait -> swap.
        for cur, tgt in ((0, 1), (1, 2), (2, 3), (3, 0), (0, 3), (1, 0)):
            self.assertTrue(display.needs_dimension_swap(cur, tgt), (cur, tgt))

    def test_half_and_no_turn_keep_dims(self):
        # 0 or 180 degrees keeps the aspect ratio -> no swap.
        for cur, tgt in ((0, 0), (0, 2), (1, 3), (2, 0), (3, 1)):
            self.assertFalse(display.needs_dimension_swap(cur, tgt), (cur, tgt))

    def test_cycle_always_swaps(self):
        # Every single click (the panel's gesture) flips the aspect ratio.
        for cur in range(4):
            self.assertTrue(
                display.needs_dimension_swap(cur, display.next_orientation(cur)))


class DevmodeLayout(unittest.TestCase):
    def test_struct_size(self):
        # Guards the hand-written ctypes layout (both anonymous unions collapsed
        # to a single branch). A wrong size means wrong field offsets, which
        # would corrupt every ChangeDisplaySettingsEx call.
        self.assertEqual(ctypes.sizeof(display._DEVMODEW), 220)

    def test_orientation_lives_in_first_union(self):
        # dmDisplayOrientation must sit right after the 8-byte POINTL position.
        self.assertEqual(display._DEVMODE_DISPLAY.dmDisplayOrientation.offset, 8)


class DeviceLabel(unittest.TestCase):
    def test_secondary(self):
        self.assertEqual(
            rotate._device_label({"device": r"\\.\DISPLAY2", "primary": False}),
            "DISPLAY2")

    def test_primary_marked(self):
        self.assertEqual(
            rotate._device_label({"device": r"\\.\DISPLAY1", "primary": True}),
            "DISPLAY1 (primary)")

    def test_missing_primary_key_defaults_off(self):
        self.assertEqual(
            rotate._device_label({"device": r"\\.\DISPLAY3"}), "DISPLAY3")


if __name__ == "__main__":
    unittest.main()
