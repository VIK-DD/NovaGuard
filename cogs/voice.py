"""Voice session reports with per-member time accumulation."""

from __future__ import annotations

import asyncio
import copy
import io
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from core.storage import get_guild_settings, load_data, save_data, update_guild_settings
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import defer_interaction, respond


VOICE_REPORT_CHANNEL_KEY = "voice_report_channel"
MIN_SESSION_SECONDS = 60 * 60
MAX_ACTIVITY_FIELDS = 3
MAX_FIELD_LENGTH = 1000
ACTIVITY_BAR_SLOTS = 12
VOICE_PENDING_REPORTS_STORE = "voice_pending_reports"
VOICE_REPORT_HISTORY_STORE = "voice_report_history"
REPORT_RETRY_SECONDS = 90
REPORT_SEND_TIMEOUT_SECONDS = 15
REPORT_HISTORY_LIMIT = 10
REPORT_SEND_SPACING_SECONDS = 3
REPORT_SEND_QUEUE_MAXSIZE = 50


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


class StoredVoiceChannel:
    def __init__(self, guild: discord.Guild, channel_id: int | str, channel_name: str):
        self.guild = guild
        self.id = int(channel_id)
        self.name = channel_name or f"Voice #{channel_id}"
        self.mention = f"<#{self.id}>"


def record_member_join(session: dict, member_id: int, display_name: str, joined_at: datetime) -> bool:
    member_key = str(member_id)
    members = session.setdefault("members", {})
    record = members.setdefault(
        member_key,
        {
            "display_name": display_name,
            "joined_at": None,
            "first_joined_at": None,
            "last_left_at": None,
            "longest_streak": 0,
            "total_seconds": 0,
            "joins": 0,
        },
    )
    record["display_name"] = display_name
    if record.get("joined_at"):
        return False
    record["joined_at"] = as_iso(joined_at)
    if not record.get("first_joined_at"):
        record["first_joined_at"] = as_iso(joined_at)
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
    record["longest_streak"] = max(float(record.get("longest_streak", 0)), elapsed)
    record["last_left_at"] = as_iso(left_at)
    record["joined_at"] = None
    session["updated_at"] = as_iso(left_at)
    return elapsed


def session_duration(session: dict, ended_at: datetime) -> float:
    started_at = parse_time(session.get("started_at"))
    if started_at is None:
        return 0
    return max(0, (ended_at - started_at).total_seconds())


def participant_seconds(session: dict) -> float:
    """Return the combined time spent by everyone in the completed session."""
    return sum(float(record.get("total_seconds", 0)) for record in session.get("members", {}).values())


def session_activity(session: dict, ended_at: datetime) -> tuple[int, float]:
    """Measure how consistently the room was occupied, relative to its peak."""
    duration = session_duration(session, ended_at)
    peak_members = max(int(session.get("peak_members", 0)), 1)
    if duration <= 0:
        return 0, 0
    average_concurrent = participant_seconds(session) / duration
    percent = min(round(average_concurrent / peak_members * 100), 100)
    return percent, average_concurrent


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


def member_activity_rows(session: dict) -> list[dict]:
    rows = []
    for member_id, record in session.get("members", {}).items():
        total = float(record.get("total_seconds", 0))
        longest = float(record.get("longest_streak") or total)
        first_joined = parse_time(record.get("first_joined_at"))
        last_left = parse_time(record.get("last_left_at"))
        rows.append(
            {
                "member_id": member_id,
                "display_name": record.get("display_name", "Unknown"),
                "total_seconds": total,
                "joins": int(record.get("joins", 0)),
                "longest_streak": longest,
                "first_joined_at": first_joined,
                "last_left_at": last_left,
            }
        )
    rows.sort(key=lambda row: (-row["total_seconds"], str(row["display_name"]).lower()))
    return rows


