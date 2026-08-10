"""🎧 Voice hours — how long each member actually spends in voice, per month.

Separate from the Voice cog on purpose. That one reports on a *session*: it
starts when a channel fills, ends when it empties, and only runs at all once a
server has picked a report channel. This one answers a different question -
"how many hours did I spend in voice this month?" - which has to work on every
server, configured or not, and has to outlive the session it was earned in.

Time is credited on a timer rather than on join/leave events. A tick that never
fires credits nothing, so a bot that was offline does not later hand out hours
it did not see; and there is no open "in voice since..." state to persist, so a
crash costs one tick at most instead of an entire evening.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.database import (
    add_voice_seconds,
    voice_member_history,
    voice_month_leaderboard,
    voice_month_rank,
    voice_month_summary,
    voice_month_total,
)
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.voice_hours import (
    counts_towards_hours,
    current_month,
    format_hours,
    month_label,
    shift_month,
    split_by_month,
    voice_timezone,
)

TICK_SECONDS = 300
# A tick delayed by a slow host must not pay out the whole gap: the members it
# credits are the ones connected *now*, and it cannot know who was there for
# the minutes it missed.
MAX_TICK_CREDIT_SECONDS = TICK_SECONDS * 2
LEADERBOARD_SIZE = 10
HISTORY_MONTHS = 6


def now_utc() -> datetime:
    return datetime.now(UTC)


def member_record(member: discord.Member) -> dict:
    """The few facts the eligibility rule needs, without the Discord object."""
    state = member.voice
    return {
        "bot": member.bot,
        "self_deaf": bool(state and state.self_deaf),
        "deaf": bool(state and state.deaf),
    }


class VoiceHours(commands.Cog):
    """A running monthly total of voice time, per member, per server."""

    EMOJI = "🎧"
    COLOR = Palette.PRIMARY
    DESCRIPTION = "Monthly voice hours, with a leaderboard and your own trend."

    def __init__(self, bot):
        self.bot = bot
        self.last_tick: datetime | None = None

    async def cog_load(self):
        self.ledger_tick.start()

    async def cog_unload(self):
        self.ledger_tick.cancel()

    def collect(self, elapsed: float) -> list[tuple[str, str, list[tuple[str, float]]]]:
        """Who is in voice right now, and which months their time belongs to."""
        ended_at = now_utc()
        buckets = split_by_month(ended_at - timedelta(seconds=elapsed), ended_at, voice_timezone())
        if not buckets:
            return []

        rows = []
        for guild in self.bot.guilds:
            afk_id = guild.afk_channel.id if guild.afk_channel else None
            for channel in [*guild.voice_channels, *guild.stage_channels]:
                is_afk = channel.id == afk_id
                for member in channel.members:
                    if counts_towards_hours(member_record(member), channel_is_afk=is_afk):
                        rows.append((str(guild.id), str(member.id), buckets))
        return rows

    @tasks.loop(seconds=TICK_SECONDS)
    async def ledger_tick(self):
        moment = now_utc()
        previous, self.last_tick = self.last_tick, moment
        if previous is None:
            # The first tick after start-up only sets the baseline: crediting
            # from it would pay for time before the bot was watching.
            return

        elapsed = min((moment - previous).total_seconds(), MAX_TICK_CREDIT_SECONDS)
        if elapsed <= 0:
            return

        try:
            for guild_id, user_id, buckets in self.collect(elapsed):
                await asyncio.to_thread(add_voice_seconds, guild_id, user_id, buckets)
        except Exception as error:
            # Losing a tick is a rounding error. Letting the exception out
            # would stop every future tick for the life of the process.
            print(f"Voice hours tick skipped: {error!r}")

    @ledger_tick.before_loop
    async def before_ledger_tick(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="vh", description="See voice hours for this month")
    @app_commands.describe(
        member="Whose hours? (defaults to you)",
        month="How far back? 0 is this month, 1 is last month",
    )
    @app_commands.guild_only()
    async def vh(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        month: app_commands.Range[int, 0, 11] = 0,
    ):
        target = member or interaction.user
        tz = voice_timezone()
        key = shift_month(current_month(tz), -int(month))
        guild_id = interaction.guild_id

        totals = await asyncio.to_thread(voice_month_total, guild_id, target.id, key)
        summary = await asyncio.to_thread(voice_month_summary, guild_id, key)
        seconds = totals["seconds"]

        if seconds <= 0:
            embed = make_embed(
                f"🎧 Voice hours • {month_label(key)}",
                f"{target.mention} has no voice time recorded for {month_label(key)}.",
                color=Palette.PRIMARY,
            )
            embed.add_field(
                name="Nothing is missing",
                value="-# Hours start counting as soon as someone joins a voice channel.",
                inline=False,
            )
            brand_footer(embed, f"Measured in {tz.key}")
            return await interaction.response.send_message(embed=embed)

        rank = await asyncio.to_thread(voice_month_rank, guild_id, target.id, key)
        history = await asyncio.to_thread(
            voice_member_history, guild_id, target.id, HISTORY_MONTHS
        )

        embed = make_embed(
            f"🎧 Voice hours • {month_label(key)}",
            f"{target.mention} spent **{format_hours(seconds)}** in voice.",
            color=Palette.PRIMARY,
        )
        embed.add_field(
            name="Rank",
            value=f"`#{rank}` of `{summary['members']}`" if rank else "`—`",
            inline=True,
        )
        share = seconds / summary["seconds"] if summary["seconds"] else 0
        embed.add_field(name="Share of the server", value=f"`{round(share * 100)}%`", inline=True)
        embed.add_field(
            name="Server total", value=f"`{format_hours(summary['seconds'])}`", inline=True
        )

        trend = [row for row in history if row["month"] != key][: HISTORY_MONTHS - 1]
        if trend:
            peak = max([seconds, *(row["seconds"] for row in trend)]) or 1
            embed.add_field(
                name="Previous months",
                value="\n".join(
                    f"`{month_label(row['month'])[:3]}` {progress_bar(row['seconds'], peak)}"
                    f" `{format_hours(row['seconds'])}`"
                    for row in trend
                ),
                inline=False,
            )

        brand_footer(embed, f"Measured in {tz.key}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="vhtop", description="Who spent the most time in voice this month")
    @app_commands.describe(month="How far back? 0 is this month, 1 is last month")
    @app_commands.guild_only()
    async def vhtop(
        self,
        interaction: discord.Interaction,
        month: app_commands.Range[int, 0, 11] = 0,
    ):
        tz = voice_timezone()
        key = shift_month(current_month(tz), -int(month))
        board = await asyncio.to_thread(
            voice_month_leaderboard, interaction.guild_id, key, LEADERBOARD_SIZE
        )

        if not board:
            embed = make_embed(
                f"🎧 Voice leaderboard • {month_label(key)}",
                "Nobody has been in voice yet this month.",
                color=Palette.PRIMARY,
            )
            brand_footer(embed, f"Measured in {tz.key}")
            return await interaction.response.send_message(embed=embed)

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        embed = make_embed(
            f"🎧 Voice leaderboard • {month_label(key)}",
            "\n".join(
                f"{medals.get(index, f'`#{index}`')} <@{row['user_id']}>"
                f" — `{format_hours(row['seconds'])}`"
                for index, row in enumerate(board, 1)
            ),
            color=Palette.PRIMARY,
        )
        brand_footer(embed, f"Measured in {tz.key}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(VoiceHours(bot))
