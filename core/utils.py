"""Small shared helpers: time parsing, text shaping, link button views."""

import logging
import re
import textwrap
from datetime import UTC, datetime, timedelta

import discord

log = logging.getLogger(__name__)

DURATION_PATTERN = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
# Ten years. Every caller clamps far below this (/timeout to 28 days, /remind
# to 90), so this is not a policy - it is the point past which a number stops
# being a duration a person typed and starts being an attempt to break the
# parser. Refusing here hands callers the None they already handle, instead of
# an exception out of timedelta.
MAX_DURATION_SECONDS = 10 * 365 * 86400
# Longer than any honest duration, and short enough that int() can never reach
# CPython's 4300-digit string-conversion limit, which raises rather than parses.
MAX_DURATION_TEXT = 100


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


# Discord's own embed limits. discord.py does not enforce them locally, so an
# oversized value is only refused by the API - as a 400 that reaches the global
# command error handler and files an error digest. Clamping is therefore not
# cosmetic: without it any member who can put text in a command option, and
# any GitHub contributor whose commit the watcher renders, can decide whether
# the bot's own reply succeeds.
EMBED_TITLE_LIMIT = 256
EMBED_DESCRIPTION_LIMIT = 4096
EMBED_FIELD_VALUE_LIMIT = 1024
EMBED_FIELD_NAME_LIMIT = 256


def clamp(text, limit):
    """Hard-cut `text` to `limit` characters, marking the cut when one happens.

    Unlike `truncate` this preserves newlines and does not collapse
    whitespace, so it suits an assembled block - a list of lines, a code
    block - where `truncate`'s word-shortening would destroy the shape.
    """
    value = "" if text is None else str(text)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def first_line(text, fallback="No details available."):
    if not text:
        return fallback
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    return lines[0] if lines else fallback


def parse_duration(text):
    """Parse strings like '10m', '1h30m', '2d' into a timedelta.

    Returns None for anything that is not a usable duration, hostile input
    included. `9999999999w` used to reach timedelta and raise OverflowError,
    and a few thousand digits used to reach int() and raise ValueError; both
    escaped to the global command error handler, which answers the member and
    files an error digest. That turned a text box any member can type into
    into a way to generate log traffic on demand.
    """
    text = text or ""
    if len(text) > MAX_DURATION_TEXT:
        return None
    matches = DURATION_PATTERN.findall(text)
    if not matches:
        return None

    total_seconds = 0
    for amount, unit in matches:
        total_seconds += int(amount) * UNIT_SECONDS[unit.lower()]
        # Checked inside the loop: a sum of several enormous parts must not be
        # allowed to build up before anyone looks at it.
        if total_seconds > MAX_DURATION_SECONDS:
            return None
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
            log.warning("Interaction acknowledgement skipped: Discord expired the interaction token.")
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
        callback = await interaction.response.send_message(embed=embed, ephemeral=ephemeral, **extra)
        # discord.py 2.6 returns an InteractionCallbackResponse here, not a
        # Message. Callers that need the sent message (poll, giveaway) expect a
        # Message or None and fall back to interaction.original_response().
        resource = getattr(callback, "resource", None)
        return resource if isinstance(resource, discord.Message) else None
    except discord.NotFound as error:
        if getattr(error, "code", None) == 10062:
            log.warning("Interaction response skipped: Discord expired the interaction token.")
            return None
        raise
