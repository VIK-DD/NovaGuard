"""🏆 Levels category — chat XP, level-up celebrations and the server leaderboard."""

import asyncio
import random
import time
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.backups import create_backup
from core.database import load_levels_data, save_levels_data
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import humanize_number, respond

XP_COOLDOWN_SECONDS = 120
XP_FLUSH_SECONDS = 30
XP_GAIN_MIN = 5
XP_GAIN_MAX = 10
MIN_XP_MESSAGE_CHARS = 4
BACKFILL_DEFAULT_DAYS = 365
BACKFILL_DEFAULT_XP_PER_MESSAGE = 2
BACKFILL_DEFAULT_CAP_PER_USER = 20_000
BACKFILL_DEFAULT_MAX_PER_CHANNEL = 50_000
RANK_COLORS = {1: Palette.GOLD, 2: 0xBDC3C7, 3: 0xCD7F32}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def parse_saved_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def xp_needed(level):
    return 5 * level * level + 50 * level + 100


def level_from_xp(total_xp):
    level = 0
    remaining = total_xp
    while remaining >= xp_needed(level):
        remaining -= xp_needed(level)
        level += 1
    return level, remaining


def meaningful_message(message: discord.Message):
    content = (message.content or "").strip()
    if len(content) >= MIN_XP_MESSAGE_CHARS:
        return True
    return bool(message.attachments or message.stickers)


def meaningful_historical_message(message: discord.Message):
    if message.content:
        return meaningful_message(message)
    return True


def rank_position(guild_data, user_id):
    ordered = sorted(guild_data.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)
    position = next((index for index, (uid, _) in enumerate(ordered, 1) if uid == str(user_id)), 0)
    return position, len(ordered)


def historical_cutoff_before(guild_data, now=None):
    now = now or datetime.now(UTC)
    timestamps = [
        parsed
        for record in guild_data.values()
        if isinstance(record, dict)
        for parsed in [parse_saved_datetime(record.get("last_gain"))]
        if parsed
    ]
    return min(timestamps) if timestamps else now


def xp_from_message_counts(message_counts, xp_per_message, cap_per_user):
    return {
        user_id: min(count * xp_per_message, cap_per_user)
        for user_id, count in message_counts.items()
        if count > 0
    }


def apply_backfill_to_guild(guild_data, message_counts, xp_by_user):
    now = datetime.now(UTC).isoformat()
    applied_xp = 0
    applied_messages = 0

    for user_id, xp_amount in xp_by_user.items():
        if xp_amount <= 0:
            continue
        record = guild_data.setdefault(user_id, {"xp": 0, "messages": 0, "last_gain": None})
        record["xp"] = int(record.get("xp", 0) or 0) + int(xp_amount)
        record["messages"] = int(record.get("messages", 0) or 0) + int(message_counts.get(user_id, 0))
        record["last_gain"] = record.get("last_gain") or now
        applied_xp += int(xp_amount)
        applied_messages += int(message_counts.get(user_id, 0))

    return applied_xp, applied_messages


def backfill_top_lines(xp_by_user, message_counts, limit=10):
    ranked = sorted(xp_by_user.items(), key=lambda item: item[1], reverse=True)
    lines = []
    for index, (user_id, xp_amount) in enumerate(ranked[:limit], 1):
        medal = MEDALS.get(index, f"`#{index}`")
        lines.append(
            f"{medal} <@{user_id}> — `+{humanize_number(xp_amount)} XP` "
            f"from `{humanize_number(message_counts.get(user_id, 0))}` message(s)"
        )
    return lines


def readable_dt(value):
    return discord.utils.format_dt(value, "f")


