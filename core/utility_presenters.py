"""Discord cards for read-only utility commands."""

from collections import Counter
from datetime import UTC, datetime

import discord

from .theme import Palette, brand_footer, make_embed, progress_bar
from .utils import format_timedelta, truncate


BADGE_LABELS = {
    "staff": "Discord Staff",
    "partner": "Partner",
    "hypesquad": "HypeSquad Events",
    "bug_hunter": "Bug Hunter",
    "bug_hunter_level_2": "Bug Hunter Gold",
    "hypesquad_bravery": "Bravery",
    "hypesquad_brilliance": "Brilliance",
    "hypesquad_balance": "Balance",
    "early_supporter": "Early Supporter",
    "verified_bot_developer": "Early Verified Bot Dev",
    "active_developer": "Active Developer",
}

TIMESTAMP_STYLES = [
    ("t", "Short time"),
    ("T", "Long time"),
    ("d", "Short date"),
    ("D", "Long date"),
    ("f", "Short date/time"),
    ("F", "Long date/time"),
    ("R", "Relative"),
]


def build_reminder_select_options(items, checked_at=None):
    checked_at = checked_at or datetime.now(UTC)
    options = []
    for item in items[:25]:
        due = datetime.fromisoformat(item["due_at"])
        options.append(
            discord.SelectOption(
                label=truncate(item["message"], 90),
                value=item["id"],
                description=f"in {format_timedelta(due - checked_at)}",
                emoji="⏰",
            )
        )
    return options


def build_reminder_cancelled_embed():
    embed = make_embed(
        "🗑️ Reminder cancelled",
        "That reminder will not fire anymore.",
        color=Palette.SUCCESS,
    )
    brand_footer(embed)
    return embed


def build_reminder_delivery_embed(message):
    embed = make_embed("⏰ Reminder", message, color=Palette.WARNING)
    brand_footer(embed, "You asked me to remind you")
    return embed


def build_invalid_reminder_duration_embed():
    embed = make_embed(
        "🤔 I did not get that",
        "Use formats like `10m`, `1h30m`, `2d`, `1w`.",
        color=Palette.WARNING,
    )
    brand_footer(embed)
    return embed


def build_reminder_too_far_embed():
    embed = make_embed(
        "📅 Too far away",
        "Reminders max out at 90 days.",
        color=Palette.WARNING,
    )
    brand_footer(embed)
    return embed


def build_reminder_set_embed(due_at, message):
    embed = make_embed(
        "⏰ Reminder set!",
        f"I'll ping you {discord.utils.format_dt(due_at, 'R')} about:\n> {message}",
        color=Palette.SUCCESS,
    )
    brand_footer(embed, "Reminder saved")
    return embed


def build_no_reminders_embed():
    embed = make_embed(
        "💤 Nothing pending",
        "You have no reminders. Set one with `/remind`!",
        color=Palette.INFO,
    )
    brand_footer(embed)
    return embed


def build_reminders_embed(items):
    lines = []
    for item in items[:15]:
        due = datetime.fromisoformat(item["due_at"])
        lines.append(
            f"⏰ {discord.utils.format_dt(due, 'R')} — {truncate(item['message'], 80)}"
        )
    embed = make_embed("🗓️ Your reminders", "\n".join(lines), color=Palette.INFO)
    brand_footer(embed, f"{len(items)} pending")
    return embed


def build_poll_embed(question, options, votes, author_name, closed=False):
    total = len(votes)
    counts = Counter(votes.values())
    lines = []
    for index, option in enumerate(options):
        count = counts.get(index, 0)
        percent = round(count / total * 100) if total else 0
        bar = progress_bar(count, total or 1, slots=12)
        lines.append(f"**{option}**\n{bar} `{count} vote(s) • {percent}%`")

    title = ("🏁 " if closed else "📊 ") + question
    embed = make_embed(
        title,
        "\n\n".join(lines),
        color=Palette.SUCCESS if closed else Palette.INFO,
    )
    status = "Final results" if closed else "Vote by clicking a button below"
    brand_footer(
        embed,
        f"Poll by {author_name} • {total} vote(s) • {status} • temporary 24h",
    )
    return embed


