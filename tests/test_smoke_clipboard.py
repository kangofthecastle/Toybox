import unittest

from tests.smoke import run_smoke


class TestSmokeClipboard(unittest.TestCase):
    def test_launches_and_exits_clean(self):
        rc, err = run_smoke("clipboard.pyw", 1500)
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.strip(), "")

    def test_panel_smoke_clean(self):
        rc, err = run_smoke("clipboard.pyw", 1800,
                            extra_env={"TOYBOX_SMOKE_PANEL": "1"})
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.strip(), "")


if __name__ == "__main__":
    unittest.main()
