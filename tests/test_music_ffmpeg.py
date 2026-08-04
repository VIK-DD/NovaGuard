"""Tests for the tiny FFmpeg option layer in the music cog."""

import os
import sys
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.music import Music  # noqa: E402
from core.music_queue import Track  # noqa: E402


class FfmpegOptionsTests(unittest.TestCase):
    def test_headers_are_added_before_the_input_url(self):
        music = Music(bot=None)
        track = Track(
            title="Song",
            url="https://soundcloud.com/a/song",
            duration=1,
            source="soundcloud",
            requester_id="1",
            stream_url="https://media.test/song.m3u8",
            http_headers={"User-Agent": "NovaTest", "Referer": "https://soundcloud.com/"},
        )

        options = music._ffmpeg_before_options(track)

        self.assertIn("-headers", options)
        self.assertIn("User-Agent: NovaTest", options)
        self.assertIn("Referer: https://soundcloud.com/", options)

    def test_tracks_without_headers_keep_the_base_options(self):
        music = Music(bot=None)
        track = Track(
            title="Song",
            url="https://youtube.com/watch?v=abc",
            duration=1,
            source="youtube",
            requester_id="1",
        )

        self.assertEqual(music._ffmpeg_before_options(track), music.FFMPEG_BEFORE)

    def test_soundcheck_uses_a_local_lavfi_tone(self):
        music = Music(bot=None)

        source, before_options, options = music._soundcheck_source_args()

        self.assertEqual(source, "sine=frequency=880:duration=5")
        self.assertEqual(before_options, "-f lavfi")
        self.assertEqual(options, "-vn")

    def test_long_track_ending_immediately_is_treated_as_early_end(self):
        music = Music(bot=None)
        session = SimpleNamespace(started_at=time.monotonic() - 10)
        track = Track(
            title="Song",
            url="https://youtube.com/watch?v=abc",
            duration=240,
            source="youtube",
            requester_id="1",
        )

        self.assertTrue(music._ended_too_early(session, track))

    def test_track_near_its_natural_end_is_not_retried(self):
        music = Music(bot=None)
        session = SimpleNamespace(started_at=time.monotonic() - 235)
        track = Track(
            title="Song",
            url="https://youtube.com/watch?v=abc",
            duration=240,
            source="youtube",
            requester_id="1",
        )

        self.assertFalse(music._ended_too_early(session, track))


if __name__ == "__main__":
    unittest.main()
