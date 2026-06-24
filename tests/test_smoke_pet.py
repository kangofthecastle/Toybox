import unittest
from tests.smoke import run_smoke


class TestSmokePet(unittest.TestCase):
    def test_launches_and_exits_clean(self):
        rc, err = run_smoke("pet.pyw", 1500)
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.strip(), "")


if __name__ == "__main__":
    unittest.main()
