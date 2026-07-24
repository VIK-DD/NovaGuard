"""Voice session reports with per-member time accumulation."""

from __future__ import annotations

import asyncio
import copy
import io
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from core.storage import get_guild_settings, load_data, save_data, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond


VOICE_REPORT_CHANNEL_KEY = "voice_report_channel"
MIN_SESSION_SECONDS = 60 * 60
MAX_ACTIVITY_FIELDS = 3
MAX_FIELD_LENGTH = 1000


def now_utc():
    return datetime.now(UTC)


def as_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def human_duration(total_seconds: float | int) -> str:
    seconds = max(0, int(round(total_seconds)))
    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def active_member_ids(session: dict) -> list[str]:
    return [member_id for member_id, record in session.get("members", {}).items() if record.get("joined_at")]


def new_session(channel_id: int, channel_name: str, started_at: datetime) -> dict:
    return {
        "channel_id": str(channel_id),
        "channel_name": channel_name,
        "started_at": as_iso(started_at),
        "updated_at": as_iso(started_at),
        "peak_members": 0,
        "members": {},
    }


def record_member_join(session: dict, member_id: int, display_name: str, joined_at: datetime) -> bool:
    member_key = str(member_id)
    members = session.setdefault("members", {})
    record = members.setdefault(
        member_key,
        {"display_name": display_name, "joined_at": None, "total_seconds": 0, "joins": 0},
    )
    record["display_name"] = display_name
    if record.get("joined_at"):
        return False
    record["joined_at"] = as_iso(joined_at)
    record["joins"] = int(record.get("joins", 0)) + 1
    session["updated_at"] = as_iso(joined_at)
    session["peak_members"] = max(int(session.get("peak_members", 0)), len(active_member_ids(session)))
    return True


def record_member_leave(session: dict, member_id: int, left_at: datetime) -> float:
    record = session.get("members", {}).get(str(member_id))
    if not record:
        return 0
    joined_at = parse_time(record.get("joined_at"))
    if joined_at is None:
        return 0
    elapsed = max(0, (left_at - joined_at).total_seconds())
    record["total_seconds"] = float(record.get("total_seconds", 0)) + elapsed
    record["joined_at"] = None
    session["updated_at"] = as_iso(left_at)
    return elapsed


def session_duration(session: dict, ended_at: datetime) -> float:
    started_at = parse_time(session.get("started_at"))
    if started_at is None:
        return 0
    return max(0, (ended_at - started_at).total_seconds())


def participant_lines(session: dict) -> list[str]:
    rows = []
    for member_id, record in session.get("members", {}).items():
        duration = human_duration(record.get("total_seconds", 0))
        joins = int(record.get("joins", 0))
        join_note = "entry" if joins == 1 else f"{joins} entries"
        rows.append(
            (
                float(record.get("total_seconds", 0)),
                f"<@{member_id}> - `{duration}` ({join_note})",
                f"{record.get('display_name', 'Unknown')} ({member_id}) - {duration} ({join_note})",
            )
        )
    rows.sort(key=lambda row: (-row[0], row[1].lower()))
    return [row[1] for row in rows]


def full_participant_lines(session: dict) -> list[str]:
    rows = []
    for member_id, record in session.get("members", {}).items():
        duration = human_duration(record.get("total_seconds", 0))
        joins = int(record.get("joins", 0))
        join_note = "entry" if joins == 1 else f"{joins} entries"
        rows.append((float(record.get("total_seconds", 0)), f"{record.get('display_name', 'Unknown')} ({member_id}) - {duration} ({join_note})"))
    return [line for _, line in sorted(rows, key=lambda row: (-row[0], row[1].lower()))]


def split_lines(lines: list[str], limit: int = MAX_FIELD_LENGTH) -> list[str]:
    chunks = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if current and len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or ["No member activity was recorded."]


def build_report_embed(session: dict, channel: discord.abc.GuildChannel, ended_at: datetime):
    started_at = parse_time(session.get("started_at")) or ended_at
    duration = session_duration(session, ended_at)
    lines = participant_lines(session)
    chunks = split_lines(lines)
    shown_chunks = chunks[:MAX_ACTIVITY_FIELDS]
    overflow = len(chunks) > MAX_ACTIVITY_FIELDS

    embed = make_embed(
        "Voice session complete",
        f"{channel.mention} - the room is now empty.",
        color=Palette.TEAL,
        timestamp=False,
    )
    embed.timestamp = ended_at
    embed.add_field(
        name="Session window",
        value=(
            f"Started: {discord.utils.format_dt(started_at, 'F')}\n"
            f"Ended: {discord.utils.format_dt(ended_at, 'F')}"
        ),
        inline=False,
    )
    embed.add_field(name="Session duration", value=f"`{human_duration(duration)}`", inline=True)
    embed.add_field(name="Unique participants", value=f"`{len(session.get('members', {}))}`", inline=True)
    embed.add_field(name="Peak concurrent", value=f"`{session.get('peak_members', 0)}`", inline=True)
    for index, chunk in enumerate(shown_chunks, 1):
        name = "Member activity" if index == 1 else "Member activity (continued)"
        embed.add_field(name=name, value=chunk, inline=False)

    if overflow:
        embed.add_field(
            name="Full attendance",
            value="The complete participant list is attached because it does not fit safely in one embed.",
            inline=False,
        )
    brand_footer(embed, "Voice session report")
    return embed, overflow


