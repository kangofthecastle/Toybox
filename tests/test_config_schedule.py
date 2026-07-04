import json
import os
import tempfile
import unittest

import config


class TestConfigScheduleDefault(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def test_default_shape(self):
        self.assertEqual(config.defaults()["hud"]["schedule"], {"path": ""})

    def test_path_roundtrips_through_load(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"hud": {"schedule": {"path": "C:/x/s.xlsx"}}}, f)
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"]["schedule"]["path"], "C:/x/s.xlsx")

    def test_missing_schedule_fills_default(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"hud": {"x": 5}}, f)
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"]["schedule"], {"path": ""})


if __name__ == "__main__":
    unittest.main()
