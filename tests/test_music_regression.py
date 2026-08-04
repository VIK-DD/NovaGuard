"""Boundary between the music player and the voice attendance reports."""

import inspect
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cogs.music as music_cog  # noqa: E402
import cogs.music_lavalink as lavalink_music_cog  # noqa: E402
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

    def test_missing_davey_is_recognised_as_a_voice_dependency_problem(self):
        error = RuntimeError("davey library needed in order to use voice")
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

    def test_lavalink_login_failures_get_an_oauth_hint(self):
        class Payload:
            exception = "All clients failed to load the item. This video requires login."

        notice = lavalink_music_cog._track_failure_notice(Payload())

        self.assertIn("OAuth", notice)
        self.assertIn("remoteCipher", notice)

    def test_lavalink_signature_failures_get_a_remote_cipher_hint(self):
        class Payload:
            exception = "Must find sig function for YouTube signature cipher."

        notice = lavalink_music_cog._track_failure_notice(Payload())

        self.assertIn("remoteCipher", notice)

    def test_lavalink_player_helpers_keep_labels_compact(self):
        self.assertEqual(lavalink_music_cog._queue_count_label(0), "empty")
        self.assertEqual(lavalink_music_cog._queue_count_label(1), "1 queued")
        self.assertEqual(lavalink_music_cog._queue_count_label(3), "3 queued")
        self.assertEqual(lavalink_music_cog._loop_label("queue"), "looping queue")
        self.assertEqual(lavalink_music_cog._volume_meter(50, slots=4), "▰▰▱▱")

    def test_lavalink_node_status_accepts_connected_name_or_text(self):
        class Status:
            name = "CONNECTED"

            def __str__(self):
                return "NodeStatus.CONNECTED"

        class Node:
            status = Status()

        self.assertTrue(lavalink_music_cog._node_is_connected(Node()))

    def test_lavalink_controls_keep_volume_buttons(self):
        source = inspect.getsource(lavalink_music_cog.LavalinkControls)

        self.assertIn("ng:lavalink:voldown", source)
        self.assertIn("ng:lavalink:volup", source)
        self.assertIn("set_volume", source)


class LavalinkSearchBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_queries_use_wavelink_source_without_double_prefix(self):
        calls = []

        class FakePlayable:
            @staticmethod
            async def search(query, source=None):
                calls.append((query, source))
                return ["track"]

        class FakeWavelink:
            Playable = FakePlayable

            class Playlist:
                pass

        with mock.patch.object(lavalink_music_cog, "wavelink", FakeWavelink):
            cog = lavalink_music_cog.LavalinkMusic(bot=mock.Mock())
            tracks = await cog._load_tracks("drake 9")

        self.assertEqual(tracks, ["track"])
        self.assertEqual(calls, [("drake 9", "ytmsearch")])

    async def test_prefixed_queries_are_passed_through_once(self):
        calls = []

        class FakePlayable:
            @staticmethod
            async def search(query, source=None):
                calls.append((query, source))
                return ["track"]

        class FakeWavelink:
            Playable = FakePlayable

            class Playlist:
                pass

        with mock.patch.object(lavalink_music_cog, "wavelink", FakeWavelink):
            cog = lavalink_music_cog.LavalinkMusic(bot=mock.Mock())
            tracks = await cog._load_tracks("ytmsearch:drake 9")

        self.assertEqual(tracks, ["track"])
        self.assertEqual(calls, [("ytmsearch:drake 9", None)])


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
