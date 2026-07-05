"""🚀 Setup category — one-command onboarding and server configuration."""

import io
import json

import discord
from discord import app_commands
from discord.ext import commands

from core.backups import create_backup
from core.config import github_config
from core.storage import get_guild_settings, reset_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import respond


CHANNEL_KEYS = {
    "update_channel": ("🚀 Bot Updates", "Automatic code changelog and restart summaries"),
    "github_event_channel": ("🐙 GitHub Feed", "Push, PR, issue and release activity"),
    "error_log_channel": ("🚨 Admin Errors", "Serious bot error digest embeds"),
    "log_channel": ("📋 Server Logs", "Deleted/edited messages, joins/leaves, bans"),
    "welcome_channel": ("👋 Welcome", "New member welcome cards"),
    "goodbye_channel": ("📤 Goodbye", "Leave messages"),
}

RECOMMENDED_KEYS = (
    "update_channel",
    "error_log_channel",
    "log_channel",
    "welcome_channel",
)


def mention_channel(guild, channel_id):
    if not channel_id:
        return "`Not set`"
    try:
        channel = guild.get_channel(int(channel_id))
    except (TypeError, ValueError):
        return "`Invalid channel`"
    return channel.mention if channel else f"`{channel_id}`"


def setup_score(settings):
    total = len(RECOMMENDED_KEYS)
    done = sum(1 for key in RECOMMENDED_KEYS if settings.get(key))
    if github_config.watch_repos or github_config.primary_repo:
        total += 1
        done += 1 if settings.get("github_event_channel") else 0
    return done, total


def build_setup_embed(guild):
    settings = get_guild_settings(guild.id)
    done, total = setup_score(settings)
    ratio_text = f"{done}/{total}"

    if done >= total:
        color = Palette.SUCCESS
        status = "NovaGuard is fully configured for this server."
    elif done:
        color = Palette.WARNING
        status = "NovaGuard is partially configured. A few finishing touches remain."
    else:
        color = Palette.PRIMARY
        status = "Welcome. Let's configure NovaGuard in a couple of clicks."

    embed = make_embed(
        "🚀 NovaGuard Setup",
        (
            f"{status}\n\n"
            "Pick a setup item from the menu, then choose a channel from the dropdown. "
            "You can also run `/setup` inside a channel and use the quick buttons below."
        ),
        color=color,
    )
    embed.add_field(
        name="Progress",
        value=f"{progress_bar(done, total, slots=12)} `{ratio_text}` recommended items",
        inline=False,
    )

    core_lines = []
    for key in ("update_channel", "github_event_channel", "error_log_channel", "log_channel"):
        label, description = CHANNEL_KEYS[key]
        core_lines.append(f"{label}: {mention_channel(guild, settings.get(key))}\n`{description}`")
    embed.add_field(name="Core Channels", value="\n\n".join(core_lines), inline=False)

    community_lines = []
    for key in ("welcome_channel", "goodbye_channel"):
        label, description = CHANNEL_KEYS[key]
        community_lines.append(f"{label}: {mention_channel(guild, settings.get(key))}\n`{description}`")
    autorole = settings.get("autorole")
    try:
        role = guild.get_role(int(autorole)) if autorole else None
    except (TypeError, ValueError):
        role = None
    community_lines.append(f"🎭 Auto-role: {role.mention if role else '`Not set`'}\n`Use /welcome set when you want an auto-role too`")
    embed.add_field(name="Community", value="\n\n".join(community_lines), inline=False)

    embed.add_field(
        name="Optional Next Steps",
        value=(
            "`/ticketpanel channel:#support staff_role:@Staff` for tickets\n"
            "`/rolepanel` for self-role buttons\n"
            "`/automod status` to review moderation filters"
        ),
        inline=False,
    )
    brand_footer(embed, "Server setup")
    return embed


def build_config_embed(guild):
    settings = get_guild_settings(guild.id)
    done, total = setup_score(settings)
    embed = make_embed(
        "🧭 NovaGuard Config",
        "Advanced server configuration overview. Use `/setup` for the friendly wizard.",
        color=Palette.INFO,
    )
    embed.add_field(
        name="Setup Health",
        value=f"{progress_bar(done, total, slots=12)} `{done}/{total}` recommended items",
        inline=False,
    )

    lines = []
    for key, (label, description) in CHANNEL_KEYS.items():
        lines.append(f"{label}: {mention_channel(guild, settings.get(key))}\n`{key}` • {description}")
    embed.add_field(name="Channels", value="\n\n".join(lines), inline=False)

    extra = []
    for key in ("autorole", "ticket_staff_role", "setup_completed"):
        value = settings.get(key)
        if key.endswith("_role") or key == "autorole":
            try:
                role = guild.get_role(int(value)) if value else None
            except (TypeError, ValueError):
                role = None
            display = role.mention if role else "`Not set`"
        else:
            display = f"`{value}`" if value is not None else "`Not set`"
        extra.append(f"`{key}`: {display}")
    embed.add_field(name="Other Settings", value="\n".join(extra), inline=False)
    brand_footer(embed, "Config view")
    return embed


def export_config_file(guild):
    settings = get_guild_settings(guild.id)
    payload = {
        "guild_id": guild.id,
        "guild_name": guild.name,
        "settings": settings,
    }
    data = json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")
    return discord.File(io.BytesIO(data), filename=f"novaguard-config-{guild.id}.json")


class SetupTargetSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label.replace("🚀 ", "").replace("🐙 ", "").replace("🚨 ", "").replace("📋 ", "").replace("👋 ", "").replace("📤 ", ""), value=key, description=description[:100])
            for key, (label, description) in CHANNEL_KEYS.items()
        ]
        super().__init__(
            placeholder="1. Choose what you want to configure...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction):
        self.view.selected_key = self.values[0]
        label, _ = CHANNEL_KEYS[self.values[0]]
        await interaction.response.send_message(
            f"Selected **{label}**. Now use the channel dropdown below.",
            ephemeral=True,
        )


class SetupChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="2. Pick the channel to save...",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            row=1,
        )

    async def callback(self, interaction):
        key = getattr(self.view, "selected_key", "update_channel")
        channel = self.values[0]
        update_guild_settings(interaction.guild_id, **{key: channel.id})
        label, _ = CHANNEL_KEYS[key]
        await interaction.response.edit_message(embed=build_setup_embed(interaction.guild), view=self.view)
        await interaction.followup.send(f"Saved **{label}** as {channel.mention}.", ephemeral=True)


class SetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)
        self.selected_key = "update_channel"
        self.add_item(SetupTargetSelect())
        self.add_item(SetupChannelSelect())

    async def interaction_check(self, interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Only members with **Manage Server** can use setup.", ephemeral=True)
            return False
        return True

    async def set_current_channel(self, interaction, key):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Run setup inside a server text channel.", ephemeral=True)

        update_guild_settings(interaction.guild_id, **{key: interaction.channel_id})
        await interaction.response.edit_message(embed=build_setup_embed(interaction.guild), view=self)

    @discord.ui.button(label="Updates", emoji="🚀", style=discord.ButtonStyle.primary, row=2)
    async def set_updates(self, interaction, button):
        await self.set_current_channel(interaction, "update_channel")

    @discord.ui.button(label="GitHub", emoji="🐙", style=discord.ButtonStyle.primary, row=2)
    async def set_github(self, interaction, button):
        await self.set_current_channel(interaction, "github_event_channel")

    @discord.ui.button(label="Admin Errors", emoji="🚨", style=discord.ButtonStyle.danger, row=2)
    async def set_errors(self, interaction, button):
        await self.set_current_channel(interaction, "error_log_channel")

    @discord.ui.button(label="Server Logs", emoji="📋", style=discord.ButtonStyle.secondary, row=3)
    async def set_logs(self, interaction, button):
        await self.set_current_channel(interaction, "log_channel")

    @discord.ui.button(label="Welcome", emoji="👋", style=discord.ButtonStyle.secondary, row=3)
    async def set_welcome(self, interaction, button):
        await self.set_current_channel(interaction, "welcome_channel")

    @discord.ui.button(label="Goodbye", emoji="📤", style=discord.ButtonStyle.secondary, row=3)
    async def set_goodbye(self, interaction, button):
        await self.set_current_channel(interaction, "goodbye_channel")

    @discord.ui.button(label="Mark Complete", emoji="✅", style=discord.ButtonStyle.success, row=4)
    async def mark_complete(self, interaction, button):
        update_guild_settings(interaction.guild_id, setup_completed=True)
        await interaction.response.edit_message(embed=build_setup_embed(interaction.guild), view=self)


class Setup(commands.Cog):
    """A friendly setup dashboard for new servers."""

    EMOJI = "🚀"
    COLOR = Palette.SUCCESS
    DESCRIPTION = "One-command onboarding and server configuration."

    config = app_commands.Group(
        name="config",
        description="Advanced NovaGuard configuration",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Open the NovaGuard setup dashboard")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await respond(interaction, build_setup_embed(interaction.guild), view=SetupView(), ephemeral=True)

    @config.command(name="view", description="View the saved NovaGuard configuration")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await respond(interaction, build_config_embed(interaction.guild), ephemeral=True)

    @config.command(name="export", description="Export this server's NovaGuard config as JSON")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = make_embed(
            "📦 Config export ready",
            "This file contains server setup settings only. It does not include bot tokens or API keys.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Config export")
        await interaction.followup.send(embed=embed, file=export_config_file(interaction.guild), ephemeral=True)

    @config.command(name="backup", description="Create a manual backup archive now")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_backup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        backup = await self.bot.loop.run_in_executor(None, create_backup, "manual")
        embed = make_embed(
            "🧳 Backup created",
            f"`{backup['name']}`\nIncluded `{len(backup['included'])}` state file(s).",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Manual backup")
        await respond(interaction, embed, ephemeral=True)

    @config.command(name="reset", description="Reset NovaGuard setup/config for this server")
    @app_commands.describe(confirm="Set to true to confirm the reset")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_reset(self, interaction: discord.Interaction, confirm: bool = False):
        await interaction.response.defer(ephemeral=True)
        if not confirm:
            embed = make_embed(
                "⚠️ Reset confirmation needed",
                "Run `/config reset confirm:true` to clear saved setup channels/settings for this server.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Config reset")
            return await respond(interaction, embed, ephemeral=True)

        reset_guild_settings(interaction.guild_id)
        embed = make_embed(
            "🧹 Config reset",
            "Saved setup channels/settings were cleared. Run `/setup` to configure NovaGuard again.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Config reset")
        await respond(interaction, embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if not (perms.send_messages and perms.embed_links):
                continue

            try:
                await channel.send(embed=build_setup_embed(guild), view=SetupView())
            except discord.HTTPException:
                continue
            break


async def setup(bot):
    await bot.add_cog(Setup(bot))