def build_backfill_embed(
    *,
    guild,
    mode,
    stats,
    xp_by_user,
    message_counts,
    after,
    before,
    xp_per_message,
    cap_per_user,
    max_per_channel,
    backup=None,
):
    total_xp = sum(xp_by_user.values())
    title = "XP backfill preview" if mode == "preview" else "XP backfill applied"
    description = (
        f"Scanned historical messages in **{guild.name}**.\n"
        f"Window: {readable_dt(after)} -> {readable_dt(before)}"
    )
    embed = make_embed(title, description, color=Palette.INFO if mode == "preview" else Palette.SUCCESS)
    embed.add_field(
        name="Scan",
        value=(
            f"`{stats['channels_scanned']}` channel(s) scanned\n"
            f"`{stats['channels_skipped']}` skipped/no access\n"
            f"`{humanize_number(stats['messages_seen'])}` message(s) read\n"
            f"`{humanize_number(stats['eligible_messages'])}` eligible message(s)"
        ),
        inline=True,
    )
    embed.add_field(
        name="XP",
        value=(
            f"`{humanize_number(len(xp_by_user))}` member(s)\n"
            f"`+{humanize_number(total_xp)}` XP total\n"
            f"`{xp_per_message}` XP/message\n"
            f"`{humanize_number(cap_per_user)}` XP cap/user"
        ),
        inline=True,
    )
    embed.add_field(
        name="Safety",
        value=(
            f"`{humanize_number(max_per_channel)}` max/channel\n"
            f"`{stats['errors']}` channel error(s)\n"
            + (f"Backup: `{backup['name']}`" if backup else "No data changed")
        ),
        inline=False,
    )

    lines = backfill_top_lines(xp_by_user, message_counts)
    embed.add_field(
        name="Top estimated changes" if mode == "preview" else "Top applied changes",
        value="\n".join(lines) if lines else "`No eligible historical messages found.`",
        inline=False,
    )
    if mode == "preview" and xp_by_user:
        embed.add_field(
            name="Apply",
            value="Run `/levels backfill run confirm:true` with the same options to write these XP changes.",
            inline=False,
        )
    brand_footer(embed, "Levels backfill")
    return embed


