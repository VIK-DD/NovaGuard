"""Tests for the music search/metadata cache."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as database  # noqa: E402


class MusicCacheTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._old_path = database.DB_PATH
        self._old_initialized = database._INITIALIZED
        database.DB_PATH = Path(self._temp.name) / "test.sqlite3"
        database._INITIALIZED = False
        database.init_database()

    def tearDown(self):
        database.DB_PATH = self._old_path
        database._INITIALIZED = self._old_initialized
        self._temp.cleanup()

    def test_a_stored_payload_comes_back_unchanged(self):
        database.cache_put("yt:abc", {"title": "Song", "duration": 210}, 3600)
        self.assertEqual(database.cache_get("yt:abc"), {"title": "Song", "duration": 210})

    def test_a_missing_key_returns_none(self):
        self.assertIsNone(database.cache_get("nope"))

    def test_an_expired_entry_is_treated_as_missing(self):
        database.cache_put("yt:old", {"title": "Old"}, -1)
        self.assertIsNone(database.cache_get("yt:old"))

    def test_storing_the_same_key_twice_overwrites(self):
        database.cache_put("yt:abc", {"title": "First"}, 3600)
        database.cache_put("yt:abc", {"title": "Second"}, 3600)
        self.assertEqual(database.cache_get("yt:abc"), {"title": "Second"})

    def test_prefix_search_finds_matching_live_entries(self):
        database.cache_put("search:bohemian rhapsody", {"title": "Bohemian Rhapsody"}, 3600)
        database.cache_put("search:bohemian like you", {"title": "Bohemian Like You"}, 3600)
        database.cache_put("search:something else", {"title": "Something Else"}, 3600)
        found = database.cache_prefix_search("search:bohemian", 10)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(key.startswith("search:bohemian") for key, _ in found))

    def test_prefix_search_skips_expired_entries(self):
        database.cache_put("search:live", {"title": "Live"}, 3600)
        database.cache_put("search:dead", {"title": "Dead"}, -1)
        found = database.cache_prefix_search("search:", 10)
        self.assertEqual([key for key, _ in found], ["search:live"])

    def test_prefix_search_honours_the_limit(self):
        for index in range(10):
            database.cache_put(f"search:x{index}", {"title": str(index)}, 3600)
        self.assertEqual(len(database.cache_prefix_search("search:", 3)), 3)

    def test_a_percent_sign_in_the_prefix_is_not_a_wildcard(self):
        database.cache_put("search:100% pure", {"title": "Pure"}, 3600)
        database.cache_put("search:anything", {"title": "Anything"}, 3600)
        found = database.cache_prefix_search("search:100%", 10)
        self.assertEqual([key for key, _ in found], ["search:100% pure"])

    def test_purge_removes_only_expired_rows(self):
        database.cache_put("search:live", {"title": "Live"}, 3600)
        database.cache_put("search:dead", {"title": "Dead"}, -1)
        self.assertEqual(database.cache_purge_expired(), 1)
        self.assertIsNotNone(database.cache_get("search:live"))


if __name__ == "__main__":
    unittest.main()
