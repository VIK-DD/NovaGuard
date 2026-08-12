"""Privacy controls available directly inside Discord."""

import asyncio
import io
import json
from contextlib import AsyncExitStack

import discord
from discord import app_commands
from discord.ext import commands

from core.privacy import (
    erase_guild_data,
    erase_user_data,
    export_guild_data,
    export_user_data,
    scrub_user_state,
)
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, respond


PRIVACY_URL = "https://novaguard.fun/privacy"
USER_DELETE_CONFIRMATION = "DELETE MY DATA"
GUILD_DELETE_CONFIRMATION = "DELETE SERVER DATA"


def _json_file(payload, filename):
    content = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    return discord.File(io.BytesIO(content), filename=filename)


def _live_cogs(bot):
    return {
        "levels": bot.get_cog("Levels"),
        "economy": bot.get_cog("Economy"),
        "voice": bot.get_cog("VoiceReports"),
    }


async def flush_live_privacy_state(bot):
    """Persist dirty feature caches before producing an access export."""
    cogs = _live_cogs(bot)
    for name in ("levels", "economy"):
        cog = cogs[name]
        if cog is not None:
            await cog.flush()
    voice = cogs["voice"]
    if voice is not None:
        await voice._persist()
        await voice._persist_pending()
        await voice._persist_history()


def _runtime_locks(cogs):
    locks = []
    for cog, names in (
        (cogs["levels"], ("flush_lock",)),
        (cogs["economy"], ("flush_lock",)),
        (cogs["voice"], ("_persist_lock", "_pending_lock", "_history_lock")),
    ):
        if cog is None:
            continue
        locks.extend(getattr(cog, name) for name in names if hasattr(cog, name))
    return locks


async def erase_live_user_data(bot, user_id):
    """Erase persisted data while preventing dirty caches from restoring it."""
    user_id = str(user_id)
    cogs = _live_cogs(bot)
    async with AsyncExitStack() as stack:
        for lock in _runtime_locks(cogs):
            await stack.enter_async_context(lock)
        report = await asyncio.to_thread(erase_user_data, user_id)

        for name in ("levels", "economy"):
            cog = cogs[name]
            if cog is None:
                continue
            for guild_id in list(cog.data):
                members = cog.data.get(guild_id)
                if isinstance(members, dict):
                    members.pop(user_id, None)
                    if not members:
                        cog.data.pop(guild_id, None)
            cog.dirty_keys = {key for key in cog.dirty_keys if key[1] != user_id}

        voice = cogs["voice"]
        if voice is not None:
            for attribute in ("sessions", "pending_reports", "report_history"):
                cleaned, _ = scrub_user_state(getattr(voice, attribute), user_id)
                setattr(voice, attribute, cleaned)
    return report


async def erase_live_guild_data(bot, guild_id):
    """Erase a guild from disk and every feature cache in one critical section."""
    guild_id = str(guild_id)
    cogs = _live_cogs(bot)
    async with AsyncExitStack() as stack:
        for lock in _runtime_locks(cogs):
            await stack.enter_async_context(lock)
        report = await asyncio.to_thread(erase_guild_data, guild_id)

        for name in ("levels", "economy"):
            cog = cogs[name]
            if cog is None:
                continue
            cog.data.pop(guild_id, None)
            cog.dirty_keys = {key for key in cog.dirty_keys if key[0] != guild_id}

        voice = cogs["voice"]
        if voice is not None:
            voice.sessions.pop(guild_id, None)
            voice.pending_reports.pop(guild_id, None)
            voice.report_history.pop(guild_id, None)
    return report


