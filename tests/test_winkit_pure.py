import os
import unittest

from winkit.input import vk_for
from winkit.startup import pythonw_command


class TestVkFor(unittest.TestCase):
    def test_modifiers(self):
        self.assertEqual(vk_for("ctrl"), 0x11)
        self.assertEqual(vk_for("control"), 0x11)
        self.assertEqual(vk_for("shift"), 0x10)
        self.assertEqual(vk_for("alt"), 0x12)
        self.assertEqual(vk_for("win"), 0x5B)

    def test_letter_is_uppercase_ascii(self):
        self.assertEqual(vk_for("v"), 0x56)
        self.assertEqual(vk_for("V"), 0x56)

    def test_digit(self):
        self.assertEqual(vk_for("3"), 0x33)

    def test_unknown_token_raises(self):
        with self.assertRaises(ValueError):
            vk_for("nope")


class TestPythonwCommand(unittest.TestCase):
    def test_two_independently_quoted_paths(self):
        cmd = pythonw_command("hud.pyw")
        self.assertEqual(cmd.count('"'), 4)        # exactly two quoted tokens
        self.assertTrue(cmd.startswith('"'))
        self.assertTrue(cmd.endswith('"'))

    def test_script_path_is_absolute_and_quoted(self):
        cmd = pythonw_command("hud.pyw")
        self.assertIn('"' + os.path.abspath("hud.pyw") + '"', cmd)


if __name__ == "__main__":
    unittest.main()
