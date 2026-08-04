"""Tests for how user input is classified and normalised before extraction."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.music_sources as music_sources  # noqa: E402
from core.music_sources import (  # noqa: E402
    configured_proxy,
    ffmpeg_proxy_url,
    youtube_bot_check_recent,
    classify_input,
    best_search_entry,
    format_duration,
    normalise_query,
    search_entry_score,
    search_cache_key,
    search_cache_prefix,
    spotify_credentials_configured,
    spotify_to_query,
    stream_cache_key,
    search_providers,
    soundcloud_fallback_enabled,
    ydl_runtime_options,
    ydl_format_selector,
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

    def test_cache_prefix_uses_the_search_cache_version(self):
        self.assertEqual(search_cache_prefix("Daft"), "search:v3:daft")

    def test_search_and_stream_keys_never_collide(self):
        self.assertNotEqual(search_cache_key("abc"), stream_cache_key("abc"))
        self.assertTrue(search_cache_key("abc").startswith("search:v3:"))
        self.assertTrue(stream_cache_key("abc").startswith("stream:"))


class SearchScoringTests(unittest.TestCase):
    def test_best_search_entry_prefers_the_exact_music_result(self):
        entries = [
            {
                "title": "Nicolae Guta - Toate pozele cu tine Karaoke",
                "webpage_url": "https://youtube.test/karaoke",
                "duration": 240,
            },
            {
                "title": "Nicolae Guta - Toate pozele cu tine",
                "webpage_url": "https://youtube.test/original",
                "duration": 250,
                "view_count": 2_000_000,
            },
        ]

        entry, score = best_search_entry("toate pozele cu tine nicolae guta", entries, "youtube")

        self.assertEqual(entry["webpage_url"], "https://youtube.test/original")
        self.assertGreater(score, 70)

    def test_search_score_penalizes_unrequested_cover_terms(self):
        original = {
            "title": "Vanilla x Alex Velea - 7 din 7",
            "webpage_url": "https://youtube.test/original",
            "duration": 190,
        }
        cover = {
            "title": "Vanilla x Alex Velea - 7 din 7 cover karaoke",
            "webpage_url": "https://youtube.test/cover",
            "duration": 190,
        }

        self.assertGreater(
            search_entry_score("vanilla alex velea 7 din 7", original, "youtube"),
            search_entry_score("vanilla alex velea 7 din 7", cover, "youtube"),
        )


class YtDlpRuntimeOptionsTests(unittest.TestCase):
    def setUp(self):
        self._saved_file = os.environ.pop("MUSIC_YTDLP_COOKIES_FILE", None)
        self._saved_browser = os.environ.pop("MUSIC_YTDLP_COOKIES_FROM_BROWSER", None)
        self._saved_js_runtime = os.environ.pop("MUSIC_YTDLP_JS_RUNTIME", None)
        self._saved_js_runtimes = os.environ.pop("MUSIC_YTDLP_JS_RUNTIMES", None)
        self._saved_remote_components = os.environ.pop("MUSIC_YTDLP_REMOTE_COMPONENTS", None)
        self._saved_extractor_args = os.environ.pop("MUSIC_YTDLP_EXTRACTOR_ARGS", None)
        self._saved_min_bitrate = os.environ.pop("MUSIC_MIN_AUDIO_BITRATE_KBPS", None)
        self._saved_strict_bitrate = os.environ.pop("MUSIC_STRICT_MIN_AUDIO_BITRATE", None)
        self._saved_proxy = os.environ.pop("MUSIC_YTDLP_PROXY", None)

    def tearDown(self):
        os.environ.pop("MUSIC_YTDLP_COOKIES_FILE", None)
        os.environ.pop("MUSIC_YTDLP_COOKIES_FROM_BROWSER", None)
        os.environ.pop("MUSIC_YTDLP_JS_RUNTIME", None)
        os.environ.pop("MUSIC_YTDLP_JS_RUNTIMES", None)
        os.environ.pop("MUSIC_YTDLP_REMOTE_COMPONENTS", None)
        os.environ.pop("MUSIC_YTDLP_EXTRACTOR_ARGS", None)
        os.environ.pop("MUSIC_MIN_AUDIO_BITRATE_KBPS", None)
        os.environ.pop("MUSIC_STRICT_MIN_AUDIO_BITRATE", None)
        os.environ.pop("MUSIC_YTDLP_PROXY", None)
        if self._saved_file is not None:
            os.environ["MUSIC_YTDLP_COOKIES_FILE"] = self._saved_file
        if self._saved_browser is not None:
            os.environ["MUSIC_YTDLP_COOKIES_FROM_BROWSER"] = self._saved_browser
        if self._saved_js_runtime is not None:
            os.environ["MUSIC_YTDLP_JS_RUNTIME"] = self._saved_js_runtime
        if self._saved_js_runtimes is not None:
            os.environ["MUSIC_YTDLP_JS_RUNTIMES"] = self._saved_js_runtimes
        if self._saved_remote_components is not None:
            os.environ["MUSIC_YTDLP_REMOTE_COMPONENTS"] = self._saved_remote_components
        if self._saved_extractor_args is not None:
            os.environ["MUSIC_YTDLP_EXTRACTOR_ARGS"] = self._saved_extractor_args
        if self._saved_min_bitrate is not None:
            os.environ["MUSIC_MIN_AUDIO_BITRATE_KBPS"] = self._saved_min_bitrate
        if self._saved_strict_bitrate is not None:
            os.environ["MUSIC_STRICT_MIN_AUDIO_BITRATE"] = self._saved_strict_bitrate
        if self._saved_proxy is not None:
            os.environ["MUSIC_YTDLP_PROXY"] = self._saved_proxy

    def test_no_cookie_options_are_added_by_default(self):
        with mock.patch("core.music_sources.detected_deno_path", return_value=None):
            self.assertEqual(ydl_runtime_options(), {})

    def test_cookie_file_is_passed_to_yt_dlp(self):
        os.environ["MUSIC_YTDLP_COOKIES_FILE"] = "~/cookies.txt"
        self.assertTrue(ydl_runtime_options()["cookiefile"].endswith("/cookies.txt"))

    def test_browser_cookie_spec_is_a_tuple_for_the_python_api(self):
        os.environ["MUSIC_YTDLP_COOKIES_FROM_BROWSER"] = "chrome:Default"
        self.assertEqual(ydl_runtime_options()["cookiesfrombrowser"], ("chrome", "Default"))

    def test_js_runtime_can_be_forced(self):
        os.environ["MUSIC_YTDLP_JS_RUNTIME"] = "deno:/home/ubuntu/.deno/bin/deno"
        self.assertEqual(
            ydl_runtime_options()["js_runtimes"],
            {"deno": {"path": "/home/ubuntu/.deno/bin/deno"}},
        )

    def test_bare_js_runtime_path_defaults_to_deno(self):
        os.environ["MUSIC_YTDLP_JS_RUNTIME"] = "/home/ubuntu/.deno/bin/deno"
        self.assertEqual(
            ydl_runtime_options()["js_runtimes"],
            {"deno": {"path": "/home/ubuntu/.deno/bin/deno"}},
        )

    def test_multiple_js_runtimes_can_be_configured(self):
        os.environ["MUSIC_YTDLP_JS_RUNTIMES"] = "node,deno:/opt/deno"
        self.assertEqual(
            ydl_runtime_options()["js_runtimes"],
            {"node": {"path": None}, "deno": {"path": "/opt/deno"}},
        )

    def test_remote_components_are_passed_to_yt_dlp(self):
        os.environ["MUSIC_YTDLP_REMOTE_COMPONENTS"] = "ejs:github|ejs:npm"
        with mock.patch("core.music_sources.detected_deno_path", return_value=None):
            self.assertEqual(ydl_runtime_options()["remote_components"], ["ejs:github", "ejs:npm"])

    def test_extractor_args_are_passed_to_yt_dlp(self):
        os.environ["MUSIC_YTDLP_EXTRACTOR_ARGS"] = (
            "youtubepot-bgutilscript:server-home=/home/ubuntu/bgutil/server|"
            "youtube:player-client=mweb,default;po-token=mweb.gvs+TOKEN"
        )
        with mock.patch("core.music_sources.detected_deno_path", return_value=None):
            self.assertEqual(
                ydl_runtime_options()["extractor_args"],
                {
                    "youtubepot-bgutilscript": {
                        "server_home": ["/home/ubuntu/bgutil/server"],
                    },
                    "youtube": {
                        "player_client": ["mweb,default"],
                        "po_token": ["mweb.gvs+TOKEN"],
                    },
                },
            )

    def test_deno_is_auto_detected_when_runtime_is_not_explicit(self):
        with mock.patch("core.music_sources.detected_deno_path", return_value="/usr/local/bin/deno"):
            self.assertEqual(
                ydl_runtime_options()["js_runtimes"],
                {"deno": {"path": "/usr/local/bin/deno"}},
            )

    def test_proxy_is_passed_to_yt_dlp(self):
        os.environ["MUSIC_YTDLP_PROXY"] = "http://user:pass@proxy.test:3128"
        with mock.patch("core.music_sources.detected_deno_path", return_value=None):
            self.assertEqual(
                ydl_runtime_options()["proxy"], "http://user:pass@proxy.test:3128"
            )

    def test_no_proxy_option_is_added_by_default(self):
        with mock.patch("core.music_sources.detected_deno_path", return_value=None):
            self.assertNotIn("proxy", ydl_runtime_options())

    def test_http_proxy_is_offered_to_ffmpeg(self):
        os.environ["MUSIC_YTDLP_PROXY"] = "http://user:pass@proxy.test:3128"
        self.assertEqual(ffmpeg_proxy_url(), "http://user:pass@proxy.test:3128")

    def test_socks_proxy_is_refused_for_ffmpeg(self):
        os.environ["MUSIC_YTDLP_PROXY"] = "socks5://proxy.test:1080"
        with mock.patch.object(music_sources.log, "warning") as warn:
            self.assertIsNone(ffmpeg_proxy_url())
        self.assertEqual(configured_proxy(), "socks5://proxy.test:1080")
        # the warning is emitted once, not per track
        with mock.patch.object(music_sources.log, "warning") as warn_again:
            self.assertIsNone(ffmpeg_proxy_url())
        self.assertLessEqual(warn_again.call_count + warn.call_count, 1)

    def test_format_prefers_direct_audio_over_hls(self):
        selector = ydl_format_selector()

        self.assertIn("protocol!=m3u8", selector)
        self.assertIn("protocol!=m3u8_native", selector)
        self.assertTrue(selector.endswith("/bestaudio/best"))

    def test_min_bitrate_is_a_preference_by_default(self):
        os.environ["MUSIC_MIN_AUDIO_BITRATE_KBPS"] = "320"

        selector = ydl_format_selector()

        self.assertIn("abr>=320", selector)
        self.assertTrue(selector.endswith("/bestaudio/best"))

    def test_min_bitrate_can_be_strict_when_requested(self):
        os.environ["MUSIC_MIN_AUDIO_BITRATE_KBPS"] = "320"
        os.environ["MUSIC_STRICT_MIN_AUDIO_BITRATE"] = "true"

        selector = ydl_format_selector()

        self.assertIn("abr>=320", selector)
        self.assertFalse(selector.endswith("/bestaudio/best"))


class YoutubeBotCheckTests(unittest.TestCase):
    def setUp(self):
        music_sources._bot_check_seen_at = 0.0
        music_sources._last_bot_check_hint_at = 0.0
        self._saved_proxy = os.environ.pop("MUSIC_YTDLP_PROXY", None)

    def tearDown(self):
        music_sources._bot_check_seen_at = 0.0
        music_sources._last_bot_check_hint_at = 0.0
        os.environ.pop("MUSIC_YTDLP_PROXY", None)
        if self._saved_proxy is not None:
            os.environ["MUSIC_YTDLP_PROXY"] = self._saved_proxy

    def test_bot_check_message_is_recognised_with_either_apostrophe(self):
        for message in (
            "ERROR: [youtube] abc123: Sign in to confirm you're not a bot",
            "ERROR: [youtube] abc123: Sign in to confirm you’re not a bot",
        ):
            self.assertTrue(music_sources._is_youtube_bot_check(message))

    def test_unrelated_errors_are_not_a_bot_check(self):
        self.assertFalse(music_sources._is_youtube_bot_check("[youtube] abc: Video unavailable"))
        self.assertFalse(music_sources._is_youtube_bot_check("[soundcloud] sign in to confirm"))

    def test_a_seen_bot_check_is_reported_as_recent(self):
        self.assertFalse(youtube_bot_check_recent())
        with mock.patch.object(music_sources.log, "warning"):
            music_sources._maybe_log_youtube_bot_check_hint(
                "ERROR: [youtube] abc: Sign in to confirm you're not a bot"
            )
        self.assertTrue(youtube_bot_check_recent())

    def test_the_operator_hint_mentions_the_proxy_env_var(self):
        with mock.patch.object(music_sources.log, "warning") as warn:
            music_sources._maybe_log_youtube_bot_check_hint(
                "ERROR: [youtube] abc: Sign in to confirm you're not a bot"
            )
        blob = " ".join(str(call) for call in warn.call_args_list)
        self.assertIn("MUSIC_YTDLP_PROXY", blob)


class SearchProviderConfigTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("MUSIC_ENABLE_SOUNDCLOUD_FALLBACK", None)

    def tearDown(self):
        os.environ.pop("MUSIC_ENABLE_SOUNDCLOUD_FALLBACK", None)
        if self._saved is not None:
            os.environ["MUSIC_ENABLE_SOUNDCLOUD_FALLBACK"] = self._saved

    def test_soundcloud_fallback_is_disabled_by_default(self):
        self.assertFalse(soundcloud_fallback_enabled())
        self.assertEqual([source for _, source in search_providers()], ["youtube"])

    def test_soundcloud_fallback_can_be_enabled(self):
        os.environ["MUSIC_ENABLE_SOUNDCLOUD_FALLBACK"] = "true"
        self.assertTrue(soundcloud_fallback_enabled())
        self.assertEqual([source for _, source in search_providers()], ["youtube", "soundcloud"])


if __name__ == "__main__":
    unittest.main()
