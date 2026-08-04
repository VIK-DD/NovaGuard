"""Tests for how user input is classified and normalised before extraction."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_sources import (  # noqa: E402
    classify_input,
    format_duration,
    normalise_query,
    search_cache_key,
    spotify_credentials_configured,
    spotify_to_query,
    stream_cache_key,
    search_providers,
    soundcloud_fallback_enabled,
    ydl_runtime_options,
)


class ClassifyInputTests(unittest.TestCase):
    def test_plain_words_are_a_search(self):
        kind, platform, identifier = classify_input("bohemian rhapsody queen")
        self.assertEqual(kind, "search")
        self.assertIsNone(platform)
        self.assertEqual(identifier, "bohemian rhapsody queen")

    def test_youtube_watch_url_is_a_track(self):
        kind, platform, _ = classify_input("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual((kind, platform), ("track", "youtube"))

    def test_youtube_short_url_is_a_track(self):
        kind, platform, _ = classify_input("https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual((kind, platform), ("track", "youtube"))

    def test_youtube_list_url_is_a_playlist(self):
        kind, platform, _ = classify_input("https://www.youtube.com/playlist?list=PL123")
        self.assertEqual((kind, platform), ("playlist", "youtube"))

    def test_a_watch_url_carrying_a_list_still_plays_the_single_video(self):
        kind, platform, _ = classify_input("https://www.youtube.com/watch?v=abc&list=PL123")
        self.assertEqual((kind, platform), ("track", "youtube"))

    def test_soundcloud_url_is_a_track(self):
        kind, platform, _ = classify_input("https://soundcloud.com/artist/some-song")
        self.assertEqual((kind, platform), ("track", "soundcloud"))

    def test_soundcloud_sets_url_is_a_playlist(self):
        kind, platform, _ = classify_input("https://soundcloud.com/artist/sets/my-mix")
        self.assertEqual((kind, platform), ("playlist", "soundcloud"))

    def test_spotify_track_url_is_recognised_with_its_id(self):
        kind, platform, identifier = classify_input(
            "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
        )
        self.assertEqual((kind, platform), ("track", "spotify"))
        self.assertEqual(identifier, "4cOdK2wGLETKBW3PvgPWqT")

    def test_spotify_playlist_and_album_are_playlists(self):
        for path in ("playlist", "album"):
            kind, platform, _ = classify_input(f"https://open.spotify.com/{path}/abc123")
            self.assertEqual((kind, platform), ("playlist", "spotify"))

    def test_a_localised_spotify_link_still_parses(self):
        kind, platform, identifier = classify_input("https://open.spotify.com/intl-ro/track/abc123")
        self.assertEqual((kind, platform), ("track", "spotify"))
        self.assertEqual(identifier, "abc123")

    def test_query_string_after_a_spotify_link_is_ignored(self):
        _, _, identifier = classify_input("https://open.spotify.com/track/abc123?si=xyz")
        self.assertEqual(identifier, "abc123")

    def test_an_unknown_url_falls_back_to_search(self):
        kind, platform, _ = classify_input("https://example.com/whatever")
        self.assertEqual((kind, platform), ("search", None))

    def test_surrounding_whitespace_and_angle_brackets_are_stripped(self):
        kind, platform, _ = classify_input("  <https://youtu.be/dQw4w9WgXcQ>  ")
        self.assertEqual((kind, platform), ("track", "youtube"))

    def test_empty_input_is_an_empty_search(self):
        self.assertEqual(classify_input(""), ("search", None, ""))
        self.assertEqual(classify_input(None), ("search", None, ""))


class SpotifyQueryTests(unittest.TestCase):
    def test_artist_and_title_are_combined(self):
        self.assertEqual(
            spotify_to_query({"title": "Bohemian Rhapsody", "artist": "Queen"}),
            "Queen - Bohemian Rhapsody",
        )

    def test_a_missing_artist_leaves_just_the_title(self):
        self.assertEqual(spotify_to_query({"title": "Untitled"}), "Untitled")

    def test_empty_metadata_yields_an_empty_string(self):
        self.assertEqual(spotify_to_query({}), "")

    def test_spotify_credentials_require_both_values(self):
        saved_id = os.environ.pop("SPOTIFY_CLIENT_ID", None)
        saved_secret = os.environ.pop("SPOTIFY_CLIENT_SECRET", None)
        try:
            self.assertFalse(spotify_credentials_configured())
            os.environ["SPOTIFY_CLIENT_ID"] = "client"
            self.assertFalse(spotify_credentials_configured())
            os.environ["SPOTIFY_CLIENT_SECRET"] = "secret"
            self.assertTrue(spotify_credentials_configured())
        finally:
            os.environ.pop("SPOTIFY_CLIENT_ID", None)
            os.environ.pop("SPOTIFY_CLIENT_SECRET", None)
            if saved_id is not None:
                os.environ["SPOTIFY_CLIENT_ID"] = saved_id
            if saved_secret is not None:
                os.environ["SPOTIFY_CLIENT_SECRET"] = saved_secret


class FormattingTests(unittest.TestCase):
    def test_durations_under_an_hour_are_minutes_and_seconds(self):
        self.assertEqual(format_duration(65), "1:05")
        self.assertEqual(format_duration(599), "9:59")

    def test_durations_over_an_hour_include_hours(self):
        self.assertEqual(format_duration(3600), "1:00:00")
        self.assertEqual(format_duration(3725), "1:02:05")

    def test_zero_renders_as_the_live_label_when_one_is_given(self):
        self.assertEqual(format_duration(0, live_label="LIVE"), "LIVE")

    def test_unknown_or_negative_durations_render_as_zero(self):
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(None), "0:00")
        self.assertEqual(format_duration(-5), "0:00")


class CacheKeyTests(unittest.TestCase):
    def test_queries_normalise_case_and_whitespace(self):
        self.assertEqual(normalise_query("  Bohemian   RHAPSODY "), "bohemian rhapsody")

    def test_equivalent_queries_share_a_cache_key(self):
        self.assertEqual(search_cache_key("Daft Punk"), search_cache_key("  daft   punk  "))

    def test_search_and_stream_keys_never_collide(self):
        self.assertNotEqual(search_cache_key("abc"), stream_cache_key("abc"))
        self.assertTrue(search_cache_key("abc").startswith("search:"))
        self.assertTrue(stream_cache_key("abc").startswith("stream:"))


class YtDlpRuntimeOptionsTests(unittest.TestCase):
    def setUp(self):
        self._saved_file = os.environ.pop("MUSIC_YTDLP_COOKIES_FILE", None)
        self._saved_browser = os.environ.pop("MUSIC_YTDLP_COOKIES_FROM_BROWSER", None)

    def tearDown(self):
        os.environ.pop("MUSIC_YTDLP_COOKIES_FILE", None)
        os.environ.pop("MUSIC_YTDLP_COOKIES_FROM_BROWSER", None)
        if self._saved_file is not None:
            os.environ["MUSIC_YTDLP_COOKIES_FILE"] = self._saved_file
        if self._saved_browser is not None:
            os.environ["MUSIC_YTDLP_COOKIES_FROM_BROWSER"] = self._saved_browser

    def test_no_cookie_options_are_added_by_default(self):
        self.assertEqual(ydl_runtime_options(), {})

    def test_cookie_file_is_passed_to_yt_dlp(self):
        os.environ["MUSIC_YTDLP_COOKIES_FILE"] = "~/cookies.txt"
        self.assertTrue(ydl_runtime_options()["cookiefile"].endswith("/cookies.txt"))

    def test_browser_cookie_spec_is_a_tuple_for_the_python_api(self):
        os.environ["MUSIC_YTDLP_COOKIES_FROM_BROWSER"] = "chrome:Default"
        self.assertEqual(ydl_runtime_options()["cookiesfrombrowser"], ("chrome", "Default"))


class SearchProviderConfigTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("MUSIC_ENABLE_SOUNDCLOUD_FALLBACK", None)

    def tearDown(self):
        os.environ.pop("MUSIC_ENABLE_SOUNDCLOUD_FALLBACK", None)
        if self._saved is not None:
            os.environ["MUSIC_ENABLE_SOUNDCLOUD_FALLBACK"] = self._saved

    def test_soundcloud_fallback_is_enabled_by_default(self):
        self.assertTrue(soundcloud_fallback_enabled())
        self.assertEqual([source for _, source in search_providers()], ["youtube", "soundcloud"])

    def test_soundcloud_fallback_can_be_disabled(self):
        os.environ["MUSIC_ENABLE_SOUNDCLOUD_FALLBACK"] = "false"
        self.assertFalse(soundcloud_fallback_enabled())
        self.assertEqual([source for _, source in search_providers()], ["youtube"])


if __name__ == "__main__":
    unittest.main()
