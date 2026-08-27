"""Discord presentation helpers for levels and historical XP rebuilds."""

from __future__ import annotations

import discord

from .level_curve import MAX_LEVEL, level_from_xp, xp_needed
from .level_helpers import BACKFILL_MAX_DAYS
from .theme import Palette, brand_footer, make_embed, progress_bar
from .utils import humanize_number


RANK_COLORS = {1: Palette.GOLD, 2: 0xBDC3C7, 3: 0xCD7F32}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def backfill_top_lines(xp_by_user, message_counts, limit=10):
    ranked = sorted(xp_by_user.items(), key=lambda item: item[1], reverse=True)
    lines = []
    for index, (user_id, xp_amount) in enumerate(ranked[:limit], 1):
        medal = MEDALS.get(index, f"`#{index}`")
        lines.append(
            f"{medal} <@{user_id}> — `{humanize_number(xp_amount)} XP` "
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
    days,
    xp_per_message,
    cap_per_user,
    backup=None,
):
    total_xp = sum(xp_by_user.values())
    title = "XP rebuild preview" if mode == "preview" else "XP rebuild applied"
    description = (
        f"Scanned historical messages in **{guild.name}**.\n"
        f"Window: {readable_dt(after)} -> {readable_dt(before)}\n"
        "Existing XP and message totals are replaced, never added to."
    )
    embed = make_embed(
        title,
        description,
        color=Palette.INFO if mode == "preview" else Palette.SUCCESS,
    )
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
            f"`{humanize_number(total_xp)}` XP rebuilt\n"
            f"`{xp_per_message}` XP/message\n"
            f"`{humanize_number(cap_per_user)}` XP cap/user"
        ),
        inline=True,
    )
    embed.add_field(
        name="Safety",
        value=(
            f"Latest `{days}` day window (`{BACKFILL_MAX_DAYS}` max)\n"
            "Rebuilds this server's XP from scratch\n"
            "No per-channel message cap\n"
            f"`{stats['errors']}` channel error(s)\n"
            + (f"Backup: `{backup['name']}`" if backup else "No data changed")
        ),
        inline=False,
    )

    lines = backfill_top_lines(xp_by_user, message_counts)
    embed.add_field(
        name="Top rebuilt totals",
        value="\n".join(lines) if lines else "`No eligible historical messages found.`",
        inline=False,
    )
    if mode == "preview" and xp_by_user:
        embed.add_field(
            name="Apply",
            value=(
                "Run `/levels backfill run confirm:true` with the same options "
                "to replace the current XP totals."
            ),
            inline=False,
        )
    brand_footer(embed, "Levels backfill")
    return embed


def build_level_up_embed(member, guild, record, new_level, xp_gain, position, ranked_count):
    total_xp = record.get("xp", 0)
    into_level = level_from_xp(total_xp)[1]
    needed = xp_needed(new_level)

    embed = make_embed(
        f"Level {new_level} unlocked",
        (
            f"You leveled up in **{guild.name}**.\n"
            "Nice, quiet progress. No channel spam, just your own XP card."
        ),
        color=Palette.GOLD,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if new_level >= MAX_LEVEL:
        embed.add_field(
            name="Level cap",
            value=f"`Level {MAX_LEVEL}` is the maximum.",
            inline=False,
        )
    else:
        bar = progress_bar(into_level, needed, slots=14)
        embed.add_field(
            name="Next level",
            value=f"{bar}\n`{humanize_number(into_level)} / {humanize_number(needed)} XP`",
            inline=False,
        )
    embed.add_field(name="Total XP", value=f"`{humanize_number(total_xp)}`", inline=True)
    embed.add_field(name="Reward", value=f"`+{xp_gain} XP`", inline=True)
    if position:
        embed.add_field(
            name="Server rank",
            value=f"`#{position}` of `{ranked_count}`",
            inline=True,
        )
    brand_footer(embed, "Private level-up")
    return embed
