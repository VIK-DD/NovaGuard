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
                "http_headers": {"User-Agent": "NovaTest", "Referer": "https://soundcloud.com/"},
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
        self.assertEqual(
            track.http_headers,
            {"User-Agent": "NovaTest", "Referer": "https://soundcloud.com/"},
        )

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

    def test_http_headers_are_sanitized_before_ffmpeg(self):
        track = track_from_entry(
            {
                "title": "Headers",
                "url": "https://stream.test/audio",
                "http_headers": {
                    "User-Agent": "NovaTest",
                    "Accept-Encoding": "gzip",
                    "Bad\nHeader": "x",
                    "Referer": "https://soundcloud.com/\r\nInjected: no",
                    "Empty": "",
                },
            },
            requester_id="1",
            source="soundcloud",
        )
        self.assertEqual(track.http_headers, {"User-Agent": "NovaTest"})


class SearchFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_falls_back_to_soundcloud_when_youtube_has_no_entries(self):
        calls = []

        async def fake_extract(target, *, flat=False, include_cookies=True):
            calls.append((target, flat, include_cookies))
            if target.startswith("ytsearch"):
                return {"entries": []}
            if target.startswith("scsearch"):
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

        with mock.patch.dict(os.environ, {"MUSIC_ENABLE_SOUNDCLOUD_FALLBACK": "true"}), mock.patch.object(
            music_sources.log, "warning"
        ), mock.patch.object(
            music_sources, "cache_get", return_value=None
        ), mock.patch.object(music_sources, "cache_put") as cache_put, mock.patch.object(
            music_sources, "_extract", side_effect=fake_extract
        ):
            tracks = await music_sources._extract_by_search("search", None, "fallback song", "42")

        self.assertEqual(
            calls,
            [
                ("ytsearch8:fallback song", True, False),
                ("scsearch5:fallback song", True, False),
            ],
        )
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].source, "soundcloud")
        self.assertEqual(tracks[0].title, "Fallback Song")
        cache_put.assert_called_once()
        self.assertEqual(cache_put.call_args.args[1]["_source"], "soundcloud")

    async def test_search_respects_disabled_soundcloud_fallback(self):
        calls = []

        async def fake_extract(target, *, flat=False, include_cookies=True):
            calls.append((target, flat, include_cookies))
            return {"entries": []}

        with mock.patch.dict(os.environ, {"MUSIC_ENABLE_SOUNDCLOUD_FALLBACK": "false"}), mock.patch.object(
            music_sources.log, "warning"
        ), mock.patch.object(music_sources, "cache_get", return_value=None), mock.patch.object(
            music_sources, "_extract", side_effect=fake_extract
        ):
            tracks = await music_sources._extract_by_search("search", None, "fallback song", "42")

        self.assertEqual(calls, [("ytsearch8:fallback song", True, False)])
        self.assertEqual(tracks, [])

    async def test_search_uses_flat_extraction_before_playback(self):
        calls = []

        async def fake_extract(target, *, flat=False, include_cookies=True):
            calls.append((target, flat, include_cookies))
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

        self.assertEqual(calls[0], ("ytsearch8:found song", True, False))
        self.assertEqual(tracks[0].url, "https://www.youtube.com/watch?v=f6sRk58Pj6I")
        self.assertIsNone(tracks[0].stream_url)

    async def test_search_chooses_best_scored_youtube_result(self):
        async def fake_extract(target, *, flat=False, include_cookies=True):
            self.assertEqual(target, "ytsearch8:toate pozele cu tine nicolae guta")
            self.assertTrue(flat)
            self.assertFalse(include_cookies)
            return {
                "entries": [
                    {
                        "_type": "url",
                        "title": "Toate pozele cu tine karaoke",
                        "id": "aaaaaaaaaaa",
                        "url": "aaaaaaaaaaa",
                        "duration": 200,
                    },
                    {
                        "_type": "url",
                        "title": "Nicolae Guta - Toate pozele cu tine",
                        "id": "bbbbbbbbbbb",
                        "url": "bbbbbbbbbbb",
                        "duration": 230,
                        "view_count": 2_000_000,
                    },
                ]
            }

        with mock.patch.object(music_sources, "cache_get", return_value=None), mock.patch.object(
            music_sources, "cache_put"
        ), mock.patch.object(music_sources, "soundcloud_fallback_enabled", return_value=False), mock.patch.object(
            music_sources, "_extract", side_effect=fake_extract
        ):
            tracks = await music_sources._extract_by_search(
                "search", None, "toate pozele cu tine nicolae guta", "42"
            )

        self.assertEqual(tracks[0].title, "Nicolae Guta - Toate pozele cu tine")
        self.assertEqual(tracks[0].url, "https://www.youtube.com/watch?v=bbbbbbbbbbb")

    async def test_soundcloud_rescue_uses_only_soundcloud_search(self):
        track = track_from_entry(
            {"title": "Broken YouTube", "webpage_url": "https://youtube.test/watch?v=abc"},
            requester_id="42",
            source="youtube",
        )

        async def fake_extract(target, *, flat=False, include_cookies=True):
            self.assertEqual(target, "scsearch5:Broken YouTube")
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

        with mock.patch.dict(os.environ, {"MUSIC_ENABLE_SOUNDCLOUD_FALLBACK": "true"}), mock.patch.object(
            music_sources, "_extract", side_effect=fake_extract
        ):
            fallback = await music_sources.soundcloud_fallback_for(track)

        self.assertEqual(fallback.source, "soundcloud")
        self.assertEqual(fallback.url, "https://soundcloud.com/a/broken-youtube")

    async def test_youtube_direct_link_retries_without_cookies(self):
        calls = []

        async def fake_extract(target, *, flat=False, include_cookies=True):
            calls.append((target, include_cookies))
            if include_cookies:
                return None
            return {
                "title": "Recovered",
                "webpage_url": "https://www.youtube.com/watch?v=f6sRk58Pj6I",
                "url": "https://stream.test/audio",
            }

        with mock.patch.object(music_sources.log, "warning"), mock.patch.object(
            music_sources, "_extract", side_effect=fake_extract
        ):
            tracks = await music_sources.extract("https://youtu.be/f6sRk58Pj6I", "42")

        self.assertEqual(
            calls,
            [
                ("https://youtu.be/f6sRk58Pj6I", True),
                ("https://youtu.be/f6sRk58Pj6I", False),
            ],
        )
        self.assertEqual(tracks[0].title, "Recovered")

    async def test_youtube_stream_refresh_retries_without_cookies(self):
        calls = []
        track = track_from_entry(
            {"title": "Recovered", "webpage_url": "https://www.youtube.com/watch?v=f6sRk58Pj6I"},
            requester_id="42",
            source="youtube",
        )

        async def fake_extract(target, *, flat=False, include_cookies=True):
            calls.append((target, include_cookies))
            if include_cookies:
                return None
            return {
                "title": "Recovered",
                "webpage_url": target,
                "url": "https://stream.test/audio",
            }

        with mock.patch.object(music_sources.log, "warning"), mock.patch.object(
            music_sources, "_extract", side_effect=fake_extract
        ):
            ok = await music_sources.refresh_stream_url(track)

        self.assertTrue(ok)
        self.assertEqual(
            calls,
            [
                ("https://www.youtube.com/watch?v=f6sRk58Pj6I", True),
                ("https://www.youtube.com/watch?v=f6sRk58Pj6I", False),
            ],
        )
        self.assertEqual(track.stream_url, "https://stream.test/audio")


if __name__ == "__main__":
    unittest.main()
