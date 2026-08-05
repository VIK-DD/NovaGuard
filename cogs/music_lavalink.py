"""Music category backed by a Lavalink node."""

import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.lavalink_config import lavalink_password, lavalink_uri, lavalink_wavelink_search
from core.music_filters import FILTER_PRESETS, is_reset, preset_label, resolve_preset
from core.music_card import progress_bar
from core.music_sources import (
    classify_input,
    format_duration,
    parse_position,
    spotify_credentials_configured,
)
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
MAX_CONSECUTIVE_FAILURES = 5
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
SOURCE_ICONS = {
    "youtube": "📺",
    "youtubemusic": "🎬",
    "soundcloud": "🟠",
    "spotify": "🟢",
    "bandcamp": "🔵",
    "twitch": "🟣",
}
_STATE_ICONS = {"playing": "▶️", "paused": "⏸️", "idle": "💤"}


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


def _source_icon(track):
    return SOURCE_ICONS.get(_track_source_key(track), "🎧")


def _queue_runtime_label(tracks):
    """How long everything still queued would take to play."""
    total = sum(_track_length_seconds(track) for track in tracks)
    if total <= 0:
        return "0:00"
    return format_duration(total)


def _time_left_label(position, length):
    if length <= 0:
        return "live"
    remaining = max(0, length - position)
    return f"`-{format_duration(remaining)}` left"


def _volume_meter(volume, slots=10):
    clamped = min(100, max(0, int(volume or 0)))
    filled = round((clamped / 100) * slots)
    return "▰" * filled + "▱" * (slots - filled)


def _music_title(title):
    return f"{MUSIC_LABEL} • {title}"


def _music_footer(embed):
    """Brand only.

    Playback state lives in the card's own fields, so repeating it in the
    footer just made a long line nobody read.
    """
    brand_footer(embed)


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


def _end_reason(payload):
    """Normalise Lavalink's track-end reason to a lowercase string."""
    reason = getattr(payload, "reason", None)
    return str(getattr(reason, "value", reason) or "").strip().lower()


def _should_advance_on_end(reason):
    """Whether a track-end event should pull the next track.

    Lavalink reports a failed track twice: once as an exception and once as an
    end with reason ``loadFailed``. Advancing on both silently eats the track
    after it. ``replaced`` and ``cleanup`` are our own doing and must not
    advance either. An unknown reason still advances so a future Lavalink
    version cannot strand the player.
    """
    return reason not in {"loadfailed", "replaced", "cleanup"}


def _track_identity(track):
    for key in ("identifier", "uri", "title"):
        value = getattr(track, key, None)
        if value:
            return str(value)
    return ""


