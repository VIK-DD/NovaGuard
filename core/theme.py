"""Visual identity: color palette, embed factory, progress bars."""

from datetime import UTC, datetime

import discord

from .config import github_config


class Palette:
    PRIMARY = 0x5865F2   # blurple
    SUCCESS = 0x57F287   # green
    WARNING = 0xFEE75C   # yellow
    DANGER = 0xED4245    # red
    FUN = 0xEB459E       # fuchsia
    INFO = 0x3498DB      # blue
    GOLD = 0xF1C40F
    TEAL = 0x1ABC9C
    PURPLE = 0x9B59B6
    ORANGE = 0xE67E22
    DARK = 0x2B2D31


LANGUAGE_COLORS = {
    "Python": 0x3572A5,
    "JavaScript": 0xF1E05A,
    "TypeScript": 0x3178C6,
    "HTML": 0xE34C26,
    "CSS": 0x563D7C,
    "Go": 0x00ADD8,
    "Rust": 0xDEA584,
    "PHP": 0x4F5D95,
}


def pick_embed_color(language_name=None, fallback=Palette.PRIMARY):
    return discord.Color(LANGUAGE_COLORS.get(language_name or "", fallback))


def make_embed(title=None, description=None, color=Palette.PRIMARY, timestamp=True, url=None):
    embed = discord.Embed(title=title, description=description, color=discord.Color(color), url=url)
    if timestamp:
        embed.timestamp = datetime.now(UTC)
    return embed


def brand_footer(embed, label=None):
    text = f"{github_config.brand_name} • {label}" if label else github_config.brand_name
    embed.set_footer(text=text)
    return embed


def progress_bar(current, total, slots=10, filled="▰", empty="▱"):
    if total <= 0:
        total = 1
    ratio = min(max(current / total, 0), 1)
    filled_slots = round(ratio * slots)
    return filled * filled_slots + empty * (slots - filled_slots)
