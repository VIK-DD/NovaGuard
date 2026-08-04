"""Tests for converting yt-dlp entries into Track objects."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.music_sources as music_sources  # noqa: E402
from core.music_sources import track_from_entry  # noqa: E402


class TrackFromEntryTests(unittest.TestCase):
    def test_a_full_entry_maps_every_field(self):
        track = track_from_entry(
            {
                "title": "Bohemian Rhapsody",
                "webpage_url": "https://youtu.be/fJ9rUzIMcZQ",
                "duration": 355,
                "thumbnail": "https://img.test/x.jpg",
                "uploader": "Queen Official",
                "url": "https://stream.test/audio",
            },
            requester_id="42",
            source="youtube",
        )
        self.assertEqual(track.title, "Bohemian Rhapsody")
        self.assertEqual(track.url, "https://youtu.be/fJ9rUzIMcZQ")
        self.assertEqual(track.duration, 355)
        self.assertEqual(track.uploader, "Queen Official")
        self.assertEqual(track.requester_id, "42")
        self.assertEqual(track.source, "youtube")
        self.assertEqual(track.stream_url, "https://stream.test/audio")

    def test_missing_optional_fields_do_not_raise(self):
        track = track_from_entry({"title": "Bare"}, requester_id="1", source="soundcloud")
        self.assertEqual(track.title, "Bare")
        self.assertEqual(track.duration, 0)
        self.assertIsNone(track.thumbnail)
        self.assertIsNone(track.uploader)

    def test_an_entirely_empty_entry_gets_a_readable_placeholder(self):
        track = track_from_entry({}, requester_id="1", source="youtube")
        self.assertEqual(track.title, "Unknown track")

    def test_a_none_entry_does_not_raise(self):
        track = track_from_entry(None, requester_id="1", source="youtube")
        self.assertEqual(track.title, "Unknown track")

    def test_a_null_duration_becomes_zero_rather_than_none(self):
        track = track_from_entry(
            {"title": "Live", "duration": None}, requester_id="1", source="youtube"
        )
        self.assertEqual(track.duration, 0)

    def test_the_page_url_is_preferred_over_the_expiring_stream_url(self):
        track = track_from_entry(
            {"title": "T", "webpage_url": "https://page.test/t", "url": "https://cdn.test/expiring"},
            requester_id="1",
            source="youtube",
        )
        self.assertEqual(track.url, "https://page.test/t")
        self.assertEqual(track.stream_url, "https://cdn.test/expiring")

    def test_the_requester_id_is_always_stored_as_a_string(self):
        track = track_from_entry({"title": "T"}, requester_id=42, source="youtube")
        self.assertEqual(track.requester_id, "42")

    def test_flat_youtube_result_builds_a_page_url_not_a_stream_url(self):
        track = track_from_entry(
            {"_type": "url", "id": "f6sRk58Pj6I", "url": "f6sRk58Pj6I", "title": "Flat"},
            requester_id="1",
            source="youtube",
        )
        self.assertEqual(track.url, "https://www.youtube.com/watch?v=f6sRk58Pj6I")
        self.assertIsNone(track.stream_url)

    def test_flat_url_result_is_not_treated_as_a_direct_stream(self):
        track = track_from_entry(
            {
                "_type": "url",
                "title": "Flat SoundCloud",
                "webpage_url": "https://soundcloud.com/a/b",
                "url": "https://soundcloud.com/a/b",
            },
            requester_id="1",
            source="soundcloud",
        )
        self.assertEqual(track.url, "https://soundcloud.com/a/b")
        self.assertIsNone(track.stream_url)


class SearchFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_falls_back_to_soundcloud_when_youtube_has_no_entries(self):
        calls = []

        async def fake_extract(target, *, flat=False):
            calls.append(target)
            if target.startswith("ytsearch1:"):
                return {"entries": []}
            if target.startswith("scsearch1:"):
                return {
                    "entries": [
                        {
                            "title": "Fallback Song",
                            "webpage_url": "https://soundcloud.com/artist/fallback-song",
                            "duration": 123,
                            "url": "https://stream.test/fallback",
                        }
                    ]
                }
            return None

        with mock.patch.object(music_sources.log, "warning"), mock.patch.object(
            music_sources, "cache_get", return_value=None
        ), mock.patch.object(music_sources, "cache_put") as cache_put, mock.patch.object(
            music_sources, "_extract", side_effect=fake_extract
        ):
            tracks = await music_sources._extract_by_search("search", None, "fallback song", "42")

        self.assertEqual(calls, ["ytsearch1:fallback song", "scsearch1:fallback song"])
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].source, "soundcloud")
        self.assertEqual(tracks[0].title, "Fallback Song")
        cache_put.assert_called_once()
        self.assertEqual(cache_put.call_args.args[1]["_source"], "soundcloud")

    async def test_search_respects_disabled_soundcloud_fallback(self):
        calls = []

        async def fake_extract(target, *, flat=False):
            calls.append(target)
            return {"entries": []}

        with mock.patch.dict(os.environ, {"MUSIC_ENABLE_SOUNDCLOUD_FALLBACK": "false"}), mock.patch.object(
            music_sources.log, "warning"
        ), mock.patch.object(music_sources, "cache_get", return_value=None), mock.patch.object(
            music_sources, "_extract", side_effect=fake_extract
        ):
            tracks = await music_sources._extract_by_search("search", None, "fallback song", "42")

        self.assertEqual(calls, ["ytsearch1:fallback song"])
        self.assertEqual(tracks, [])

    async def test_search_uses_flat_extraction_before_playback(self):
        flat_values = []

        async def fake_extract(target, *, flat=False):
            flat_values.append(flat)
            return {
                "entries": [
                    {
                        "_type": "url",
                        "id": "f6sRk58Pj6I",
                        "url": "f6sRk58Pj6I",
                        "title": "Found Song",
                    }
                ]
            }

        with mock.patch.object(music_sources, "cache_get", return_value=None), mock.patch.object(
            music_sources, "cache_put"
        ), mock.patch.object(music_sources, "_extract", side_effect=fake_extract):
            tracks = await music_sources._extract_by_search("search", None, "found song", "42")

        self.assertEqual(flat_values, [True])
        self.assertEqual(tracks[0].url, "https://www.youtube.com/watch?v=f6sRk58Pj6I")
        self.assertIsNone(tracks[0].stream_url)

    async def test_soundcloud_rescue_uses_only_soundcloud_search(self):
        track = track_from_entry(
            {"title": "Broken YouTube", "webpage_url": "https://youtube.test/watch?v=abc"},
            requester_id="42",
            source="youtube",
        )

        async def fake_extract(target, *, flat=False):
            self.assertEqual(target, "scsearch1:Broken YouTube")
            self.assertTrue(flat)
            return {
                "entries": [
                    {
                        "_type": "url",
                        "title": "Broken YouTube",
                        "webpage_url": "https://soundcloud.com/a/broken-youtube",
                    }
                ]
            }

        with mock.patch.object(music_sources, "_extract", side_effect=fake_extract):
            fallback = await music_sources.soundcloud_fallback_for(track)

        self.assertEqual(fallback.source, "soundcloud")
        self.assertEqual(fallback.url, "https://soundcloud.com/a/broken-youtube")


if __name__ == "__main__":
    unittest.main()
