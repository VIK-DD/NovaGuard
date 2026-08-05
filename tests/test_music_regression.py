"""Boundary between the music player and the voice attendance reports."""

import inspect
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord  # noqa: E402

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


class LavalinkQueueTests(unittest.TestCase):
    def test_a_track_queued_after_the_queue_ran_dry_still_plays(self):
        # Regression for the player going silent after the last track: the
        # cursor parked past the end, so a newly queued track landed under it
        # and the next advance skipped it. /disconnect was the only way out.
        queue = lavalink_music_cog.LavalinkQueue()
        queue.add_many(["a"])
        queue.advance()
        self.assertIsNone(queue.advance())
        self.assertIsNone(queue.current)

        queue.add_many(["b"])

        self.assertEqual(queue.upcoming, ["b"])
        self.assertEqual(queue.advance(), "b")
        self.assertEqual(queue.current, "b")

    def test_a_finished_queue_has_no_current_track_or_leftovers(self):
        queue = lavalink_music_cog.LavalinkQueue()
        queue.add_many(["a", "b"])
        queue.advance()
        queue.advance()
        self.assertIsNone(queue.advance())

        self.assertIsNone(queue.current)
        self.assertEqual(queue.upcoming, [])

    def test_loop_modes_still_repeat_after_the_fix(self):
        queue = lavalink_music_cog.LavalinkQueue()
        queue.add_many(["a", "b"])
        queue.loop = "queue"

        self.assertEqual(queue.advance(), "a")
        self.assertEqual(queue.advance(), "b")
        self.assertEqual(queue.advance(), "a")

    def test_the_cap_counts_waiting_tracks_not_played_history(self):
        queue = lavalink_music_cog.LavalinkQueue()
        queue.add_many([str(index) for index in range(lavalink_music_cog.MAX_QUEUE_LENGTH)])
        for _ in range(10):
            queue.advance()

        self.assertEqual(queue.add_many(["late"]), 1)


class LavalinkTrackEndGatingTests(unittest.TestCase):
    def test_a_failed_track_does_not_advance_twice(self):
        # Lavalink reports a failure as an exception AND an end event. Acting
        # on both ate the following song - the "sometimes it skips" symptom.
        self.assertFalse(lavalink_music_cog._should_advance_on_end("loadfailed"))
        self.assertFalse(lavalink_music_cog._should_advance_on_end("replaced"))
        self.assertFalse(lavalink_music_cog._should_advance_on_end("cleanup"))

    def test_natural_ends_and_skips_still_advance(self):
        self.assertTrue(lavalink_music_cog._should_advance_on_end("finished"))
        self.assertTrue(lavalink_music_cog._should_advance_on_end("stopped"))

    def test_an_unknown_reason_still_advances(self):
        self.assertTrue(lavalink_music_cog._should_advance_on_end(""))

    def test_end_reasons_are_normalised_from_enums_and_case(self):
        class Reason:
            value = "LoadFailed"

        class Payload:
            reason = Reason()

        self.assertEqual(lavalink_music_cog._end_reason(Payload()), "loadfailed")

    def test_tracks_are_matched_by_identifier_not_object_identity(self):
        class Track:
            def __init__(self, identifier):
                self.identifier = identifier

        self.assertTrue(lavalink_music_cog._same_track(Track("abc"), Track("abc")))
        self.assertFalse(lavalink_music_cog._same_track(Track("abc"), Track("xyz")))
        self.assertFalse(lavalink_music_cog._same_track(None, Track("abc")))


class LavalinkCommandSurfaceTests(unittest.TestCase):
    def _command_names(self):
        return {command.name for command in lavalink_music_cog.LavalinkMusic.__cog_app_commands__}

    def test_the_lavalink_backend_matches_the_ytdlp_command_surface(self):
        # Switching MUSIC_BACKEND should not quietly remove commands people
        # already use.
        ytdlp = {command.name for command in music_cog.Music.__cog_app_commands__}

        self.assertEqual(ytdlp - self._command_names(), set())

    def test_the_new_playback_commands_exist(self):
        self.assertLessEqual(
            {"shuffle", "loop", "seek", "filter", "soundcheck"}, self._command_names()
        )


class LavalinkFooterTests(unittest.TestCase):
    def test_the_music_footer_carries_the_brand_only(self):
        embed = discord.Embed()

        lavalink_music_cog._music_footer(embed)

        self.assertNotIn("Lavalink ready", embed.footer.text or "")
        self.assertNotIn(lavalink_music_cog.MUSIC_LABEL, embed.footer.text or "")


class LavalinkPlaybackRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def _cog_with_session(self):
        class FakePlayer:
            connected = True

            def __init__(self):
                self.played = []

            async def play(self, track, volume=100):
                self.played.append(track)

        cog = lavalink_music_cog.LavalinkMusic(bot=mock.Mock())
        session = lavalink_music_cog.LavalinkSession("1")
        session.player = FakePlayer()
        cog.sessions["1"] = session
        return cog, session

    async def test_playback_resumes_after_the_queue_ran_dry(self):
        # The reported failure end to end: last track finishes, the queue is
        # empty, then someone runs /play again. Before the fix nothing played
        # until /disconnect threw the session away.
        cog, session = self._cog_with_session()

        with mock.patch.object(cog, "_announce_track", new=mock.AsyncMock()), mock.patch.object(
            cog, "refresh_card", new=mock.AsyncMock()
        ):
            session.queue.add_many(["a"])
            self.assertTrue(await cog._play_next(session))
            self.assertFalse(await cog._play_next(session))

            session.queue.add_many(["b"])
            self.assertTrue(await cog._play_next(session))

        self.assertEqual(session.player.played, ["a", "b"])

    async def test_a_run_of_failing_tracks_stops_instead_of_recursing(self):
        cog, session = self._cog_with_session()

        async def always_fail(track, volume=100):
            raise RuntimeError("node refused the track")

        session.player.play = always_fail
        session.queue.add_many([str(index) for index in range(20)])

        with mock.patch.object(cog, "_announce_track", new=mock.AsyncMock()), mock.patch.object(
            cog, "refresh_card", new=mock.AsyncMock()
        ), mock.patch.object(cog, "_notify", new=mock.AsyncMock()) as notify:
            self.assertFalse(await cog._play_next(session))

        self.assertIn(
            "Too many tracks in a row failed",
            " ".join(str(call) for call in notify.call_args_list),
        )


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
