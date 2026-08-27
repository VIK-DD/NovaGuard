"""Contracts for extracted setup scores and configuration cards."""

import unittest
from types import SimpleNamespace
from unittest import mock

import cogs.setup as setup_cog
from core import setup_presenters
from core.theme import Palette


class FakeGuild:
    def __init__(self):
        self.id = 42
        self.channels = {100: SimpleNamespace(mention="#updates")}
        self.roles = {200: SimpleNamespace(mention="@Member")}

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    def get_role(self, role_id):
        return self.roles.get(role_id)


def fields(embed):
    return {field.name: field.value for field in embed.fields}


class SetupCompatibilityTests(unittest.TestCase):
    def test_cog_reexports_moved_setup_presenters(self):
        for name in (
            "CHANNEL_KEYS",
            "RECOMMENDED_KEYS",
            "SETUP_PRIVACY_NOTICE",
            "mention_channel",
            "setup_score",
            "build_setup_embed",
            "build_config_embed",
            "plain_label",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(setup_cog, name), getattr(setup_presenters, name))


class SetupPresenterTests(unittest.TestCase):
    def test_channel_mentions_distinguish_missing_invalid_unknown_and_known(self):
        guild = FakeGuild()

        self.assertEqual(setup_presenters.mention_channel(guild, None), "`Not set`")
        self.assertEqual(setup_presenters.mention_channel(guild, "not-an-id"), "`Invalid channel`")
        self.assertEqual(setup_presenters.mention_channel(guild, 999), "`999`")
        self.assertEqual(setup_presenters.mention_channel(guild, 100), "#updates")

    def test_setup_score_adds_github_only_when_the_integration_is_configured(self):
        settings = {"update_channel": 100, "github_event_channel": 101}

        with (
            mock.patch.object(setup_presenters.github_config, "watch_repos", []),
            mock.patch.object(setup_presenters.github_config, "primary_repo", None),
        ):
            self.assertEqual(setup_presenters.setup_score(settings), (1, 4))

        with mock.patch.object(
            setup_presenters.github_config,
            "watch_repos",
            ["VIK-DD/NovaGuard"],
        ):
            self.assertEqual(setup_presenters.setup_score(settings), (2, 5))

    def test_setup_card_preserves_notice_completion_channels_and_privacy(self):
        settings = {
            "setup_completed": True,
            "update_channel": 100,
            "github_event_channel": None,
            "error_log_channel": None,
            "log_channel": None,
            "welcome_channel": None,
            "goodbye_channel": None,
            "voice_report_channel": None,
            "autorole": 200,
        }
        with (
            mock.patch.object(setup_presenters, "get_guild_settings", return_value=settings),
            mock.patch.object(setup_presenters.github_config, "watch_repos", []),
            mock.patch.object(setup_presenters.github_config, "primary_repo", None),
        ):
            embed = setup_presenters.build_setup_embed(FakeGuild(), notice="Saved")
        card_fields = fields(embed)

        self.assertEqual(embed.title, "✅ NovaGuard Setup — Complete")
        self.assertEqual(embed.color.value, Palette.SUCCESS)
        self.assertTrue(embed.description.startswith("> Saved"))
        self.assertIn("#updates", card_fields["Core Channels"])
        self.assertIn("@Member", card_fields["Community"])
        self.assertIn("Anthropic", card_fields["Privacy before enabling features"])

    def test_config_card_preserves_all_channels_and_extra_settings(self):
        settings = {
            "update_channel": 100,
            "autorole": 200,
            "ticket_staff_role": None,
            "setup_completed": False,
        }
        with (
            mock.patch.object(setup_presenters, "get_guild_settings", return_value=settings),
            mock.patch.object(setup_presenters.github_config, "watch_repos", []),
            mock.patch.object(setup_presenters.github_config, "primary_repo", None),
        ):
            embed = setup_presenters.build_config_embed(FakeGuild())
        card_fields = fields(embed)

        self.assertEqual(embed.title, "🧭 NovaGuard Config")
        self.assertEqual(card_fields["Channels"].count("`Not set`"), 7)
        self.assertIn("@Member", card_fields["Other Settings"])
        self.assertIn("`setup_completed`: `False`", card_fields["Other Settings"])

    def test_plain_labels_drop_only_the_leading_emoji(self):
        self.assertEqual(setup_presenters.plain_label("update_channel"), "Bot Updates")
        self.assertEqual(setup_presenters.plain_label("voice_report_channel"), "Voice Reports")


if __name__ == "__main__":
    unittest.main()
