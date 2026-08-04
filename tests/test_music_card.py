"""Tests for rendering the player card."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_card import card_fields, progress_bar  # noqa: E402
from core.music_queue import LoopMode, Track  # noqa: E402


def track(title="Song", duration=200):
    return Track(
        title=title,
        url="https://example.test/x",
        duration=duration,
        source="youtube",
        requester_id="7",
        uploader="Uploader",
    )


def fields(**overrides):
    base = dict(
        current=track(), upcoming=[], elapsed=0,
        volume=100, loop=LoopMode.OFF, paused=False,
    )
    base.update(overrides)
    return card_fields(**base)


class ProgressBarTests(unittest.TestCase):
    def test_the_bar_is_always_the_requested_width(self):
        for elapsed in (0, 50, 200, 5000):
            self.assertEqual(len(progress_bar(elapsed, 200, slots=12)), 12)

    def test_an_unknown_total_renders_an_empty_bar(self):
        self.assertEqual(len(progress_bar(30, 0, slots=10)), 10)

    def test_progress_never_overflows_past_the_end(self):
        self.assertEqual(len(progress_bar(999, 100, slots=10)), 10)


class CardFieldsTests(unittest.TestCase):
    def test_the_title_and_uploader_reach_the_card(self):
        result = fields(current=track("Bohemian Rhapsody"))
        self.assertIn("Bohemian Rhapsody", result["description"])
        self.assertIn("Uploader", result["description"])

    def test_an_idle_session_says_so_instead_of_crashing(self):
        result = fields(current=None)
        self.assertIn("Nothing playing", result["title"])
        self.assertEqual(result["next_up"], "The queue is empty.")

    def test_paused_state_is_visible_in_the_title(self):
        self.assertIn("Paused", fields(paused=True)["title"])

    def test_next_up_lists_the_queue_and_counts_the_remainder(self):
        result = fields(current=track("Current"), upcoming=[track(f"Song {i}") for i in range(8)])
        self.assertIn("Song 0", result["next_up"])
        self.assertIn("more", result["next_up"])

    def test_a_short_queue_is_listed_without_a_remainder(self):
        result = fields(upcoming=[track("Only One")])
        self.assertIn("Only One", result["next_up"])
        self.assertNotIn("more", result["next_up"])

    def test_an_empty_queue_after_the_current_track_says_so(self):
        self.assertIn("Nothing queued", fields()["next_up"])

    def test_the_footer_reports_volume_and_loop_mode(self):
        result = fields(volume=40, loop=LoopMode.QUEUE)
        self.assertIn("40%", result["footer"])
        self.assertIn("queue", result["footer"].lower())

    def test_a_livestream_shows_LIVE_rather_than_a_zero_length(self):
        self.assertIn("LIVE", fields(current=track(duration=0))["progress"])


if __name__ == "__main__":
    unittest.main()
