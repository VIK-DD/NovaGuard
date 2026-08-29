"""Contracts for read-only utility command cards."""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import cogs.utility as utility_cog
from core import utility_presenters
from core.theme import Palette


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class FakeAsset:
    def __init__(self, url):
        self.url = url
        self.requested_size = None

    def with_size(self, size):
        self.requested_size = size
        return self


def role(name, value=0, **flags):
    return SimpleNamespace(
        name=name,
        mention=f"@{name}",
        id=flags.pop("id", 1),
        color=SimpleNamespace(value=value),
        members=flags.pop("members", []),
        position=flags.pop("position", 1),
        created_at=flags.pop("created_at", NOW),
        hoist=flags.pop("hoist", False),
        mentionable=flags.pop("mentionable", False),
        managed=flags.pop("managed", False),
        **flags,
    )


class UtilityCompatibilityTests(unittest.TestCase):
    def test_cog_reexports_moved_presenters(self):
        for name in (
            "BADGE_LABELS",
            "TIMESTAMP_STYLES",
            "build_poll_embed",
            "build_reminder_select_options",
            "build_reminder_cancelled_embed",
            "build_reminder_delivery_embed",
            "build_invalid_reminder_duration_embed",
            "build_reminder_too_far_embed",
            "build_reminder_set_embed",
            "build_no_reminders_embed",
            "build_reminders_embed",
            "build_userinfo_embed",
            "build_serverinfo_embed",
            "build_avatar_embed",
            "build_roleinfo_embed",
            "build_timestamp_embed",
            "build_choice_embed",
            "build_color_embed",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(utility_cog, name), getattr(utility_presenters, name))


