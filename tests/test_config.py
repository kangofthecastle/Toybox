import json
import os
import shutil
import tempfile
import unittest

import config


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_defaults_returns_independent_copy(self):
        a = config.defaults()
        a["hud"]["x"] = -999
        b = config.defaults()
        self.assertNotEqual(b["hud"]["x"], -999)

    def test_load_missing_returns_defaults(self):
        self.assertEqual(config.load(self.path), config.defaults())

    def test_save_then_load_roundtrip(self):
        cfg = config.defaults()
        cfg["hud"]["x"] = 123
        cfg["clipboard"]["max_items"] = 7
        config.save(self.path, cfg)
        loaded = config.load(self.path)
        self.assertEqual(loaded["hud"]["x"], 123)
        self.assertEqual(loaded["clipboard"]["max_items"], 7)

    def test_corrupt_file_returns_defaults(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ not valid json ")
        self.assertEqual(config.load(self.path), config.defaults())

    def test_partial_config_filled_from_defaults(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"hud": {"x": 999}}, f)
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"]["x"], 999)          # provided value kept
        self.assertEqual(cfg["hud"]["alpha"], config.DEFAULTS["hud"]["alpha"])  # missing key filled
        self.assertIn("clipboard", cfg)                  # missing section filled
        self.assertIn("pet", cfg)

    def test_unknown_keys_ignored_not_crash(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"hud": {"x": 5}, "bogus": {"nope": 1}}, f)
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"]["x"], 5)

    def test_save_leaves_no_temp_file(self):
        config.save(self.path, config.defaults())
        leftovers = [f for f in os.listdir(self.dir) if f != "config.json"]
        self.assertEqual(leftovers, [])

    def test_save_creates_parent_dir(self):
        nested = os.path.join(self.dir, "sub", "deep", "config.json")
        config.save(nested, config.defaults())
        self.assertTrue(os.path.exists(nested))


if __name__ == "__main__":
    unittest.main()
