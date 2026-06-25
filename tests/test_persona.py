# tests/test_persona.py
import unittest
import petkit.persona as persona


class TestPersona(unittest.TestCase):
    def test_band_boundaries(self):
        self.assertEqual(persona.band_name(0), "night")
        self.assertEqual(persona.band_name(4), "night")
        self.assertEqual(persona.band_name(5), "morning")
        self.assertEqual(persona.band_name(10), "morning")
        self.assertEqual(persona.band_name(11), "day")
        self.assertEqual(persona.band_name(16), "day")
        self.assertEqual(persona.band_name(17), "evening")
        self.assertEqual(persona.band_name(20), "evening")
        self.assertEqual(persona.band_name(21), "night")
        self.assertEqual(persona.band_name(23), "night")

    def test_glow_rgb_is_triple(self):
        rgb = persona.glow_rgb(13)
        self.assertEqual(len(rgb), 3)
        self.assertTrue(all(0 <= c <= 255 for c in rgb))

    def test_greeting_is_nonempty(self):
        self.assertTrue(persona.greeting(8))


if __name__ == "__main__":
    unittest.main()
