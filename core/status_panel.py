"""The public status card, and the clock that decides when it is due.

Deliberately free of Discord calls and network probes: the cog gathers the
readings, this turns them into a card. Keeping the two apart is what lets the
interesting cases — the database down, the API silent, maintenance running —
be tested without a bot, a server or a wait.

Scheduling reuses the backup schedule's parser and its Europe/Chisinau
default, so an operator learns one convention rather than two.
"""

import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.backups import parse_backup_schedule
from core.theme import Palette, brand_footer, make_embed
from core.utils import format_timedelta

DEFAULT_STATUS_SCHEDULE = "07:00,19:00"
DEFAULT_STATUS_TIMEZONE = "Europe/Chisinau"
STATUS_MESSAGE_LIFETIME = timedelta(days=14)

OPERATIONAL = "operational"
DEGRADED = "degraded"
MAINTENANCE = "maintenance"

_UP = "🟢"
_DOWN = "🔴"

_STATE_TITLES = {
    OPERATIONAL: "🟢 All Operational",
    DEGRADED: "🔴 Degraded Service",
    MAINTENANCE: "🟡 Under Maintenance",
}

_STATE_COLORS = {
    OPERATIONAL: Palette.SUCCESS,
    DEGRADED: Palette.DANGER,
    MAINTENANCE: Palette.WARNING,
}


def status_schedule():
    return parse_backup_schedule(os.getenv("STATUS_SCHEDULE", DEFAULT_STATUS_SCHEDULE))


def status_timezone_name():
    return os.getenv("STATUS_TIMEZONE", DEFAULT_STATUS_TIMEZONE).strip() or DEFAULT_STATUS_TIMEZONE


def status_timezone():
    try:
        return ZoneInfo(status_timezone_name())
    except ZoneInfoNotFoundError:
        return UTC


def status_schedule_label():
    times = ", ".join(f"{hour:02d}:{minute:02d}" for hour, minute in status_schedule())
    return f"{times} {status_timezone_name()}"


def due_slot(now=None):
    """The slot owed at ``now``, or None.

    A slot is a minute stamped in the operator's timezone, so the caller can
    remember the last one it served and post exactly once per slot. Reading
    the hour off UTC instead would drift the post by the offset all year.
    """
    local_now = (now or datetime.now(UTC)).astimezone(status_timezone())
    if (local_now.hour, local_now.minute) not in status_schedule():
        return None
    return local_now.strftime("%Y-%m-%d %H:%M")


def status_message_is_stale(created_at, *, now=None):
    """Whether the public card is old enough to be replaced.

    Scheduled refreshes edit the existing Discord message.  A fresh message is
    posted only once the current one has lived for fourteen days, which keeps
    the channel quiet without leaving one card buried forever.
    """
    if not isinstance(created_at, datetime):
        return True

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC) >= created_at.astimezone(UTC) + STATUS_MESSAGE_LIFETIME


def status_clock_label(now=None):
    """The zone as people say it: EEST in summer, EET in winter.

    ``Europe/Chisinau`` is a database key, not a clock, and it tells a reader
    glancing at the card nothing. Reading the abbreviation off the moment being
    described also survives the daylight-saving switch, which any fixed string
    gets wrong for half the year.
    """
    local_now = (now or datetime.now(UTC)).astimezone(status_timezone())
    return local_now.tzname() or status_timezone_name()


def next_slot_label(now=None):
    """The next scheduled time, so a reader can judge whether a card is stale."""
    local_now = (now or datetime.now(UTC)).astimezone(status_timezone())
    schedule = status_schedule()
    minutes_now = local_now.hour * 60 + local_now.minute
    upcoming = [h * 60 + m for h, m in schedule if h * 60 + m > minutes_now]
    total = upcoming[0] if upcoming else (schedule[0][0] * 60 + schedule[0][1])
    return f"{total // 60:02d}:{total % 60:02d}"


def build_snapshot(
    *,
    bot_ready,
    latency_ms,
    api_ok,
    api_detail,
    database_ok,
    maintenance,
    uptime_seconds,
    guilds,
    members,
    generated_at=None,
):
    """One reading of every component, in the order the card lists them."""
    return {
        "components": [
            {
                "name": "NovaGuard",
                "ok": bool(bot_ready),
                "detail": f"{latency_ms} ms to Discord" if bot_ready else "not connected",
            },
            {
                "name": "Dashboard API",
                "ok": bool(api_ok),
                "detail": api_detail,
            },
            {
                "name": "Database",
                "ok": bool(database_ok),
                "detail": "responding" if database_ok else "not responding",
            },
        ],
        "maintenance": maintenance or {"enabled": False, "message": ""},
        "uptime_seconds": max(int(uptime_seconds or 0), 0),
        "guilds": int(guilds or 0),
        "members": int(members or 0),
        "generated_at": generated_at or datetime.now(UTC),
    }


def overall_state(snapshot):
    """Maintenance wins.

    While maintenance is on, components are expected to be down; reporting
    that as a fault sends people looking for a problem that is not there.
    """
    if snapshot["maintenance"].get("enabled"):
        return MAINTENANCE
    if any(not component["ok"] for component in snapshot["components"]):
        return DEGRADED
    return OPERATIONAL


def _reach_line(guilds, members):
    servers = f"{guilds:,} server" + ("" if guilds == 1 else "s")
    people = f"{members:,} member" + ("" if members == 1 else "s")
    return f"Looking after **{servers}** and **{people}**."


def build_status_embed(snapshot, *, now=None):
    state = overall_state(snapshot)
    maintenance = snapshot["maintenance"]

    description = []
    if state == MAINTENANCE:
        message = (maintenance.get("message") or "").strip()
        description.append(f"> {message}" if message else "> Maintenance is in progress.")
    description.append(_reach_line(snapshot["guilds"], snapshot["members"]))

    embed = make_embed(
        _STATE_TITLES[state],
        "\n\n".join(description),
        color=_STATE_COLORS[state],
    )

    for component in snapshot["components"]:
        # Each row keeps its own truth. The banner above carries the
        # maintenance state; painting a working component amber while it reads
        # "Operational" would contradict itself, and would hide a real fault
        # sitting underneath a maintenance window.
        mark = _UP if component["ok"] else _DOWN
        label = "Operational" if component["ok"] else "Not responding"
        detail = (component.get("detail") or "").strip()
        # Reads better with a capital: "responding" becomes "Responding". A
        # detail that starts with a number ("101 ms to Discord") is left as it
        # is, since upper-casing a digit does nothing and the line already
        # reads cleanly.
        if detail and detail[0].isalpha():
            detail = detail[0].upper() + detail[1:]
        # A detail that only repeats the label is noise.
        if detail.lower() == label.lower():
            detail = ""
        # Stacked, not inline: Discord packs inline fields three to a row on
        # desktop, squeezing each into a column too narrow for its detail line.
        # Stacking is all the separation the rows need \u2014 a trailing zero-width
        # space added a second gap on top of Discord's own, and three rows of
        # that made the card look like it had come apart.
        embed.add_field(
            name=component["name"],
            value=f"{mark} **{label}**" + (f"\n{detail}" if detail else ""),
            inline=False,
        )

    embed.add_field(
        name="Uptime",
        value=format_timedelta(timedelta(seconds=snapshot["uptime_seconds"])),
        inline=False,
    )
    moment = now or snapshot["generated_at"]
    embed.add_field(
        name="Next refresh",
        value=f"{next_slot_label(moment)} {status_clock_label(moment)}",
        inline=False,
    )

    embed.timestamp = snapshot["generated_at"]
    brand_footer(embed, "Service status")
    return embed