class Privacy(commands.Cog):
    """Transparent access, export and deletion controls."""

    EMOJI = "🔏"
    COLOR = Palette.TEAL
    DESCRIPTION = "See NovaGuard's privacy rules, export your data or request deletion."

    privacy = app_commands.Group(name="privacy", description="Privacy, export and deletion controls")

    def __init__(self, bot):
        self.bot = bot

    @privacy.command(name="policy", description="See what NovaGuard stores and why")
    async def privacy_policy(self, interaction: discord.Interaction):
        embed = make_embed(
            "🔏 Your privacy in NovaGuard",
            "NovaGuard does not sell personal data or use advertising trackers. "
            "You can export or erase your stored records directly below.",
            color=Palette.TEAL,
        )
        embed.add_field(
            name="Controls",
            value=(
                "`/privacy export` — download your own data\n"
                "`/privacy delete` — export, then erase your own data\n"
                "`/privacy server-export` — server administrator export"
            ),
            inline=False,
        )
        embed.add_field(
            name="Full policy",
            value=f"[Read the Privacy Policy]({PRIVACY_URL})",
            inline=False,
        )
        brand_footer(embed, "Privacy controls")
        await respond(interaction, embed, ephemeral=True)

    @privacy.command(name="export", description="Privately download the data tied to your Discord ID")
    async def privacy_export(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        await flush_live_privacy_state(self.bot)
        payload = await asyncio.to_thread(export_user_data, interaction.user.id)
        embed = make_embed(
            "📦 Your private export is ready",
            "The attachment contains NovaGuard records tied to your Discord ID. "
            "OAuth tokens and session secrets are never included.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Personal data export")
        await interaction.followup.send(
            embed=embed,
            file=_json_file(payload, f"novaguard-user-{interaction.user.id}.json"),
            ephemeral=True,
        )

    @privacy.command(name="delete", description="Export, then erase data tied to your Discord ID")
    @app_commands.describe(confirmation=f"Type {USER_DELETE_CONFIRMATION} exactly")
    async def privacy_delete(self, interaction: discord.Interaction, confirmation: str):
        await defer_interaction(interaction, ephemeral=True)
        if confirmation.strip() != USER_DELETE_CONFIRMATION:
            embed = make_embed(
                "Deletion not confirmed",
                f"Nothing changed. Run the command again and type `{USER_DELETE_CONFIRMATION}` exactly.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Privacy deletion")
            return await respond(interaction, embed, ephemeral=True)

        await flush_live_privacy_state(self.bot)
        payload = await asyncio.to_thread(export_user_data, interaction.user.id)
        report = await erase_live_user_data(self.bot, interaction.user.id)
        removed = sum(report["counts"].values())
        embed = make_embed(
            "🧹 Your NovaGuard data was erased",
            f"Removed or anonymised `{removed}` live record reference(s). "
            "Your final pre-deletion export is attached. New voluntary use of NovaGuard may create new records.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Personal data deletion")
        await interaction.followup.send(
            embed=embed,
            file=_json_file(payload, f"novaguard-user-{interaction.user.id}-final.json"),
            ephemeral=True,
        )

    @privacy.command(name="server-export", description="Export all NovaGuard data for this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def privacy_server_export(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        await flush_live_privacy_state(self.bot)
        payload = await asyncio.to_thread(export_guild_data, interaction.guild_id)
        payload["guild_name"] = interaction.guild.name
        embed = make_embed(
            "📦 Server privacy export ready",
            "This administrator-only attachment contains all live NovaGuard state scoped to this server.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Server data export")
        await interaction.followup.send(
            embed=embed,
            file=_json_file(payload, f"novaguard-server-{interaction.guild_id}.json"),
            ephemeral=True,
        )

    @privacy.command(
        name="server-delete",
        description="Export and permanently remove NovaGuard from this server",
    )
    @app_commands.describe(confirmation=f"Type {GUILD_DELETE_CONFIRMATION} exactly")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def privacy_server_delete(self, interaction: discord.Interaction, confirmation: str):
        await defer_interaction(interaction, ephemeral=True)
        if interaction.user.id != interaction.guild.owner_id:
            embed = make_embed(
                "Server owner required",
                "Only the Discord server owner can erase all server data and remove NovaGuard.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Server data deletion")
            return await respond(interaction, embed, ephemeral=True)
        if confirmation.strip() != GUILD_DELETE_CONFIRMATION:
            embed = make_embed(
                "Deletion not confirmed",
                f"Nothing changed. Run the command again and type `{GUILD_DELETE_CONFIRMATION}` exactly.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Server data deletion")
            return await respond(interaction, embed, ephemeral=True)

        await flush_live_privacy_state(self.bot)
        payload = await asyncio.to_thread(export_guild_data, interaction.guild_id)
        payload["guild_name"] = interaction.guild.name
        report = await erase_live_guild_data(self.bot, interaction.guild_id)
        removed = sum(report["counts"].values())
        embed = make_embed(
            "🧹 Server data erased",
            f"Removed `{removed}` live record(s). The final export is attached and NovaGuard will now leave the server.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Server data deletion")
        await interaction.followup.send(
            embed=embed,
            file=_json_file(payload, f"novaguard-server-{interaction.guild_id}-final.json"),
            ephemeral=True,
        )
        await interaction.guild.leave()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await erase_live_guild_data(self.bot, guild.id)


async def setup(bot):
    await bot.add_cog(Privacy(bot))
