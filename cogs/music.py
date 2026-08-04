"""Music category — playback from YouTube and SoundCloud with a button player."""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.music_session import IDLE_DISCONNECT_SECONDS, SessionRegistry
from core.music_sources import extract, format_duration, refresh_stream_url
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

    # Reconnect flags matter on a small host: without them a brief network
    # hiccup can end a track silently instead of resuming it.
    FFMPEG_BEFORE = (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-nostdin -loglevel warning"
    )
    MAX_CONSECUTIVE_SKIPS = 5

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

    async def _connect(self, interaction):
        """Join the caller's voice channel, honouring the session cap.

        Returns ``(session, error_embed)``; exactly one is None.
        """
        voice = getattr(interaction.user, "voice", None)
        if voice is None or voice.channel is None:
            embed = make_embed(
                "Join a voice channel first",
                "Hop into a voice channel and run the command again.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Music")
            return None, embed

        existing = self.sessions.get(interaction.guild_id)
        if existing is None and not self.sessions.has_capacity():
            embed = make_embed(
                "All music slots are busy",
                f"I can play in `{self.sessions.MAX_SESSIONS}` servers at once and they are all "
                "in use right now. Try again in a few minutes.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Music")
            return None, embed

        if (
            existing is not None
            and existing.voice_client is not None
            and existing.voice_client.is_connected()
            and existing.voice_client.channel.id != voice.channel.id
            and not interaction.user.guild_permissions.manage_guild
        ):
            return None, not_in_voice_embed()

        session = self.sessions.create(interaction.guild_id)
        session.text_channel_id = interaction.channel_id
        session.touch()

        client = session.voice_client
        try:
            if client is None or not client.is_connected():
                session.voice_client = await voice.channel.connect(self_deaf=True, timeout=20)
            elif client.channel.id != voice.channel.id:
                await client.move_to(voice.channel)
        except (discord.ClientException, asyncio.TimeoutError, discord.HTTPException) as error:
            print(f"Music connect failed in guild {interaction.guild_id}: {error!r}")
            await self._teardown(session)
            embed = make_embed(
                "Could not join",
                "Check that I can view and connect to that voice channel.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Music")
            return None, embed

        return session, None

    async def _audio_source(self, track, volume):
        """Build the audio source, refreshing an expired link once if needed."""
        if not track.stream_url and not await refresh_stream_url(track):
            return None

        for attempt in (1, 2):
            try:
                if volume >= 100:
                    return await discord.FFmpegOpusAudio.from_probe(
                        track.stream_url, before_options=self.FFMPEG_BEFORE, options="-vn"
                    )
                pcm = discord.FFmpegPCMAudio(
                    track.stream_url, before_options=self.FFMPEG_BEFORE, options="-vn"
                )
                return discord.PCMVolumeTransformer(pcm, volume=volume / 100)
            except Exception as error:
                if attempt == 2 or not await refresh_stream_url(track):
                    print(f"Music source failed for {track.url}: {error!r}")
                    return None
        return None

    async def _play_next(self, session):
        """Advance the queue and start the next track."""
        client = session.voice_client
        if client is None or not client.is_connected():
            await self._teardown(session)
            return

        for _ in range(self.MAX_CONSECUTIVE_SKIPS):
            track = session.queue.advance()
            if track is None:
                session.started_at = None
                session.touch()
                await self.refresh_card(session)
                return

            source = await self._audio_source(track, session.volume)
            if source is None:
                await self._notify(session, f"Skipped **{track.title}** - it could not be played.")
                continue

            def after_playing(error, session=session):
                if error:
                    print(f"Music playback error in guild {session.guild_id}: {error!r}")
                self.bot.loop.create_task(self._on_track_finished(session))

            try:
                client.play(source, after=after_playing)
            except discord.ClientException as error:
                print(f"Music play call failed in guild {session.guild_id}: {error!r}")
                continue

            session.touch()
            await self._announce_track(session, track)
            self._schedule_prefetch(session)
            return

        await self._notify(session, "Too many tracks in a row failed. Stopping here.")

    def _schedule_prefetch(self, session):
        """Resolve the next track's stream link while this one plays."""
        upcoming = session.queue.upcoming
        if not upcoming or upcoming[0].stream_url:
            return
        task = self.bot.loop.create_task(self._prefetch(upcoming[0]))
        self._prefetch_tasks.add(task)
        task.add_done_callback(self._prefetch_tasks.discard)

    async def _prefetch(self, track):
        """Best-effort warm-up before a queued track starts."""
        try:
            await refresh_stream_url(track)
        except Exception as error:
            print(f"Music prefetch skipped for {track.url}: {error!r}")

    async def _on_track_finished(self, session):
        """Chain to the next track without stranding the session on errors."""
        try:
            await self._play_next(session)
        except Exception as error:
            print(f"Music advance failed in guild {session.guild_id}: {error!r}")
            session.touch()

    async def _notify(self, session, text):
        channel = self.bot.get_channel(session.text_channel_id) if session.text_channel_id else None
        if channel is None:
            return
        try:
            await channel.send(text)
        except discord.HTTPException:
            pass

    async def _announce_track(self, session, track):
        """Placeholder replaced by the player card in the next task."""
        import time

        session.started_at = time.monotonic()
        await self._notify(
            session, f"Now playing **{track.title}** `{format_duration(track.duration)}`"
        )

    async def refresh_card(self, session, interaction=None):
        """Placeholder replaced by the player card in the next task."""
        return

    @app_commands.command(name="play", description="Play a song from a link or a search")
    @app_commands.describe(query="A YouTube/SoundCloud/Spotify link, or words to search for")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str):
        await defer_interaction(interaction, thinking=True)

        session, error = await self._connect(interaction)
        if error is not None:
            return await respond(interaction, error, ephemeral=True)

        tracks = await extract(query, interaction.user.id)
        if not tracks:
            embed = make_embed(
                "Nothing found", f"I could not find anything for `{query[:120]}`.", color=Palette.WARNING
            )
            brand_footer(embed, "Music")
            return await respond(interaction, embed, ephemeral=True)

        accepted = session.queue.add_many(tracks)
        if accepted == 0:
            embed = make_embed(
                "Queue is full",
                "The music queue is full right now. Skip or clear a few tracks first.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Music")
            return await respond(interaction, embed, ephemeral=True)

        session.touch()

        client = session.voice_client
        was_idle = not (client.is_playing() or client.is_paused())
        if was_idle:
            await self._play_next(session)

        first = tracks[0]
        if accepted == 1:
            title = "Playing now" if was_idle else "Added to the queue"
            description = f"**{first.title}** `{format_duration(first.duration)}`"
        else:
            title = "Playlist added"
            description = f"Queued `{accepted}` tracks, starting with **{first.title}**."
        embed = make_embed(title, description, color=Palette.FUN)
        if first.thumbnail:
            embed.set_thumbnail(url=first.thumbnail)
        brand_footer(embed, "Music")
        await respond(interaction, embed)

    @app_commands.command(name="skip", description="Skip the current track")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None or session.voice_client is None:
            return await respond(
                interaction, nothing_playing_embed("There is nothing to skip."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        current = session.queue.current
        session.voice_client.stop()
        session.touch()
        embed = make_embed(
            "Skipped",
            f"**{current.title}** was skipped." if current else "Moving on.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)

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