def session_highlights(session: dict) -> str:
    rows = member_activity_rows(session)
    if not rows:
        return "No member activity was recorded."

    most_active = rows[0]
    longest = max(rows, key=lambda row: (row["longest_streak"], row["total_seconds"]))
    first = min(
        (row for row in rows if row["first_joined_at"]),
        key=lambda row: row["first_joined_at"],
        default=None,
    )
    last = max(
        (row for row in rows if row["last_left_at"]),
        key=lambda row: row["last_left_at"],
        default=None,
    )

    lines = [
        f"Most active: <@{most_active['member_id']}> - `{human_duration(most_active['total_seconds'])}`",
        f"Longest stay: <@{longest['member_id']}> - `{human_duration(longest['longest_streak'])}` continuous",
    ]
    if first:
        lines.append(f"First joined: <@{first['member_id']}> - {discord.utils.format_dt(first['first_joined_at'], 't')}")
    if last:
        lines.append(f"Last left: <@{last['member_id']}> - {discord.utils.format_dt(last['last_left_at'], 't')}")
    return "\n".join(lines)


def full_participant_lines(session: dict) -> list[str]:
    rows = []
    for row in member_activity_rows(session):
        duration = human_duration(row["total_seconds"])
        joins = row["joins"]
        join_note = "entry" if joins == 1 else f"{joins} entries"
        longest = human_duration(row["longest_streak"])
        rows.append(
            (
                row["total_seconds"],
                f"{row['display_name']} ({row['member_id']}) - {duration} ({join_note}, longest {longest})",
            )
        )
    return [line for _, line in sorted(rows, key=lambda item: (-item[0], item[1].lower()))]


def csv_escape(value) -> str:
    text = "" if value is None else str(value)
    return f'"{text.replace(chr(34), chr(34) * 2)}"'


def report_export_text(report: dict, *, csv: bool = False) -> str:
    session = report.get("session", {})
    ended_at = parse_time(report.get("ended_at")) or now_utc()
    started_at = parse_time(session.get("started_at")) or ended_at
    rows = []
    for row in member_activity_rows(session):
        rows.append(
            (
                row["total_seconds"],
                row["member_id"],
                row["display_name"],
                row["joins"],
                row["longest_streak"],
                row["first_joined_at"],
                row["last_left_at"],
            )
        )
    rows.sort(key=lambda row: (-row[0], str(row[2]).lower()))

    if csv:
        lines = ["member_id,display_name,total_seconds,duration,entries,longest_streak,first_joined_at,last_left_at"]
        for total, member_id, display_name, joins, longest, first_joined, last_left in rows:
            lines.append(
                ",".join(
                    [
                        csv_escape(member_id),
                        csv_escape(display_name),
                        str(round(total, 3)),
                        csv_escape(human_duration(total)),
                        str(joins),
                        csv_escape(human_duration(longest)),
                        csv_escape(first_joined.isoformat() if first_joined else ""),
                        csv_escape(last_left.isoformat() if last_left else ""),
                    ]
                )
            )
        return "\n".join(lines)

    return "\n".join(
        [
            f"Voice session: {report.get('channel_name', 'Unknown channel')}",
            f"Channel ID: {report.get('channel_id', 'unknown')}",
            f"Started: {started_at.isoformat()}",
            f"Ended: {ended_at.isoformat()}",
            f"Duration: {human_duration(session_duration(session, ended_at))}",
            f"Unique participants: {len(session.get('members', {}))}",
            f"Peak concurrent: {session.get('peak_members', 0)}",
            "",
            "Participant activity:",
            *[
                (
                    f"{display_name} ({member_id}) - {human_duration(total)} "
                    f"({joins} {'entry' if joins == 1 else 'entries'}, longest {human_duration(longest)})"
                )
                for total, member_id, display_name, joins, longest, _, _ in rows
            ],
        ]
    )


