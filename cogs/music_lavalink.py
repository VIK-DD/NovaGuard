"""Music category backed by a Lavalink node."""

import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.lavalink_config import lavalink_password, lavalink_uri, lavalink_wavelink_search
from core.music_card import progress_bar
from core.music_sources import classify_input, format_duration, spotify_credentials_configured
from core.music_session import IDLE_DISCONNECT_SECONDS
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, respond

try:
    import wavelink
except ModuleNotFoundError:  # pragma: no cover - optional backend dependency
    wavelink = None

IDLE_CHECK_SECONDS = 30
MAX_PLAYLIST_TRACKS = 100
MAX_QUEUE_LENGTH = 500
NODE_CONNECT_WAIT_SECONDS = 20
VOLUME_STEP = 10
MUSIC_LABEL = "VIK Dev Music"
LOOP_LABELS = {
    "off": "loop off",
    "track": "looping track",
    "queue": "looping queue",
}
SOURCE_COLORS = {
    "youtube": 0xFF0033,
    "youtubemusic": 0xFF0033,
    "soundcloud": Palette.ORANGE,
}


def _track_title(track):
    return getattr(track, "title", None) or str(track)


def _track_author(track):
    return getattr(track, "author", None) or getattr(track, "uploader", None) or ""


def _track_url(track):
    return getattr(track, "uri", None) or getattr(track, "url", None) or ""


def _track_artwork(track):
    return getattr(track, "artwork", None) or getattr(track, "thumbnail", None)


def _track_length_seconds(track):
    length = getattr(track, "length", None) or getattr(track, "duration", None) or 0
    return int(length / 1000) if length and length > 1000 else int(length or 0)


def _track_source_label(track):
    labels = {
        "youtube": "YouTube",
        "youtubemusic": "YouTube Music",
        "soundcloud": "SoundCloud",
    }
    return labels.get(_track_source_key(track), _track_source_name(track))


def _track_source_name(track):
    source = getattr(track, "source", None)
    return getattr(source, "name", None) or str(source or "Lavalink")


def _track_source_key(track):
    return _track_source_name(track).replace(" ", "").lower()


def _track_color(track):
    return SOURCE_COLORS.get(_track_source_key(track), Palette.FUN)


def _track_link(track):
    title = _track_title(track)
    url = _track_url(track)
    return f"[{title}]({url})" if url else title


def _loop_label(loop):
    return LOOP_LABELS.get(str(loop or "off"), "loop off")


def _queue_count_label(count):
    if count <= 0:
        return "empty"
    if count == 1:
        return "1 queued"
    return f"{count} queued"


def _volume_meter(volume, slots=10):
    clamped = min(100, max(0, int(volume or 0)))
    filled = round((clamped / 100) * slots)
    return "▰" * filled + "▱" * (slots - filled)


def _music_title(title):
    return f"{MUSIC_LABEL} • {title}"


def _music_footer(embed, label=None):
    brand_footer(embed, label or MUSIC_LABEL)


def _nothing_found_description(query):
    kind, platform, _ = classify_input(query)
    if platform == "spotify" and kind == "playlist" and not spotify_credentials_configured():
        return (
            "Spotify playlists need LavaSrc on the Lavalink node or Spotify credentials "
            "for metadata resolving. Try a YouTube link or a plain search."
        )
    return (
        f"Lavalink could not load `{query[:120]}`. Check the Lavalink logs first; "
        "the Discord voice connection can be fine while the node rejects the source."
    )


def _payload_error_text(payload):
    exception = getattr(payload, "exception", None) or getattr(payload, "error", None)
    return str(exception or payload or "")


def _track_failure_notice(payload):
    details = _payload_error_text(payload).lower()
    if any(
        marker in details
        for marker in (
            "requires login",
            "sign in",
            "all clients failed",
            "must find sig function",
            "signature",
            "cipher",
            "403",
            "forbidden",
        )
    ):
        return (
            "YouTube rejected this stream on the Lavalink node. NovaGuard skipped it; "
            "check OAuth/remoteCipher if this repeats."
        )
    if "video is unavailable" in details:
        return "YouTube says this video is unavailable from the Lavalink node; moving to the next item."
    return "Lavalink reported a track error; moving to the next item."


