"""Boundary between the music player and the voice attendance reports."""

import inspect
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cogs.music as music_cog  # noqa: E402
import cogs.voice as voice_cog  # noqa: E402
from core.music_session import SessionRegistry, configured_max_sessions  # noqa: E402


class VoiceReportBoundaryTests(unittest.TestCase):
    def test_voice_reports_still_ignore_bots(self):
        """Music joins voice channels while attendance watches the same events."""
        source = inspect.getsource(voice_cog.VoiceReports.on_voice_state_update)
        self.assertIn("member.bot", source)


class MusicErrorMessageTests(unittest.TestCase):
    def test_missing_pynacl_is_recognised_as_a_voice_dependency_problem(self):
        error = RuntimeError("PyNaCl library needed in order to use voice")
        self.assertTrue(music_cog.is_missing_voice_backend_error(error))

    def test_spotify_playlist_without_credentials_gets_a_setup_hint(self):
        with mock.patch.dict(
            os.environ,
            {"SPOTIFY_CLIENT_ID": "", "SPOTIFY_CLIENT_SECRET": ""},
            clear=False,
        ):
            description = music_cog.nothing_found_description(
                "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
            )
        self.assertIn("SPOTIFY_CLIENT_ID", description)
        self.assertIn("Spotify Web API", description)


class SessionCapTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("MUSIC_MAX_SESSIONS", None)

    def tearDown(self):
        os.environ.pop("MUSIC_MAX_SESSIONS", None)
        if self._saved is not None:
            os.environ["MUSIC_MAX_SESSIONS"] = self._saved

    def test_the_cap_falls_back_to_the_default_when_unset(self):
        self.assertEqual(configured_max_sessions(), 3)

    def test_a_nonsense_cap_falls_back_rather_than_crashing_at_import(self):
        os.environ["MUSIC_MAX_SESSIONS"] = "banana"
        self.assertEqual(configured_max_sessions(), 3)

    def test_the_cap_is_never_below_one(self):
        os.environ["MUSIC_MAX_SESSIONS"] = "0"
        self.assertEqual(configured_max_sessions(), 1)

    def test_a_configured_cap_is_honoured(self):
        os.environ["MUSIC_MAX_SESSIONS"] = "5"
        self.assertEqual(SessionRegistry().MAX_SESSIONS, 5)


if __name__ == "__main__":
    unittest.main()