class VoiceReports(commands.Cog):
    """Track complete voice sessions and report them after the room empties."""

    EMOJI = "🎙️"
    COLOR = Palette.TEAL
    DESCRIPTION = "Voice session reports with joined, left and accumulated time."

    voice = app_commands.Group(
        name="voice",
        description="Configure voice session reports",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot
        self.sessions: dict[str, dict[str, dict]] = {}
        self._persist_lock = asyncio.Lock()
        self._restore_task: asyncio.Task | None = None

    async def cog_load(self):
        raw_sessions = await asyncio.to_thread(load_data, "voice_sessions", {})
        self.sessions = raw_sessions if isinstance(raw_sessions, dict) else {}
        self._restore_task = asyncio.create_task(self._restore_sessions_after_ready())

    async def cog_unload(self):
        if self._restore_task and not self._restore_task.done():
            self._restore_task.cancel()

    async def _persist(self):
        async with self._persist_lock:
            snapshot = copy.deepcopy(self.sessions)
            await asyncio.to_thread(save_data, "voice_sessions", snapshot)

    @staticmethod
    def _voice_channel(channel):
        if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return channel
        return None

    def _guild_sessions(self, guild_id: int) -> dict[str, dict]:
        return self.sessions.setdefault(str(guild_id), {})

    async def _report_channel(self, guild: discord.Guild):
        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        channel_id = settings.get(VOICE_REPORT_CHANNEL_KEY)
        if not channel_id:
            return None
        try:
            channel = guild.get_channel(int(channel_id))
        except (TypeError, ValueError):
            return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _tracking_enabled(self, guild: discord.Guild) -> bool:
        return await self._report_channel(guild) is not None

    async def _begin_channel_session(self, channel, members, started_at: datetime):
        human_members = [member for member in members if not member.bot]
        if not human_members:
            return None
        guild_sessions = self._guild_sessions(channel.guild.id)
        session = guild_sessions.get(str(channel.id))
        if session is None:
            session = new_session(channel.id, channel.name, started_at)
            guild_sessions[str(channel.id)] = session
        session["channel_name"] = channel.name
        for member in human_members:
            record_member_join(session, member.id, member.display_name, started_at)
        return session

    async def _handle_join(self, member: discord.Member, channel):
        guild_sessions = self._guild_sessions(member.guild.id)
        session = guild_sessions.get(str(channel.id))
        if session is None:
            if not await self._tracking_enabled(member.guild):
                return
            session = await self._begin_channel_session(channel, [member], now_utc())
        else:
            record_member_join(session, member.id, member.display_name, now_utc())
        await self._persist()

    async def _handle_leave(self, member: discord.Member, channel):
        guild_sessions = self._guild_sessions(member.guild.id)
        session = guild_sessions.get(str(channel.id))
        if session is None:
            return

        ended_at = now_utc()
        record_member_leave(session, member.id, ended_at)
        if active_member_ids(session):
            await self._persist()
            return

        guild_sessions.pop(str(channel.id), None)
        if not guild_sessions:
            self.sessions.pop(str(member.guild.id), None)
        await self._persist()

        if session_duration(session, ended_at) < MIN_SESSION_SECONDS:
            return
        await self._send_report(member.guild, channel, session, ended_at)

    async def _send_report(self, guild: discord.Guild, voice_channel, session: dict, ended_at: datetime):
        report_channel = await self._report_channel(guild)
        if report_channel is None:
            return

        embed, needs_attachment = build_report_embed(session, voice_channel, ended_at)
        file = None
        if needs_attachment:
            started_at = parse_time(session.get("started_at")) or ended_at
            full_text = "\n".join(
                [
                    f"Voice session: {voice_channel.name}",
                    f"Started: {started_at.isoformat()}",
                    f"Ended: {ended_at.isoformat()}",
                    f"Duration: {human_duration(session_duration(session, ended_at))}",
                    f"Unique participants: {len(session.get('members', {}))}",
                    f"Peak concurrent: {session.get('peak_members', 0)}",
                    "",
                    "Participant activity:",
                    *full_participant_lines(session),
                ]
            )
            file = discord.File(
                io.BytesIO(full_text.encode("utf-8")),
                filename=f"voice-session-{voice_channel.id}-{ended_at:%Y%m%d-%H%M}.txt",
            )
        try:
            await asyncio.wait_for(report_channel.send(embed=embed, file=file), timeout=8)
        except (discord.HTTPException, asyncio.TimeoutError) as error:
            print(f"Voice session report skipped for #{voice_channel.id}: {error!r}")

    async def _restore_sessions_after_ready(self):
        await self.bot.wait_until_ready()
        restored_at = now_utc()
        changed = False

        for guild in self.bot.guilds:
            guild_sessions = self.sessions.get(str(guild.id), {})
            channels = [*guild.voice_channels, *guild.stage_channels]
            for channel in channels:
                session = guild_sessions.get(str(channel.id))
                connected = [member for member in channel.members if not member.bot]
                if session is None:
                    if connected and await self._tracking_enabled(guild):
                        await self._begin_channel_session(channel, connected, restored_at)
                        changed = True
                    continue

                session["channel_name"] = channel.name
                connected_ids = {str(member.id) for member in connected}
                for member_id in active_member_ids(session):
                    if member_id not in connected_ids:
                        record_member_leave(session, int(member_id), restored_at)
                        changed = True
                for member in connected:
                    if str(member.id) not in active_member_ids(session):
                        record_member_join(session, member.id, member.display_name, restored_at)
                        changed = True
                if not active_member_ids(session):
                    guild_sessions.pop(str(channel.id), None)
                    changed = True

            known_channel_ids = {str(channel.id) for channel in channels}
            for channel_id in list(guild_sessions):
                if channel_id not in known_channel_ids:
                    guild_sessions.pop(channel_id, None)
                    changed = True
            if not guild_sessions:
                self.sessions.pop(str(guild.id), None)

        if changed:
            await self._persist()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or before.channel == after.channel:
            return
        previous_channel = self._voice_channel(before.channel)
        next_channel = self._voice_channel(after.channel)
        if previous_channel is not None:
            await self._handle_leave(member, previous_channel)
        if next_channel is not None:
            await self._handle_join(member, next_channel)

    @voice.command(name="set", description="Choose the channel for completed voice session reports")
    @app_commands.describe(channel="Text channel that receives voice session reports")
    async def voice_set(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await asyncio.to_thread(update_guild_settings, interaction.guild_id, **{VOICE_REPORT_CHANNEL_KEY: channel.id})
        seeded = 0
        started_at = now_utc()
        for voice_channel in [*interaction.guild.voice_channels, *interaction.guild.stage_channels]:
            if any(not member.bot for member in voice_channel.members):
                await self._begin_channel_session(voice_channel, voice_channel.members, started_at)
                seeded += 1
        await self._persist()

        description = f"Completed voice sessions will be posted in {channel.mention}."
        if seeded:
            description += f" Tracking started now for `{seeded}` active voice channel(s)."
        description += " Reports are sent only after a session reaches `1h`."
        embed = make_embed("Voice reports enabled", description, color=Palette.TEAL)
        brand_footer(embed, "Voice session reports")
        await respond(interaction, embed, ephemeral=True)

    @voice.command(name="off", description="Disable voice session reports for this server")
    async def voice_off(self, interaction: discord.Interaction):
        await asyncio.to_thread(update_guild_settings, interaction.guild_id, **{VOICE_REPORT_CHANNEL_KEY: None})
        self.sessions.pop(str(interaction.guild_id), None)
        await self._persist()
        embed = make_embed(
            "Voice reports disabled",
            "Active voice tracking for this server was cleared. No report will be sent until you enable it again.",
            color=Palette.WARNING,
        )
        brand_footer(embed, "Voice session reports")
        await respond(interaction, embed, ephemeral=True)

    @voice.command(name="status", description="View the voice session reporting configuration")
    async def voice_status(self, interaction: discord.Interaction):
        report_channel = await self._report_channel(interaction.guild)
        active_sessions = self.sessions.get(str(interaction.guild_id), {})
        if report_channel is None:
            description = "No report channel is configured. Use `/voice set` to enable tracking."
            color = Palette.WARNING
        else:
            description = (
                f"Reports: {report_channel.mention}\n"
                f"Minimum session: `1h`\n"
                f"Active tracked rooms: `{len(active_sessions)}`"
            )
            color = Palette.TEAL
        embed = make_embed("Voice report status", description, color=color)
        brand_footer(embed, "Voice session reports")
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(VoiceReports(bot))
