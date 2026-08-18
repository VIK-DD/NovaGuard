"""📋 Logs category — a clean audit trail for messages, members and moderation."""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond, truncate

log = logging.getLogger(__name__)


LOG_SEND_TIMEOUT_SECONDS = 10
LOG_QUEUE_MAXSIZE = 100


class Logs(commands.Cog):
    """Server logging: deleted/edited messages, joins/leaves, bans and mod actions."""

    EMOJI = "📋"
    COLOR = 0x95A5A6
    DESCRIPTION = "Logs deleted/edited messages, joins, bans and moderation actions."

    logs = app_commands.Group(
        name="logs",
        description="Logging system setup",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot
        self._queue: asyncio.Queue[tuple[int, int, discord.Embed]] = asyncio.Queue(maxsize=LOG_QUEUE_MAXSIZE)
        self._worker_task: asyncio.Task | None = None

    async def cog_load(self):
        self._worker_task = asyncio.create_task(self._log_worker())

    async def cog_unload(self):
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()

    async def send_log(self, guild, embed):
        if guild is None:
            return
        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        channel_id = settings.get("log_channel")
        if not channel_id:
            return

        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            return

        try:
            self._queue.put_nowait((guild.id, channel_id, embed))
        except asyncio.QueueFull:
            log.warning(f"Server log skipped for guild #{guild.id}: log queue is full")

    async def _log_worker(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            guild_id, channel_id, embed = await self._queue.get()
            try:
                guild = self.bot.get_guild(guild_id)
                channel = guild.get_channel(channel_id) if guild else None
                if channel is None:
                    continue
                await asyncio.wait_for(
                    channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none()),
                    timeout=LOG_SEND_TIMEOUT_SECONDS,
                )
            except (discord.HTTPException, asyncio.TimeoutError) as error:
                log.warning(f"Server log skipped for channel #{channel_id}: {error!r}")
            finally:
                self._queue.task_done()

    async def _flush_logs(self):
        try:
            await asyncio.wait_for(self._queue.join(), timeout=LOG_SEND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            pass

    @logs.command(name="set", description="Choose the channel where logs are posted")
    @app_commands.describe(channel="The log channel")
    async def logs_set(self, interaction: discord.Interaction, channel: discord.TextChannel):
        update_guild_settings(interaction.guild_id, log_channel=channel.id)
        embed = make_embed("✅ Logging enabled", f"All server logs will go to {channel.mention}.", color=Palette.SUCCESS)
        brand_footer(embed, "Logging system")
        await respond(interaction, embed)

    @logs.command(name="off", description="Disable logging")
    async def logs_off(self, interaction: discord.Interaction):
        update_guild_settings(interaction.guild_id, log_channel=None)
        embed = make_embed("🔕 Logging disabled", "I will stop posting server logs.", color=Palette.WARNING)
        brand_footer(embed)
        await respond(interaction, embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None or message.author.bot or not message.content:
            return
        embed = make_embed(
            "🗑️ Message deleted",
            f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n\n>>> {truncate(message.content, 500)}",
            color=Palette.DANGER,
        )
        brand_footer(embed, f"Author ID: {message.author.id}")
        await self.send_log(message.guild, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        embed = make_embed(
            "✏️ Message edited",
            f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention} • [Jump]({after.jump_url})",
            color=Palette.WARNING,
        )
        embed.add_field(name="Before", value=truncate(before.content, 400) or "*empty*", inline=False)
        embed.add_field(name="After", value=truncate(after.content, 400) or "*empty*", inline=False)
        brand_footer(embed, f"Author ID: {before.author.id}")
        await self.send_log(before.guild, embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        embed = make_embed(
            "📥 Member joined",
            f"{member.mention} • `{member.id}`\nAccount created {discord.utils.format_dt(member.created_at, 'R')}",
            color=Palette.SUCCESS,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        brand_footer(embed, f"{member.guild.member_count} members")
        await self.send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        embed = make_embed(
            "📤 Member left",
            f"**{member.display_name}** • `{member.id}`\nJoined {discord.utils.format_dt(member.joined_at, 'R') if member.joined_at else 'Unknown'}",
            color=Palette.ORANGE,
        )
        brand_footer(embed, f"{member.guild.member_count} members")
        await self.send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        embed = make_embed("🔨 Member banned", f"**{user.display_name}** • `{user.id}`", color=Palette.DANGER)
        brand_footer(embed, "Ban event")
        await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        embed = make_embed("🕊️ Member unbanned", f"**{user.display_name}** • `{user.id}`", color=Palette.SUCCESS)
        brand_footer(embed, "Unban event")
        await self.send_log(guild, embed)

    @commands.Cog.listener("on_modlog")
    async def on_modlog(self, guild, embed):
        await self.send_log(guild, embed)


async def setup(bot):
    await bot.add_cog(Logs(bot))
