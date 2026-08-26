"""Discord help hub and reusable embed pagination controls."""

import discord
from discord import app_commands

from .release_versions import current_project_release
from .theme import Palette, brand_footer, make_embed
from .utils import truncate


def command_line_entries(command, prefix=""):
    current = f"{prefix} {command.name}".strip()
    if isinstance(command, app_commands.Group):
        lines = []
        for subcommand in command.commands:
            lines.extend(command_line_entries(subcommand, current))
        return lines or [f"`/{current}` — {command.description}"]
    return [f"`/{current}` — {command.description}"]


def cog_command_lines(cog):
    lines = []
    for command in cog.get_app_commands():
        lines.extend(command_line_entries(command))
    return lines


def build_category_embed(cog):
    emoji = getattr(cog, "EMOJI", "📦")
    color = getattr(cog, "COLOR", Palette.PRIMARY)
    description = getattr(cog, "DESCRIPTION", "")
    lines = cog_command_lines(cog)

    embed = make_embed(
        f"{emoji} {cog.qualified_name}",
        f"{description}\n\n" + "\n".join(lines),
        color=color,
    )
    brand_footer(embed, f"{len(lines)} command(s) in this category")
    return embed


def build_help_home_embed(bot):
    release = current_project_release()
    lines = []
    total = 0
    for name, cog in bot.cogs.items():
        commands_count = len(cog_command_lines(cog))
        total += commands_count
        emoji = getattr(cog, "EMOJI", "📦")
        description = getattr(cog, "DESCRIPTION", "Commands")
        lines.append(f"{emoji} **{name}** `{commands_count}` — {description}")

    embed = make_embed(
        "🌈 Command Hub",
        "Everything is a **slash command** now — type `/` and explore!\n"
        "Pick a category from the menu below for the full list.\n\n" + "\n".join(lines),
        color=Palette.PRIMARY,
    )
    embed.add_field(
        name="Quick Stats",
        value=(
            f"Categories: `{len(bot.cogs)}` • Commands: `{total}` • "
            f"Version: `v{release['version']} {release['phase_label']}`"
        ),
        inline=False,
    )
    brand_footer(embed, "Help hub")
    return embed


class HelpSelect(discord.ui.Select):
    def __init__(self, bot):
        options = [
            discord.SelectOption(
                label="Overview",
                value="__home__",
                emoji="🌈",
                description="Back to the category overview",
            )
        ]
        for name, cog in bot.cogs.items():
            options.append(
                discord.SelectOption(
                    label=name,
                    value=name,
                    emoji=getattr(cog, "EMOJI", "📦"),
                    description=truncate(getattr(cog, "DESCRIPTION", "Commands"), 90),
                )
            )
        super().__init__(placeholder="Pick a category to explore…", options=options[:25])
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__home__":
            embed = build_help_home_embed(self.bot)
        else:
            cog = self.bot.cogs.get(self.values[0])
            embed = build_category_embed(cog) if cog else build_help_home_embed(self.bot)
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.add_item(HelpSelect(bot))


class Paginator(discord.ui.View):
    def __init__(self, embeds, user_id):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.user_id = user_id
        self.index = 0
        self._sync_buttons()

    def _sync_buttons(self):
        self.previous_page.disabled = self.index == 0
        self.next_page.disabled = self.index >= len(self.embeds) - 1
        self.counter.label = f"{self.index + 1}/{len(self.embeds)}"

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Start your own session to flip these pages!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction, button):
        self.index = max(self.index - 1, 0)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.gray, disabled=True)
    async def counter(self, interaction, button):
        pass

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        self.index = min(self.index + 1, len(self.embeds) - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)
