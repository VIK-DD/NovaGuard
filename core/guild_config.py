"""Guild-scoped configuration helpers."""

import asyncio

import discord

from .storage import get_guild_settings


def unique_ids(values):
    seen = set()
    result = []
    for value in values:
        if not value:
            continue
        try:
            channel_id = int(value)
        except (TypeError, ValueError):
            continue
        if channel_id in seen:
            continue
        seen.add(channel_id)
        result.append(channel_id)
    return result


def get_guild_channel_id(guild_id, key, fallback_id=None):
    settings = get_guild_settings(guild_id)
    return settings.get(key) or fallback_id


async def resolve_channel(bot, channel_id):
    if not channel_id:
        return None

    channel = bot.get_channel(int(channel_id))
    if channel is not None:
        return channel

    try:
        return await asyncio.wait_for(bot.fetch_channel(int(channel_id)), timeout=8)
    except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError, ValueError):
        return None


async def resolve_configured_channels(bot, key, fallback_id=None):
    channel_ids = []
    for guild in bot.guilds:
        settings = get_guild_settings(guild.id)
        channel_ids.append(settings.get(key))

    if fallback_id:
        channel_ids.append(fallback_id)

    channels = []
    for channel_id in unique_ids(channel_ids):
        channel = await resolve_channel(bot, channel_id)
        if channel is not None:
            channels.append(channel)
    return channels