def _node_is_connected(node):
    status = getattr(node, "status", None)
    status_name = str(getattr(status, "name", "") or "").lower()
    status_text = str(status or "").lower()
    return status_name == "connected" or status_text.endswith("connected")


class LavalinkQueue:
    """Small queue wrapper around Wavelink tracks."""

    def __init__(self):
        self._tracks = []
        self._index = -1
        self.loop = "off"

    @property
    def current(self):
        if 0 <= self._index < len(self._tracks):
            return self._tracks[self._index]
        return None

    @property
    def upcoming(self):
        return self._tracks[self._index + 1 :]

    def add_many(self, tracks):
        accepted = 0
        for track in tracks:
            if len(self._tracks) >= MAX_QUEUE_LENGTH:
                break
            self._tracks.append(track)
            accepted += 1
        return accepted

    def advance(self):
        if not self._tracks:
            self._index = -1
            return None
        if self.loop == "track" and self.current is not None:
            return self.current
        if self._index + 1 < len(self._tracks):
            self._index += 1
            return self.current
        if self.loop == "queue":
            self._index = 0
            return self.current
        self._index = len(self._tracks)
        return None

    def remove(self, position):
        if position < 1 or position > len(self.upcoming):
            return None
        return self._tracks.pop(self._index + position)

    def clear(self):
        del self._tracks[self._index + 1 :]

    def shuffle(self):
        upcoming = self.upcoming
        random.shuffle(upcoming)
        self._tracks[self._index + 1 :] = upcoming

    def next_loop(self):
        modes = ("off", "track", "queue")
        self.loop = modes[(modes.index(self.loop) + 1) % len(modes)]
        return self.loop


class LavalinkSession:
    def __init__(self, guild_id):
        import time

        self.guild_id = str(guild_id)
        self.queue = LavalinkQueue()
        self.player = None
        self.text_channel_id = None
        self.card_message_id = None
        self.volume = 100
        self._idle_since = time.monotonic()

    def touch(self):
        import time

        self._idle_since = time.monotonic()

    def idle_seconds(self):
        import time

        return time.monotonic() - self._idle_since


class LavalinkControls(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def _session_or_refusal(self, interaction):
        session = self.cog.sessions.get(str(interaction.guild_id))
        player = session.player if session else None
        if session is None or player is None or not getattr(player, "connected", False):
            await interaction.response.send_message("This session has ended.", ephemeral=True)
            return None
        if not self.cog._can_control(interaction, session):
            await interaction.response.send_message(
                "You have to be in my voice channel to control playback.", ephemeral=True
            )
            return None
        return session

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary, custom_id="ng:lavalink:toggle")
    async def toggle(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        await session.player.pause(not session.player.paused)
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="ng:lavalink:skip")
    async def skip_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.touch()
        await session.player.skip(force=True)
        await interaction.response.defer()

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="ng:lavalink:stop")
    async def stop_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        await self.cog._teardown(session)
        await interaction.response.edit_message(content="Playback stopped.", embed=None, view=None)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="ng:lavalink:shuffle")
    async def shuffle_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.queue.shuffle()
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="ng:lavalink:loop")
    async def loop_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.queue.next_loop()
        session.touch()
        await self.cog.refresh_card(session, interaction)

    async def _set_volume(self, interaction, delta):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.volume = min(100, max(0, session.volume + delta))
        await session.player.set_volume(session.volume)
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=1, custom_id="ng:lavalink:voldown")
    async def volume_down(self, interaction, button):
        await self._set_volume(interaction, -VOLUME_STEP)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=1, custom_id="ng:lavalink:volup")
    async def volume_up(self, interaction, button):
        await self._set_volume(interaction, VOLUME_STEP)


