"""Tests for converting yt-dlp entries into Track objects."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


if __name__ == "__main__":
    unittest.main()