def _same_track(left, right):
    """True when two payload/queue tracks refer to the same song."""
    if left is None or right is None:
        return False
    if left is right:
        return True
    left_id, right_id = _track_identity(left), _track_identity(right)
    return bool(left_id and right_id and left_id == right_id)


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
        # Set once the cursor has walked off the end. Kept as a flag rather
        # than by parking the index past the last track: a track queued after
        # the queue ran dry would land exactly under such an index and be
        # skipped by the next advance, leaving the player silent until a
        # reconnect rebuilt the session.
        self._finished = False
        self.loop = "off"

    @property
    def current(self):
        if self._finished:
            return None
        if 0 <= self._index < len(self._tracks):
            return self._tracks[self._index]
        return None

    @property
    def upcoming(self):
        return self._tracks[self._index + 1 :]

    def add_many(self, tracks):
        accepted = 0
        for track in tracks:
            # The cap counts what is still waiting, not what already played,
            # so a long session cannot lock itself out of queueing anything.
            if len(self.upcoming) >= MAX_QUEUE_LENGTH:
                break
            self._tracks.append(track)
            accepted += 1
        return accepted

    def advance(self):
        if not self._tracks:
            self._index = -1
            self._finished = False
            return None
        if self.loop == "track" and self.current is not None:
            return self.current
        if self._index + 1 < len(self._tracks):
            self._index += 1
            self._finished = False
            return self.current
        if self.loop == "queue":
            self._index = 0
            self._finished = False
            return self.current
        # Park on the last track and mark the queue finished. Anything queued
        # from here lands in `upcoming`, so the next advance plays it.
        self._index = len(self._tracks) - 1
        self._finished = True
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
        self.filter_preset = "off"
        # Who queued each track, keyed by object identity so the same song
        # queued twice keeps a separate requester. Dropped with the session.
        self.requesters = {}
        # Track-end, track-exception and /play can all reach for the next
        # track at once. Serialising them keeps two advances from racing and
        # skipping a song.
        self.advance_lock = asyncio.Lock()
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
        embed = make_embed(
            _music_title("Stopped"),
            "Playback stopped and the queue was cleared.",
            color=Palette.DARK,
        )
        _music_footer(embed)
        await interaction.response.edit_message(content=None, embed=embed, view=None)

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
        self._node_task = None

    async def cog_load(self):
        self.bot.add_view(LavalinkControls(self))
        self.idle_watcher.start()
        # Wavelink needs the bot's own user id, which only exists after login,
        # so the first connect waits for ready instead of failing at import.
        self._node_task = self.bot.loop.create_task(self._connect_node_when_ready())

    async def _connect_node_when_ready(self):
        try:
            await self.bot.wait_until_ready()
            await self._ensure_node()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Lavalink startup connect failed: {error!r}")

    async def cog_unload(self):
        self.idle_watcher.cancel()
        if self._node_task is not None:
            self._node_task.cancel()
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

        node = None
        try:
            node = wavelink.Pool.get_node()
        except Exception:
            node = None

        if node is not None and _node_is_connected(node):
            self._node_error = None
            return True

        if node is None:
            # Only register a node the pool does not have yet; re-adding a
            # known node raises while Wavelink is already retrying it.
            try:
                node = wavelink.Node(uri=lavalink_uri(), password=lavalink_password(), retries=10)
                await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)
            except Exception as error:
                self._node_error = str(error) or repr(error)
                print(f"Lavalink node unavailable: {error!r}")
                return False

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
            "Check `pm2 logs lavalink` and make sure the password matches."
        )
        return False

    def _session(self, guild_id):
        key = str(guild_id)
        if key not in self.sessions:
            self.sessions[key] = LavalinkSession(key)
        return self.sessions[key]

    def _requester_mention(self, session, track):
        user_id = session.requesters.get(id(track))
        return f"<@{user_id}>" if user_id else ""

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
            # A player left over from a kick, a node restart or a manual
            # disconnect still hangs off the guild but can no longer play.
            # Drop it rather than handing it back a queue it will never start.
            if player is not None and (
                not isinstance(player, wavelink.Player) or not getattr(player, "connected", False)
            ):
                try:
                    await player.disconnect(force=True)
                except Exception:
                    pass
                player = None
            if player is None:
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
        """Start the next track. Returns True when playback actually began.

        Runs under the session lock so a track-end and a track-exception for
        the same song cannot advance the queue twice.
        """
        async with session.advance_lock:
            if self.sessions.get(str(session.guild_id)) is not session:
                return False

            player = session.player
            if player is None or not getattr(player, "connected", False):
                await self._teardown(session)
                return False

            for _ in range(MAX_CONSECUTIVE_FAILURES):
                track = session.queue.advance()
                if track is None:
                    await self.refresh_card(session)
                    return False
                try:
                    await player.play(track, volume=session.volume)
                except Exception as error:
                    print(f"Lavalink play failed in guild {session.guild_id}: {error!r}")
                    await self._notify(
                        session, f"Skipped **{_track_title(track)}** - Lavalink could not play it."
                    )
                    continue
                session.touch()
                await self._announce_track(session)
                return True

            await self._notify(session, "Too many tracks in a row failed. Stopping here.")
            return False

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
        upcoming = session.queue.upcoming
        queue_count = len(upcoming)

        if current is None:
            embed = make_embed(
                _music_title("Idle"),
                "Nothing is playing. Use `/play` with a link or a few words to start.",
                color=Palette.DARK,
            )
            embed.add_field(
                name="Player",
                value=(
                    f"{_STATE_ICONS['idle']} `standby`\n"
                    f"🔊 `{session.volume}%` {_volume_meter(session.volume, slots=8)}\n"
                    f"🔁 `{_loop_label(session.queue.loop)}`"
                ),
                inline=True,
            )
            embed.add_field(
                name="Queue",
                value=f"📋 `{_queue_count_label(queue_count)}`",
                inline=True,
            )
            _music_footer(embed)
            return embed

        length = _track_length_seconds(current)
        position = int((getattr(player, "position", 0) or 0) / 1000)
        paused = bool(getattr(player, "paused", False))
        state = "paused" if paused else "playing"

        # Anything after the heading goes on its own subtext line; appending
        # to the `###` line would swallow it into the heading.
        description = f"### {_track_link(current)}"
        meta = [part for part in (_track_author(current),) if part]
        requester = self._requester_mention(session, current)
        if requester:
            meta.append(f"requested by {requester}")
        if meta:
            description += "\n-# " + "  •  ".join(meta)

        embed = make_embed(
            _music_title("Paused") if paused else _music_title("Now playing"),
            description,
            color=_track_color(current),
        )
        artwork = _track_artwork(current)
        if artwork:
            embed.set_thumbnail(url=artwork)

        timing = f"`{format_duration(position)}` / `{format_duration(length, live_label='LIVE')}`"
        embed.add_field(
            name="​",
            value=f"{progress_bar(position, length, slots=16)}\n{timing}  •  {_time_left_label(position, length)}",
            inline=False,
        )
        embed.add_field(
            name="Player",
            value=(
                f"{_STATE_ICONS[state]} `{state}`\n"
                f"🔊 `{session.volume}%` {_volume_meter(session.volume, slots=8)}\n"
                f"🔁 `{_loop_label(session.queue.loop)}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Track",
            value=(
                f"{_source_icon(current)} `{_track_source_label(current)}`\n"
                f"📋 `{_queue_count_label(queue_count)}`\n"
                f"⏳ `{_queue_runtime_label(upcoming)}`"
                + (
                    f"\n{preset_label(session.filter_preset)}"
                    if not is_reset(getattr(session, "filter_preset", "off"))
                    else ""
                )
            ),
            inline=True,
        )

        if upcoming:
            lines = []
            for index, track in enumerate(upcoming[:5], start=1):
                title = _track_title(track)
                if len(title) > 42:
                    title = f"{title[:41]}…"
                lines.append(
                    f"`{index}.` {title} `{format_duration(_track_length_seconds(track), live_label='LIVE')}`"
                )
            remaining = queue_count - len(lines)
            if remaining > 0:
                lines.append(f"-# and `{remaining}` more")
            embed.add_field(name="Up next", value="\n".join(lines), inline=False)

        _music_footer(embed)
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
                    # Redraw so the progress bar advances on its own instead
                    # of freezing at whatever it read when the track started.
                    await self.refresh_card(session)
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

    def _session_for_payload(self, payload):
        """The session this event belongs to, or None when it is stale."""
        player = getattr(payload, "player", None)
        guild = getattr(player, "guild", None)
        if guild is None:
            return None
        session = self.sessions.get(str(guild.id))
        if session is None or session.player is not player:
            return None
        # An event for a song the queue has already moved past is a duplicate
        # (Lavalink reports a failure as both an exception and an end).
        track = getattr(payload, "track", None)
        current = session.queue.current
        if track is not None and current is not None and not _same_track(track, current):
            return None
        return session

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload):
        reason = _end_reason(payload)
        if not _should_advance_on_end(reason):
            return
        session = self._session_for_payload(payload)
        if session is not None:
            await self._play_next(session)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload):
        session = self._session_for_payload(payload)
        if session is None:
            return
        details = _payload_error_text(payload).replace("\n", " ")[:240]
        if details:
            print(f"Lavalink track exception in guild {session.guild_id}: {details}")
        await self._notify(session, _track_failure_notice(payload))
        await self._play_next(session)

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload):
        await self.on_wavelink_track_exception(payload)

    async def remove_autocomplete(self, interaction: discord.Interaction, current: str):
        """Offer the queued tracks by position; no Lavalink call is needed."""
        session = self.sessions.get(str(interaction.guild_id))
        if session is None:
            return []
        text = (current or "").lower()
        choices = []
        for position, track in enumerate(session.queue.upcoming[:25], start=1):
            label = f"{position}. {_track_title(track)}"[:100]
            if text and text not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label, value=position))
        return choices[:25]

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

        for track in tracks[:accepted]:
            session.requesters[id(track)] = interaction.user.id

        player = session.player
        was_idle = not bool(getattr(player, "playing", False) or getattr(player, "paused", False))
        if was_idle and not await self._play_next(session):
            # Saying "Playing now" while the channel stays silent is the
            # confusion this branch exists to prevent.
            embed = make_embed(
                _music_title("Could not start playback"),
                "The track was queued but Lavalink did not start it. "
                "Check `pm2 logs lavalink` - the node usually says why.",
                color=Palette.DANGER,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        first = tracks[0]
        queued_after = len(session.queue.upcoming)
        if accepted > 1:
            title = "Playlist added"
            description = f"### {_track_link(first)}\n-# and `{accepted - 1}` more tracks"
        else:
            title = "Playing now" if was_idle else "Added to the queue"
            description = f"### {_track_link(first)}"
            author = _track_author(first)
            if author:
                description += f"\n-# {author}"

        embed = make_embed(_music_title(title), description, color=_track_color(first))
        embed.add_field(
            name="Source",
            value=f"{_source_icon(first)} `{_track_source_label(first)}`",
            inline=True,
        )
        embed.add_field(
            name="Length",
            value=f"⏱️ `{format_duration(_track_length_seconds(first), live_label='LIVE')}`",
            inline=True,
        )
        embed.add_field(
            name="Queue",
            value=f"📋 `{_queue_count_label(queued_after)}`",
            inline=True,
        )
        if not was_idle and queued_after:
            # Time until the first newly queued track starts: what is left of
            # the current track, plus everything already waiting ahead of it.
            playing = session.queue.current
            position = int((getattr(player, "position", 0) or 0) / 1000)
            wait = max(0, _track_length_seconds(playing) - position) if playing else 0
            wait += sum(
                _track_length_seconds(track) for track in session.queue.upcoming[:-accepted]
            )
            embed.add_field(name="Starts in", value=f"⏳ `{format_duration(wait)}`", inline=False)
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

    async def _controlled_session(self, interaction, idle_detail):
        """Session the caller may drive, or None after sending the refusal."""
        session = self.sessions.get(str(interaction.guild_id))
        if session is None or session.player is None:
            embed = make_embed(_music_title("Nothing playing"), idle_detail, color=Palette.WARNING)
            _music_footer(embed)
            await respond(interaction, embed, ephemeral=True)
            return None
        if not self._can_control(interaction, session):
            embed = make_embed(
                _music_title("Join my voice channel"),
                "You have to be with me to control playback.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            await respond(interaction, embed, ephemeral=True)
            return None
        return session

    @app_commands.command(name="shuffle", description="Shuffle the queued tracks")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = await self._controlled_session(interaction, "There is nothing to shuffle.")
        if session is None:
            return

        queued = len(session.queue.upcoming)
        if queued < 2:
            embed = make_embed(
                _music_title("Nothing to shuffle"),
                "Queue at least two tracks first.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        session.queue.shuffle()
        session.touch()
        await self.refresh_card(session)
        embed = make_embed(
            _music_title("Shuffled"),
            f"🔀 Reordered `{queued}` queued track(s). The current track keeps playing.",
            color=Palette.SUCCESS,
        )
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="loop", description="Set the repeat mode")
    @app_commands.describe(mode="What to repeat")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="🚫 Off", value="off"),
            app_commands.Choice(name="🔂 This track", value="track"),
            app_commands.Choice(name="🔁 Whole queue", value="queue"),
        ]
    )
    @app_commands.guild_only()
    async def loop(self, interaction: discord.Interaction, mode: str):
        await defer_interaction(interaction, ephemeral=True)
        session = await self._controlled_session(interaction, "There is nothing to loop.")
        if session is None:
            return

        session.queue.loop = mode
        session.touch()
        await self.refresh_card(session)
        embed = make_embed(
            _music_title("Repeat set"),
            f"🔁 Now `{_loop_label(mode)}`.",
            color=Palette.SUCCESS if mode != "off" else Palette.DARK,
        )
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="seek", description="Jump to a position in the current track")
    @app_commands.describe(position="Where to jump, like 1:30, 90 or 1:02:03")
    @app_commands.guild_only()
    async def seek(self, interaction: discord.Interaction, position: str):
        await defer_interaction(interaction, ephemeral=True)
        session = await self._controlled_session(interaction, "There is nothing to seek.")
        if session is None:
            return

        seconds = parse_position(position)
        if seconds is None:
            embed = make_embed(
                _music_title("Position not understood"),
                f"`{position[:40]}` is not a position. Try `1:30`, `90` or `1:02:03`.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        current = session.queue.current
        length = _track_length_seconds(current)
        if current is None:
            embed = make_embed(
                _music_title("Nothing playing"), "There is nothing to seek.", color=Palette.WARNING
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        if length and seconds >= length:
            embed = make_embed(
                _music_title("Past the end"),
                f"This track is only `{format_duration(length)}` long. Use `/skip` to move on.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        try:
            await session.player.seek(seconds * 1000)
        except Exception as error:
            print(f"Lavalink seek failed in guild {session.guild_id}: {error!r}")
            embed = make_embed(
                _music_title("Seek failed"),
                f"Lavalink refused the jump: `{error}`. Live streams cannot be seeked.",
                color=Palette.DANGER,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        session.touch()
        await self.refresh_card(session)
        embed = make_embed(
            _music_title("Jumped"),
            f"⏩ Now at `{format_duration(seconds)}` of `{format_duration(length, live_label='LIVE')}`.",
            color=Palette.SUCCESS,
        )
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="soundcheck", description="Check the music path end to end")
    @app_commands.guild_only()
    async def soundcheck(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)

        node_ok = await self._ensure_node()
        session = self.sessions.get(str(interaction.guild_id))
        player = session.player if session else None
        connected = bool(player and getattr(player, "connected", False))
        current = session.queue.current if session else None

        lines = [
            f"{'✅' if node_ok else '❌'} **Lavalink node** — "
            + (f"connected at `{lavalink_uri()}`" if node_ok else f"`{self._node_error}`"),
            f"{'✅' if connected else '💤'} **Voice** — "
            + (
                f"connected to `{getattr(getattr(player, 'channel', None), 'name', 'unknown')}`"
                if connected
                else "not in a voice channel here"
            ),
        ]
        if current is not None:
            lines.append(
                f"▶️ **Playing** — {_track_link(current)} via `{_track_source_label(current)}`"
            )
        elif connected:
            lines.append("💤 **Playing** — nothing right now")

        if node_ok and connected and current is not None:
            verdict = "Everything is working. If you still hear nothing, check your own Discord volume and whether you muted the bot locally."
            color = Palette.SUCCESS
        elif node_ok:
            verdict = "The node is healthy. Join a voice channel and run `/play` to test the rest."
            color = Palette.INFO
        else:
            verdict = "The node is the problem, not Discord. Check `pm2 logs lavalink`."
            color = Palette.DANGER

        embed = make_embed(_music_title("Soundcheck"), "\n".join(lines), color=color)
        embed.add_field(name="Verdict", value=verdict, inline=False)
        embed.add_field(
            name="Note",
            value=(
                "-# Lavalink streams from the node, so there is no local test tone on this "
                "backend. This checks the whole path instead: node, voice, and source."
            ),
            inline=False,
        )
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="filter", description="Apply an audio effect to playback")
    @app_commands.describe(preset="Which effect to apply, or Off to clear")
    @app_commands.choices(
        preset=[
            app_commands.Choice(name=f"{spec['emoji']} {spec['label']}", value=key)
            for key, spec in FILTER_PRESETS.items()
        ]
    )
    @app_commands.guild_only()
    async def filter_command(self, interaction: discord.Interaction, preset: str):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(str(interaction.guild_id))
        if session is None or session.player is None:
            embed = make_embed(
                _music_title("Nothing playing"), "There is nothing to filter.", color=Palette.WARNING
            )
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

        spec = resolve_preset(preset)
        if spec is None:
            embed = make_embed(
                _music_title("Unknown effect"),
                f"There is no `{preset[:40]}` effect. Pick one from the list.",
                color=Palette.WARNING,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        try:
            await self._apply_filters(session, preset)
        except Exception as error:
            print(f"Lavalink filter {preset!r} failed in guild {session.guild_id}: {error!r}")
            embed = make_embed(
                _music_title("Effect failed"),
                f"Lavalink refused the effect: `{error}`. Check that it is enabled under "
                "`lavalink.server.filters` in `application.yml`.",
                color=Palette.DANGER,
            )
            _music_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        session.filter_preset = "off" if is_reset(preset) else preset
        session.touch()
        await self.refresh_card(session)

        if is_reset(preset):
            description = "Effects cleared. Playing the track as recorded."
        else:
            description = f"### {preset_label(preset)}\n-# {spec['description']}"
        embed = make_embed(
            _music_title("Effect applied"),
            description,
            color=Palette.SUCCESS if not is_reset(preset) else Palette.DARK,
        )
        if not is_reset(preset):
            embed.add_field(
                name="Heads up",
                value=(
                    "-# Effects take a moment to settle and make Lavalink re-encode audio, "
                    "so they cost a little CPU."
                ),
                inline=False,
            )
        _music_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    async def _apply_filters(self, session, preset):
        """Translate a preset into Wavelink's filter objects and send it."""
        player = session.player
        filters = player.filters
        # Always start from a clean slate: presets are a choice of one effect,
        # not a stack, so switching must not leave the previous one underneath.
        filters.reset()

        spec = resolve_preset(preset) or {}
        wanted = spec.get("filters") or {}

        if "equalizer" in wanted:
            filters.equalizer.set(bands=wanted["equalizer"])
        if "timescale" in wanted:
            filters.timescale.set(**wanted["timescale"])
        if "rotation" in wanted:
            filters.rotation.set(**wanted["rotation"])
        if "karaoke" in wanted:
            filters.karaoke.set(**wanted["karaoke"])

        await player.set_filters(filters)

    @app_commands.command(name="remove", description="Remove a track from the queue")
    @app_commands.describe(position="Which queued track to remove")
    @app_commands.autocomplete(position=remove_autocomplete)
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