class LavalinkMusic(commands.Cog):
    """Music playback with Lavalink."""

    EMOJI = "🎵"
    COLOR = Palette.FUN
    DESCRIPTION = "Play music through Lavalink with a queue and button player."

    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self._node_error = None

    async def cog_load(self):
        self.bot.add_view(LavalinkControls(self))
        self.idle_watcher.start()
        await self._ensure_node()

    async def cog_unload(self):
        self.idle_watcher.cancel()
        for session in list(self.sessions.values()):
            await self._teardown(session)
        if wavelink is not None:
            try:
                await wavelink.Pool.close()
            except Exception:
                pass

    async def _ensure_node(self):
        if wavelink is None:
            self._node_error = "Install `wavelink>=3.4,<4` in the venv."
            return False
        try:
            node = wavelink.Pool.get_node()
            if _node_is_connected(node):
                self._node_error = None
                return True
        except Exception:
            pass

        try:
            node = wavelink.Node(uri=lavalink_uri(), password=lavalink_password(), retries=10)
            await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)
            for _ in range(NODE_CONNECT_WAIT_SECONDS * 2):
                try:
                    candidate = wavelink.Pool.get_node()
                except Exception:
                    candidate = node
                if _node_is_connected(candidate):
                    self._node_error = None
                    return True
                await asyncio.sleep(0.5)
            self._node_error = (
                f"Lavalink at `{lavalink_uri()}` did not reach CONNECTED state yet. "
                "Wait until Lavalink says ready, then try again."
            )
            return False
        except Exception as error:
            self._node_error = str(error) or repr(error)
            print(f"Lavalink node unavailable: {error!r}")
            return False

    def _session(self, guild_id):
        key = str(guild_id)
        if key not in self.sessions:
            self.sessions[key] = LavalinkSession(key)
        return self.sessions[key]

    def _can_control(self, interaction, session):
        if interaction.user.guild_permissions.manage_guild:
            return True
        voice = getattr(interaction.user, "voice", None)
        if voice is None or voice.channel is None:
            return False
        player = session.player
        channel = getattr(player, "channel", None)
        return bool(channel and channel.id == voice.channel.id)

    async def _connect(self, interaction):
        if not await self._ensure_node():
            embed = make_embed(
                _music_title("Lavalink is not ready"),
                f"The Lavalink backend is enabled, but the node is unavailable: `{self._node_error}`",
                color=Palette.DANGER,
            )
            _music_footer(embed)
            return None, embed

        voice = getattr(interaction.user, "voice", None)
        if voice is None or voice.channel is None:
            embed = make_embed(
                _music_title("Join voice first"),
                "Hop into a voice channel and run the command again.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return None, embed

        session = self._session(interaction.guild_id)
        session.text_channel_id = interaction.channel_id
        session.touch()

        player = interaction.guild.voice_client
        try:
            if player is None or not isinstance(player, wavelink.Player):
                player = await voice.channel.connect(cls=wavelink.Player, self_deaf=True, timeout=20)
            elif getattr(player, "channel", None) and player.channel.id != voice.channel.id:
                if not interaction.user.guild_permissions.manage_guild:
                    embed = make_embed(
                        _music_title("Join my voice channel"),
                        "I am already playing somewhere else in this server.",
                        color=Palette.WARNING,
                    )
                    _music_footer(embed)
                    return None, embed
                await player.move_to(voice.channel)
        except Exception as error:
            embed = make_embed(
                _music_title("Could not join"),
                f"Lavalink could not connect to that voice channel: `{error}`",
                color=Palette.DANGER,
            )
            _music_footer(embed)
            return None, embed

        session.player = player
        return session, None

    async def _teardown(self, session):
        player = session.player
        session.player = None
        self.sessions.pop(str(session.guild_id), None)
        if player is None:
            return
        try:
            await player.disconnect(force=True)
        except Exception:
            pass

    async def _load_tracks(self, query):
        target, source = lavalink_wavelink_search(query)
        try:
            results = await wavelink.Playable.search(target, source=source)
        except Exception as error:
            source_hint = f" via {source}" if source else ""
            print(f"Lavalink search failed for {target}{source_hint}: {error!r}")
            return []
        if not results:
            return []
        if isinstance(results, wavelink.Playlist):
            return list(results.tracks[:MAX_PLAYLIST_TRACKS])
        kind, _, _ = classify_input(query)
        return list(results[:MAX_PLAYLIST_TRACKS]) if kind == "playlist" else [results[0]]

    async def _play_next(self, session):
        player = session.player
        if player is None or not getattr(player, "connected", False):
            await self._teardown(session)
            return
        track = session.queue.advance()
        if track is None:
            await self.refresh_card(session)
            return
        try:
            await player.play(track, volume=session.volume)
        except Exception as error:
            print(f"Lavalink play failed in guild {session.guild_id}: {error!r}")
            await self._notify(session, f"Skipped **{_track_title(track)}** - Lavalink could not play it.")
            await self._play_next(session)
            return
        session.touch()
        await self._announce_track(session)

    async def _notify(self, session, text):
        channel = self.bot.get_channel(session.text_channel_id) if session.text_channel_id else None
        if channel is None:
            return
        try:
            await channel.send(text)
        except discord.HTTPException:
            pass

    def build_card(self, session):
        player = session.player
        current = session.queue.current
        queue_count = len(session.queue.upcoming)
        if current is None:
            embed = make_embed(
                MUSIC_LABEL,
                "Queue is idle. Use `/play` with a YouTube link or search to start.",
                color=Palette.DARK,
            )
            embed.add_field(name="Progress", value=progress_bar(0, 0, slots=14), inline=False)
            embed.add_field(
                name="Session",
                value=(
                    f"Volume `{session.volume}%` {_volume_meter(session.volume, slots=8)}\n"
                    f"Queue `{_queue_count_label(queue_count)}`\n"
                    f"Loop `{_loop_label(session.queue.loop)}`"
                ),
                inline=True,
            )
            embed.add_field(name="Next up", value="The queue is empty.", inline=False)
            _music_footer(embed, f"{MUSIC_LABEL} • Lavalink ready")
            return embed

        length = _track_length_seconds(current)
        position = int((getattr(player, "position", 0) or 0) / 1000)
        paused = bool(getattr(player, "paused", False))
        author = _track_author(current)
        source_label = _track_source_label(current)
        description = f"**{_track_link(current)}**"
        if author:
            description += f"\n{author}"

        embed = make_embed(
            _music_title("Paused") if paused else _music_title("Now playing"),
            description,
            color=_track_color(current),
        )
        artwork = _track_artwork(current)
        if artwork:
            embed.set_thumbnail(url=artwork)
        timing = f"`{format_duration(position)} / {format_duration(length, live_label='LIVE')}`"
        embed.add_field(name="Progress", value=f"{progress_bar(position, length, slots=14)} {timing}", inline=False)
        embed.add_field(
            name="Session",
            value=(
                f"Source `{source_label}`\n"
                f"Volume `{session.volume}%` {_volume_meter(session.volume, slots=8)}\n"
                f"Loop `{_loop_label(session.queue.loop)}`"
            ),
            inline=True,
        )
        embed.add_field(name="Queue", value=f"`{_queue_count_label(queue_count)}`", inline=True)
        upcoming = session.queue.upcoming[:5]
        if upcoming:
            lines = [f"`{index}.` {_track_title(track)}" for index, track in enumerate(upcoming, start=1)]
            remaining = queue_count - len(upcoming)
            if remaining > 0:
                lines.append(f"...and `{remaining}` more")
            next_up = "\n".join(lines)
        else:
            next_up = "Nothing queued after this."
        embed.add_field(name="Next up", value=next_up, inline=False)
        brand_footer(
            embed,
            f"{MUSIC_LABEL} • {source_label} • Volume {session.volume}% • {_loop_label(session.queue.loop)}",
        )
        return embed

    async def refresh_card(self, session, interaction=None):
        embed = self.build_card(session)
        if interaction is not None:
            try:
                await interaction.response.edit_message(embed=embed, view=LavalinkControls(self))
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
            await message.edit(embed=embed, view=LavalinkControls(self))
        except discord.HTTPException:
            pass

    async def _announce_track(self, session):
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
            message = await channel.send(embed=self.build_card(session), view=LavalinkControls(self))
            session.card_message_id = message.id
        except discord.HTTPException as error:
            print(f"Lavalink card could not be posted in guild {session.guild_id}: {error!r}")

    @tasks.loop(seconds=IDLE_CHECK_SECONDS)
    async def idle_watcher(self):
        try:
            for session in list(self.sessions.values()):
                player = session.player
                if player is None or not getattr(player, "connected", False):
                    await self._teardown(session)
                    continue
                channel = getattr(player, "channel", None)
                humans = [member for member in channel.members if not member.bot] if channel else []
                playing = bool(getattr(player, "playing", False) or getattr(player, "paused", False))
                if humans and playing:
                    session.touch()
                    continue
                if session.idle_seconds() >= IDLE_DISCONNECT_SECONDS:
                    await self._teardown(session)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Lavalink idle watcher sweep failed, will retry: {error!r}")

    @idle_watcher.before_loop
    async def before_idle_watcher(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload):
        player = getattr(payload, "player", None)
        guild = getattr(player, "guild", None)
        if guild is None:
            return
        session = self.sessions.get(str(guild.id))
        if session and session.player is player:
            await self._play_next(session)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload):
        player = getattr(payload, "player", None)
        guild = getattr(player, "guild", None)
        if guild is None:
            return
        session = self.sessions.get(str(guild.id))
        if session:
            details = _payload_error_text(payload).replace("\n", " ")[:240]
            if details:
                print(f"Lavalink track exception in guild {guild.id}: {details}")
            await self._notify(session, _track_failure_notice(payload))
            await self._play_next(session)

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload):
        await self.on_wavelink_track_exception(payload)

    @app_commands.command(name="play", description="Play a song through Lavalink")
    @app_commands.describe(query="A YouTube link, playlist, or words to search for")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str):
        await defer_interaction(interaction, thinking=True)
        session, error = await self._connect(interaction)
        if error is not None:
            return await respond(interaction, error, ephemeral=True)

        tracks = await self._load_tracks(query)
        if not tracks:
            embed = make_embed(_music_title("Nothing found"), _nothing_found_description(query), color=Palette.WARNING)
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        accepted = session.queue.add_many(tracks)
        if accepted == 0:
            embed = make_embed(_music_title("Queue is full"), "The music queue is full right now.", color=Palette.WARNING)
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        player = session.player
        was_idle = not bool(getattr(player, "playing", False) or getattr(player, "paused", False))
        if was_idle:
            await self._play_next(session)

        first = tracks[0]
        title = "Playing now" if was_idle and accepted == 1 else "Added to the queue"
        if accepted > 1:
            title = "Playlist added"
            description = f"Queued `{accepted}` tracks from Lavalink, starting with **{_track_link(first)}**."
        else:
            description = f"**{_track_link(first)}**"
        embed = make_embed(_music_title(title), description, color=_track_color(first))
        embed.add_field(name="Source", value=f"`{_track_source_label(first)} via Lavalink`", inline=True)
        embed.add_field(name="Length", value=f"`{format_duration(_track_length_seconds(first), live_label='LIVE')}`", inline=True)
        embed.add_field(
            name="Queue",
            value=f"`{_queue_count_label(len(session.queue.upcoming))}`",
            inline=True,
        )
        artwork = _track_artwork(first)
        if artwork:
            embed.set_thumbnail(url=artwork)
        _music_footer(embed)
        await respond(interaction, embed)

    @app_commands.command(name="skip", description="Skip the current track")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(str(interaction.guild_id))
        if session is None or session.player is None:
            embed = make_embed(_music_title("Nothing playing"), "There is nothing to skip.", color=Palette.WARNING)
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        if not self._can_control(interaction, session):
            embed = make_embed(
                _music_title("Join my voice channel"),
                "You have to be with me to control playback.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        current = session.queue.current
        await session.player.skip(force=True)
        embed = make_embed(
            _music_title("Skipped"),
            f"**{_track_link(current)}** was skipped." if current else "Moving on.",
            color=Palette.SUCCESS,
        )
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="queue", description="Show what is playing and what comes next")
    @app_commands.guild_only()
    async def queue_command(self, interaction: discord.Interaction):
        await defer_interaction(interaction)
        session = self.sessions.get(str(interaction.guild_id))
        if session is None or session.queue.current is None:
            embed = make_embed(_music_title("Nothing playing"), "Use `/play` to start.", color=Palette.WARNING)
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        await respond(interaction, self.build_card(session), view=LavalinkControls(self))

    @app_commands.command(name="nowplaying", description="Show the player card")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction):
        await self.queue_command.callback(self, interaction)

    @app_commands.command(name="volume", description="Set playback volume (0-100)")
    @app_commands.describe(level="Volume percentage")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(str(interaction.guild_id))
        if session is None or session.player is None:
            embed = make_embed(_music_title("Nothing playing"), "There is nothing to adjust.", color=Palette.WARNING)
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        if not self._can_control(interaction, session):
            embed = make_embed(
                _music_title("Join my voice channel"),
                "You have to be with me to control playback.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        session.volume = int(level)
        await session.player.set_volume(int(level))
        await self.refresh_card(session)
        embed = make_embed(
            _music_title("Volume set"),
            f"Playback volume is now `{int(level)}%` {_volume_meter(level, slots=8)}.",
            color=Palette.SUCCESS,
        )
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="remove", description="Remove a track from the queue")
    @app_commands.describe(position="Which queued track to remove")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, position: int):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(str(interaction.guild_id))
        if session is None:
            embed = make_embed(_music_title("Nothing playing"), "There is nothing to remove.", color=Palette.WARNING)
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        if not self._can_control(interaction, session):
            embed = make_embed(
                _music_title("Join my voice channel"),
                "You have to be with me to control playback.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        removed = session.queue.remove(position)
        if removed is None:
            embed = make_embed(_music_title("Not in the queue"), f"There is no track at position `{position}`.", color=Palette.WARNING)
        else:
            embed = make_embed(_music_title("Removed"), f"**{_track_link(removed)}** left the queue.", color=Palette.SUCCESS)
            await self.refresh_card(session)
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="clear", description="Clear the queue without stopping the current track")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(str(interaction.guild_id))
        if session is None:
            embed = make_embed(_music_title("Nothing playing"), "The queue is already empty.", color=Palette.WARNING)
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        if not self._can_control(interaction, session):
            embed = make_embed(
                _music_title("Join my voice channel"),
                "You have to be with me to control playback.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        removed = len(session.queue.upcoming)
        session.queue.clear()
        await self.refresh_card(session)
        embed = make_embed(_music_title("Queue cleared"), f"Removed `{removed}` queued track(s).", color=Palette.SUCCESS)
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="disconnect", description="Stop the music and leave the voice channel")
    @app_commands.guild_only()
    async def disconnect(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(str(interaction.guild_id))
        if session is None or session.player is None:
            embed = make_embed(_music_title("Nothing playing"), "I am not in a voice channel here.", color=Palette.WARNING)
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        if not self._can_control(interaction, session):
            embed = make_embed(
                _music_title("Join my voice channel"),
                "You have to be with me to control playback.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        await self._teardown(session)
        embed = make_embed(_music_title("Disconnected"), "Playback stopped and the queue was cleared.", color=Palette.SUCCESS)
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(LavalinkMusic(bot))
