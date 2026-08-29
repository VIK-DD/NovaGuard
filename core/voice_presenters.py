"""Discord presentation and file helpers for completed voice sessions."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import discord

from .theme import Palette, brand_footer, make_embed, progress_bar
from .voice_sessions import (
    active_member_ids,
    human_duration,
    now_utc,
    participant_lines,
    participant_seconds,
    parse_time,
    report_export_text,
    session_activity,
    session_duration,
    session_highlights,
)

MAX_ACTIVITY_FIELDS = 3
MAX_FIELD_LENGTH = 1000
ACTIVITY_BAR_SLOTS = 12


class StoredVoiceChannel:
    def __init__(self, guild: discord.Guild, channel_id: int | str, channel_name: str):
        self.guild = guild
        self.id = int(channel_id)
        self.name = channel_name or f"Voice #{channel_id}"
        self.mention = f"<#{self.id}>"


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


def active_session_status_lines(guild, sessions: dict[str, dict], checked_at: datetime) -> list[str]:
    rows = []
    for channel_id, session in sorted(sessions.items(), key=lambda item: item[1].get("started_at") or ""):
        try:
            channel = guild.get_channel(int(channel_id))
        except (TypeError, ValueError):
            channel = None
        channel_label = getattr(channel, "mention", None) or f"<#{channel_id}>"
        started_at = parse_time(session.get("started_at"))
        started_text = discord.utils.format_dt(started_at, "R") if started_at else "unknown start"
        duration = human_duration(session_duration(session, checked_at))
        active = len(active_member_ids(session))
        unique = len(session.get("members", {}))
        peak = int(session.get("peak_members", 0) or 0)
        rows.append(
            f"{channel_label} - `{duration}` running\n"
            f"`{active}` active • `{unique}` unique • peak `{peak}` • started {started_text}"
        )
    return rows


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
