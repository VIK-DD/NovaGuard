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
        settings = get_guild_settings(guild.id)
        channel_id = settings.get("error_log_channel") or ERROR_LOG_CHANNEL_ID
        return await resolve_channel(bot, channel_id)

    channels = await resolve_configured_channels(bot, "error_log_channel", ERROR_LOG_CHANNEL_ID)
    return channels[0] if channels else None


async def send_error_digest(bot, title, error, context=None, interaction=None):
    """Send one concise admin embed for serious errors, with short dedupe protection."""
    guild = interaction.guild if interaction is not None else None
    channel = await resolve_error_channel(bot, guild)
    if channel is None:
        return False

    loop = asyncio.get_running_loop()
    cache = getattr(bot, "_error_digest_cache", {})
    signature = f"{title}:{type(error).__name__}:{str(error)[:160]}:{context or ''}"
    last_sent = cache.get(signature, 0)
    if loop.time() - last_sent < DIGEST_DEDUP_SECONDS:
        return False
    cache[signature] = loop.time()
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
        channel = getattr(interaction, "channel", None)
        channel_label = getattr(channel, "mention", None) or f"`{interaction.channel_id or 'unknown'}`"
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
        await asyncio.wait_for(channel.send(embed=embed), timeout=8)
        return True
    except (discord.HTTPException, asyncio.TimeoutError):
        return False
