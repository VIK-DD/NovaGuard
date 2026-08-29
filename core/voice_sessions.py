"""Voice-session timekeeping, participant summaries and text exports."""

from datetime import UTC, datetime

import discord


MIN_SESSION_SECONDS = 60 * 60


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
