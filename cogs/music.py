"""Music category — playback from YouTube and SoundCloud with a button player."""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.music_session import IDLE_DISCONNECT_SECONDS, SessionRegistry
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, respond

IDLE_CHECK_SECONDS = 30


def in_voice_with_bot(interaction, session):
    """True when the caller may control this session."""
    if interaction.user.guild_permissions.manage_guild:
        return True
    voice = getattr(interaction.user, "voice", None)
    if voice is None or voice.channel is None:
        return False
    client = session.voice_client if session else None
    return bool(client and client.channel and client.channel.id == voice.channel.id)


def not_in_voice_embed():
    embed = make_embed(
        "Join the voice channel first",
        "You have to be in my voice channel to control playback.",
        color=Palette.WARNING,
    )
    brand_footer(embed, "Music")
    return embed


def nothing_playing_embed(detail="There is nothing playing here."):
    embed = make_embed("Nothing playing", detail, color=Palette.WARNING)
    brand_footer(embed, "Music")
    return embed


class Music(commands.Cog):
    """Music playback with a queue and a button-driven player."""

    EMOJI = "🎵"
    COLOR = Palette.FUN
    DESCRIPTION = "Play music from YouTube and SoundCloud, with a queue and a button player."

    def __init__(self, bot):
        self.bot = bot
        self.sessions = SessionRegistry()
        self._prefetch_tasks: set = set()

    async def cog_load(self):
        self.idle_watcher.start()

    async def cog_unload(self):
        self.idle_watcher.cancel()
        for session in self.sessions.all_sessions():
            await self._teardown(session)

    async def _teardown(self, session):
        """Disconnect and forget a session. Safe to call twice."""
        client = session.voice_client
        session.voice_client = None
        if client is not None:
            try:
                await client.disconnect(force=True)
            except Exception:
                pass
        self.sessions.drop(session.guild_id)

    @tasks.loop(seconds=IDLE_CHECK_SECONDS)
    async def idle_watcher(self):
        """Leave channels nobody is listening in."""
        try:
            for session in self.sessions.all_sessions():
                client = session.voice_client
                if client is None or not client.is_connected():
                    await self._teardown(session)
                    continue
                humans = [member for member in client.channel.members if not member.bot] if client.channel else []
                playing = client.is_playing() or client.is_paused()
                if humans and playing:
                    session.touch()
                    continue
                if session.idle_seconds() >= IDLE_DISCONNECT_SECONDS:
                    await self._teardown(session)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Music idle watcher sweep failed, will retry: {error!r}")

    @idle_watcher.before_loop
    async def before_idle_watcher(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="disconnect", description="Stop the music and leave the voice channel")
    @app_commands.guild_only()
    async def disconnect(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None or session.voice_client is None:
            return await respond(
                interaction, nothing_playing_embed("I am not in a voice channel here."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        await self._teardown(session)
        embed = make_embed(
            "Disconnected", "Playback stopped and the queue was cleared.", color=Palette.SUCCESS
        )
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Music(bot))
