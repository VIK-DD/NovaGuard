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
import logging
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.voice import VOICE_REPORT_CHANNEL_KEY
from core.loop_guard import keep_running
from core.database import (
    add_voice_seconds,
    voice_member_history,
    voice_month_leaderboard,
    voice_month_rank,
    voice_month_summary,
    voice_month_total,
)
from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.voice_hours import (
    COINS_PER_BLOCK,
    PAYOUT_BLOCK_SECONDS,
    XP_PER_BLOCK,
    counts_towards_hours,
    current_month,
    daily_pace,
    format_hours,
    month_label,
    month_window,
    projected_total,
    recap_due,
    rewardable,
    shift_month,
    split_by_month,
    voice_payout,
    voice_timezone,
)

log = logging.getLogger(__name__)

TICK_SECONDS = 300
# A tick delayed by a slow host must not pay out the whole gap: the members it
# credits are the ones connected *now*, and it cannot know who was there for
# the minutes it missed.
MAX_TICK_CREDIT_SECONDS = TICK_SECONDS * 2
LEADERBOARD_SIZE = 10
HISTORY_MONTHS = 6
# Checked hourly rather than once a day, so a bot that was offline exactly at
# midnight on the 1st still catches up within the hour instead of waiting a
# full day for the next chance.
RECAP_CHECK_SECONDS = 3600
RECAP_LAST_POSTED_KEY = "voice_recap_last_month"


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
        # Voice time banked but not yet worth a payout, per member. Kept in
        # memory on purpose: a restart costs someone at most one unfinished
        # block, which is not worth a wallet write every five minutes for
        # everyone who happens to be in a call.
        self.unpaid: dict[tuple[str, str], float] = {}

    async def cog_load(self):
        self.ledger_tick.start()
        self.recap_check.start()

    async def cog_unload(self):
        self.ledger_tick.cancel()
        self.recap_check.cancel()

    def collect(self, elapsed: float) -> list[dict]:
        """Who is in voice right now, and whether their time also earns.

        Alone in a channel still counts towards the hours - it happened - but
        does not pay, or an idle mic would be the best-paying thing on the
        server.
        """
        ended_at = now_utc()
        buckets = split_by_month(ended_at - timedelta(seconds=elapsed), ended_at, voice_timezone())
        if not buckets:
            return []

        rows = []
        for guild in self.bot.guilds:
            afk_id = guild.afk_channel.id if guild.afk_channel else None
            for channel in [*guild.voice_channels, *guild.stage_channels]:
                is_afk = channel.id == afk_id
                present = [
                    member
                    for member in channel.members
                    if counts_towards_hours(member_record(member), channel_is_afk=is_afk)
                ]
                earns = rewardable(len(present))
                for member in present:
                    rows.append(
                        {
                            "guild": guild,
                            "guild_id": str(guild.id),
                            "user_id": str(member.id),
                            "buckets": buckets,
                            "earns": earns,
                        }
                    )
        return rows

    async def _pay(self, row: dict, elapsed: float):
        """Bank a member's time and pay out whatever whole blocks it completes."""
        key = (row["guild_id"], row["user_id"])
        coins, xp, remainder = voice_payout(self.unpaid.get(key, 0.0) + elapsed)
        self.unpaid[key] = remainder
        if not coins and not xp:
            return

        economy = self.bot.get_cog("Economy")
        if economy is not None and coins:
            await economy.award_coins(row["guild_id"], row["user_id"], coins)

        levels = self.bot.get_cog("Levels")
        if levels is not None and xp:
            levels.award_voice_xp(row["guild"], row["user_id"], xp)

    @tasks.loop(seconds=TICK_SECONDS)
    @keep_running(log, "voice ledger tick")
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
            rows = self.collect(elapsed)
            for row in rows:
                await asyncio.to_thread(
                    add_voice_seconds, row["guild_id"], row["user_id"], row["buckets"]
                )
                if row["earns"]:
                    await self._pay(row, elapsed)

            # Members who left keep nothing banked: their part-block is gone
            # with them, and holding it would let someone bank minutes across
            # an evening of joining and leaving.
            live = {(row["guild_id"], row["user_id"]) for row in rows}
            self.unpaid = {key: value for key, value in self.unpaid.items() if key in live}
        except Exception as error:
            # Losing a tick is a rounding error. Letting the exception out
            # would stop every future tick for the life of the process.
            log.warning(f"Voice hours tick skipped: {error!r}", exc_info=True)

    @ledger_tick.before_loop
    async def before_ledger_tick(self):
        await self.bot.wait_until_ready()

    def _leaderboard_embed(self, title: str, board: list[dict], footer: str) -> discord.Embed:
        """The ranked list /voicetop shows, and the monthly recap posts unasked.

        One builder for both, so the recap looks like the leaderboard a member
        would have pulled up themselves rather than a second, different-looking
        format nobody asked for.
        """
        if not board:
            embed = make_embed(title, "Nobody was in voice.", color=Palette.PRIMARY)
            brand_footer(embed, footer)
            return embed

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        embed = make_embed(
            title,
            "\n".join(
                f"{medals.get(index, f'`#{index}`')} <@{row['user_id']}>"
                f" — `{format_hours(row['seconds'])}`"
                for index, row in enumerate(board, 1)
            ),
            color=Palette.PRIMARY,
        )
        brand_footer(embed, footer)
        return embed

    async def _recap_guild(self, guild: discord.Guild):
        """Post last month's leaderboard once, the first time it is checked
        after that month has finished."""
        tz = voice_timezone()
        target_month = shift_month(current_month(tz), -1)

        settings = get_guild_settings(guild.id)
        if not recap_due(settings.get(RECAP_LAST_POSTED_KEY), target_month):
            return

        channel_id = settings.get(VOICE_REPORT_CHANNEL_KEY)
        if not channel_id:
            # Nowhere to post, and nothing to catch up on: recap goes to the
            # same channel as session reports, and a server that never set
            # one gets no automatic messages from this cog either.
            return
        channel = guild.get_channel(int(channel_id)) if str(channel_id).isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            return

        board = await asyncio.to_thread(
            voice_month_leaderboard, guild.id, target_month, LEADERBOARD_SIZE
        )
        # An empty month (no report channel until partway through, or a quiet
        # month) still marks the recap done - there is nothing to show, and
        # re-checking it every hour forever would be pure waste.
        if board:
            summary = await asyncio.to_thread(voice_month_summary, guild.id, target_month)
            embed = self._leaderboard_embed(
                f"🎧 Voice recap • {month_label(target_month)}",
                board,
                f"Server total {format_hours(summary['seconds'])} · Measured in {tz.key}",
            )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException as error:
                # A send failure should not lose the month permanently, only
                # delay it to the next hourly check.
                log.warning(f"Voice recap send failed for guild {guild.id}: {error!r}")
                return

        update_guild_settings(guild.id, **{RECAP_LAST_POSTED_KEY: target_month})

    @tasks.loop(seconds=RECAP_CHECK_SECONDS)
    @keep_running(log, "voice recap check")
    async def recap_check(self):
        for guild in self.bot.guilds:
            try:
                await self._recap_guild(guild)
            except Exception as error:
                # One guild's bad state (missing channel, storage hiccup)
                # must not stop every other guild's recap from being checked.
                log.warning(f"Voice recap check skipped for guild {guild.id}: {error!r}", exc_info=True)

    @recap_check.before_loop
    async def before_recap_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="voicehours", description="Voice hours banked so far this month")
    @app_commands.describe(
        member="Whose hours? (defaults to you)",
        month="How far back? 0 is this month, 1 is last month",
    )
    @app_commands.guild_only()
    async def voicehours(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        month: app_commands.Range[int, 0, 11] = 0,
    ):
        target = member or interaction.user
        tz = voice_timezone()
        key = shift_month(current_month(tz), -int(month))
        window = month_window(key, tz=tz)
        guild_id = interaction.guild_id

        totals = await asyncio.to_thread(voice_month_total, guild_id, target.id, key)
        summary = await asyncio.to_thread(voice_month_summary, guild_id, key)
        seconds = totals["seconds"]

        if seconds <= 0:
            embed = make_embed(
                f"🎧 Voice hours • {window['label']}",
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

        # The month is named with the days it actually covers, because someone
        # asking on the 10th wants what they have banked so far, not a figure
        # that reads like the finished month.
        counted = (
            f"day 1 to day {window['elapsed']}" if window["current"] else "the whole month"
        )
        embed = make_embed(
            f"🎧 Voice hours • {window['label']}",
            f"{target.mention} has **{format_hours(seconds)}** in voice"
            f" across {counted}.",
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

        if window["current"] and window["elapsed"] > 0:
            pace = daily_pace(seconds, window["elapsed"])
            projection = projected_total(seconds, window["elapsed"], window["days"])
            embed.add_field(
                name="Pace",
                value=f"`{format_hours(pace)}` a day",
                inline=True,
            )
            embed.add_field(
                name=f"On track for day {window['days']}",
                value=f"`{format_hours(projection)}`",
                inline=True,
            )
            embed.add_field(
                name="Month left",
                value=f"`{window['remaining']}` day(s)",
                inline=True,
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

        per_hour = 3600 // PAYOUT_BLOCK_SECONDS
        embed.add_field(
            name="Time pays",
            value=f"-# `{COINS_PER_BLOCK * per_hour}` coins and `{XP_PER_BLOCK * per_hour}` XP"
            " an hour, while someone else is in the channel with you.",
            inline=False,
        )
        brand_footer(embed, f"Measured in {tz.key}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="voicetop", description="Most time in voice this month")
    @app_commands.checks.cooldown(1, 10.0)
    @app_commands.describe(month="How far back? 0 is this month, 1 is last month")
    @app_commands.guild_only()
    async def voicetop(
        self,
        interaction: discord.Interaction,
        month: app_commands.Range[int, 0, 11] = 0,
    ):
        tz = voice_timezone()
        key = shift_month(current_month(tz), -int(month))
        window = month_window(key, tz=tz)
        board = await asyncio.to_thread(
            voice_month_leaderboard, interaction.guild_id, key, LEADERBOARD_SIZE
        )

        note = f" · {window['remaining']} day(s) left" if window["current"] else ""
        embed = self._leaderboard_embed(
            f"🎧 Voice leaderboard • {window['label']}", board, f"Measured in {tz.key}{note}"
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(VoiceHours(bot))
