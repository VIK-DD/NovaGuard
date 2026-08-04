"""Tests for the tiny FFmpeg option layer in the music cog."""

import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