class UtilityPresenterTests(unittest.TestCase):
    def test_userinfo_preserves_dates_roles_badges_and_color(self):
        everyone = role("everyone")
        roles = [everyone] + [role(f"role-{index}") for index in range(1, 8)]
        target = SimpleNamespace(
            display_name="Victor",
            mention="@Victor",
            id=42,
            public_flags=[("staff", True), ("partner", False), ("unknown", True)],
            roles=roles,
            color=SimpleNamespace(value=0x123456),
            display_avatar=FakeAsset("https://example.com/avatar.png"),
            created_at=NOW,
            joined_at=None,
            bot=False,
            top_role=roles[-1],
        )

        embed = utility_presenters.build_userinfo_embed(target)
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "👤 Victor")
        self.assertEqual(embed.color.value, 0x123456)
        self.assertEqual(embed.thumbnail.url, "https://example.com/avatar.png")
        self.assertIn("Joined: Unknown", fields["📅 Dates"])
        self.assertIn("Top role: @role-7", fields["🎭 Identity"])
        self.assertEqual(fields["✨ Badges"], "Discord Staff")
        self.assertEqual(fields["🏷️ Roles (7)"].count("@role-"), 5)

    def test_serverinfo_preserves_counts_assets_and_owner(self):
        guild = SimpleNamespace(
            name="Nova",
            description=None,
            icon=FakeAsset("https://example.com/icon.png"),
            banner=FakeAsset("https://example.com/banner.png"),
            member_count=12_345,
            owner=SimpleNamespace(mention="@Owner"),
            text_channels=[1, 2, 3],
            voice_channels=[1, 2],
            roles=[1, 2, 3, 4],
            emojis=[1],
            premium_tier=2,
            premium_subscription_count=None,
            created_at=NOW,
            id=99,
        )

        embed = utility_presenters.build_serverinfo_embed(guild)
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "🏰 Nova")
        self.assertEqual(embed.description, "A great place to be.")
        self.assertIn("12,345", fields["👥 People"])
        self.assertIn("Text: `3`", fields["💬 Channels"])
        self.assertIn("Boosts: `0`", fields["🚀 Boosts"])
        self.assertEqual(embed.thumbnail.url, "https://example.com/icon.png")
        self.assertEqual(embed.image.url, "https://example.com/banner.png")

    def test_avatar_requests_original_at_1024(self):
        asset = FakeAsset("https://example.com/avatar-1024.png")
        target = SimpleNamespace(display_name="Nova", display_avatar=asset)

        embed, asset_url = utility_presenters.build_avatar_embed(target)

        self.assertEqual(asset.requested_size, 1024)
        self.assertEqual(asset_url, "https://example.com/avatar-1024.png")
        self.assertEqual(embed.image.url, asset_url)

    def test_roleinfo_preserves_fallback_color_and_flags(self):
        target = role(
            "Moderator",
            value=0,
            id=77,
            members=[1, 2],
            position=5,
            hoist=True,
            mentionable=False,
            managed=True,
        )

        embed = utility_presenters.build_roleinfo_embed(target)
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.color.value, Palette.PRIMARY)
        self.assertIn("Members: `2`", fields["Details"])
        self.assertIn("Color: `#000000`", fields["Details"])
        self.assertIn("Hoisted: `Yes`", fields["Flags"])
        self.assertIn("Mentionable: `No`", fields["Flags"])
        self.assertIn("Managed: `Yes`", fields["Flags"])

    def test_poll_card_preserves_counts_percentages_and_closed_state(self):
        votes = {10: 0, 11: 0, 12: 1}

        open_embed = utility_presenters.build_poll_embed(
            "Best fruit?",
            ["Apple", "Pear"],
            votes,
            "Victor",
        )
        closed_embed = utility_presenters.build_poll_embed(
            "Best fruit?",
            ["Apple", "Pear"],
            votes,
            "Victor",
            closed=True,
        )

        self.assertEqual(open_embed.title, "📊 Best fruit?")
        self.assertEqual(open_embed.color.value, Palette.INFO)
        self.assertIn("2 vote(s) • 67%", open_embed.description)
        self.assertIn("1 vote(s) • 33%", open_embed.description)
        self.assertEqual(closed_embed.title, "🏁 Best fruit?")
        self.assertEqual(closed_embed.color.value, Palette.SUCCESS)

    def test_timestamp_card_lists_all_discord_styles(self):
        embed = utility_presenters.build_timestamp_embed(NOW)
        unix = int(NOW.timestamp())

        self.assertEqual(embed.title, "🕐 Timestamp generator")
        self.assertEqual(len(embed.description.splitlines()), 7)
        for code, label in utility_presenters.TIMESTAMP_STYLES:
            with self.subTest(code=code):
                self.assertIn(f"<t:{unix}:{code}>", embed.description)
                self.assertIn(label, embed.description)

    def test_choice_card_preserves_options_and_winner(self):
        embed = utility_presenters.build_choice_embed(
            ["pizza", "sushi", "tacos"],
            "sushi",
        )

        self.assertEqual(embed.title, "🎯 The wheel of fate has spoken")
        self.assertIn("`pizza`, `sushi`, `tacos`", embed.description)
        self.assertTrue(embed.description.endswith("# 🏆 sushi"))
        self.assertEqual(embed.color.value, Palette.FUN)

    def test_color_card_preserves_case_rgb_integer_and_preview(self):
        embed = utility_presenters.build_color_embed("a1B2c3")
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "🎨 #A1B2C3")
        self.assertEqual(embed.color.value, 0xA1B2C3)
        self.assertEqual(fields["RGB"], "`161, 178, 195`")
        self.assertEqual(fields["Int"], f"`{0xA1B2C3}`")
        self.assertEqual(
            embed.image.url,
            "https://singlecolorimage.com/get/a1B2c3/400x100",
        )

    def test_reminder_select_options_are_bounded_and_use_supplied_clock(self):
        items = [
            {
                "id": f"item-{index}",
                "message": "x" * 120,
                "due_at": (NOW + timedelta(minutes=10 + index)).isoformat(),
            }
            for index in range(30)
        ]

        options = utility_presenters.build_reminder_select_options(items, NOW)

        self.assertEqual(len(options), 25)
        self.assertEqual(options[0].value, "item-0")
        self.assertEqual(options[0].label, "...")
        self.assertEqual(options[0].description, "in 10m")

    def test_reminder_state_cards_preserve_titles_messages_and_colors(self):
        cancelled = utility_presenters.build_reminder_cancelled_embed()
        delivery = utility_presenters.build_reminder_delivery_embed("stand up")
        invalid = utility_presenters.build_invalid_reminder_duration_embed()
        too_far = utility_presenters.build_reminder_too_far_embed()
        reminder_set = utility_presenters.build_reminder_set_embed(NOW, "drink water")
        empty = utility_presenters.build_no_reminders_embed()

        self.assertEqual(cancelled.title, "🗑️ Reminder cancelled")
        self.assertEqual(cancelled.color.value, Palette.SUCCESS)
        self.assertEqual(delivery.description, "stand up")
        self.assertEqual(delivery.color.value, Palette.WARNING)
        self.assertIn("10m", invalid.description)
        self.assertIn("90 days", too_far.description)
        self.assertIn(f"<t:{int(NOW.timestamp())}:R>", reminder_set.description)
        self.assertIn("drink water", reminder_set.description)
        self.assertIn("/remind", empty.description)

    def test_pending_reminders_card_limits_rows_and_truncates_messages(self):
        items = [
            {
                "id": f"item-{index}",
                "message": f"message-{index}-" + "x" * 100,
                "due_at": (NOW + timedelta(minutes=index)).isoformat(),
            }
            for index in range(20)
        ]

        embed = utility_presenters.build_reminders_embed(items)

        self.assertEqual(embed.title, "🗓️ Your reminders")
        self.assertEqual(len(embed.description.splitlines()), 15)
        self.assertIn("message-0-", embed.description)
        self.assertNotIn("message-15-", embed.description)


if __name__ == "__main__":
    unittest.main()
