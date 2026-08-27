"""Contracts for read-only utility command cards."""

import unittest
from datetime import UTC, datetime
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
            "build_userinfo_embed",
            "build_serverinfo_embed",
            "build_avatar_embed",
            "build_roleinfo_embed",
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


if __name__ == "__main__":
    unittest.main()
