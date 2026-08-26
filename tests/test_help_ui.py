"""Tests for the extracted Discord help hub and paginator controls."""

import unittest
from types import SimpleNamespace
from unittest import mock

import discord
from discord import app_commands

from core.config import github_config
from core.help_ui import (
    HelpView,
    Paginator,
    build_category_embed,
    build_help_home_embed,
    command_line_entries,
)


async def _command_callback(interaction):
    del interaction


def _command(name, description):
    return app_commands.Command(
        name=name,
        description=description,
        callback=_command_callback,
    )


class FakeCog:
    EMOJI = "🧪"
    COLOR = 0x123456
    DESCRIPTION = "Test commands"
    qualified_name = "Testing"

    def __init__(self, commands):
        self._commands = commands

    def get_app_commands(self):
        return self._commands


class HelpEmbedTests(unittest.TestCase):
    def test_group_commands_are_rendered_with_their_full_path(self):
        group = app_commands.Group(name="settings", description="Settings")
        group.add_command(_command("show", "Show settings"))

        self.assertEqual(
            command_line_entries(group),
            ["`/settings show` — Show settings"],
        )

    def test_category_embed_lists_commands_and_keeps_brand_footer(self):
        cog = FakeCog([_command("ping", "Check latency")])

        embed = build_category_embed(cog)

        self.assertEqual(embed.title, "🧪 Testing")
        self.assertIn("`/ping` — Check latency", embed.description)
        self.assertEqual(embed.footer.text, github_config.brand_name)

    def test_home_embed_counts_leaf_commands(self):
        group = app_commands.Group(name="settings", description="Settings")
        group.add_command(_command("show", "Show settings"))
        bot = SimpleNamespace(cogs={"Testing": FakeCog([group, _command("ping", "Ping")])})

        with mock.patch(
            "core.help_ui.current_project_release",
            return_value={"version": "2.6", "phase_label": "Open Beta"},
        ):
            embed = build_help_home_embed(bot)

        self.assertIn("🧪 **Testing** `2`", embed.description)
        self.assertEqual(
            embed.fields[0].value,
            "Categories: `1` • Commands: `2` • Version: `v2.6 Open Beta`",
        )


class HelpControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_help_menu_stays_within_discords_option_limit(self):
        bot = SimpleNamespace(
            cogs={f"Cog {index}": FakeCog([]) for index in range(30)}
        )

        view = HelpView(bot)
        select = view.children[0]

        self.assertEqual(len(select.options), 25)
        self.assertEqual(select.options[0].value, "__home__")

    async def test_paginator_rejects_other_users(self):
        view = Paginator([discord.Embed(title="One"), discord.Embed(title="Two")], 42)
        response = SimpleNamespace(send_message=mock.AsyncMock())
        interaction = SimpleNamespace(user=SimpleNamespace(id=7), response=response)

        self.assertFalse(await view.interaction_check(interaction))
        response.send_message.assert_awaited_once_with(
            "Start your own session to flip these pages!",
            ephemeral=True,
        )
        self.assertTrue(view.previous_page.disabled)
        self.assertFalse(view.next_page.disabled)
        self.assertEqual(view.counter.label, "1/2")

    async def test_paginator_accepts_its_owner(self):
        view = Paginator([discord.Embed(title="One")], 42)
        interaction = SimpleNamespace(user=SimpleNamespace(id=42))

        self.assertTrue(await view.interaction_check(interaction))
        self.assertTrue(view.previous_page.disabled)
        self.assertTrue(view.next_page.disabled)


if __name__ == "__main__":
    unittest.main()
