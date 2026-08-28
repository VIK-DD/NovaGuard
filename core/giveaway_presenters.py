"""Discord presentation helpers for giveaway lifecycle messages."""

from datetime import datetime

import discord

from .theme import Palette, brand_footer, make_embed


def build_giveaway_embed(entry, ended=False, winner_ids=None):
    ends_at = datetime.fromisoformat(entry["ends_at"])
    entrants = entry.get("entrants", [])

    if ended:
        if winner_ids:
            winners_text = ", ".join(f"<@{user_id}>" for user_id in winner_ids)
            description = (
                f"# {entry['prize']}\n\n"
                f"🏆 **Winner{'s' if len(winner_ids) > 1 else ''}:** {winners_text}"
            )
        else:
            description = f"# {entry['prize']}\n\n😢 No valid entries — nobody wins this time."
        embed = make_embed("🏁 GIVEAWAY ENDED", description, color=Palette.DARK)
    else:
        description = (
            f"# {entry['prize']}\n\n"
            f"Ends {discord.utils.format_dt(ends_at, 'R')} ({discord.utils.format_dt(ends_at, 'f')})\n"
            f"Winners: `{entry['winners']}` • Entries: `{len(entrants)}`\n\n"
            "**Click 🎉 below to enter!**"
        )
        embed = make_embed("🎁 GIVEAWAY", description, color=Palette.FUN)

    brand_footer(embed, f"Hosted by {entry.get('host_name', 'staff')}")
    return embed


def build_giveaway_result_embed(entry, winner_ids):
    if winner_ids:
        mentions = ", ".join(f"<@{user_id}>" for user_id in winner_ids)
        embed = make_embed(
            "🎊 We have a winner!",
            f"Congratulations {mentions} — you won **{entry['prize']}**!",
            color=Palette.GOLD,
        )
    else:
        embed = make_embed(
            "😢 No winner",
            f"Nobody entered the giveaway for **{entry['prize']}**.",
            color=Palette.DARK,
        )
    brand_footer(embed, "Giveaway result")
    return embed


def build_giveaway_reroll_announcement_embed(entry, winner_ids):
    mentions = ", ".join(f"<@{user_id}>" for user_id in winner_ids)
    embed = make_embed(
        "🎲 Giveaway rerolled",
        f"New winner{'s' if len(winner_ids) > 1 else ''} for **{entry['prize']}**: {mentions} 🎊",
        color=Palette.GOLD,
    )
    brand_footer(embed, "Giveaway reroll")
    return embed
