"""Admin-facing error digest embeds for serious runtime issues."""

import asyncio
import traceback

import discord

from .config import ERROR_LOG_CHANNEL_ID
from .guild_config import resolve_configured_channels, resolve_channel
from .storage import get_guild_settings
from .theme import Palette, brand_footer, make_embed
from .utils import truncate

DIGEST_DEDUP_SECONDS = 120


def clamp_code_block(text, limit=900):
    cleaned = (text or "No traceback available.").strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3] + "..."
    return f"```py\n{cleaned}\n```"


async def resolve_error_channel(bot, guild=None):
    if guild is not None:
        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        channel_id = settings.get("error_log_channel") or ERROR_LOG_CHANNEL_ID
        return await resolve_channel(bot, channel_id)

    channels = await resolve_configured_channels(bot, "error_log_channel", ERROR_LOG_CHANNEL_ID)
    return channels[0] if channels else None


SECURITY_ALERT_DEDUP_SECONDS = 15 * 60


async def send_security_alert(bot, title, description, *, fields=(), key=None):
    """Push one security event to the admin channel, instead of only filing it.

    The admin-key lockout was recorded in `admin_audit` and nowhere else, which
    means it was discoverable exactly when someone thought to go and look. A
    brute-force attempt against the second factor is the kind of thing an
    operator wants to hear about while it is happening.

    Deliberately not routed through `send_error_digest`: this is not an
    exception, has no traceback, and must not be deduplicated against unrelated
    runtime errors. It carries no attempted key, no key hash, and no salt -
    only who, how often, and for how long they are locked out.
    """
    destination = await resolve_error_channel(bot)
    if destination is None:
        return False

    loop = asyncio.get_running_loop()
    cache = getattr(bot, "_security_alert_cache", {})
    signature = key or title
    last_sent = cache.get(signature)
    now = loop.time()
    # One alert per subject per lockout window. A repeated attacker is one
    # story, not forty messages - and an alert channel nobody can read is the
    # same as no alert at all.
    if last_sent is not None and now - last_sent < SECURITY_ALERT_DEDUP_SECONDS:
        return False
    cache[signature] = now
    bot._security_alert_cache = cache

    embed = make_embed(f"🔐 {title}", description, color=Palette.DANGER)
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=True)
    brand_footer(embed, "Security")
    try:
        await destination.send(embed=embed)
    except discord.HTTPException:
        return False
    return True


async def send_error_digest(bot, title, error, context=None, interaction=None):
    """Send one concise admin embed for serious errors, with short dedupe protection.

    The destination is deliberately held in its own name. It used to be called
    `channel`, and the interaction block below then reused that name for the
    channel the command was typed in - which silently redirected every slash
    command traceback into whatever public channel the member was standing in.
    Nothing here may rebind `destination`.
    """
    guild = interaction.guild if interaction is not None else None
    destination = await resolve_error_channel(bot, guild)
    if destination is None:
        return False

    loop = asyncio.get_running_loop()
    cache = getattr(bot, "_error_digest_cache", {})
    signature = f"{title}:{type(error).__name__}:{str(error)[:160]}:{context or ''}"
    # `None`, not `0`, for "never sent". loop.time() is a monotonic clock
    # counting from the machine's boot, so on a host that started a minute ago
    # it reads about 60 - and `60 - 0 < 120` made every first digest look like
    # a duplicate of one that never happened. The window it silently swallowed
    # was the first DIGEST_DEDUP_SECONDS of uptime: precisely the minutes after
    # a reboot or a bad deploy when an error most needs to be heard.
    last_sent = cache.get(signature)
    now = loop.time()
    if last_sent is not None and now - last_sent < DIGEST_DEDUP_SECONDS:
        return False
    cache[signature] = now
    bot._error_digest_cache = cache

    embed = make_embed(
        f"🚨 {title}",
        "A serious bot issue was captured automatically. The bot will keep running if recovery is possible.",
        color=Palette.DANGER,
    )
    embed.add_field(
        name="Error",
        value=f"`{type(error).__name__}: {truncate(str(error), 300)}`",
        inline=False,
    )

    if interaction is not None:
        command_name = interaction.command.qualified_name if interaction.command else "unknown"
        guild_name = interaction.guild.name if interaction.guild else "DM / unknown"
        source_channel = getattr(interaction, "channel", None)
        channel_label = (
            getattr(source_channel, "mention", None) or f"`{interaction.channel_id or 'unknown'}`"
        )
        embed.add_field(
            name="Interaction",
            value=(
                f"Command: `/{command_name}`\n"
                f"User: {interaction.user.mention} (`{interaction.user.id}`)\n"
                f"Guild: `{guild_name}`\n"
                f"Channel: {channel_label}"
            ),
            inline=False,
        )

    if context:
        embed.add_field(name="Context", value=truncate(context, 900), inline=False)

    traceback_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    embed.add_field(name="Traceback", value=clamp_code_block(traceback_text), inline=False)
    brand_footer(embed, "Error digest")

    try:
        await asyncio.wait_for(destination.send(embed=embed), timeout=8)
        return True
    except (discord.HTTPException, asyncio.TimeoutError):
        return False
