"""📋 Logs category — a clean audit trail for messages, members and moderation."""

import discord
from discord import app_commands
from discord.ext import commands

from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond, truncate


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

    async def send_log(self, guild, embed):
        if guild is None:
            return
        settings = get_guild_settings(guild.id)
        channel_id = settings.get("log_channel")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
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
