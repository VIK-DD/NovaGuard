"""Unit tests for voice session accumulation without connecting to Discord."""

from datetime import UTC, datetime, timedelta
import os
import sys
import unittest

# Keep this standalone test runnable with `python tests/test_voice.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.voice import (
    MIN_SESSION_SECONDS,
    active_member_ids,
    human_duration,
    new_session,
    participant_lines,
    record_member_join,
    record_member_leave,
    session_duration,
    split_lines,
)


class VoiceSessionTests(unittest.TestCase):
    def setUp(self):
        self.started_at = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
        self.session = new_session(123, "Late-night", self.started_at)

    def test_rejoining_accumulates_member_time_and_tracks_peak(self):
        record_member_join(self.session, 1, "Victor", self.started_at)
        record_member_join(self.session, 2, "Mira", self.started_at + timedelta(minutes=15))
        self.assertEqual(self.session["peak_members"], 2)

        record_member_leave(self.session, 2, self.started_at + timedelta(minutes=45))
        record_member_join(self.session, 2, "Mira", self.started_at + timedelta(minutes=70))
        record_member_leave(self.session, 2, self.started_at + timedelta(minutes=85))
        record_member_leave(self.session, 1, self.started_at + timedelta(hours=2))

        self.assertEqual(active_member_ids(self.session), [])
        self.assertEqual(self.session["members"]["2"]["joins"], 2)
        self.assertEqual(self.session["members"]["2"]["total_seconds"], 45 * 60)
        self.assertEqual(session_duration(self.session, self.started_at + timedelta(hours=2)), 2 * 60 * 60)
        self.assertIn("<@2> - `45m 0s` (2 entries)", participant_lines(self.session))

    def test_short_sessions_can_be_filtered_by_the_one_hour_threshold(self):
        self.assertEqual(MIN_SESSION_SECONDS, 60 * 60)
        self.assertLess(session_duration(self.session, self.started_at + timedelta(minutes=59, seconds=59)), MIN_SESSION_SECONDS)
        self.assertGreaterEqual(session_duration(self.session, self.started_at + timedelta(hours=1)), MIN_SESSION_SECONDS)

    def test_duration_format_and_field_chunking_are_stable(self):
        self.assertEqual(human_duration(90_061), "1d 1h 1m 1s")
        lines = ["x" * 600, "y" * 600, "z" * 600]
        self.assertEqual([len(chunk) for chunk in split_lines(lines, limit=1000)], [600, 600, 600])


if __name__ == "__main__":
    unittest.main()