def build_level_up_embed(member, guild, record, new_level, xp_gain, position, ranked_count):
    total_xp = record.get("xp", 0)
    into_level = level_from_xp(total_xp)[1]
    needed = xp_needed(new_level)
    bar = progress_bar(into_level, needed, slots=14)

    embed = make_embed(
        f"Level {new_level} unlocked",
        (
            f"You leveled up in **{guild.name}**.\n"
            "Nice, quiet progress. No channel spam, just your own XP card."
        ),
        color=Palette.GOLD,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(
        name="Next level",
        value=f"{bar}\n`{humanize_number(into_level)} / {humanize_number(needed)} XP`",
        inline=False,
    )
    embed.add_field(name="Total XP", value=f"`{humanize_number(total_xp)}`", inline=True)
    embed.add_field(name="Reward", value=f"`+{xp_gain} XP`", inline=True)
    if position:
        embed.add_field(name="Server rank", value=f"`#{position}` of `{ranked_count}`", inline=True)
    brand_footer(embed, "Private level-up")
    return embed


class Levels(commands.Cog):
    """XP for chatting, with celebrations and a leaderboard."""

    EMOJI = "🏆"
    COLOR = Palette.GOLD
    DESCRIPTION = "Chat XP, level-up celebrations and the server leaderboard."
    levels = app_commands.Group(
        name="levels",
        description="Level system admin tools",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )
    backfill = app_commands.Group(
        name="backfill",
        description="Import historical chat activity into XP",
        parent=levels,
    )

    def __init__(self, bot):
        self.bot = bot
        self.data = load_levels_data()
        self.dirty = False
        self.flush_lock = asyncio.Lock()

    async def cog_load(self):
        self.flush_loop.start()

    async def cog_unload(self):
        self.flush_loop.cancel()
        await self.flush()

    async def flush(self):
        async with self.flush_lock:
            if not self.dirty:
                return

            snapshot = deepcopy(self.data)
            self.dirty = False

            try:
                await asyncio.to_thread(save_levels_data, snapshot)
            except Exception:
                self.dirty = True
                raise

    @tasks.loop(seconds=XP_FLUSH_SECONDS)
    async def flush_loop(self):
        try:
            await self.flush()
        except Exception as error:
            print(f"Levels flush skipped due to storage issue: {error!r}")

    async def scan_historical_messages(self, guild, *, after, before, max_per_channel):
        counts = Counter()
        stats = {
            "channels_scanned": 0,
            "channels_skipped": 0,
            "messages_seen": 0,
            "eligible_messages": 0,
            "errors": 0,
            "elapsed_seconds": 0,
        }
        started = time.monotonic()
        me = guild.me or guild.get_member(self.bot.user.id)

        if before <= after or me is None:
            stats["elapsed_seconds"] = round(time.monotonic() - started, 2)
            return counts, stats

        for channel in guild.text_channels:
            permissions = channel.permissions_for(me)
            if not (permissions.view_channel and permissions.read_message_history):
                stats["channels_skipped"] += 1
                continue

            stats["channels_scanned"] += 1
            try:
                async for message in channel.history(limit=max_per_channel, after=after, before=before):
                    stats["messages_seen"] += 1
                    if message.author.bot or message.webhook_id:
                        continue
                    if not meaningful_historical_message(message):
                        continue
                    counts[str(message.author.id)] += 1
                    stats["eligible_messages"] += 1
            except discord.Forbidden:
                stats["channels_skipped"] += 1
            except discord.HTTPException as error:
                stats["errors"] += 1
                print(f"Levels backfill skipped #{channel.id} due to Discord API issue: {error!r}")

        stats["elapsed_seconds"] = round(time.monotonic() - started, 2)
        return counts, stats

    async def calculate_backfill(self, guild, *, days, xp_per_message, cap_per_user, max_per_channel):
        guild_data = self.data.setdefault(str(guild.id), {})
        before = historical_cutoff_before(guild_data)
        after = before - timedelta(days=days)
        message_counts, stats = await self.scan_historical_messages(
            guild,
            after=after,
            before=before,
            max_per_channel=max_per_channel,
        )
        xp_by_user = xp_from_message_counts(message_counts, xp_per_message, cap_per_user)
        return guild_data, message_counts, xp_by_user, stats, after, before

    @backfill.command(name="preview", description="Preview historical XP import without changing data")
    @app_commands.describe(
        days="How many days before the XP system started to scan",
        xp_per_message="XP awarded for each eligible historical message",
        cap_per_user="Maximum historical XP one member can receive",
        max_per_channel="Maximum messages to scan per channel",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backfill_preview(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 3650] = BACKFILL_DEFAULT_DAYS,
        xp_per_message: app_commands.Range[int, 1, 10] = BACKFILL_DEFAULT_XP_PER_MESSAGE,
        cap_per_user: app_commands.Range[int, 500, 100000] = BACKFILL_DEFAULT_CAP_PER_USER,
        max_per_channel: app_commands.Range[int, 100, 100000] = BACKFILL_DEFAULT_MAX_PER_CHANNEL,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        _, message_counts, xp_by_user, stats, after, before = await self.calculate_backfill(
            interaction.guild,
            days=days,
            xp_per_message=xp_per_message,
            cap_per_user=cap_per_user,
            max_per_channel=max_per_channel,
        )
        embed = build_backfill_embed(
            guild=interaction.guild,
            mode="preview",
            stats=stats,
            xp_by_user=xp_by_user,
            message_counts=message_counts,
            after=after,
            before=before,
            xp_per_message=xp_per_message,
            cap_per_user=cap_per_user,
            max_per_channel=max_per_channel,
        )
        await respond(interaction, embed, ephemeral=True)

    @backfill.command(name="run", description="Apply historical XP import after creating a backup")
    @app_commands.describe(
        confirm="Must be true before any XP is written",
        days="How many days before the XP system started to scan",
        xp_per_message="XP awarded for each eligible historical message",
        cap_per_user="Maximum historical XP one member can receive",
        max_per_channel="Maximum messages to scan per channel",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backfill_run(
        self,
        interaction: discord.Interaction,
        confirm: bool = False,
        days: app_commands.Range[int, 1, 3650] = BACKFILL_DEFAULT_DAYS,
        xp_per_message: app_commands.Range[int, 1, 10] = BACKFILL_DEFAULT_XP_PER_MESSAGE,
        cap_per_user: app_commands.Range[int, 500, 100000] = BACKFILL_DEFAULT_CAP_PER_USER,
        max_per_channel: app_commands.Range[int, 100, 100000] = BACKFILL_DEFAULT_MAX_PER_CHANNEL,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not confirm:
            embed = make_embed(
                "Confirmation needed",
                (
                    "Run `/levels backfill preview` first. If the numbers look good, run "
                    "`/levels backfill run confirm:true` with the same options."
                ),
                color=Palette.WARNING,
            )
            brand_footer(embed, "Levels backfill")
            return await respond(interaction, embed, ephemeral=True)

        guild_data, message_counts, xp_by_user, stats, after, before = await self.calculate_backfill(
            interaction.guild,
            days=days,
            xp_per_message=xp_per_message,
            cap_per_user=cap_per_user,
            max_per_channel=max_per_channel,
        )

        backup = None
        if xp_by_user:
            backup = await self.bot.loop.run_in_executor(None, create_backup, "levels-backfill")
            apply_backfill_to_guild(guild_data, message_counts, xp_by_user)
            self.dirty = True
            await self.flush()

        embed = build_backfill_embed(
            guild=interaction.guild,
            mode="run",
            stats=stats,
            xp_by_user=xp_by_user,
            message_counts=message_counts,
            after=after,
            before=before,
            xp_per_message=xp_per_message,
            cap_per_user=cap_per_user,
            max_per_channel=max_per_channel,
            backup=backup,
        )
        await respond(interaction, embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or message.webhook_id:
            return
        if not meaningful_message(message):
            return

        guild_data = self.data.setdefault(str(message.guild.id), {})
        record = guild_data.setdefault(str(message.author.id), {"xp": 0, "messages": 0, "last_gain": None})
        record["messages"] = record.get("messages", 0) + 1
        self.dirty = True

        now = datetime.now(UTC)
        last_gain = parse_saved_datetime(record.get("last_gain"))
        if last_gain and (now - last_gain).total_seconds() < XP_COOLDOWN_SECONDS:
            return

        old_level, _ = level_from_xp(record.get("xp", 0))
        xp_gain = random.randint(XP_GAIN_MIN, XP_GAIN_MAX)
        record["xp"] = record.get("xp", 0) + xp_gain
        record["last_gain"] = now.isoformat()
        new_level, _ = level_from_xp(record["xp"])

        if new_level > old_level:
            try:
                await self.flush()
            except Exception as error:
                print(f"Levels immediate flush skipped due to storage issue: {error!r}")
            position, ranked_count = rank_position(guild_data, message.author.id)
            embed = build_level_up_embed(
                message.author,
                message.guild,
                record,
                new_level,
                xp_gain,
                position,
                ranked_count,
            )
            try:
                await message.author.send(embed=embed)
            except discord.HTTPException:
                pass

    @app_commands.command(name="rank", description="Your XP card: level, progress and server rank")
    @app_commands.describe(member="Whose rank? (defaults to you)")
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        guild_data = self.data.get(str(interaction.guild_id), {})
        record = guild_data.get(str(target.id))

        if not record or not record.get("xp"):
            embed = make_embed(
                "🌱 No XP yet",
                f"**{target.display_name}** has not earned XP yet. Start chatting!",
                color=Palette.INFO,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        total_xp = record.get("xp", 0)
        level, into_level = level_from_xp(total_xp)
        needed = xp_needed(level)

        position, ranked_count = rank_position(guild_data, target.id)

        color = RANK_COLORS.get(position, Palette.PRIMARY)
        medal = MEDALS.get(position, "🏅")
        bar = progress_bar(into_level, needed, slots=12)

        embed = make_embed(
            f"{medal} {target.display_name}",
            f"**Level {level}** • Rank `#{position}` of `{ranked_count}`",
            color=color,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="Progress to next level",
            value=f"{bar}\n`{humanize_number(into_level)} / {humanize_number(needed)} XP`",
            inline=False,
        )
        embed.add_field(name="Total XP", value=f"`{humanize_number(total_xp)}`", inline=True)
        embed.add_field(name="Messages", value=f"`{humanize_number(record.get('messages', 0))}`", inline=True)
        brand_footer(embed, "XP card")
        await respond(interaction, embed)

    @app_commands.command(name="leaderboard", description="Top 10 most active members")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction):
        guild_data = self.data.get(str(interaction.guild_id), {})
        ordered = sorted(guild_data.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)
        ordered = [(uid, rec) for uid, rec in ordered if rec.get("xp")]

        if not ordered:
            embed = make_embed("🌱 Nothing yet", "Nobody has earned XP yet. Get chatting!", color=Palette.INFO)
            brand_footer(embed)
            return await respond(interaction, embed)

        lines = []
        for index, (uid, record) in enumerate(ordered[:10], 1):
            medal = MEDALS.get(index, f"`#{index}`")
            level, _ = level_from_xp(record.get("xp", 0))
            lines.append(f"{medal} <@{uid}> — Level `{level}` • `{humanize_number(record.get('xp', 0))}` XP")

        embed = make_embed(
            f"🏆 Leaderboard • {interaction.guild.name}",
            "\n".join(lines),
            color=Palette.GOLD,
        )
        brand_footer(embed, f"{len(ordered)} member(s) ranked")
        await respond(interaction, embed)


async def setup(bot):
    await bot.add_cog(Levels(bot))
