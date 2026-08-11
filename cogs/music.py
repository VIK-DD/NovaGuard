"""Music category — playback from YouTube and SoundCloud with a button player."""

import asyncio
import shlex

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.database import cache_prefix_search
from core.music_card import card_fields
from core.music_queue import LoopMode
from core.music_session import IDLE_DISCONNECT_SECONDS, SessionRegistry
from core.music_sources import (
    classify_input,
    extract,
    ffmpeg_proxy_url,
    format_duration,
    refresh_stream_url,
    search_cache_prefix,
    soundcloud_fallback_for,
    spotify_credentials_configured,
    youtube_bot_check_recent,
)
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


def is_missing_voice_backend_error(error):
    text = str(error or "")
    return "library needed in order to use voice" in text


def missing_voice_backend_embed():
    embed = make_embed(
        "Voice support is not installed",
        "Install the Python voice dependencies on the host, then restart the bot: "
        "`venv/bin/python -m pip install -r requirements.txt`.",
        color=Palette.DANGER,
    )
    brand_footer(embed, "Music")
    return embed


def nothing_found_description(query):
    kind, platform, _ = classify_input(query)
    if platform == "spotify" and kind == "playlist" and not spotify_credentials_configured():
        return (
            "Spotify playlist and album links need `SPOTIFY_CLIENT_ID` and "
            "`SPOTIFY_CLIENT_SECRET` in `.env`. Single Spotify track links can still "
            "work best-effort; playlists need the Spotify Web API."
        )
    if platform == "spotify":
        return (
            "I could not read that Spotify link or find a playable match for it. "
            "Spotify audio cannot be streamed directly, so I search YouTube for the track."
        )
    if youtube_bot_check_recent():
        return (
            "YouTube is currently challenging this server's IP "
            "(\"Sign in to confirm you're not a bot\"), so streams cannot be resolved. "
            "The host needs a clean egress: set `MUSIC_YTDLP_PROXY` in `.env` or move "
            "the bot to an unflagged IP - see SETUP.md > Music."
        )
    return (
        f"I could not find anything for `{query[:120]}`. If this happens for every song, "
        "check the host logs for `Music extraction` - YouTube may be blocking yt-dlp there."
    )


