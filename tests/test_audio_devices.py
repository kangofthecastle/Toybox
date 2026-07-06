import unittest

from winkit.audio import match_device, active_slot

# (endpoint_id, friendly_name) as returned by list_render_devices()
DEVICES = [
    ("{id-hd-speakers}", "Speakers (High Definition Audio Device)"),
    ("{id-arcam}", "Speakers (ARCAM USB Audio 1.0)"),
    ("{id-spdif}", "Digital Audio (S/PDIF) (High Definition Audio Device)"),
    ("{id-at2020}", "Headphones (2- AT2020USB+)"),
]


class TestMatchDevice(unittest.TestCase):
    def test_exact_id_wins(self):
        # even with a bogus substring, a present id binds exactly
        self.assertEqual(match_device(DEVICES, "{id-arcam}", "nonsense"), "{id-arcam}")

    def test_falls_back_to_name_substring_when_id_absent(self):
        # id changed (e.g. new USB port) -> recover by friendly-name substring
        self.assertEqual(match_device(DEVICES, "{gone}", "ARCAM"), "{id-arcam}")

    def test_name_substring_case_insensitive(self):
        self.assertEqual(match_device(DEVICES, "", "arcam"), "{id-arcam}")

    def test_first_match_wins_for_ambiguous_substring(self):
        # both HD-speakers and S/PDIF contain "High Definition Audio Device";
        # list order decides -> the real speakers
        self.assertEqual(
            match_device(DEVICES, "{gone}", "High Definition Audio Device"),
            "{id-hd-speakers}")

    def test_no_match_returns_none(self):
        self.assertIsNone(match_device(DEVICES, "{gone}", "bluetooth"))

    def test_empty_id_and_empty_substring_is_none(self):
        # empty substring must NOT match every device
        self.assertIsNone(match_device(DEVICES, "", ""))


class TestActiveSlot(unittest.TestCase):
    def test_speaker_active(self):
        self.assertEqual(active_slot("{id-hd-speakers}", "{id-hd-speakers}", "{id-arcam}"), "speaker")

    def test_headphone_active(self):
        self.assertEqual(active_slot("{id-arcam}", "{id-hd-speakers}", "{id-arcam}"), "headphone")

    def test_other_device_active_is_none(self):
        self.assertIsNone(active_slot("{id-spdif}", "{id-hd-speakers}", "{id-arcam}"))

    def test_none_default_is_none(self):
        self.assertIsNone(active_slot(None, "{id-hd-speakers}", "{id-arcam}"))

    def test_empty_default_does_not_match_empty_config(self):
        # a blank current-default must never light an unconfigured ("") slot
        self.assertIsNone(active_slot("", "", ""))


if __name__ == "__main__":
    unittest.main()
