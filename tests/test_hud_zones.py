"""Unit tests for the HUD's zones plumbing: the pure config-list helpers, plus
the state/cycle/drop/resnap methods exercised on a fake Hud (no Tk)."""
import unittest
import unittest.mock as mock

import hud

MON = {"handle": 1, "device": "\\\\.\\DISPLAY2", "rect": (0, 0, 1440, 2560),
       "work": (0, 0, 1440, 2520), "primary": True}
DEV = MON["device"]


class ZoneStateFor(unittest.TestCase):
    def test_unknown_device_defaults_off(self):
        self.assertEqual(hud.zone_state_for([], DEV), ("off", 0.5))
        self.assertEqual(hud.zone_state_for(None, DEV), ("off", 0.5))

    def test_reads_entry(self):
        zones = [{"device": DEV, "layout": "h", "ratio": 0.3}]
        self.assertEqual(hud.zone_state_for(zones, DEV), ("h", 0.3))

    def test_coerces_garbage(self):
        zones = [{"device": DEV, "layout": "diagonal", "ratio": "wat"},
                 "not-a-dict"]
        self.assertEqual(hud.zone_state_for(zones, DEV), ("off", 0.5))

    def test_clamps_ratio(self):
        zones = [{"device": DEV, "layout": "v", "ratio": 0.01}]
        self.assertEqual(hud.zone_state_for(zones, DEV),
                         ("v", hud.zgeom.RATIO_MIN))


class ZonesWithState(unittest.TestCase):
    def test_creates_entry(self):
        zones = hud.zones_with_state([], DEV, layout="v")
        self.assertEqual(zones, [{"device": DEV, "layout": "v", "ratio": 0.5}])

    def test_updates_only_passed_fields(self):
        zones = [{"device": DEV, "layout": "v", "ratio": 0.3}]
        out = hud.zones_with_state(zones, DEV, ratio=0.7)
        self.assertEqual(out, [{"device": DEV, "layout": "v", "ratio": 0.7}])
        self.assertEqual(zones[0]["ratio"], 0.3)   # input list untouched

    def test_other_devices_survive(self):
        zones = [{"device": "\\\\.\\DISPLAY1", "layout": "h", "ratio": 0.4}]
        out = hud.zones_with_state(zones, DEV, layout="v")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], zones[0])

    def test_drops_non_dict_entries(self):
        out = hud.zones_with_state(["junk", 42], DEV, layout="v")
        self.assertEqual(out, [{"device": DEV, "layout": "v", "ratio": 0.5}])


class _FakeHud:
    """Carries only what the zones methods read/write; methods under test are
    called unbound (same pattern as test_hud_audio)."""

    def __init__(self, zones=None, mons=None):
        self.cfg = {"hud": {"zones": zones or []}}
        self._monitors = mons if mons is not None else [MON]
        self._zone_windows = {}
        self._zone_hover = None
        self._zone_items = []
        self._zone_hits = []
        self._recolored = 0

    # stubs for collaborators the methods call
    def _recolor_zone_glyphs(self):
        self._recolored += 1

    def _resnap_zone_windows(self, device):
        hud.Hud._resnap_zone_windows(self, device)

    def _zone_state(self, device):
        return hud.Hud._zone_state(self, device)

    def _monitor_by_device(self, device):
        return hud.Hud._monitor_by_device(self, device)

    def _set_zone_state(self, device, layout=None, ratio=None):
        return hud.Hud._set_zone_state(self, device, layout=layout, ratio=ratio)


class SetAndCycle(unittest.TestCase):
    def test_cycle_writes_config_scoped(self):
        fake = _FakeHud()
        with mock.patch.object(hud.config, "update") as upd:
            hud.Hud._cycle_zone_layout(fake, DEV)
        self.assertEqual(fake._zone_state(DEV)[0], "v")
        upd.assert_called_once()
        path, partial = upd.call_args[0]
        self.assertEqual(partial, {"hud": {"zones": fake.cfg["hud"]["zones"]}})

    def test_cycle_full_circle(self):
        fake = _FakeHud()
        with mock.patch.object(hud.config, "update"):
            for expect in ("v", "h", "off"):
                hud.Hud._cycle_zone_layout(fake, DEV)
                self.assertEqual(fake._zone_state(DEV)[0], expect)

    def test_config_write_failure_never_raises(self):
        fake = _FakeHud()
        with mock.patch.object(hud.config, "update", side_effect=OSError):
            hud.Hud._cycle_zone_layout(fake, DEV)   # must not raise
        self.assertEqual(fake._zone_state(DEV)[0], "v")


