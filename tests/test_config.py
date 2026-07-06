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

    def test_phase3_nudge_defaults_present(self):
        pet = config.defaults()["pet"]
        for key in ("nudges",):
            self.assertIn(key, pet)
            self.assertIsInstance(pet[key], bool)
        self.assertNotIn("clip_actions", pet)
        self.assertNotIn("focus_tracker", pet)
        self.assertIn("nudge_min", pet)
        self.assertIsInstance(pet["nudge_min"], int)
        self.assertNotIsInstance(pet["nudge_min"], bool)

    def test_phase4_pin_carry_defaults_present(self):
        pet = config.defaults()["pet"]
        for key in ("pin", "carry"):
            self.assertIn(key, pet)
            self.assertIsInstance(pet[key], bool)
        self.assertNotIn("pin_hotkey", pet)   # hotkey removed; pinning is cat-driven now

    def test_clipboard_layout_default(self):
        self.assertEqual(config.defaults()["clipboard"]["layout"], "columns")

    def test_hud_audio_defaults_present(self):
        audio = config.defaults()["hud"]["audio"]
        for slot in ("speaker", "headphone"):
            self.assertIn(slot, audio)
            for key in ("id", "name"):
                self.assertIn(key, audio[slot])
                self.assertEqual(audio[slot][key], "")

    def test_hud_audio_partial_config_merges_with_defaults(self):
        self._write({"hud": {"audio": {"headphone": {"id": "X", "name": "ARCAM"}}}})
        audio = config.load(self.path)["hud"]["audio"]
        self.assertEqual(audio["headphone"], {"id": "X", "name": "ARCAM"})  # provided kept
        self.assertEqual(audio["speaker"], {"id": "", "name": ""})          # other slot filled

    def test_clipboard_layout_roundtrip(self):
        cfg = config.defaults()
        cfg["clipboard"]["layout"] = "stacked"
        config.save(self.path, cfg)
        self.assertEqual(config.load(self.path)["clipboard"]["layout"], "stacked")

    def test_clipboard_layout_non_string_falls_back(self):
        self._write({"clipboard": {"layout": 5}})
        cfg = config.load(self.path)
        self.assertEqual(cfg["clipboard"]["layout"], "columns")

    def test_clipboard_sync_defaults(self):
        c = config.defaults()["clipboard"]
        self.assertIs(c["sync"], False)
        self.assertEqual(c["sync_passphrase"], "")

    def test_clipboard_sync_roundtrip(self):
        cfg = config.defaults()
        cfg["clipboard"]["sync"] = True
        cfg["clipboard"]["sync_passphrase"] = "hunter2"
        config.save(self.path, cfg)
        loaded = config.load(self.path)
        self.assertIs(loaded["clipboard"]["sync"], True)
        self.assertEqual(loaded["clipboard"]["sync_passphrase"], "hunter2")

    def test_clipboard_sync_wrong_types_fall_back(self):
        self._write({"clipboard": {"sync": "yes", "sync_passphrase": 123}})
        c = config.load(self.path)["clipboard"]
        self.assertIs(c["sync"], False)          # non-bool rejected
        self.assertEqual(c["sync_passphrase"], "")  # non-str rejected

    def test_clipboard_persist_recent_default(self):
        self.assertIs(config.defaults()["clipboard"]["persist_recent"], True)

    def test_clipboard_pin_default(self):
        self.assertIs(config.defaults()["clipboard"]["pin"], False)

    def test_clipboard_keep_open_default(self):
        self.assertIs(config.defaults()["clipboard"]["keep_open"], False)

    def test_clipboard_pin_roundtrip(self):
        cfg = config.defaults()
        cfg["clipboard"]["pin"] = True
        config.save(self.path, cfg)
        self.assertIs(config.load(self.path)["clipboard"]["pin"], True)

    def test_clipboard_persist_recent_wrong_type_falls_back(self):
        self._write({"clipboard": {"persist_recent": "yes"}})
        c = config.load(self.path)["clipboard"]
        self.assertIs(c["persist_recent"], True)   # non-bool rejected -> default

    def test_feeds_default_is_empty_list(self):
        self.assertEqual(config.defaults()["feeds"], [])

    def test_github_token_default_is_empty_string(self):
        self.assertEqual(config.defaults()["hud"]["github_token"], "")

    def test_feeds_list_roundtrip(self):
        cfg = config.defaults()
        cfg["feeds"] = [{"type": "rss", "url": "https://x/y", "title": "X"}]
        config.save(self.path, cfg)
        self.assertEqual(config.load(self.path)["feeds"],
                         [{"type": "rss", "url": "https://x/y", "title": "X"}])

    def test_feeds_non_list_falls_back_to_empty(self):
        self._write({"feeds": "nope"})
        self.assertEqual(config.load(self.path)["feeds"], [])

    def test_github_token_non_string_falls_back(self):
        self._write({"hud": {"github_token": 123}})
        self.assertEqual(config.load(self.path)["hud"]["github_token"], "")

    # --- scoped update (read-modify-write; a writer touches only its own keys) ---

    def test_update_preserves_keys_the_writer_does_not_own(self):
        # full config on disk: feeds + token + a clipboard setting
        cfg = config.defaults()
        cfg["feeds"] = [{"type": "rss", "url": "https://x/y", "title": "X"}]
        cfg["hud"]["github_token"] = "ghp_secret"
        cfg["clipboard"]["max_items"] = 7
        config.save(self.path, cfg)
        # a HUD-style positional save touches ONLY hud x/y/alpha/locked
        config.update(self.path, {"hud": {"x": 99, "y": 88, "alpha": 0.5, "locked": True}})
        loaded = config.load(self.path)
        self.assertEqual(loaded["hud"]["x"], 99)                       # partial applied
        self.assertEqual(loaded["hud"]["github_token"], "ghp_secret")  # NOT clobbered
        self.assertEqual(loaded["feeds"],
                         [{"type": "rss", "url": "https://x/y", "title": "X"}])  # NOT clobbered
        self.assertEqual(loaded["clipboard"]["max_items"], 7)          # NOT clobbered

    def test_update_merges_into_nested_section_keeping_siblings(self):
        cfg = config.defaults()
        cfg["hud"]["github_token"] = "tok"
        cfg["hud"]["alpha"] = 0.9
        config.save(self.path, cfg)
        config.update(self.path, {"hud": {"x": 5}})
        loaded = config.load(self.path)
        self.assertEqual(loaded["hud"]["x"], 5)
        self.assertEqual(loaded["hud"]["github_token"], "tok")  # sibling preserved
        self.assertEqual(loaded["hud"]["alpha"], 0.9)

    def test_update_missing_file_uses_defaults_plus_partial(self):
        config.update(self.path, {"feeds": [{"type": "notifications"}]})
        loaded = config.load(self.path)
        self.assertEqual(loaded["feeds"], [{"type": "notifications"}])
        self.assertEqual(loaded["hud"]["alpha"], config.DEFAULTS["hud"]["alpha"])  # defaults filled

    def test_update_feeds_only_does_not_touch_hud_position(self):
        cfg = config.defaults()
        cfg["hud"]["x"] = 1234
        config.save(self.path, cfg)
        config.update(self.path, {"feeds": [{"type": "notifications"}]})
        self.assertEqual(config.load(self.path)["hud"]["x"], 1234)  # position preserved

    def test_update_returns_merged_config(self):
        config.save(self.path, config.defaults())
        merged = config.update(self.path, {"hud": {"x": 42}})
        self.assertEqual(merged["hud"]["x"], 42)

    def test_update_preserves_unknown_keys_written_by_newer_code(self):
        # A key this build's DEFAULTS doesn't know (a newer version's section, or a
        # hand-added one) must SURVIVE a scoped update by a writer that doesn't
        # recognize it -- else older code silently wipes newer config on its own save.
        import json
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"hud": {"x": 5, "future": {"deep": "keep me"}},
                       "brandnew": {"k": 1}}, f)
        config.update(self.path, {"hud": {"x": 6}})       # writer touches only hud.x
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        self.assertEqual(raw["hud"]["x"], 6)                          # partial applied
        self.assertEqual(raw["hud"]["future"], {"deep": "keep me"})  # unknown nested key kept
        self.assertEqual(raw["brandnew"], {"k": 1})                  # unknown top-level kept

    def test_stale_build_update_does_not_wipe_hud_audio(self):
        # The reported regression: a toy whose DEFAULTS predate hud.audio must NOT
        # strip hud.audio when it saves its OWN (clipboard) section.
        import json, copy
        cfg = config.defaults()
        cfg["hud"]["audio"] = {"speaker": {"id": "SPK", "name": "Spk"},
                               "headphone": {"id": "HP", "name": "Hp"}}
        config.save(self.path, cfg)
        orig = config.DEFAULTS
        stale = copy.deepcopy(config.DEFAULTS)
        del stale["hud"]["audio"]                          # simulate a pre-audio build
        config.DEFAULTS = stale
        try:
            config.update(self.path, {"clipboard": {"max_items": 7}})
        finally:
            config.DEFAULTS = orig
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        self.assertEqual(raw["hud"]["audio"]["speaker"]["id"], "SPK")     # survived
        self.assertEqual(raw["hud"]["audio"]["headphone"]["id"], "HP")


if __name__ == "__main__":
    unittest.main()