def report_to_file(report: dict, *, csv: bool = False) -> discord.File:
    ended_at = parse_time(report.get("ended_at")) or now_utc()
    suffix = "csv" if csv else "txt"
    payload = report_export_text(report, csv=csv).encode("utf-8")
    return discord.File(
        io.BytesIO(payload),
        filename=f"voice-session-{report.get('channel_id', 'unknown')}-{ended_at:%Y%m%d-%H%M}.{suffix}",
    )


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


def pending_report_lines(reports: dict[str, dict]) -> list[str]:
    rows = []
    for report_id, report in reports.items():
        ended_at = parse_time(report.get("ended_at"))
        ended = discord.utils.format_dt(ended_at, "R") if ended_at else "unknown end"
        attempts = int(report.get("attempts", 0))
        error = str(report.get("last_error") or "none")
        if len(error) > 120:
            error = f"{error[:117]}..."
        rows.append(
            (
                ended_at or datetime.min.replace(tzinfo=UTC),
                (
                    f"`{report_id}`\n"
                    f"{report.get('channel_name', 'Unknown channel')} (`{report.get('channel_id', 'unknown')}`) • "
                    f"ended {ended} • attempts `{attempts}`\n"
                    f"last error: `{error}`"
                ),
            )
        )
    rows.sort(key=lambda row: row[0], reverse=True)
    return [line for _, line in rows]