class Drop(unittest.TestCase):
    def test_drop_moves_and_records(self):
        fake = _FakeHud(zones=[{"device": DEV, "layout": "h", "ratio": 0.5}])
        with mock.patch.object(hud.monitors, "monitor_at", return_value=MON), \
             mock.patch.object(hud.window, "move_window", return_value=True) as mv:
            hud.Hud._zone_drop(fake, 777, 700, 100)   # top zone
        mv.assert_called_once_with(777, 0, 0, 1440, 1260)
        self.assertEqual(fake._zone_windows[777], (DEV, 0))

    def test_drop_with_layout_off_is_noop(self):
        fake = _FakeHud()
        with mock.patch.object(hud.monitors, "monitor_at", return_value=MON), \
             mock.patch.object(hud.window, "move_window") as mv:
            hud.Hud._zone_drop(fake, 777, 700, 100)
        mv.assert_not_called()
        self.assertEqual(fake._zone_windows, {})

    def test_failed_move_not_recorded(self):
        fake = _FakeHud(zones=[{"device": DEV, "layout": "v", "ratio": 0.5}])
        with mock.patch.object(hud.monitors, "monitor_at", return_value=MON), \
             mock.patch.object(hud.window, "move_window", return_value=False):
            hud.Hud._zone_drop(fake, 777, 100, 100)
        self.assertEqual(fake._zone_windows, {})


class Resnap(unittest.TestCase):
    def test_ratio_change_resnaps_session_windows(self):
        fake = _FakeHud(zones=[{"device": DEV, "layout": "h", "ratio": 0.5}])
        fake._zone_windows = {10: (DEV, 0), 11: (DEV, 1)}
        with mock.patch.object(hud.config, "update"), \
             mock.patch.object(hud.window, "is_window", return_value=True), \
             mock.patch.object(hud.window, "move_window", return_value=True) as mv:
            fake._set_zone_state(DEV, ratio=0.25)
        self.assertEqual(mv.call_count, 2)
        mv.assert_any_call(10, 0, 0, 1440, 630)      # top: 2520 * 0.25
        mv.assert_any_call(11, 0, 630, 1440, 2520)
        self.assertEqual(set(fake._zone_windows), {10, 11})

    def test_dead_windows_pruned(self):
        fake = _FakeHud(zones=[{"device": DEV, "layout": "v", "ratio": 0.5}])
        fake._zone_windows = {10: (DEV, 0)}
        with mock.patch.object(hud.config, "update"), \
             mock.patch.object(hud.window, "is_window", return_value=False), \
             mock.patch.object(hud.window, "move_window") as mv:
            fake._set_zone_state(DEV, ratio=0.4)
        mv.assert_not_called()
        self.assertEqual(fake._zone_windows, {})

    def test_layout_off_forgets_windows(self):
        fake = _FakeHud(zones=[{"device": DEV, "layout": "v", "ratio": 0.5}])
        fake._zone_windows = {10: (DEV, 0)}
        with mock.patch.object(hud.config, "update"), \
             mock.patch.object(hud.window, "is_window", return_value=True):
            fake._set_zone_state(DEV, layout="off")
        self.assertEqual(fake._zone_windows, {})

    def test_other_monitors_windows_untouched(self):
        other = "\\\\.\\DISPLAY9"
        fake = _FakeHud(zones=[{"device": DEV, "layout": "v", "ratio": 0.5}])
        fake._zone_windows = {10: (other, 0)}
        with mock.patch.object(hud.config, "update"), \
             mock.patch.object(hud.window, "is_window", return_value=True), \
             mock.patch.object(hud.window, "move_window") as mv:
            fake._set_zone_state(DEV, ratio=0.4)
        mv.assert_not_called()
        self.assertEqual(fake._zone_windows, {10: (other, 0)})


class AnyActive(unittest.TestCase):
    def test_off_everywhere_is_inactive(self):
        fake = _FakeHud()
        self.assertFalse(hud.Hud._any_zone_active(fake))

    def test_one_active_layout(self):
        fake = _FakeHud(zones=[{"device": DEV, "layout": "h", "ratio": 0.5}])
        self.assertTrue(hud.Hud._any_zone_active(fake))

    def test_active_config_for_absent_monitor_is_inactive(self):
        fake = _FakeHud(zones=[{"device": "\\\\.\\GONE", "layout": "h", "ratio": 0.5}])
        self.assertFalse(hud.Hud._any_zone_active(fake))


if __name__ == "__main__":
    unittest.main()
