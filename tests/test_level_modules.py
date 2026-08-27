"""Direct contracts for the extracted level helpers and presenters."""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import cogs.levels as levels_cog
from core import level_helpers, level_presenters
from core.level_curve import MAX_LEVEL, total_xp_for_level


class LevelCompatibilityTests(unittest.TestCase):
    def test_cog_reexports_moved_helpers_and_presenters(self):
        for name in (
            "parse_saved_datetime",
            "meaningful_message",
            "meaningful_historical_message",
            "rank_position",
            "backfill_window",
            "boosted_xp",
            "xp_from_message_counts",
            "replace_backfill_for_guild",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(levels_cog, name), getattr(level_helpers, name))

        for name in (
            "RANK_COLORS",
            "MEDALS",
            "backfill_top_lines",
            "readable_dt",
            "build_backfill_embed",
            "build_level_up_embed",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(levels_cog, name), getattr(level_presenters, name))


class LevelHelperTests(unittest.TestCase):
    def test_saved_datetimes_are_normalized_to_utc(self):
        naive = level_helpers.parse_saved_datetime("2026-08-27T12:00:00")
        offset = level_helpers.parse_saved_datetime("2026-08-27T15:00:00+03:00")

        self.assertEqual(naive, datetime(2026, 8, 27, 12, tzinfo=UTC))
        self.assertEqual(offset, datetime(2026, 8, 27, 12, tzinfo=UTC))
        self.assertIsNone(level_helpers.parse_saved_datetime("broken"))

    def test_historical_messages_without_content_remain_eligible(self):
        message = SimpleNamespace(content="", attachments=[], stickers=[])

        self.assertTrue(level_helpers.meaningful_historical_message(message))
        self.assertFalse(level_helpers.meaningful_message(message))

    def test_backfill_window_is_bounded_on_both_sides(self):
        now = datetime(2026, 8, 27, 12, tzinfo=UTC)

        self.assertEqual(level_helpers.backfill_window(0, now), (now - timedelta(days=1), now))
        self.assertEqual(
            level_helpers.backfill_window(50_000, now),
            (now - timedelta(days=level_helpers.BACKFILL_MAX_DAYS), now),
        )

    def test_non_positive_message_counts_do_not_create_backfill_rows(self):
        result = level_helpers.xp_from_message_counts(
            {"negative": -1, "zero": 0, "member": 15},
            xp_per_message=2,
            cap_per_user=20,
        )

        self.assertEqual(result, {"member": 20})


class LevelPresenterTests(unittest.TestCase):
    def test_preview_explains_safety_and_apply_step(self):
        now = datetime(2026, 8, 27, 12, tzinfo=UTC)
        embed = level_presenters.build_backfill_embed(
            guild=SimpleNamespace(name="Test server"),
            mode="preview",
            stats={
                "channels_scanned": 2,
                "channels_skipped": 0,
                "messages_seen": 10,
                "eligible_messages": 8,
                "errors": 0,
            },
            xp_by_user={"42": 16},
            message_counts={"42": 8},
            after=now - timedelta(days=7),
            before=now,
            days=7,
            xp_per_message=2,
            cap_per_user=100,
        )

        self.assertEqual(embed.title, "XP rebuild preview")
        self.assertIn("No data changed", embed.fields[2].value)
        self.assertEqual(embed.fields[-1].name, "Apply")

    def test_level_cap_card_does_not_offer_more_progress(self):
        member = SimpleNamespace(display_avatar=SimpleNamespace(url="https://example.com/a.png"))
        guild = SimpleNamespace(name="Test server")
        embed = level_presenters.build_level_up_embed(
            member,
            guild,
            {"xp": total_xp_for_level(MAX_LEVEL)},
            MAX_LEVEL,
            10,
            1,
            5,
        )

        self.assertEqual(embed.fields[0].name, "Level cap")
        self.assertIn(str(MAX_LEVEL), embed.fields[0].value)


if __name__ == "__main__":
    unittest.main()
