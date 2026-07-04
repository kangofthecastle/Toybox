import unittest
import unittest.mock as mock

import hud


class _FakeHud:
    """Minimal stand-in carrying only what _resolve_audio reads/writes, so the
    method can be exercised as an unbound function without building a real Tk Hud."""
    def __init__(self, cfg):
        self.cfg = cfg


def _cfg(speaker, headphone):
    return {"hud": {"audio": {"speaker": speaker, "headphone": headphone}}}


class TestResolveAudio(unittest.TestCase):
    def test_unconfigured_skips_com_and_disables(self):
        fake = _FakeHud(_cfg({"id": "", "name": ""}, {"id": "", "name": ""}))
        with mock.patch.object(hud.audio, "list_render_devices") as lst:
            hud.Hud._resolve_audio(fake)
        lst.assert_not_called()                       # no COM enumeration when nothing configured
        self.assertFalse(fake._audio_on)
        self.assertIsNone(fake._spk_id)
        self.assertIsNone(fake._hp_id)

    def test_missing_audio_section_disables(self):
        fake = _FakeHud({"hud": {}})
        with mock.patch.object(hud.audio, "list_render_devices") as lst:
            hud.Hud._resolve_audio(fake)
        lst.assert_not_called()
        self.assertFalse(fake._audio_on)

    def test_both_resolve_enables(self):
        devs = [("SPK", "Speakers (High Definition Audio Device)"),
                ("ARC", "Speakers (ARCAM USB Audio 1.0)")]
        fake = _FakeHud(_cfg({"id": "SPK", "name": "High Definition"},
                             {"id": "ARC", "name": "ARCAM"}))
        with mock.patch.object(hud.audio, "list_render_devices", return_value=devs):
            hud.Hud._resolve_audio(fake)
        self.assertTrue(fake._audio_on)
        self.assertEqual(fake._spk_id, "SPK")
        self.assertEqual(fake._hp_id, "ARC")

    def test_only_one_resolves_disables(self):
        devs = [("SPK", "Speakers (High Definition Audio Device)")]   # ARCAM absent
        fake = _FakeHud(_cfg({"id": "SPK", "name": "High Definition"},
                             {"id": "ARC", "name": "ARCAM"}))
        with mock.patch.object(hud.audio, "list_render_devices", return_value=devs):
            hud.Hud._resolve_audio(fake)
        self.assertFalse(fake._audio_on)              # feature needs BOTH devices
        self.assertEqual(fake._spk_id, "SPK")
        self.assertIsNone(fake._hp_id)

    def test_name_fallback_when_ids_are_stale(self):
        devs = [("SPK-NEW", "Speakers (High Definition Audio Device)"),
                ("ARC-NEW", "Speakers (ARCAM USB Audio 1.0)")]
        fake = _FakeHud(_cfg({"id": "OLD", "name": "High Definition Audio Device"},
                             {"id": "OLD2", "name": "ARCAM"}))
        with mock.patch.object(hud.audio, "list_render_devices", return_value=devs):
            hud.Hud._resolve_audio(fake)
        self.assertTrue(fake._audio_on)               # recovered via name substring
        self.assertEqual(fake._spk_id, "SPK-NEW")
        self.assertEqual(fake._hp_id, "ARC-NEW")


if __name__ == "__main__":
    unittest.main()