class MusicControls(discord.ui.View):
    """The player buttons."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def _session_or_refusal(self, interaction):
        session = self.cog.sessions.get(interaction.guild_id)
        if session is None or session.voice_client is None:
            await interaction.response.send_message("This session has ended.", ephemeral=True)
            return None
        if not in_voice_with_bot(interaction, session):
            await interaction.response.send_message(
                "You have to be in my voice channel to control playback.", ephemeral=True
            )
            return None
        return session

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary, custom_id="ng:music:toggle")
    async def toggle(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        client = session.voice_client
        if client.is_paused():
            client.resume()
        else:
            client.pause()
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="ng:music:skip")
    async def skip_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.voice_client.stop()
        session.touch()
        await interaction.response.defer()

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="ng:music:stop")
    async def stop_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        await self.cog._teardown(session)
        await interaction.response.edit_message(content="Playback stopped.", embed=None, view=None)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="ng:music:shuffle")
    async def shuffle_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.queue.shuffle()
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="ng:music:loop")
    async def loop_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.queue.set_loop(LoopMode.next_mode(session.queue.loop))
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=1, custom_id="ng:music:voldown")
    async def volume_down(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.volume = max(0, session.volume - 10)
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=1, custom_id="ng:music:volup")
    async def volume_up(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.volume = min(100, session.volume + 10)
        session.touch()
        await self.cog.refresh_card(session, interaction)


class Music(commands.Cog):
    """Music playback with a queue and a button-driven player."""

    EMOJI = "🎵"
    COLOR = Palette.FUN
    DESCRIPTION = "Play music from YouTube and SoundCloud, with a queue and a button player."

    def __init__(self, bot):
        self.bot = bot
        self.sessions = SessionRegistry()
        self._prefetch_tasks: set = set()
        # Futures handed back from the audio thread, held so nothing collects
        # them mid-flight. See _schedule_from_audio_thread.
        self._after_tasks: set = set()
        self._early_end_retries = {}

    # Reconnect flags matter on a small host: without them a brief network
    # hiccup can end a track silently instead of resuming it. 403/404 are
    # deliberately not retried: a dead signed CDN URL never recovers, and
    # retrying it holds the track in silent "playing" limbo instead of letting
    # the early-end logic refresh the stream URL.
    FFMPEG_BEFORE = (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-reconnect_at_eof 1 -reconnect_on_network_error 1 "
        "-reconnect_on_http_error 429,5xx -rw_timeout 15000000 "
        "-nostdin -loglevel warning"
    )
    SOUNDCHECK_DURATION_SECONDS = 5
    MAX_CONSECUTIVE_SKIPS = 5
    EARLY_END_GRACE_SECONDS = 20
    EARLY_END_RETRY_WINDOW_SECONDS = 90
    MAX_EARLY_END_RETRIES = 1

    def _ffmpeg_before_options(self, track):
        """Include yt-dlp's HTTP headers so signed CDN URLs do not 403."""
        parts = [self.FFMPEG_BEFORE]
        proxy = ffmpeg_proxy_url()
        if proxy and getattr(track, "source", "") == "youtube":
            # YouTube CDN URLs are bound to the IP that resolved them, so the
            # stream must ride the same proxy yt-dlp used.
            parts.append(f"-http_proxy {shlex.quote(proxy)}")
        headers = getattr(track, "http_headers", None) or {}
        if headers:
            header_lines = []
            for name, value in headers.items():
                header_lines.append(f"{name}: {value}")
            header_blob = "\r\n".join(header_lines) + "\r\n"
            parts.append(f"-headers {shlex.quote(header_blob)}")
        return " ".join(parts)

    def _soundcheck_source_args(self):
        """Arguments for a local test tone; no yt-dlp, no network, no CDN."""
        return (
            f"sine=frequency=880:duration={self.SOUNDCHECK_DURATION_SECONDS}",
            "-f lavfi",
            "-vn",
        )

    def _soundcheck_source(self):
        """Build the local test tone source."""
        source, before_options, options = self._soundcheck_source_args()
        pcm = discord.FFmpegPCMAudio(
            source,
            before_options=before_options,
            options=options,
        )
        return discord.PCMVolumeTransformer(pcm, volume=0.35)

    async def cog_load(self):
        self.bot.add_view(MusicControls(self))
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
        except RuntimeError as error:
            if not is_missing_voice_backend_error(error):
                raise
            print(f"Music voice backend missing in guild {interaction.guild_id}: {error!r}")
            await self._teardown(session)
            return None, missing_voice_backend_embed()
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
                before_options = self._ffmpeg_before_options(track)
                if volume >= 100:
                    return await discord.FFmpegOpusAudio.from_probe(
                        track.stream_url, before_options=before_options, options="-vn"
                    )
                pcm = discord.FFmpegPCMAudio(
                    track.stream_url, before_options=before_options, options="-vn"
                )
                return discord.PCMVolumeTransformer(pcm, volume=volume / 100)
            except Exception as error:
                if attempt == 2 or not await refresh_stream_url(track):
                    print(f"Music source failed for {track.url}: {error!r}")
                    return None
        return None

    def _track_retry_key(self, session, track):
        return (str(session.guild_id), getattr(track, "url", None) or getattr(track, "title", ""))

    def _ended_too_early(self, session, track):
        """True when FFmpeg ended long before the track should have ended."""
        import time

        if not track or not track.duration or not session.started_at:
            return False
        elapsed = int(time.monotonic() - session.started_at)
        if elapsed >= self.EARLY_END_RETRY_WINDOW_SECONDS:
            return False
        return elapsed + self.EARLY_END_GRACE_SECONDS < int(track.duration)

    async def _retry_early_end(self, session, track):
        """Refresh one dead CDN URL and replay the same track once."""
        import time

        if not self._ended_too_early(session, track):
            return False

        key = self._track_retry_key(session, track)
        retries = self._early_end_retries.get(key, 0)
        if retries >= self.MAX_EARLY_END_RETRIES:
            return False
        self._early_end_retries[key] = retries + 1

        client = session.voice_client
        if client is None or not client.is_connected():
            return False

        track.stream_url = None
        track.http_headers = {}
        source = await self._audio_source(track, session.volume)
        if source is None:
            return False

        await self._notify(session, f"Stream refreshed for **{track.title}** - retrying playback.")

        def after_playing(error, session=session, track=track):
            if error:
                print(f"Music playback error in guild {session.guild_id}: {error!r}")
            self._schedule_from_audio_thread(self._on_track_finished(session, track))

        try:
            client.play(source, after=after_playing)
        except discord.ClientException as error:
            print(f"Music retry play call failed in guild {session.guild_id}: {error!r}")
            return False

        session.started_at = time.monotonic()
        session.touch()
        await self.refresh_card(session)
        return True

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
                fallback = await soundcloud_fallback_for(track)
                if fallback is not None:
                    fallback_source = await self._audio_source(fallback, session.volume)
                    if fallback_source is not None:
                        session.queue.replace_current(fallback)
                        track = fallback
                        source = fallback_source
                    else:
                        source = None
                if source is None:
                    await self._notify(session, f"Skipped **{track.title}** - it could not be played.")
                    continue

            self._early_end_retries.pop(self._track_retry_key(session, track), None)

            def after_playing(error, session=session, track=track):
                if error:
                    print(f"Music playback error in guild {session.guild_id}: {error!r}")
                self._schedule_from_audio_thread(self._on_track_finished(session, track))

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

    def _schedule_from_audio_thread(self, coro):
        """Hand a coroutine back to the event loop from the audio player thread.

        discord.py calls `after=` from `AudioPlayer.run`, which is a plain
        thread — `loop.create_task` there touches the loop from the wrong
        thread and may never schedule the coroutine at all. The returned future
        is also kept: asyncio holds only a weak reference to running work, and
        the coroutine this schedules is the one that advances the queue, so
        losing it stops the music with no error anywhere.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
        self._after_tasks.add(future)
        future.add_done_callback(self._after_tasks.discard)
        return future

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

    async def _on_track_finished(self, session, finished_track=None):
        """Chain to the next track without stranding the session on errors."""
        try:
            if await self._retry_early_end(session, finished_track):
                return
            await self._play_next(session)
        except Exception as error:
            print(f"Music advance failed in guild {session.guild_id}: {error!r}")
            session.touch()

    async def _on_soundcheck_finished(self, session, error):
        """Clean up an isolated soundcheck without disturbing a real queue."""
        if error:
            print(f"Music soundcheck playback error in guild {session.guild_id}: {error!r}")
        session.touch()
        await asyncio.sleep(2)
        client = session.voice_client
        if client and not (client.is_playing() or client.is_paused()) and session.queue.current is None:
            await self._teardown(session)

    async def _notify(self, session, text):
        channel = self.bot.get_channel(session.text_channel_id) if session.text_channel_id else None
        if channel is None:
            return
        try:
            await channel.send(text)
        except discord.HTTPException:
            pass

    def build_card(self, session):
        import time

        elapsed = int(time.monotonic() - session.started_at) if session.started_at else 0
        client = session.voice_client
        fields = card_fields(
            current=session.queue.current,
            upcoming=session.queue.upcoming,
            elapsed=elapsed,
            volume=session.volume,
            loop=session.queue.loop,
            paused=bool(client and client.is_paused()),
        )
        embed = make_embed(fields["title"], fields["description"], color=Palette.FUN)
        current = session.queue.current
        if current and current.thumbnail:
            embed.set_thumbnail(url=current.thumbnail)
        embed.add_field(name="Progress", value=fields["progress"], inline=False)
        embed.add_field(name="Next up", value=fields["next_up"], inline=False)
        brand_footer(embed, fields["footer"])
        return embed

    async def refresh_card(self, session, interaction=None):
        """Redraw the card in place. Called on state change only."""
        embed = self.build_card(session)
        if interaction is not None:
            try:
                await interaction.response.edit_message(embed=embed, view=MusicControls(self))
            except discord.HTTPException:
                pass
            return
        if session.text_channel_id is None or session.card_message_id is None:
            return
        channel = self.bot.get_channel(session.text_channel_id)
        if channel is None:
            return
        try:
            message = await channel.fetch_message(session.card_message_id)
            await message.edit(embed=embed, view=MusicControls(self))
        except discord.HTTPException:
            pass

    async def _announce_track(self, session, track):
        """Post a fresh card and remove the previous one."""
        import time

        session.started_at = time.monotonic()
        channel = self.bot.get_channel(session.text_channel_id) if session.text_channel_id else None
        if channel is None:
            return

        if session.card_message_id is not None:
            try:
                old = await channel.fetch_message(session.card_message_id)
                await old.delete()
            except discord.HTTPException:
                pass
            session.card_message_id = None

        try:
            message = await channel.send(embed=self.build_card(session), view=MusicControls(self))
            session.card_message_id = message.id
        except discord.HTTPException as error:
            print(f"Music card could not be posted in guild {session.guild_id}: {error!r}")

    async def play_autocomplete(self, interaction: discord.Interaction, current: str):
        """Suggestions from the cache only; never call yt-dlp from autocomplete."""
        text = (current or "").strip()
        if not text:
            return []
        try:
            rows = await asyncio.to_thread(
                cache_prefix_search, search_cache_prefix(text), 20
            )
        except Exception:
            rows = []

        choices = []
        for _, payload in rows:
            title = (payload or {}).get("title")
            if not title:
                continue
            choices.append(app_commands.Choice(name=title[:100], value=title[:100]))
            if len(choices) == 24:
                break
        if not choices:
            return [app_commands.Choice(name=f"Press Enter to search \"{text}\""[:100], value=text[:100])]
        return choices

    async def remove_autocomplete(self, interaction: discord.Interaction, current: str):
        session = self.sessions.get(interaction.guild_id)
        if session is None:
            return []
        text = (current or "").lower()
        choices = []
        for position, track in enumerate(session.queue.upcoming[:25], start=1):
            label = f"{position}. {track.title}"[:100]
            if text and text not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label, value=position))
        return choices[:25]

    @app_commands.command(name="play", description="Play a song from a link or a search")
    @app_commands.describe(query="A YouTube/SoundCloud/Spotify link, or words to search for")
    @app_commands.autocomplete(query=play_autocomplete)
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str):
        await defer_interaction(interaction, thinking=True)

        session, error = await self._connect(interaction)
        if error is not None:
            return await respond(interaction, error, ephemeral=True)

        tracks = await extract(query, interaction.user.id)
        if not tracks:
            embed = make_embed(
                "Nothing found",
                nothing_found_description(query),
                color=Palette.WARNING,
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
            client = session.voice_client
            if client is None or not (client.is_playing() or client.is_paused()):
                # Every queued track failed to start; saying "Playing now"
                # here is exactly the silent-player confusion we avoid.
                if youtube_bot_check_recent():
                    detail = (
                        "YouTube is challenging this server's IP right now, so the "
                        "stream could not be started. The host needs `MUSIC_YTDLP_PROXY` "
                        "or a clean IP - see SETUP.md > Music."
                    )
                else:
                    detail = (
                        "The track was found but its audio stream could not be started. "
                        "Check the host logs for `Music` errors."
                    )
                embed = make_embed("Could not start playback", detail, color=Palette.DANGER)
                brand_footer(embed, "Music")
                return await respond(interaction, embed, ephemeral=True)

        first = tracks[0]
        source_label = {"youtube": "YouTube", "soundcloud": "SoundCloud"}.get(first.source, first.source.title())
        if accepted == 1:
            title = "Playing now" if was_idle else "Added to the queue"
            description = f"**{first.title}** `{format_duration(first.duration)}`\nSource: `{source_label}`"
        else:
            title = "Playlist added"
            description = f"Queued `{accepted}` tracks from `{source_label}`, starting with **{first.title}**."
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

    @app_commands.command(name="queue", description="Show what is playing and what comes next")
    @app_commands.guild_only()
    async def queue_command(self, interaction: discord.Interaction):
        await defer_interaction(interaction)
        session = self.sessions.get(interaction.guild_id)
        if session is None or session.queue.current is None:
            return await respond(
                interaction, nothing_playing_embed("Use `/play` to start."), ephemeral=True
            )
        await respond(interaction, self.build_card(session), view=MusicControls(self))

    @app_commands.command(name="nowplaying", description="Show the player card")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction):
        await self.queue_command.callback(self, interaction)

    @app_commands.command(name="soundcheck", description="Play a short local test tone")
    @app_commands.guild_only()
    async def soundcheck(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session, error = await self._connect(interaction)
        if error is not None:
            return await respond(interaction, error, ephemeral=True)

        client = session.voice_client
        if client is None or client.is_playing() or client.is_paused():
            embed = make_embed(
                "Soundcheck unavailable",
                "Stop the current playback first, then run `/soundcheck` again.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Music")
            return await respond(interaction, embed, ephemeral=True)

        def after_playing(playback_error, session=session):
            self._schedule_from_audio_thread(
                self._on_soundcheck_finished(session, playback_error)
            )

        try:
            client.play(self._soundcheck_source(), after=after_playing)
        except discord.ClientException as play_error:
            embed = make_embed(
                "Soundcheck failed",
                f"Discord refused the test tone: `{play_error}`.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Music")
            return await respond(interaction, embed, ephemeral=True)

        embed = make_embed(
            "Soundcheck playing",
            f"You should hear a short tone for `{self.SOUNDCHECK_DURATION_SECONDS}` seconds. "
            "If others hear it but you do not, check your local Discord volume/mute for NovaGuard.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="volume", description="Set playback volume (0-100)")
    @app_commands.describe(level="Volume percentage")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None or session.voice_client is None:
            return await respond(
                interaction, nothing_playing_embed("There is nothing to adjust."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        session.volume = int(level)
        session.touch()
        await self.refresh_card(session)
        embed = make_embed(
            "Volume set",
            f"Playback volume is now `{int(level)}%`. It applies from the next track.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="remove", description="Remove a track from the queue")
    @app_commands.describe(position="Which queued track to remove")
    @app_commands.autocomplete(position=remove_autocomplete)
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, position: int):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None:
            return await respond(
                interaction, nothing_playing_embed("There is nothing to remove."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        removed = session.queue.remove(position)
        if removed is None:
            embed = make_embed(
                "Not in the queue", f"There is no track at position `{position}`.", color=Palette.WARNING
            )
        else:
            embed = make_embed("Removed", f"**{removed.title}** left the queue.", color=Palette.SUCCESS)
            await self.refresh_card(session)
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="clear", description="Clear the queue without stopping the current track")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None:
            return await respond(
                interaction, nothing_playing_embed("The queue is already empty."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        removed = len(session.queue.upcoming)
        session.queue.clear()
        session.touch()
        await self.refresh_card(session)
        embed = make_embed(
            "Queue cleared", f"Removed `{removed}` queued track(s).", color=Palette.SUCCESS
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
