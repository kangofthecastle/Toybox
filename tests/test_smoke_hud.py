import unittest
from tests.smoke import run_smoke


class TestSmokeHud(unittest.TestCase):
    def test_launches_and_exits_clean(self):
        rc, err = run_smoke("hud.pyw", 1500)
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.strip(), "")


if __name__ == "__main__":
    unittest.main()
