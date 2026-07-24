"""Small shared helpers: time parsing, text shaping, link button views."""

import re
import textwrap
from datetime import UTC, datetime, timedelta

import discord

DURATION_PATTERN = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_github_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def format_github_time(value, style="R"):
    dt_value = parse_github_datetime(value)
    if not dt_value:
        return "Unknown"
    return discord.utils.format_dt(dt_value, style)


def humanize_number(value):
    return f"{value:,}"


def truncate(text, limit=240):
    if not text:
        return "No details available."
    return textwrap.shorten(" ".join(text.split()), width=limit, placeholder="...")


def first_line(text, fallback="No details available."):
    if not text:
        return fallback
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    return lines[0] if lines else fallback


def parse_duration(text):
    """Parse strings like '10m', '1h30m', '2d' into a timedelta."""
    matches = DURATION_PATTERN.findall(text or "")
    if not matches:
        return None
    total_seconds = sum(int(amount) * UNIT_SECONDS[unit.lower()] for amount, unit in matches)
    return timedelta(seconds=total_seconds) if total_seconds > 0 else None


def format_timedelta(delta):
    total_seconds = max(int(delta.total_seconds()), 0)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def build_link_view(buttons):
    unique_buttons = []
    seen_urls = set()

    for label, url in buttons:
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique_buttons.append((label, url))
        if len(unique_buttons) == 5:
            break

    if not unique_buttons:
        return None

    view = discord.ui.View(timeout=None)
    for label, url in unique_buttons:
        view.add_item(discord.ui.Button(label=label, url=url))
    return view


async def send_embed(destination, embed, view=None, **kwargs):
    """Send an embed, only attaching a view when one exists."""
    if view is not None:
        kwargs["view"] = view
    return await destination.send(embed=embed, **kwargs)


async def defer_interaction(interaction, *, ephemeral=False, thinking=False):
    """Defer an interaction unless it has already been acknowledged."""
    if interaction.response.is_done():
        return False

    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=thinking)
        return True
    except discord.InteractionResponded:
        return False
    except discord.NotFound as error:
        if getattr(error, "code", None) == 10062:
            print("Interaction acknowledgement skipped: Discord expired the interaction token.")
            return False
        raise


async def respond(interaction, embed=None, view=None, ephemeral=False, content=None):
    """Reply to an interaction whether or not it was already deferred."""
    extra = {"view": view} if view is not None else {}
    if content is not None:
        extra["content"] = content
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(embed=embed, ephemeral=ephemeral, wait=True, **extra)
        return await interaction.response.send_message(embed=embed, ephemeral=ephemeral, **extra)
    except discord.NotFound as error:
        if getattr(error, "code", None) == 10062:
            print("Interaction response skipped: Discord expired the interaction token.")
            return None
        raise
