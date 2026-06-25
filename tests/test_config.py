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

    # --- leaf type coercion (a wrong-typed but JSON-valid value must not reach a toy) ---

    def _write(self, obj):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def test_wrong_typed_int_falls_back_to_default(self):
        self._write({"hud": {"x": "left"}})
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"]["x"], config.DEFAULTS["hud"]["x"])

    def test_wrong_typed_max_items_falls_back_to_int(self):
        self._write({"clipboard": {"max_items": "twenty"}})
        cfg = config.load(self.path)
        self.assertEqual(cfg["clipboard"]["max_items"], config.DEFAULTS["clipboard"]["max_items"])
        self.assertIsInstance(cfg["clipboard"]["max_items"], int)

    def test_alpha_accepts_int_coerced_to_float(self):
        self._write({"hud": {"alpha": 1}})
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"]["alpha"], 1.0)
        self.assertIsInstance(cfg["hud"]["alpha"], float)

    def test_bool_field_rejects_non_bool(self):
        self._write({"hud": {"locked": "yes"}})
        cfg = config.load(self.path)
        self.assertIs(cfg["hud"]["locked"], False)

    def test_bool_not_accepted_as_int(self):
        self._write({"clipboard": {"max_items": True}})
        cfg = config.load(self.path)
        self.assertEqual(cfg["clipboard"]["max_items"], config.DEFAULTS["clipboard"]["max_items"])

    def test_nullable_xy_accepts_none_and_number(self):
        self._write({"pet": {"x": 300, "y": None}})
        cfg = config.load(self.path)
        self.assertEqual(cfg["pet"]["x"], 300)
        self.assertIsNone(cfg["pet"]["y"])

    def test_nullable_x_rejects_string(self):
        self._write({"pet": {"x": "left"}})
        cfg = config.load(self.path)
        self.assertIsNone(cfg["pet"]["x"])

    def test_hotkey_wrong_type_falls_back_to_list(self):
        self._write({"clipboard": {"hotkey": "ctrl+v"}})
        cfg = config.load(self.path)
        self.assertEqual(cfg["clipboard"]["hotkey"], config.DEFAULTS["clipboard"]["hotkey"])

    def test_section_replaced_by_scalar_falls_back_to_defaults(self):
        self._write({"hud": "not a dict"})
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"], config.DEFAULTS["hud"])

    def test_valid_values_preserved_through_coercion(self):
        cfg_in = config.defaults()
        cfg_in["hud"]["x"] = 100
        cfg_in["hud"]["locked"] = True
        cfg_in["pet"]["x"] = 5
        config.save(self.path, cfg_in)
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"]["x"], 100)
        self.assertIs(cfg["hud"]["locked"], True)
        self.assertEqual(cfg["pet"]["x"], 5)

    def test_phase2_pet_defaults_present(self):
        pet = config.defaults()["pet"]
        for key in ("petting", "catnap", "greeter"):
            self.assertIn(key, pet)
            self.assertIsInstance(pet[key], bool)
        for key in ("nap_after_s", "away_after_s"):
            self.assertIn(key, pet)
            self.assertIsInstance(pet[key], int)
            self.assertNotIsInstance(pet[key], bool)

    def test_phase3_focus_reminder_defaults_present(self):
        pet = config.defaults()["pet"]
        for key in ("focus_min", "break_min"):
            self.assertIn(key, pet)
            self.assertIsInstance(pet[key], int)
            self.assertNotIsInstance(pet[key], bool)
        self.assertIn("reminders", pet)
        self.assertIsInstance(pet["reminders"], bool)

    def test_phase3_nudge_clip_focus_defaults_present(self):
        pet = config.defaults()["pet"]
        for key in ("nudges", "clip_actions", "focus_tracker"):
            self.assertIn(key, pet)
            self.assertIsInstance(pet[key], bool)
        self.assertIn("nudge_min", pet)
        self.assertIsInstance(pet["nudge_min"], int)
        self.assertNotIsInstance(pet["nudge_min"], bool)

    def test_phase4_pin_carry_defaults_present(self):
        pet = config.defaults()["pet"]
        for key in ("pin", "carry"):
            self.assertIn(key, pet)
            self.assertIsInstance(pet[key], bool)
        self.assertIn("pin_hotkey", pet)
        self.assertIsInstance(pet["pin_hotkey"], list)


if __name__ == "__main__":
    unittest.main()
