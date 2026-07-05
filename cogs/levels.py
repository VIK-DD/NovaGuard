"""🏆 Levels category — chat XP, level-up celebrations and the server leaderboard."""

import asyncio
import random
from copy import deepcopy
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.database import load_levels_data, save_levels_data
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import humanize_number, respond

XP_COOLDOWN_SECONDS = 60
XP_FLUSH_SECONDS = 30
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


class Levels(commands.Cog):
    """XP for chatting, with celebrations and a leaderboard."""

    EMOJI = "🏆"
    COLOR = Palette.GOLD
    DESCRIPTION = "Chat XP, level-up celebrations and the server leaderboard."

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or message.webhook_id:
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
        record["xp"] = record.get("xp", 0) + random.randint(15, 25)
        record["last_gain"] = now.isoformat()
        new_level, _ = level_from_xp(record["xp"])

        if new_level > old_level:
            try:
                await self.flush()
            except Exception as error:
                print(f"Levels immediate flush skipped due to storage issue: {error!r}")
            embed = make_embed(
                "🎉 LEVEL UP!",
                f"{message.author.mention} just reached **Level {new_level}**!",
                color=Palette.GOLD,
            )
            brand_footer(embed, "XP system")
            try:
                await message.channel.send(embed=embed)
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

        ordered = sorted(guild_data.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)
        position = next((index for index, (uid, _) in enumerate(ordered, 1) if uid == str(target.id)), 0)

        color = RANK_COLORS.get(position, Palette.PRIMARY)
        medal = MEDALS.get(position, "🏅")
        bar = progress_bar(into_level, needed, slots=12)

        embed = make_embed(
            f"{medal} {target.display_name}",
            f"**Level {level}** • Rank `#{position}` of `{len(ordered)}`",
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
