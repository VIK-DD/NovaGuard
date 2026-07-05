"""🛡️ Moderation category — clean, safe and fully slash-native mod tools."""

from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from core.storage import load_data, save_data
from core.theme import Palette, brand_footer, make_embed
from core.utils import parse_duration, respond, truncate


def can_act_on(actor: discord.Member, target: discord.Member) -> bool:
    guild = actor.guild
    if target == guild.owner:
        return False
    if actor != guild.owner and target.top_role >= actor.top_role:
        return False
    return target.top_role < guild.me.top_role


async def hierarchy_error(interaction):
    embed = make_embed(
        "🔒 Role hierarchy says no",
        "That member's top role is too high for you or for me to act on them.",
        color=Palette.DANGER,
    )
    brand_footer(embed)
    await respond(interaction, embed, ephemeral=True)


class Moderation(commands.Cog):
    """Moderation tools with polished feedback."""

    EMOJI = "🛡️"
    COLOR = Palette.DANGER
    DESCRIPTION = "Purge, kick, ban, timeouts, slowmode, announcements and warnings."

    warn = app_commands.Group(
        name="warn",
        description="Warning system for moderators",
        default_permissions=discord.Permissions(moderate_members=True),
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="purge", description="Bulk delete recent messages")
    @app_commands.describe(amount="How many messages (1-100)", user="Only delete messages from this member")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    @app_commands.guild_only()
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
        user: discord.Member | None = None,
    ):
        channel = interaction.channel
        if not hasattr(channel, "purge"):
            embed = make_embed("🚫 Wrong place", "I cannot purge this type of channel.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        deleted = await channel.purge(limit=amount, check=lambda m: user is None or m.author.id == user.id)

        target_note = f" from {user.mention}" if user else ""
        embed = make_embed("🧹 Channel cleaned", f"Deleted `{len(deleted)}` message(s){target_note}.", color=Palette.SUCCESS)
        brand_footer(embed, "Purge complete")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="Who gets the boot?", reason="Why?")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None):
        if not can_act_on(interaction.user, member):
            return await hierarchy_error(interaction)

        await member.kick(reason=f"{interaction.user} • {reason or 'No reason given'}")
        embed = make_embed(
            "🥾 Member kicked",
            f"**{member.display_name}** was kicked.\n> {reason or 'No reason given'}",
            color=Palette.ORANGE,
        )
        brand_footer(embed, f"By {interaction.user.display_name}")
        await respond(interaction, embed)
        self.bot.dispatch("modlog", interaction.guild, embed)

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.describe(member="Who gets banned?", reason="Why?")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None):
        if not can_act_on(interaction.user, member):
            return await hierarchy_error(interaction)

        await interaction.guild.ban(member, reason=f"{interaction.user} • {reason or 'No reason given'}")
        embed = make_embed(
            "🔨 Member banned",
            f"**{member.display_name}** is gone for good.\n> {reason or 'No reason given'}",
            color=Palette.DANGER,
        )
        brand_footer(embed, f"By {interaction.user.display_name}")
        await respond(interaction, embed)
        self.bot.dispatch("modlog", interaction.guild, embed)

    @app_commands.command(name="timeout", description="Timeout a member (e.g. 10m, 1h, 1d)")
    @app_commands.describe(member="Who needs a break?", duration="How long? e.g. 10m, 1h, 1d", reason="Why?")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: str | None = None,
    ):
        if not can_act_on(interaction.user, member):
            return await hierarchy_error(interaction)

        delta = parse_duration(duration)
        if not delta:
            embed = make_embed("🤔 Invalid duration", "Use formats like `10m`, `1h`, `1d` (max 28 days).", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        delta = min(delta, timedelta(days=28))
        await member.timeout(delta, reason=f"{interaction.user} • {reason or 'No reason given'}")

        until = datetime.now(UTC) + delta
        embed = make_embed(
            "⏳ Timeout applied",
            f"**{member.display_name}** is muted until {discord.utils.format_dt(until, 'f')}.\n> {reason or 'No reason given'}",
            color=Palette.WARNING,
        )
        brand_footer(embed, f"By {interaction.user.display_name}")
        await respond(interaction, embed)
        self.bot.dispatch("modlog", interaction.guild, embed)

    @app_commands.command(name="untimeout", description="Remove a member's timeout")
    @app_commands.describe(member="Who gets unmuted?")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None, reason=f"Timeout removed by {interaction.user}")
        embed = make_embed("🔊 Timeout removed", f"**{member.display_name}** can speak again.", color=Palette.SUCCESS)
        brand_footer(embed, f"By {interaction.user.display_name}")
        await respond(interaction, embed)

    @app_commands.command(name="slowmode", description="Set channel slowmode (0 to disable)")
    @app_commands.describe(seconds="Delay between messages (0-21600)")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds:
            embed = make_embed("🐢 Slowmode on", f"One message every `{seconds}s` in this channel.", color=Palette.WARNING)
        else:
            embed = make_embed("🐇 Slowmode off", "Chat at full speed again!", color=Palette.SUCCESS)
        brand_footer(embed, "Channel settings")
        await respond(interaction, embed)

    @app_commands.command(name="announce", description="Send a styled announcement to a channel")
    @app_commands.describe(channel="Where to post", title="Announcement title", message="Body (use \\n for new lines)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        message: str,
    ):
        embed = make_embed(f"📣 {title}", message.replace("\\n", "\n"), color=Palette.PRIMARY)
        brand_footer(embed, f"Announcement by {interaction.user.display_name}")
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            error_embed = make_embed("🔒 No access", f"I cannot post in {channel.mention}.", color=Palette.DANGER)
            brand_footer(error_embed)
            return await respond(interaction, error_embed, ephemeral=True)

        confirm = make_embed("✅ Announcement sent", f"Delivered to {channel.mention}.", color=Palette.SUCCESS)
        brand_footer(confirm)
        await respond(interaction, confirm, ephemeral=True)

    @warn.command(name="add", description="Warn a member")
    @app_commands.describe(member="Who gets the warning?", reason="Why?")
    async def warn_add(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        warns = load_data("warns", {})
        guild_warns = warns.setdefault(str(interaction.guild_id), {})
        user_warns = guild_warns.setdefault(str(member.id), [])
        user_warns.append(
            {
                "reason": reason,
                "moderator_id": interaction.user.id,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        save_data("warns", warns)

        embed = make_embed(
            "⚠️ Warning issued",
            f"**{member.display_name}** now has `{len(user_warns)}` warning(s).\n> {reason}",
            color=Palette.WARNING,
        )
        brand_footer(embed, f"By {interaction.user.display_name}")
        await respond(interaction, embed)
        self.bot.dispatch("modlog", interaction.guild, embed)

        try:
            dm_embed = make_embed(
                f"⚠️ Warning in {interaction.guild.name}",
                f"> {reason}\n\nTotal warnings: `{len(user_warns)}`",
                color=Palette.WARNING,
            )
            await member.send(embed=dm_embed)
        except discord.HTTPException:
            pass

    @warn.command(name="list", description="See a member's warnings")
    @app_commands.describe(member="Whose warnings?")
    async def warn_list(self, interaction: discord.Interaction, member: discord.Member):
        warns = load_data("warns", {})
        user_warns = warns.get(str(interaction.guild_id), {}).get(str(member.id), [])
        if not user_warns:
            embed = make_embed("✨ Clean record", f"**{member.display_name}** has no warnings.", color=Palette.SUCCESS)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        lines = []
        for index, entry in enumerate(user_warns[-10:], start=max(len(user_warns) - 10, 0) + 1):
            when = datetime.fromisoformat(entry["created_at"])
            lines.append(
                f"`#{index}` {discord.utils.format_dt(when, 'R')} by <@{entry['moderator_id']}>\n> {truncate(entry['reason'], 100)}"
            )

        embed = make_embed(
            f"📋 Warnings • {member.display_name}",
            "\n".join(lines),
            color=Palette.WARNING,
        )
        brand_footer(embed, f"{len(user_warns)} total")
        await respond(interaction, embed, ephemeral=True)

    @warn.command(name="clear", description="Clear all warnings for a member")
    @app_commands.describe(member="Whose warnings to clear?")
    async def warn_clear(self, interaction: discord.Interaction, member: discord.Member):
        warns = load_data("warns", {})
        guild_warns = warns.get(str(interaction.guild_id), {})
        removed = len(guild_warns.pop(str(member.id), []))
        save_data("warns", warns)

        embed = make_embed(
            "🧽 Warnings cleared",
            f"Removed `{removed}` warning(s) for **{member.display_name}**.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, f"By {interaction.user.display_name}")
        await respond(interaction, embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
