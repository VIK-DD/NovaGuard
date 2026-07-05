"""👋 Welcome category — colorful join/leave embeds and auto-role for newcomers."""

import random

import discord
from discord import app_commands
from discord.ext import commands

from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond

WELCOME_LINES = [
    "Great to have you here, {mention}! Make yourself at home. 🏡",
    "{mention} just landed! Everyone act natural. 😎",
    "A wild {mention} appeared! ✨",
    "Welcome aboard, {mention} — grab a seat and enjoy the ride! 🚀",
    "{mention} has entered the chat. The vibes just improved. 🌈",
]
GOODBYE_LINES = [
    "**{name}** has left the server. Safe travels! 🌊",
    "**{name}** logged off for the last time. o7",
    "Goodbye, **{name}** — the door is always open. 🚪",
]


def build_welcome_embed(member):
    line = random.choice(WELCOME_LINES).format(mention=member.mention)
    embed = make_embed(f"👋 Welcome to {member.guild.name}!", line, color=Palette.SUCCESS)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(
        name="🎉 You are",
        value=f"Member `#{member.guild.member_count}`",
        inline=True,
    )
    embed.add_field(
        name="📅 Account created",
        value=discord.utils.format_dt(member.created_at, "R"),
        inline=True,
    )
    brand_footer(embed, "Welcome system")
    return embed


def build_goodbye_embed(member):
    line = random.choice(GOODBYE_LINES).format(name=member.display_name)
    embed = make_embed("🚪 Someone left…", line, color=Palette.ORANGE)
    embed.set_thumbnail(url=member.display_avatar.url)
    brand_footer(embed, f"{member.guild.member_count} members remain")
    return embed


class Welcome(commands.Cog):
    """Join/leave announcements and automatic roles."""

    EMOJI = "👋"
    COLOR = Palette.SUCCESS
    DESCRIPTION = "Welcome & goodbye embeds plus auto-role for new members."

    welcome = app_commands.Group(
        name="welcome",
        description="Welcome system setup",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        settings = get_guild_settings(member.guild.id)

        autorole_id = settings.get("autorole")
        if autorole_id:
            role = member.guild.get_role(autorole_id)
            if role and role < member.guild.me.top_role:
                try:
                    await member.add_roles(role, reason="Auto-role for new members")
                except discord.HTTPException:
                    pass

        channel_id = settings.get("welcome_channel")
        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=build_welcome_embed(member))
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        settings = get_guild_settings(member.guild.id)
        channel_id = settings.get("goodbye_channel") or settings.get("welcome_channel")
        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=build_goodbye_embed(member))
                except discord.HTTPException:
                    pass

    @welcome.command(name="set", description="Configure welcome channel, auto-role and goodbye channel")
    @app_commands.describe(
        channel="Where welcome messages go",
        autorole="Role given automatically to new members (optional)",
        goodbye_channel="Where goodbye messages go (defaults to the welcome channel)",
    )
    async def welcome_set(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        autorole: discord.Role | None = None,
        goodbye_channel: discord.TextChannel | None = None,
    ):
        if autorole and autorole >= interaction.guild.me.top_role:
            embed = make_embed(
                "🔒 Role too high",
                f"{autorole.mention} is above my top role — I cannot assign it. Move my role higher or pick another.",
                color=Palette.DANGER,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        update_guild_settings(
            interaction.guild_id,
            welcome_channel=channel.id,
            autorole=autorole.id if autorole else None,
            goodbye_channel=goodbye_channel.id if goodbye_channel else None,
        )
        embed = make_embed(
            "✅ Welcome system configured",
            (
                f"Welcome channel: {channel.mention}\n"
                f"Auto-role: {autorole.mention if autorole else '`None`'}\n"
                f"Goodbye channel: {goodbye_channel.mention if goodbye_channel else channel.mention}"
            ),
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Welcome system")
        await respond(interaction, embed)

    @welcome.command(name="off", description="Disable welcome & goodbye messages")
    async def welcome_off(self, interaction: discord.Interaction):
        update_guild_settings(interaction.guild_id, welcome_channel=None, goodbye_channel=None, autorole=None)
        embed = make_embed("🔕 Welcome system disabled", "No more join/leave messages.", color=Palette.WARNING)
        brand_footer(embed)
        await respond(interaction, embed)

    @welcome.command(name="test", description="Preview the welcome embed with yourself")
    async def welcome_test(self, interaction: discord.Interaction):
        await respond(interaction, build_welcome_embed(interaction.user))


async def setup(bot):
    await bot.add_cog(Welcome(bot))
