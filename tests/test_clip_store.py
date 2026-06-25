import json
import os
import shutil
import tempfile
import unittest

from clip_store import ClipStore


class TestClipStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fav = os.path.join(self.dir, "favorites.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def store(self, max_recent=30):
        return ClipStore(max_recent=max_recent, favorites_path=self.fav)

    def texts(self, entries):
        return [e["text"] for e in entries]

    # --- recent / add ----------------------------------------------------
    def test_add_then_recent(self):
        s = self.store()
        self.assertTrue(s.add("a", 1.0))
        self.assertEqual(self.texts(s.recent()), ["a"])
        self.assertEqual(s.recent()[0]["time"], 1.0)

    def test_whitespace_ignored(self):
        s = self.store()
        self.assertFalse(s.add("   ", 1.0))
        self.assertFalse(s.add("", 1.0))
        self.assertEqual(s.recent(), [])

    def test_newest_first(self):
        s = self.store()
        s.add("a", 1.0)
        s.add("b", 2.0)
        self.assertEqual(self.texts(s.recent()), ["b", "a"])

    def test_duplicate_recent_moves_to_front_and_refreshes_time(self):
        s = self.store()
        s.add("a", 1.0)
        s.add("b", 2.0)
        s.add("a", 3.0)
        self.assertEqual(self.texts(s.recent()), ["a", "b"])
        self.assertEqual(s.recent()[0]["time"], 3.0)

    def test_cap_evicts_oldest(self):
        s = self.store(max_recent=2)
        s.add("a", 1.0)
        s.add("b", 2.0)
        s.add("c", 3.0)
        self.assertEqual(self.texts(s.recent()), ["c", "b"])

    def test_recent_returns_copies(self):
        s = self.store()
        s.add("a", 1.0)
        got = s.recent()
        got.append({"text": "x", "time": 0})
        got[0]["text"] = "tampered"
        self.assertEqual(self.texts(s.recent()), ["a"])

    # --- favorite / unfavorite ------------------------------------------
    def test_favorite_moves_from_recent(self):
        s = self.store()
        s.add("a", 1.0)
        s.add("b", 2.0)
        s.favorite("a")
        self.assertEqual(self.texts(s.recent()), ["b"])
        self.assertEqual(self.texts(s.favorites()), ["a"])

    def test_favorite_unknown_is_noop(self):
        s = self.store()
        s.add("a", 1.0)
        s.favorite("zzz")
        self.assertEqual(self.texts(s.recent()), ["a"])
        self.assertEqual(s.favorites(), [])

    def test_favorites_newest_first(self):
        s = self.store()
        s.add("a", 1.0)
        s.add("b", 2.0)
        s.favorite("a")
        s.favorite("b")
        self.assertEqual(self.texts(s.favorites()), ["b", "a"])

    def test_unfavorite_returns_to_top_of_recent(self):
        s = self.store()
        s.add("a", 1.0)
        s.add("b", 2.0)   # recent: b, a
        s.favorite("a")   # recent: b ; fav: a
        s.unfavorite("a")
        self.assertEqual(self.texts(s.recent()), ["a", "b"])
        self.assertEqual(s.favorites(), [])

    def test_add_matching_favorite_is_ignored(self):
        s = self.store()
        s.add("a", 1.0)
        s.favorite("a")
        self.assertFalse(s.add("a", 5.0))
        self.assertEqual(s.recent(), [])
        self.assertEqual(self.texts(s.favorites()), ["a"])

    # --- delete / clear --------------------------------------------------
    def test_delete_from_recent(self):
        s = self.store()
        s.add("a", 1.0)
        s.add("b", 2.0)
        s.delete("a")
        self.assertEqual(self.texts(s.recent()), ["b"])

    def test_delete_from_favorites(self):
        s = self.store()
        s.add("a", 1.0)
        s.favorite("a")
        s.delete("a")
        self.assertEqual(s.favorites(), [])

    def test_delete_many_from_recent(self):
        s = self.store()
        for t, n in (("a", 1.0), ("b", 2.0), ("c", 3.0)):
            s.add(t, n)
        s.delete_many(["a", "c"])
        self.assertEqual(self.texts(s.recent()), ["b"])

    def test_clear_recent_keeps_favorites(self):
        s = self.store()
        s.add("a", 1.0)
        s.add("b", 2.0)
        s.favorite("a")
        s.clear_recent()
        self.assertEqual(s.recent(), [])
        self.assertEqual(self.texts(s.favorites()), ["a"])

    # --- persistence -----------------------------------------------------
    def test_favorites_persist_across_instances(self):
        s = self.store()
        s.add("a", 1.0)
        s.favorite("a")
        s2 = self.store()
        self.assertEqual(self.texts(s2.favorites()), ["a"])

    def test_recent_does_not_persist(self):
        s = self.store()
        s.add("secret", 1.0)
        s2 = self.store()
        self.assertEqual(s2.recent(), [])

    def test_corrupt_favorites_file_yields_empty(self):
        with open(self.fav, "w", encoding="utf-8") as f:
            f.write("{ not valid json ")
        s = self.store()
        self.assertEqual(s.favorites(), [])

    def test_missing_favorites_file_yields_empty(self):
        s = self.store()
        self.assertEqual(s.favorites(), [])


if __name__ == "__main__":
    unittest.main()
