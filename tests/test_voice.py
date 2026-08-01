"""Unit tests for voice session accumulation without connecting to Discord."""

import asyncio
from datetime import UTC, datetime, timedelta
import os
import sys
import unittest
from types import SimpleNamespace

# Keep this standalone test runnable with `python tests/test_voice.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.voice import (
    VoiceReports,
    MIN_SESSION_SECONDS,
    active_member_ids,
    build_report_embed,
    human_duration,
    new_session,
    participant_lines,
    record_member_join,
    record_member_leave,
    recover_active_members,
    report_export_text,
    session_activity,
    session_duration,
    session_highlights,
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

    def test_report_includes_server_identity_and_activity_bar(self):
        record_member_join(self.session, 1, "Victor", self.started_at)
        record_member_join(self.session, 2, "Mira", self.started_at + timedelta(minutes=30))
        record_member_leave(self.session, 2, self.started_at + timedelta(hours=1))
        ended_at = self.started_at + timedelta(hours=2)
        record_member_leave(self.session, 1, ended_at)

        guild = type(
            "Guild",
            (),
            {
                "name": "NovaGuard Support",
                "icon": type("Asset", (), {"url": "https://example.com/icon.png"})(),
                "banner": type("Asset", (), {"url": "https://example.com/banner.png"})(),
            },
        )()
        channel = type("VoiceChannel", (), {"mention": "#lounge", "guild": guild})()
        embed, overflow = build_report_embed(self.session, channel, ended_at)

        self.assertFalse(overflow)
        self.assertEqual(embed.author.name, "NovaGuard Support • Voice activity")
        self.assertEqual(str(embed.thumbnail.url), "https://example.com/icon.png")
        self.assertEqual(str(embed.image.url), "https://example.com/banner.png")
        self.assertIn("Room activity", [field.name for field in embed.fields])
        self.assertEqual(session_activity(self.session, ended_at), (62, 1.25))

    def test_report_highlights_track_first_last_and_longest_stay(self):
        record_member_join(self.session, 1, "Victor", self.started_at)
        record_member_join(self.session, 2, "Mira", self.started_at + timedelta(minutes=10))
        record_member_leave(self.session, 2, self.started_at + timedelta(minutes=40))
        record_member_join(self.session, 2, "Mira", self.started_at + timedelta(minutes=50))
        record_member_leave(self.session, 2, self.started_at + timedelta(minutes=70))
        record_member_leave(self.session, 1, self.started_at + timedelta(hours=2))

        highlights = session_highlights(self.session)

        self.assertIn("Most active: <@1> - `2h 0m 0s`", highlights)
        self.assertIn("Longest stay: <@1> - `2h 0m 0s` continuous", highlights)
        self.assertIn("First joined: <@1>", highlights)
        self.assertIn("Last left: <@1>", highlights)
        self.assertEqual(self.session["members"]["2"]["longest_streak"], 30 * 60)

    def test_report_exports_text_and_csv_with_continuous_stay_details(self):
        record_member_join(self.session, 1, "Victor", self.started_at)
        ended_at = self.started_at + timedelta(hours=2)
        record_member_leave(self.session, 1, ended_at)
        report = {
            "channel_id": "123",
            "channel_name": "Late-night",
            "ended_at": ended_at.isoformat(),
            "session": self.session,
        }

        text_export = report_export_text(report)
        csv_export = report_export_text(report, csv=True)

        self.assertIn("Voice session: Late-night", text_export)
        self.assertIn("Victor (1) - 2h 0m 0s (1 entry, longest 2h 0m 0s)", text_export)
        self.assertIn("member_id,display_name,total_seconds,duration,entries,longest_streak", csv_export)
        self.assertIn('"1","Victor",7200.0,"2h 0m 0s",1,"2h 0m 0s"', csv_export)

    def test_recover_active_members_moves_join_time_back(self):
        member = SimpleNamespace(id=1, display_name="Victor", bot=False)
        recovered_at = self.started_at - timedelta(hours=13)

        seeded = recover_active_members(self.session, [member], recovered_at)

        self.assertEqual(seeded, 1)
        self.assertEqual(self.session["members"]["1"]["joined_at"], recovered_at.isoformat())
        self.assertEqual(self.session["members"]["1"]["first_joined_at"], recovered_at.isoformat())
        self.assertEqual(self.session["members"]["1"]["joins"], 1)
        self.assertEqual(self.session["peak_members"], 1)

    def test_parallel_pending_sends_do_not_duplicate_the_report(self):
        async def run_check():
            cog = VoiceReports(SimpleNamespace())
            cog.pending_reports = {
                "42": {
                    "report-1": {
                        "id": "report-1",
                        "channel_id": "123",
                        "channel_name": "Late-night",
                        "ended_at": self.started_at.isoformat(),
                        "session": self.session,
                    }
                }
            }
            cog._mark_pending_sent = lambda guild_id, report_id: asyncio.sleep(0)
            cog._mark_pending_failed = lambda guild_id, report_id, error: asyncio.sleep(0)
            calls = 0

            async def fake_send(*args, **kwargs):
                nonlocal calls
                calls += 1
                await asyncio.sleep(0.05)
                return True

            cog._send_report = fake_send
            guild = SimpleNamespace(id=42, get_channel=lambda channel_id: None)
            results = await asyncio.gather(
                cog._send_pending_report(guild, "report-1"),
                cog._send_pending_report(guild, "report-1"),
            )
            return calls, results

        calls, results = asyncio.run(run_check())

        self.assertEqual(calls, 1)
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)


if __name__ == "__main__":
    unittest.main()