def build_report_embed(session: dict, channel: discord.abc.GuildChannel, ended_at: datetime):
    started_at = parse_time(session.get("started_at")) or ended_at
    duration = session_duration(session, ended_at)
    combined_time = participant_seconds(session)
    activity_percent, average_concurrent = session_activity(session, ended_at)
    lines = participant_lines(session)
    chunks = split_lines(lines)
    shown_chunks = chunks[:MAX_ACTIVITY_FIELDS]
    overflow = len(chunks) > MAX_ACTIVITY_FIELDS
    guild = getattr(channel, "guild", None)
    guild_icon = getattr(getattr(guild, "icon", None), "url", None)
    guild_banner = getattr(getattr(guild, "banner", None), "url", None)

    embed = make_embed(
        "Voice session complete",
        f"{channel.mention} is now empty. Here is the session recap.",
        color=Palette.TEAL,
        timestamp=False,
    )
    embed.timestamp = ended_at
    if guild:
        embed.set_author(
            name=f"{guild.name} • Voice activity",
            icon_url=guild_icon,
        )
    if guild_icon:
        embed.set_thumbnail(url=guild_icon)
    if guild_banner:
        embed.set_image(url=guild_banner)
    embed.add_field(
        name="Session window",
        value=(
            f"Started {discord.utils.format_dt(started_at, 'F')}\n"
            f"Ended {discord.utils.format_dt(ended_at, 'F')}"
        ),
        inline=False,
    )
    embed.add_field(name="Duration", value=f"`{human_duration(duration)}`", inline=True)
    embed.add_field(name="People", value=f"`{len(session.get('members', {}))}` unique", inline=True)
    embed.add_field(name="Peak", value=f"`{session.get('peak_members', 0)}` in voice", inline=True)
    embed.add_field(
        name="Room activity",
        value=(
            f"{progress_bar(activity_percent, 100, slots=ACTIVITY_BAR_SLOTS)} `{activity_percent}%`\n"
            f"`{human_duration(combined_time)}` combined time • "
            f"`{average_concurrent:.1f}` average people in voice"
        ),
        inline=False,
    )
    embed.add_field(name="Highlights", value=session_highlights(session), inline=False)
    for index, chunk in enumerate(shown_chunks, 1):
        name = "Member activity" if index == 1 else "Member activity (continued)"
        embed.add_field(name=name, value=chunk, inline=False)

    if overflow:
        embed.add_field(
            name="Full attendance",
            value="The complete participant list is attached because it does not fit safely in one embed.",
            inline=False,
        )
    brand_footer(embed, "Voice session report • activity is based on time spent in the room")
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
        self.pending_reports: dict[str, dict[str, dict]] = {}
        self.report_history: dict[str, list[dict]] = {}
        self._send_queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue(maxsize=REPORT_SEND_QUEUE_MAXSIZE)
        self._sending_reports: set[str] = set()
        self._sending_lock = asyncio.Lock()
        self._persist_lock = asyncio.Lock()
        self._pending_lock = asyncio.Lock()
        self._history_lock = asyncio.Lock()
        self._restore_task: asyncio.Task | None = None
        self._retry_task: asyncio.Task | None = None
        self._send_task: asyncio.Task | None = None

    async def cog_load(self):
        raw_sessions = await asyncio.to_thread(load_data, "voice_sessions", {})
        self.sessions = raw_sessions if isinstance(raw_sessions, dict) else {}
        raw_pending = await asyncio.to_thread(load_data, VOICE_PENDING_REPORTS_STORE, {})
        self.pending_reports = raw_pending if isinstance(raw_pending, dict) else {}
        raw_history = await asyncio.to_thread(load_data, VOICE_REPORT_HISTORY_STORE, {})
        self.report_history = raw_history if isinstance(raw_history, dict) else {}
        self._restore_task = asyncio.create_task(self._restore_sessions_after_ready())
        self._retry_task = asyncio.create_task(self._retry_pending_reports())
        self._send_task = asyncio.create_task(self._send_queued_reports())

    async def cog_unload(self):
        if self._restore_task and not self._restore_task.done():
            self._restore_task.cancel()
        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()

    async def _persist(self):
        async with self._persist_lock:
            snapshot = copy.deepcopy(self.sessions)
            await asyncio.to_thread(save_data, "voice_sessions", snapshot)

    async def _persist_pending(self):
        async with self._pending_lock:
            snapshot = copy.deepcopy(self.pending_reports)
            await asyncio.to_thread(save_data, VOICE_PENDING_REPORTS_STORE, snapshot)

    async def _persist_history(self):
        async with self._history_lock:
            snapshot = copy.deepcopy(self.report_history)
            await asyncio.to_thread(save_data, VOICE_REPORT_HISTORY_STORE, snapshot)

    def _pending_guild_reports(self, guild_id: int) -> dict[str, dict]:
        return self.pending_reports.setdefault(str(guild_id), {})

    def _report_payload(self, guild: discord.Guild, voice_channel, session: dict, ended_at: datetime, report_id: str | None = None):
        return {
            "id": report_id or f"{voice_channel.id}-{int(ended_at.timestamp())}",
            "guild_id": str(guild.id),
            "channel_id": str(voice_channel.id),
            "channel_name": getattr(voice_channel, "name", f"Voice #{voice_channel.id}"),
            "ended_at": as_iso(ended_at),
            "session": copy.deepcopy(session),
        }

    async def _queue_pending_report(self, guild: discord.Guild, voice_channel, session: dict, ended_at: datetime) -> str:
        report_id = f"{voice_channel.id}-{int(ended_at.timestamp())}"
        guild_reports = self._pending_guild_reports(guild.id)
        guild_reports[report_id] = {
            **self._report_payload(guild, voice_channel, session, ended_at, report_id),
            "attempts": int(guild_reports.get(report_id, {}).get("attempts", 0)),
            "last_error": guild_reports.get(report_id, {}).get("last_error"),
        }
        await self._persist_pending()
        return report_id

    async def _mark_pending_sent(self, guild_id: int, report_id: str):
        guild_reports = self.pending_reports.get(str(guild_id), {})
        guild_reports.pop(report_id, None)
        if not guild_reports:
            self.pending_reports.pop(str(guild_id), None)
        await self._persist_pending()

    async def _mark_pending_failed(self, guild_id: int, report_id: str, error: BaseException):
        guild_reports = self.pending_reports.get(str(guild_id), {})
        report = guild_reports.get(report_id)
        if not report:
            return
        report["attempts"] = int(report.get("attempts", 0)) + 1
        report["last_error"] = repr(error)
        report["last_attempt_at"] = as_iso(now_utc())
        await self._persist_pending()

    def _enqueue_pending_send(self, guild_id: int, report_id: str):
        try:
            self._send_queue.put_nowait((guild_id, report_id))
        except asyncio.QueueFull:
            print(f"Voice session report queued for retry later: send queue is full for #{report_id}")

    async def _remember_sent_report(self, guild: discord.Guild, voice_channel, session: dict, ended_at: datetime, report_id: str | None = None):
        guild_history = self.report_history.setdefault(str(guild.id), [])
        payload = self._report_payload(guild, voice_channel, session, ended_at, report_id)
        payload["sent_at"] = as_iso(now_utc())
        guild_history[:] = [report for report in guild_history if report.get("id") != payload["id"]]
        guild_history.insert(0, payload)
        del guild_history[REPORT_HISTORY_LIMIT:]
        await self._persist_history()

    def _last_report(self, guild_id: int) -> dict | None:
        reports = self.report_history.get(str(guild_id), [])
        return reports[0] if reports else None

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

        if session_duration(session, ended_at) < MIN_SESSION_SECONDS:
            guild_sessions.pop(str(channel.id), None)
            if not guild_sessions:
                self.sessions.pop(str(member.guild.id), None)
            await self._persist()
            return

        report_id = await self._queue_pending_report(member.guild, channel, session, ended_at)
        self._enqueue_pending_send(member.guild.id, report_id)
        guild_sessions.pop(str(channel.id), None)
        if not guild_sessions:
            self.sessions.pop(str(member.guild.id), None)
        await self._persist()

    async def _send_report(self, guild: discord.Guild, voice_channel, session: dict, ended_at: datetime, *, remember: bool = True, report_id: str | None = None):
        report_channel = await self._report_channel(guild)
        if report_channel is None:
            return False

        embed, needs_attachment = build_report_embed(session, voice_channel, ended_at)
        report = self._report_payload(guild, voice_channel, session, ended_at, report_id)
        file = report_to_file(report) if needs_attachment else None
        try:
            await asyncio.wait_for(
                report_channel.send(embed=embed, file=file),
                timeout=REPORT_SEND_TIMEOUT_SECONDS,
            )
            if remember:
                await self._remember_sent_report(guild, voice_channel, session, ended_at, report_id)
            return True
        except (discord.HTTPException, asyncio.TimeoutError) as error:
            print(f"Voice session report skipped for #{voice_channel.id}: {error!r}")
            return False

    async def _send_pending_report(self, guild: discord.Guild, report_id: str) -> bool:
        async with self._sending_lock:
            if report_id in self._sending_reports:
                return False
            self._sending_reports.add(report_id)

        try:
            return await self._send_pending_report_once(guild, report_id)
        finally:
            async with self._sending_lock:
                self._sending_reports.discard(report_id)

    async def _send_pending_report_once(self, guild: discord.Guild, report_id: str) -> bool:
        report = self.pending_reports.get(str(guild.id), {}).get(report_id)
        if not report:
            return True

        ended_at = parse_time(report.get("ended_at")) or now_utc()
        voice_channel = guild.get_channel(int(report.get("channel_id", 0) or 0))
        if not isinstance(voice_channel, (discord.VoiceChannel, discord.StageChannel)):
            voice_channel = StoredVoiceChannel(guild, report.get("channel_id", 0), report.get("channel_name", "Voice session"))

        try:
            sent = await self._send_report(
                guild,
                voice_channel,
                report.get("session", {}),
                ended_at,
                report_id=report.get("id"),
            )
        except Exception as error:
            await self._mark_pending_failed(guild.id, report_id, error)
            print(f"Voice session report retry failed for #{report.get('channel_id')}: {error!r}")
            return False

        if sent:
            await self._mark_pending_sent(guild.id, report_id)
            return True

        await self._mark_pending_failed(guild.id, report_id, asyncio.TimeoutError())
        return False

    async def _retry_pending_reports(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            for guild_id, reports in list(self.pending_reports.items()):
                guild = self.bot.get_guild(int(guild_id))
                if guild is None:
                    continue
                for report_id in list(reports):
                    await self._send_pending_report(guild, report_id)
                    await asyncio.sleep(1)
            await asyncio.sleep(REPORT_RETRY_SECONDS)

    async def _send_queued_reports(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            guild_id, report_id = await self._send_queue.get()
            try:
                guild = self.bot.get_guild(guild_id)
                if guild is not None:
                    await self._send_pending_report(guild, report_id)
                    await asyncio.sleep(REPORT_SEND_SPACING_SECONDS)
            finally:
                self._send_queue.task_done()

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
        pending_reports = self.pending_reports.get(str(interaction.guild_id), {})
        if report_channel is None:
            description = "No report channel is configured. Use `/voice set` to enable tracking."
            color = Palette.WARNING
        else:
            description = (
                f"Reports: {report_channel.mention}\n"
                f"Minimum session: `1h`\n"
                f"Active tracked rooms: `{len(active_sessions)}`\n"
                f"Pending reports: `{len(pending_reports)}`"
            )
            color = Palette.TEAL
        embed = make_embed("Voice report status", description, color=color)
        brand_footer(embed, "Voice session reports")
        await respond(interaction, embed, ephemeral=True)

    @voice.command(name="retry", description="Retry any voice reports that failed to send")
    async def voice_retry(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True, thinking=True)
        pending_reports = list(self.pending_reports.get(str(interaction.guild_id), {}))
        if not pending_reports:
            embed = make_embed(
                "No pending voice reports",
                "Every completed voice session report has already been sent.",
                color=Palette.SUCCESS,
            )
            brand_footer(embed, "Voice session reports")
            return await respond(interaction, embed, ephemeral=True)

        sent = 0
        for report_id in pending_reports:
            if await self._send_pending_report(interaction.guild, report_id):
                sent += 1
            await asyncio.sleep(1)

        remaining = len(self.pending_reports.get(str(interaction.guild_id), {}))
        embed = make_embed(
            "Voice report retry complete",
            f"Sent `{sent}` pending report(s). `{remaining}` still pending.",
            color=Palette.SUCCESS if remaining == 0 else Palette.WARNING,
        )
        brand_footer(embed, "Voice session reports")
        await respond(interaction, embed, ephemeral=True)

    @voice.command(name="pending", description="List voice reports waiting to be sent")
    async def voice_pending(self, interaction: discord.Interaction):
        reports = self.pending_reports.get(str(interaction.guild_id), {})
        if not reports:
            embed = make_embed(
                "No pending voice reports",
                "Every completed voice session report has already been sent.",
                color=Palette.SUCCESS,
            )
            brand_footer(embed, "Voice session reports")
            return await respond(interaction, embed, ephemeral=True)

        chunks = split_lines(pending_report_lines(reports), limit=950)
        embed = make_embed(
            "Pending voice reports",
            f"`{len(reports)}` report(s) are waiting for delivery. Use `/voice retry` to send them again.",
            color=Palette.WARNING,
        )
        for index, chunk in enumerate(chunks[:5], 1):
            embed.add_field(
                name="Reports" if index == 1 else "Reports (continued)",
                value=chunk,
                inline=False,
            )
        if len(chunks) > 5:
            embed.add_field(
                name="More reports",
                value="Only the first entries fit in Discord's embed limit. Retry or inspect `data/voice_pending_reports.json` for the full list.",
                inline=False,
            )
        brand_footer(embed, "Voice session reports")
        await respond(interaction, embed, ephemeral=True)

    resend = app_commands.Group(
        name="resend",
        description="Resend a previously delivered voice report",
        parent=voice,
    )

    @resend.command(name="last", description="Resend the most recently delivered voice report")
    async def voice_resend_last(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True, thinking=True)
        report = self._last_report(interaction.guild_id)
        if not report:
            embed = make_embed(
                "No voice report history yet",
                "I have not sent a voice report since report history was enabled.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Voice session reports")
            return await respond(interaction, embed, ephemeral=True)

        ended_at = parse_time(report.get("ended_at")) or now_utc()
        voice_channel = StoredVoiceChannel(interaction.guild, report.get("channel_id", 0), report.get("channel_name", "Voice session"))
        sent = await self._send_report(
            interaction.guild,
            voice_channel,
            report.get("session", {}),
            ended_at,
            remember=False,
            report_id=report.get("id"),
        )
        embed = make_embed(
            "Voice report resent" if sent else "Could not resend voice report",
            (
                f"The last report was posted again for {voice_channel.mention}."
                if sent
                else "Discord did not accept the resend in time. Try again in a moment."
            ),
            color=Palette.SUCCESS if sent else Palette.WARNING,
        )
        brand_footer(embed, "Voice session reports")
        await respond(interaction, embed, ephemeral=True)

    export = app_commands.Group(
        name="export",
        description="Export saved voice report data",
        parent=voice,
    )

    @export.command(name="last", description="Export the most recently delivered voice report")
    @app_commands.describe(format="Export format")
    @app_commands.choices(
        format=[
            app_commands.Choice(name="Text", value="txt"),
            app_commands.Choice(name="CSV", value="csv"),
        ]
    )
    async def voice_export_last(self, interaction: discord.Interaction, format: app_commands.Choice[str] | None = None):
        report = self._last_report(interaction.guild_id)
        if not report:
            embed = make_embed(
                "No voice report history yet",
                "I have not sent a voice report since report history was enabled.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Voice session reports")
            return await respond(interaction, embed, ephemeral=True)

        export_format = format.value if format else "txt"
        file = report_to_file(report, csv=export_format == "csv")
        await interaction.response.send_message(
            content=f"Export for `{report.get('channel_name', 'Voice session')}`.",
            file=file,
            ephemeral=True,
        )

    @voice.command(name="test", description="Send a preview voice session report to the configured channel")
    async def voice_test(self, interaction: discord.Interaction):
        report_channel = await self._report_channel(interaction.guild)
        if report_channel is None:
            embed = make_embed(
                "Voice reports are not configured",
                "Choose a channel first with `/voice set`.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Voice session reports")
            return await respond(interaction, embed, ephemeral=True)

        ended_at = now_utc()
        started_at = ended_at - timedelta(hours=1, minutes=27, seconds=18)
        session = new_session(0, "Voice report preview", started_at)
        record_member_join(session, interaction.user.id, interaction.user.display_name, started_at)
        record_member_leave(session, interaction.user.id, ended_at)

        class PreviewVoiceChannel:
            id = 0
            name = "Voice report preview"
            mention = "Voice report preview"

        embed, _ = build_report_embed(session, PreviewVoiceChannel(), ended_at)
        embed.title = "Voice session preview"
        try:
            await asyncio.wait_for(
                report_channel.send(content=f"Test requested by {interaction.user.mention}", embed=embed),
                timeout=8,
            )
        except (discord.HTTPException, asyncio.TimeoutError) as error:
            print(f"Voice session test report skipped for #{report_channel.id}: {error!r}")
            failure = make_embed(
                "Could not send the test report",
                "Check that I can view the channel, send messages and embed links there.",
                color=Palette.DANGER,
            )
            brand_footer(failure, "Voice session reports")
            return await respond(interaction, failure, ephemeral=True)

        confirmation = make_embed(
            "Test report sent",
            f"A preview was posted in {report_channel.mention}. It does not affect voice tracking.",
            color=Palette.SUCCESS,
        )
        brand_footer(confirmation, "Voice session reports")
        await respond(interaction, confirmation, ephemeral=True)


async def setup(bot):
    await bot.add_cog(VoiceReports(bot))
