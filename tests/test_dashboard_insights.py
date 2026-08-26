"""Pure dashboard summary coverage without starting the web server."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.dashboard_insights import (  # noqa: E402
    dashboard_levels_summary,
    dashboard_module_summary,
    dashboard_seconds_between,
    dashboard_setup_summary,
    dashboard_voice_summary,
)
from core.level_curve import level_from_xp  # noqa: E402


class FakeMember:
    def __init__(self, display_name):
        self.display_name = display_name


class FakeGuild:
    def __init__(self, members=None):
        self.members = members or {}

    def get_member(self, user_id):
        return self.members.get(user_id)


class DashboardTimeTests(unittest.TestCase):
    def test_duration_accepts_utc_z_and_naive_timestamps(self):
        self.assertEqual(
            dashboard_seconds_between(
                "2026-08-26T12:00:00Z",
                "2026-08-26T12:03:07+00:00",
            ),
            187,
        )
        self.assertEqual(
            dashboard_seconds_between(
                "2026-08-26T12:00:00",
                "2026-08-26T12:00:05",
            ),
            5,
        )

    def test_duration_rejects_missing_invalid_and_negative_ranges(self):
        self.assertEqual(dashboard_seconds_between(None, "2026-08-26T12:00:00Z"), 0)
        self.assertEqual(dashboard_seconds_between("not-a-date", "also-not-a-date"), 0)
        self.assertEqual(
            dashboard_seconds_between(
                "2026-08-26T12:00:05Z",
                "2026-08-26T12:00:00Z",
            ),
            0,
        )


class DashboardSetupTests(unittest.TestCase):
    def test_setup_counts_configured_and_recommended_channels(self):
        settings = {
            "update_channel": "10",
            "log_channel": "20",
            "github_event_channel": "30",
        }

        summary = dashboard_setup_summary(
            settings,
            ("update_channel", "log_channel", "welcome_channel", "unused_channel"),
            github_watch_configured=True,
        )

        self.assertEqual(
            summary,
            {
                "configured_channels": 2,
                "total_channels": 4,
                "recommended_done": 3,
                "recommended_total": 5,
            },
        )

    def test_github_channel_is_not_recommended_without_a_watch(self):
        summary = dashboard_setup_summary(
            {"github_event_channel": "30"},
            ("github_event_channel",),
        )

        self.assertEqual(summary["configured_channels"], 1)
        self.assertEqual(summary["recommended_done"], 0)
        self.assertEqual(summary["recommended_total"], 4)


class DashboardLevelTests(unittest.TestCase):
    def test_levels_are_ranked_limited_and_resolve_member_names(self):
        guild = FakeGuild({2: FakeMember("Victor")})
        records = {
            "1": {"xp": 12, "messages": 2},
            "2": {"xp": 700, "messages": 30},
            "3": {"xp": 250, "messages": 11},
            "4": {"xp": 100, "messages": 4},
            "5": {"xp": 75, "messages": 3},
            "6": {"xp": 50, "messages": 1},
            "not-a-snowflake": {"xp": -20, "messages": 0},
        }

        summary = dashboard_levels_summary(guild, records)

        self.assertEqual(summary["tracked_members"], 7)
        self.assertEqual(summary["total_xp"], 1187)
        self.assertEqual(len(summary["leaderboard"]), 5)
        self.assertEqual(summary["leaderboard"][0]["user_id"], "2")
        self.assertEqual(summary["leaderboard"][0]["display_name"], "Victor")
        self.assertEqual(summary["leaderboard"][0]["level"], level_from_xp(700)[0])
        self.assertEqual(summary["leaderboard"][1]["display_name"], "User 3")
        self.assertNotIn(
            "not-a-snowflake",
            {entry["user_id"] for entry in summary["leaderboard"]},
        )

    def test_levels_support_a_smaller_explicit_limit(self):
        summary = dashboard_levels_summary(
            FakeGuild(),
            {"1": {"xp": 1}, "2": {"xp": 2}},
            limit=1,
        )

        self.assertEqual([entry["user_id"] for entry in summary["leaderboard"]], ["2"])


class DashboardVoiceTests(unittest.TestCase):
    def test_voice_summary_preserves_the_dashboard_contract(self):
        history = [
            {
                "id": 55,
                "channel_id": 99,
                "channel_name": "General Voice",
                "ended_at": "2026-08-26T12:10:00Z",
                "sent_at": "2026-08-26T12:10:01Z",
                "session": {
                    "started_at": "2026-08-26T12:00:00Z",
                    "members": {"1": {}, "2": {}},
                    "peak_members": 3,
                },
            },
            *({"id": number} for number in range(56, 62)),
        ]

        summary = dashboard_voice_summary(
            {"voice_report_channel": 99},
            history,
            {"active-a": {}, "active-b": {}},
        )

        self.assertTrue(summary["configured"])
        self.assertEqual(summary["report_channel_id"], "99")
        self.assertEqual(summary["pending_count"], 2)
        self.assertEqual(len(summary["recent_reports"]), 5)
        self.assertEqual(
            summary["recent_reports"][0],
            {
                "id": "55",
                "channel_id": "99",
                "channel_name": "General Voice",
                "started_at": "2026-08-26T12:00:00Z",
                "ended_at": "2026-08-26T12:10:00Z",
                "sent_at": "2026-08-26T12:10:01Z",
                "duration_seconds": 600,
                "unique_members": 2,
                "peak_members": 3,
            },
        )

    def test_voice_defaults_are_safe_for_unconfigured_or_malformed_pending_data(self):
        summary = dashboard_voice_summary({}, [], ["unexpected"])

        self.assertEqual(
            summary,
            {
                "configured": False,
                "report_channel_id": None,
                "pending_count": 0,
                "recent_reports": [],
            },
        )


class DashboardModuleTests(unittest.TestCase):
    def test_module_summary_has_the_stable_order_and_expected_toggles(self):
        modules = dashboard_module_summary(
            {
                "welcome_channel": "10",
                "voice_report_channel": "20",
                "ticket_staff_role": "30",
                "github_event_channel": "40",
            },
            {"spam": True},
            {"enabled": True},
            {"enabled": False},
            {"enabled": True},
        )

        self.assertEqual(
            [module["key"] for module in modules],
            [
                "welcome",
                "moderation",
                "levels",
                "voice",
                "tickets",
                "roles",
                "giveaways",
                "ai",
                "economy",
                "updates",
            ],
        )
        enabled = {module["key"] for module in modules if module["enabled"]}
        self.assertEqual(
            enabled,
            {"welcome", "moderation", "levels", "voice", "tickets", "economy", "updates"},
        )


if __name__ == "__main__":
    unittest.main()