def build_userinfo_embed(target):
    badges = [
        BADGE_LABELS[name]
        for name, value in target.public_flags
        if value and name in BADGE_LABELS
    ]
    roles = [role.mention for role in reversed(target.roles[1:])][:5]
    color = target.color.value if target.color.value else Palette.PRIMARY

    embed = make_embed(
        f"👤 {target.display_name}",
        f"{target.mention} • `{target.id}`",
        color=color,
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(
        name="📅 Dates",
        value=(
            f"Created: {discord.utils.format_dt(target.created_at, 'R')}\n"
            f"Joined: {discord.utils.format_dt(target.joined_at, 'R') if target.joined_at else 'Unknown'}"
        ),
        inline=True,
    )
    embed.add_field(
        name="🎭 Identity",
        value=(
            f"Bot: `{('Yes 🤖' if target.bot else 'No')}`\n"
            f"Top role: {target.top_role.mention if target.top_role else '`None`'}"
        ),
        inline=True,
    )
    embed.add_field(
        name=f"🏷️ Roles ({max(len(target.roles) - 1, 0)})",
        value=" ".join(roles) if roles else "`No roles`",
        inline=False,
    )
    if badges:
        embed.add_field(name="✨ Badges", value=" • ".join(badges), inline=False)
    brand_footer(embed, "User info")
    return embed


def build_serverinfo_embed(guild):
    embed = make_embed(
        f"🏰 {guild.name}",
        guild.description or "A great place to be.",
        color=Palette.PURPLE,
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(
        name="👥 People",
        value=(
            f"Members: `{guild.member_count:,}`\n"
            f"Owner: {guild.owner.mention if guild.owner else 'Unknown'}"
        ),
        inline=True,
    )
    embed.add_field(
        name="💬 Channels",
        value=f"Text: `{len(guild.text_channels)}`\nVoice: `{len(guild.voice_channels)}`",
        inline=True,
    )
    embed.add_field(
        name="🎨 Flair",
        value=f"Roles: `{len(guild.roles)}`\nEmojis: `{len(guild.emojis)}`",
        inline=True,
    )
    embed.add_field(
        name="🚀 Boosts",
        value=f"Level: `{guild.premium_tier}`\nBoosts: `{guild.premium_subscription_count or 0}`",
        inline=True,
    )
    embed.add_field(
        name="📅 Created",
        value=discord.utils.format_dt(guild.created_at, "D"),
        inline=True,
    )
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    brand_footer(embed, f"Server ID: {guild.id}")
    return embed


def build_avatar_embed(target):
    asset = target.display_avatar.with_size(1024)
    embed = make_embed(f"🖼️ {target.display_name}'s avatar", color=Palette.FUN)
    embed.set_image(url=asset.url)
    brand_footer(embed, "Avatar viewer")
    return embed, asset.url


def build_roleinfo_embed(role):
    color = role.color.value if role.color.value else Palette.PRIMARY
    embed = make_embed(
        f"🏷️ {role.name}",
        f"{role.mention} • `{role.id}`",
        color=color,
    )
    embed.add_field(
        name="Details",
        value=(
            f"Members: `{len(role.members)}`\n"
            f"Position: `{role.position}`\n"
            f"Color: `#{role.color.value:06X}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Flags",
        value=(
            f"Hoisted: `{('Yes' if role.hoist else 'No')}`\n"
            f"Mentionable: `{('Yes' if role.mentionable else 'No')}`\n"
            f"Managed: `{('Yes' if role.managed else 'No')}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="📅 Created",
        value=discord.utils.format_dt(role.created_at, "R"),
        inline=False,
    )
    brand_footer(embed, "Role info")
    return embed


def build_timestamp_embed(moment):
    unix = int(moment.timestamp())
    lines = [
        f"`<t:{unix}:{code}>` → <t:{unix}:{code}> — {label}"
        for code, label in TIMESTAMP_STYLES
    ]
    embed = make_embed("🕐 Timestamp generator", "\n".join(lines), color=Palette.TEAL)
    brand_footer(embed, "Copy the code, paste anywhere")
    return embed


def build_choice_embed(choices, winner):
    embed = make_embed(
        "🎯 The wheel of fate has spoken",
        f"Out of {', '.join(f'`{choice}`' for choice in choices)}…\n\n# 🏆 {winner}",
        color=Palette.FUN,
    )
    brand_footer(embed, "Destiny delivered")
    return embed


def build_color_embed(hex_digits):
    value = int(hex_digits, 16)
    red, green, blue = (
        (value >> 16) & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
    )
    embed = make_embed(f"🎨 #{hex_digits.upper()}", color=value)
    embed.add_field(name="RGB", value=f"`{red}, {green}, {blue}`", inline=True)
    embed.add_field(name="Int", value=f"`{value}`", inline=True)
    embed.set_image(url=f"https://singlecolorimage.com/get/{hex_digits}/400x100")
    brand_footer(embed, "Color preview")
    return embed
