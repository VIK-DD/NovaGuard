"""Tests for the optional Lavalink music backend config."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.lavalink_config import (  # noqa: E402
    lavalink_enabled,
    lavalink_password,
    lavalink_search_query,
    lavalink_search_source,
    lavalink_uri,
)


class LavalinkConfigTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            name: os.environ.pop(name, None)
            for name in (
                "MUSIC_BACKEND",
                "LAVALINK_URI",
                "LAVALINK_PASSWORD",
                "MUSIC_LAVALINK_SEARCH_SOURCE",
            )
        }

    def tearDown(self):
        for name in self._saved:
            os.environ.pop(name, None)
        for name, value in self._saved.items():
            if value is not None:
                os.environ[name] = value

    def test_backend_is_disabled_by_default(self):
        self.assertFalse(lavalink_enabled())

    def test_lavalink_aliases_enable_backend(self):
        for value in ("lavalink", "lava", "ll"):
            os.environ["MUSIC_BACKEND"] = value
            self.assertTrue(lavalink_enabled())

    def test_node_defaults_to_localhost(self):
        self.assertEqual(lavalink_uri(), "http://127.0.0.1:2333")
        self.assertEqual(lavalink_password(), "youshallnotpass")

    def test_node_settings_are_read_from_env(self):
        os.environ["LAVALINK_URI"] = "http://10.0.0.5:2333"
        os.environ["LAVALINK_PASSWORD"] = "secret"

        self.assertEqual(lavalink_uri(), "http://10.0.0.5:2333")
        self.assertEqual(lavalink_password(), "secret")

    def test_plain_search_uses_youtube_music_by_default(self):
        self.assertEqual(lavalink_search_source(), "ytmsearch")
        self.assertEqual(lavalink_search_query("drake 9"), "ytmsearch:drake 9")

    def test_custom_search_source_is_normalized(self):
        os.environ["MUSIC_LAVALINK_SEARCH_SOURCE"] = "ytsearch:"

        self.assertEqual(lavalink_search_query("drake 9"), "ytsearch:drake 9")

    def test_urls_are_not_prefixed_as_searches(self):
        self.assertEqual(
            lavalink_search_query(" <https://www.youtube.com/watch?v=sQ4Y9IkAgoQ> "),
            "https://www.youtube.com/watch?v=sQ4Y9IkAgoQ",
        )


if __name__ == "__main__":
    unittest.main()
