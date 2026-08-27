"""🚀 Setup category — one-command onboarding and server configuration."""

import asyncio
import io
import json

import discord
from discord import app_commands
from discord.ext import commands

from core.backups import (
    create_backup,
    inspect_backup,
    latest_backup,
    list_backups,
    refresh_latest_remote_check,
    remote_backup_status,
)
from core.backup_presenters import (
    backup_contents_text,
    backup_errors_text,
    backup_health_summary,
    backup_inspect_embed,
    backup_integrity_line,
    backup_list_embed,
    backup_remote_embed,
    backup_remote_text,
    backup_restore_plan_embed,
    backup_status_embed,
    backup_test_embed,
    deletion_ledger_text,
)
from cogs.admin import require_admin
from core.config import github_config
from core.privacy import export_guild_data
from core.restore_drill import run_restore_drill
from core.storage import get_guild_settings, reset_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import defer_interaction, respond


CHANNEL_KEYS = {
    "update_channel": ("🚀 Bot Updates", "Automatic code changelog and restart summaries"),
    "github_event_channel": ("🐙 GitHub Feed", "Push, PR, issue and release activity"),
    "error_log_channel": ("🚨 Admin Errors", "Serious bot error digest embeds"),
    "log_channel": ("📋 Server Logs", "Deleted/edited messages, joins/leaves, bans"),
    "voice_report_channel": ("🎙️ Voice Reports", "Completed voice session attendance and duration reports"),
    "status_channel": ("📡 Service Status", "Public status card, refreshed twice a day"),
    "welcome_channel": ("👋 Welcome", "New member welcome cards"),
    "goodbye_channel": ("📤 Goodbye", "Leave messages"),
}

RECOMMENDED_KEYS = (
    "update_channel",
    "error_log_channel",
    "log_channel",
    "welcome_channel",
)

SETUP_PRIVACY_NOTICE = (
    "Review `/privacy policy` and tell members which optional features you enable. "
    "Server Logs can repost deleted/edited message excerpts inside Discord; `/ask` sends only "
    "the submitted question to Anthropic when AI is available. Every member can use "
    "`/privacy export` or `/privacy delete`."
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


def build_setup_embed(guild, notice=None):
    settings = get_guild_settings(guild.id)
    done, total = setup_score(settings)
    ratio_text = f"{done}/{total}"
    completed = bool(settings.get("setup_completed"))

    if completed:
        color = Palette.SUCCESS
        title = "✅ NovaGuard Setup — Complete"
        status = (
            "**Setup is marked complete.** Every channel below is optional — NovaGuard "
            "runs fine with none, some, or all of them set. Re-open `/setup` anytime to change things."
        )
    else:
        color = Palette.PRIMARY if not done else Palette.INFO
        title = "🚀 NovaGuard Setup"
        status = (
            "Every channel here is **optional** — set the ones you want, leave the rest empty. "
            "Choose a setting in the first menu, then pick its channel in the second. "
            "**Clear** removes the chosen setting, and **Mark complete** finishes "
            "(even with nothing set)."
        )

    # The panel is one message that rewrites itself, so the result of the last
    # action belongs at the top of it. A blockquote is what makes it read as an
    # answer: prepended as plain text it just grew the paragraph below, and
    # people could not tell whether anything had been saved.
    if notice:
        status = f"> {notice}\n\n{status}"

    embed = make_embed(title, status, color=color)
    embed.add_field(
        name="Optional channels set",
        value=f"{progress_bar(done, total, slots=12)} `{ratio_text}` configured — all optional",
        inline=False,
    )

    core_lines = []
    for key in ("update_channel", "github_event_channel", "error_log_channel", "log_channel"):
        label, description = CHANNEL_KEYS[key]
        core_lines.append(f"{label}: {mention_channel(guild, settings.get(key))}\n`{description}`")
    embed.add_field(name="Core Channels", value="\n\n".join(core_lines), inline=False)

    community_lines = []
    for key in ("welcome_channel", "goodbye_channel", "voice_report_channel"):
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
    embed.add_field(name="Privacy before enabling features", value=SETUP_PRIVACY_NOTICE, inline=False)
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
    """A server administrator's complete guild-scoped privacy export.

    The /backup group archives every guild at once and is the bot owner's,
    so this is how a single server takes its own data out - scoped by
    guild_id, with nothing from anyone else in it.
    """
    payload = export_guild_data(guild.id)
    payload["guild_name"] = guild.name
    data = json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")
    return discord.File(io.BytesIO(data), filename=f"novaguard-{guild.id}.json")


def find_backup(name=None):
    backups = list_backups()
    if not name:
        return backups[0] if backups else None
    target = name.strip()
    for backup in backups:
        if backup["name"] == target:
            return backup
    return None


def plain_label(key):
    """The menu label without its emoji, for reading inside a sentence."""
    label, _ = CHANNEL_KEYS[key]
    head, _, rest = label.partition(" ")
    return rest if rest and not head.isalnum() else label


class SetupTargetSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=plain_label(key), value=key, description=description[:100])
            for key, (_label, description) in CHANNEL_KEYS.items()
        ]
        super().__init__(
            placeholder="1. Choose what to configure…",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction):
        key = self.values[0]
        self.view.pending_key = key
        # Blank the channel menu, or it still shows the channel used for the
        # previous setting and this one looks already answered.
        self.view.start_target()
        await self.view.refresh(
            interaction,
            f"📝 Now choose the channel for **{plain_label(key)}** in the menu below.",
        )


class SetupChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="2. Choose a setting above first…",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            row=1,
            disabled=True,
        )

    async def callback(self, interaction):
        key = self.view.pending_key
        if not key:
            # The old panel defaulted to update_channel here and wrote there
            # without telling anyone. Refusing is the only honest answer.
            return await self.view.refresh(
                interaction, "⚠️ Nothing saved — choose what to configure first, then pick its channel."
            )
        channel = self.values[0]
        await self.view.save(interaction, key, channel.id, channel.mention)


class SetupView(discord.ui.View):
    """One message that rewrites itself, holding all of its state in the open.

    Discord clears a select menu whenever the message is edited, so any state
    kept only in a variable goes invisible the moment the panel updates. That
    is what made the previous panel write a second channel over the first.
    Here the pending setting is always mirrored into the channel menu's label
    and into the embed, and it is cleared the instant a save lands.
    """

    def __init__(self):
        super().__init__(timeout=900)
        self.pending_key = None
        self.target_select = SetupTargetSelect()
        self.channel_select = SetupChannelSelect()
        self.add_item(self.target_select)
        self.add_item(self.channel_select)
        self._sync()

    def _replace(self, attribute, factory):
        """Swap a menu for an identical, unanswered one.

        A select's chosen value is drawn by the Discord client and keyed to the
        component's custom_id — not to anything sent back with the edit.
        discord.py mints that id once, in the constructor, so re-sending the
        same item leaves the previous pick sitting in the menu: after saving
        Bot Updates to #general the channel picker still read "#general", and
        the next setting looked answered before it had been touched. A new
        item carries a new id, which is what makes the client draw it empty.
        """
        old = getattr(self, attribute)
        self.remove_item(old)
        new = factory()
        new.row = old.row
        setattr(self, attribute, new)
        self.add_item(new)

    def _sync(self):
        """Make the channel menu describe exactly what it is about to set."""
        if self.pending_key:
            self.channel_select.placeholder = f"2. Pick the channel for {plain_label(self.pending_key)}…"
            self.channel_select.disabled = False
        else:
            self.channel_select.placeholder = "2. Choose a setting above first…"
            self.channel_select.disabled = True

    def start_target(self):
        """A setting has been chosen; the channel menu must arrive blank."""
        self._replace("channel_select", SetupChannelSelect)

    def finish_action(self):
        """An action landed. Both menus go back to asking, not answering.

        The setting menu is only reset here, never while a choice is pending:
        between picking a setting and giving it a channel, that setting is the
        question on screen, and blanking it would leave a channel picker with
        nothing saying what it is for.
        """
        self.pending_key = None
        self._replace("target_select", SetupTargetSelect)
        self._replace("channel_select", SetupChannelSelect)

    async def refresh(self, interaction, notice=None):
        self._sync()
        await interaction.response.edit_message(
            embed=build_setup_embed(interaction.guild, notice=notice),
            view=self,
        )

    async def confirm(self, interaction, title, description):
        """Say what just happened, in a message of its own.

        The panel carries the same line already, quoted at the top. It was
        being missed: the embed below it is long, and a single quoted line
        loses to four blocks of settings. This lands under the panel, where
        the reader is already looking after clicking.

        Deliberately not a second panel — no view, nothing interactive. That
        is what made the original version unusable, with the real panel
        scrolling away behind its own confirmations.
        """
        embed = make_embed(title, description, color=Palette.SUCCESS)
        brand_footer(embed, "Server setup")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def save(self, interaction, key, channel_id, mention):
        update_guild_settings(interaction.guild_id, **{key: channel_id})
        # Cleared before the redraw: a target that outlived its save is what
        # let the next channel picked silently replace the previous setting.
        self.finish_action()
        label = plain_label(key)
        await self.refresh(interaction, f"✅ Saved **{label}** to {mention}.")
        await self.confirm(
            interaction,
            "✅ Saved",
            f"**{label}** now points at {mention}.\n\nPick another setting above, "
            "or press **Mark complete** when you are done.",
        )

    async def interaction_check(self, interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Only members with **Manage Server** can use setup.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Use this channel", emoji="📍", style=discord.ButtonStyle.primary, row=2)
    async def use_this_channel(self, interaction, button):
        key = self.pending_key
        if not key:
            return await self.refresh(interaction, "⚠️ Nothing saved — choose what to configure first.")
        # get_channel returns guild channels only, so a thread or a DM cannot
        # be saved as somewhere the bot will later post.
        channel = interaction.guild.get_channel(interaction.channel_id) if interaction.guild else None
        if channel is None:
            return await self.refresh(interaction, "⚠️ Nothing saved — run `/setup` in a normal server text channel.")
        await self.save(interaction, key, channel.id, channel.mention)

    @discord.ui.button(label="Clear", emoji="🗑️", style=discord.ButtonStyle.secondary, row=2)
    async def clear_selected(self, interaction, button):
        key = self.pending_key
        if not key:
            return await self.refresh(interaction, "⚠️ Nothing cleared — choose the setting from the menu above first.")
        update_guild_settings(interaction.guild_id, **{key: None})
        self.finish_action()
        label = plain_label(key)
        await self.refresh(interaction, f"🗑️ Cleared **{label}** — it is now unset.")
        await self.confirm(
            interaction,
            "🗑️ Cleared",
            f"**{label}** is unset. NovaGuard will not post there until you choose "
            "a channel for it again.",
        )

    @discord.ui.button(label="Mark complete", emoji="✅", style=discord.ButtonStyle.success, row=2)
    async def mark_complete(self, interaction, button):
        update_guild_settings(interaction.guild_id, setup_completed=True)
        self.finish_action()
        await self.refresh(
            interaction,
            "✅ Setup marked complete — every channel stays optional, and `/setup` reopens anytime.",
        )
        await self.confirm(
            interaction,
            "✅ Setup complete",
            "NovaGuard is ready. Nothing is locked in — run `/setup` again whenever "
            "you want to change a channel.",
        )


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
    backup = app_commands.Group(
        name="backup",
        description="NovaGuard backup safety tools",
        # These archive every guild at once, so they belong to the bot owner.
        # Discord cannot express "bot owner", and administrator is the
        # narrowest thing it offers: server admins still see them and are
        # refused by the owner check, ordinary members never see them.
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Open the NovaGuard setup dashboard")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup_command(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        await respond(interaction, build_setup_embed(interaction.guild), view=SetupView(), ephemeral=True)

    @config.command(name="view", description="View the saved NovaGuard configuration")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_view(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        await respond(interaction, build_config_embed(interaction.guild), ephemeral=True)

    @config.command(name="export", description="Export this server's NovaGuard config as JSON")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_export(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        embed = make_embed(
            "📦 Server export ready",
            "This file contains all live NovaGuard data scoped to this server. It never includes bot tokens or API keys.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Config export")
        await interaction.followup.send(embed=embed, file=export_config_file(interaction.guild), ephemeral=True)

    @config.command(name="backup", description="Create a manual backup archive now")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_backup(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        # Archives every guild's data, not just this one, so it is the bot
        # owner's to run. Server admins export their own guild with
        # /config export.
        if not await require_admin(interaction, self.bot, action="backup.create"):
            return
        backup = await self.bot.loop.run_in_executor(None, create_backup, "manual")
        embed = make_embed(
            "🧳 Backup created",
            f"`{backup['name']}`\nIncluded `{len(backup['included'])}` state file(s).",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Manual backup")
        await respond(interaction, embed, ephemeral=True)

    @backup.command(name="create", description="Create and verify a manual backup archive now")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_create(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.create"):
            return
        backup = await asyncio.to_thread(create_backup, "manual")
        latest = {
            "name": backup["name"],
            "size_text": backup["size_text"],
            "mtime": discord.utils.utcnow(),
        }
        embed = backup_status_embed(latest, backup["integrity"])
        embed.title = "🧳 Backup created"
        await respond(interaction, embed, ephemeral=True)

    @backup.command(name="status", description="Check the newest backup archive and restore readiness")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_status(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.status"):
            return
        latest = latest_backup()
        report = await asyncio.to_thread(inspect_backup, latest["path"]) if latest else None
        await respond(interaction, backup_status_embed(latest, report), ephemeral=True)

    @backup.command(name="remote", description="Show Google Drive/off-site backup upload status")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_remote(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        # Exposes the off-site destination path, which is worth protecting on
        # its own.
        if not await require_admin(interaction, self.bot, action="backup.remote"):
            return
        latest = latest_backup()
        current_status = remote_backup_status(latest["name"] if latest else None)
        if current_status.get("configured") and current_status.get("latest"):
            status = await asyncio.to_thread(refresh_latest_remote_check, latest["name"] if latest else None)
        else:
            status = current_status
        await respond(interaction, backup_remote_embed(status), ephemeral=True)

    @backup.command(name="list", description="List the newest backup archives")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_list(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.list"):
            return
        backups = await asyncio.to_thread(list_backups, 8)
        await respond(interaction, backup_list_embed(backups), ephemeral=True)

    @backup.command(name="inspect", description="Inspect a local backup archive without restoring it")
    @app_commands.describe(name="Backup archive name; leave empty for the latest backup")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_inspect(self, interaction: discord.Interaction, name: str | None = None):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.inspect"):
            return
        backup = await asyncio.to_thread(find_backup, name)
        if not backup:
            embed = make_embed(
                "Backup not found",
                "No matching local backup archive exists. Use `/backup list` to see available archives.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Backup inspect")
            return await respond(interaction, embed, ephemeral=True)
        report = await asyncio.to_thread(inspect_backup, backup["path"])
        await respond(interaction, backup_inspect_embed(backup, report), ephemeral=True)

    @backup.command(name="test", description="Extract and verify the newest backup without touching live data")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_test(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.test"):
            return
        latest = latest_backup()
        if not latest:
            return await respond(interaction, backup_status_embed(None), ephemeral=True)
        report = await asyncio.to_thread(run_restore_drill, latest["path"])
        await respond(interaction, backup_test_embed(latest, report), ephemeral=True)

    @backup.command(name="restore", description="Show a safe manual restore plan for a backup")
    @app_commands.describe(name="Backup archive name; leave empty for the latest backup")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_restore(self, interaction: discord.Interaction, name: str | None = None):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.restore"):
            return
        backup = await asyncio.to_thread(find_backup, name)
        if not backup:
            embed = make_embed(
                "Backup not found",
                "No matching local backup archive exists. Use `/backup list` to see available archives.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Backup restore plan")
            return await respond(interaction, embed, ephemeral=True)
        report = await asyncio.to_thread(inspect_backup, backup["path"])
        await respond(interaction, backup_restore_plan_embed(backup, report), ephemeral=True)

    @config.command(name="reset", description="Reset NovaGuard setup/config for this server")
    @app_commands.describe(confirm="Set to true to confirm the reset")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_reset(self, interaction: discord.Interaction, confirm: bool = False):
        await defer_interaction(interaction, ephemeral=True)
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

    # Arrival is handled by cogs/infopanel.py now. This panel used to be posted
    # publicly on join, which showed every member a control surface that
    # refuses them the moment they touch it. The introduction card goes out
    # instead, and its "Open setup" button opens this one privately for anyone
    # holding Manage Server.


async def setup(bot):
    await bot.add_cog(Setup(bot))
