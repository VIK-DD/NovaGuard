"""Focused checks for the chat XP helpers.

Run standalone:
    python tests/test_levels.py
"""

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.levels import (  # noqa: E402
    XP_COOLDOWN_SECONDS,
    BACKFILL_DEFAULT_DAYS,
    BACKFILL_MAX_DAYS,
    MAX_LEVEL,
    XP_GAIN_MAX,
    XP_GAIN_MIN,
    XP_PER_LEVEL,
    replace_backfill_for_guild,
    backfill_window,
    build_level_up_embed,
    level_from_xp,
    meaningful_message,
    rank_position,
    xp_from_message_counts,
    xp_needed,
)


class LevelsHelperTests(unittest.TestCase):
    def test_xp_gain_is_slower_than_old_defaults(self):
        self.assertEqual(XP_COOLDOWN_SECONDS, 120)
        self.assertLessEqual(XP_GAIN_MAX, 10)
        self.assertGreaterEqual(XP_GAIN_MIN, 5)

    def test_level_math_uses_a_fixed_169_level_curve(self):
        first_level_xp = xp_needed(0)
        level, into_level = level_from_xp(first_level_xp)

        self.assertEqual(first_level_xp, XP_PER_LEVEL)
        self.assertEqual(level, 1)
        self.assertEqual(into_level, 0)
        self.assertEqual(xp_needed(MAX_LEVEL), 0)
        self.assertEqual(level_from_xp(MAX_LEVEL * XP_PER_LEVEL + 500), (MAX_LEVEL, 0))

    def test_meaningful_message_ignores_short_xp_farming(self):
        short = SimpleNamespace(content="ok", attachments=[], stickers=[])
        attachment = SimpleNamespace(content="", attachments=[object()], stickers=[])
        normal = SimpleNamespace(content="hello there", attachments=[], stickers=[])

        self.assertFalse(meaningful_message(short))
        self.assertTrue(meaningful_message(attachment))
        self.assertTrue(meaningful_message(normal))

    def test_rank_position(self):
        guild_data = {
            "1": {"xp": 200},
            "2": {"xp": 500},
            "3": {"xp": 100},
        }

        self.assertEqual(rank_position(guild_data, "2"), (1, 3))
        self.assertEqual(rank_position(guild_data, "1"), (2, 3))

    def test_backfill_xp_uses_cap(self):
        message_counts = {"1": 20, "2": 20_000}

        self.assertEqual(xp_from_message_counts(message_counts, xp_per_message=2, cap_per_user=1000), {
            "1": 40,
            "2": 1000,
        })

    def test_backfill_window_uses_latest_days_and_hard_caps_to_700(self):
        now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
        after, before = backfill_window(5_000, now=now)

        self.assertEqual(BACKFILL_DEFAULT_DAYS, 700)
        self.assertEqual(BACKFILL_MAX_DAYS, 700)
        self.assertEqual(before, now)
        self.assertEqual(after, now - timedelta(days=700))

    def test_backfill_replaces_existing_xp_and_messages(self):
        guild_data = {
            "1": {"xp": 200, "messages": 5, "last_gain": "2026-07-23T00:00:00+00:00"},
            "stale-user": {"xp": 900, "messages": 50, "last_gain": None},
        }
        message_counts = {"1": 10, "2": 4}
        xp_by_user = {"1": 20, "2": 8}

        applied_xp, applied_messages = replace_backfill_for_guild(guild_data, message_counts, xp_by_user)

        self.assertEqual(applied_xp, 28)
        self.assertEqual(applied_messages, 14)
        self.assertEqual(guild_data["1"]["xp"], 20)
        self.assertEqual(guild_data["1"]["messages"], 10)
        self.assertIsNone(guild_data["1"]["last_gain"])
        self.assertEqual(guild_data["2"]["xp"], 8)
        self.assertEqual(guild_data["2"]["messages"], 4)
        self.assertNotIn("stale-user", guild_data)

    def test_level_up_embed_contains_private_progress(self):
        member = SimpleNamespace(display_avatar=SimpleNamespace(url="https://example.com/avatar.png"))
        guild = SimpleNamespace(name="NovaGuard")
        record = {"xp": xp_needed(0) + 25}

        embed = build_level_up_embed(
            member=member,
            guild=guild,
            record=record,
            new_level=1,
            xp_gain=7,
            position=3,
            ranked_count=10,
        )

        self.assertIn("Level 1", embed.title)
        self.assertIn("NovaGuard", embed.description)
        self.assertIn("No channel spam", embed.description)
        self.assertEqual(embed.fields[0].name, "Next level")
        self.assertIn(f"/ {XP_PER_LEVEL} XP", embed.fields[0].value)
        self.assertEqual(embed.fields[2].value, "`+7 XP`")


if __name__ == "__main__":
    unittest.main()
