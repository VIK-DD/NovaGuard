"""Monthly voice-time ledger.

The voice cog already counts seconds, but only for the session in front of it:
once a channel empties the report is sent and the numbers are thrown away.
Answering "how long was I in voice this month?" needs a running total that
outlives the session, which is what this module keeps.

Time is bucketed by *local* month, not UTC, because a member asking about "this
month" means the month on their wall clock. A call that runs across midnight on
the 1st is split, so neither month is credited with the other's minutes.
"""

import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Chisinau"

# Stretches shorter than this are noise: a misclick, or a member bounced by a
# reconnect. Counting them would inflate the session count without adding
# meaningful time.
MIN_TRACKED_SECONDS = 30


def voice_timezone_name() -> str:
    """The clock the ledger's months are measured against.

    Falls back to the backup schedule's zone so an operator who already set one
    does not have to set a second one that means the same thing.
    """
    for name in (os.getenv("VOICE_TIMEZONE"), os.getenv("BACKUP_TIMEZONE")):
        cleaned = (name or "").strip()
        if cleaned:
            return cleaned
    return DEFAULT_TIMEZONE


def voice_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(voice_timezone_name())
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def month_key(moment: datetime, tz: ZoneInfo | None = None) -> str:
    """The ``YYYY-MM`` bucket a moment belongs to, on the ledger's clock."""
    local = moment.astimezone(tz or voice_timezone())
    return f"{local.year:04d}-{local.month:02d}"


def current_month(tz: ZoneInfo | None = None) -> str:
    return month_key(datetime.now(UTC), tz)


def month_label(key: str) -> str:
    """``2026-08`` as ``August 2026``, for embed titles."""
    try:
        year, month = (int(part) for part in str(key).split("-", 1))
        return datetime(year, month, 1).strftime("%B %Y")
    except (AttributeError, TypeError, ValueError):
        return str(key)


def shift_month(key: str, months: int) -> str:
    """Walk the ``YYYY-MM`` key backwards or forwards, wrapping the year."""
    year, month = (int(part) for part in str(key).split("-", 1))
    index = (year * 12 + (month - 1)) + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _next_month_start(local: datetime, tz: ZoneInfo) -> datetime:
    year, month = local.year, local.month + 1
    if month > 12:
        year, month = year + 1, 1
    return datetime(year, month, 1, tzinfo=tz)


def split_by_month(
    start: datetime, end: datetime, tz: ZoneInfo | None = None
) -> list[tuple[str, float]]:
    """Break a stretch of voice time into ``(month, seconds)`` pieces.

    A single stretch usually lands in one month and returns one piece. The loop
    exists for the call that is still going when the month rolls over: without
    it, every second of a New Year's Eve session would land in December or
    January depending only on when the member happened to disconnect.
    """
    if start is None or end is None or end <= start:
        return []

    tz = tz or voice_timezone()
    buckets: list[tuple[str, float]] = []
    cursor = start

    while cursor < end:
        local = cursor.astimezone(tz)
        boundary = _next_month_start(local, tz).astimezone(UTC)
        # A boundary that is not ahead of the cursor would spin forever. It
        # should be impossible, but a bad zone definition must not hang the bot.
        if boundary <= cursor:
            boundary = cursor + timedelta(days=31)
        chunk_end = min(boundary, end)
        buckets.append((month_key(cursor, tz), (chunk_end - cursor).total_seconds()))
        cursor = chunk_end

    return buckets


def counts_towards_hours(member: dict, *, channel_is_afk: bool = False) -> bool:
    """Whether a connected member's time should be added to the ledger.

    ``member`` is a plain record - ``{"bot", "self_deaf", "deaf"}`` - so the
    rule can be tested without a Discord connection.

    Sitting in the AFK channel, or with sound switched off entirely, is not
    time spent with the server. Muted members still count: plenty of people
    listen without talking, and not counting them would punish the quiet ones.
    """
    if channel_is_afk:
        return False
    if member.get("bot"):
        return False
    return not (member.get("self_deaf") or member.get("deaf"))


def rewardable(member_count: int) -> bool:
    """Whether time in a channel this busy may be paid for.

    Time alone in a channel is still *tracked* - it happened, and /vh should
    say so - but paying for it would make an idle mic the best-paying job on
    the server. Earning needs someone else there.
    """
    return member_count >= 2


# Voice time is paid in blocks rather than per tick. A tick is five minutes
# and the hourly rates do not divide into it evenly, so paying per tick would
# round away a slice of every payment; a block that divides cleanly does not.
PAYOUT_BLOCK_SECONDS = 600
COINS_PER_BLOCK = 8
XP_PER_BLOCK = 10


def voice_payout(
    unpaid_seconds: float,
    *,
    block: int = PAYOUT_BLOCK_SECONDS,
    coins: int = COINS_PER_BLOCK,
    xp: int = XP_PER_BLOCK,
) -> tuple[int, int, float]:
    """Turn banked voice time into ``(coins, xp, seconds still owed)``.

    The remainder is handed back rather than dropped, so ten minutes spread
    over three ticks pays exactly the same as ten minutes in one.
    """
    banked = max(0.0, float(unpaid_seconds or 0))
    blocks = int(banked // block)
    if blocks <= 0:
        return 0, 0, banked
    return blocks * coins, blocks * xp, banked - blocks * block


def format_hours(seconds: float) -> str:
    """``9420`` as ``2h 37m``. Hours lead the format even when the total is
    under one, because hours are what the command is named after."""
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m"
    return f"{total}s"


def decimal_hours(seconds: float) -> float:
    return round(max(0.0, float(seconds or 0)) / 3600, 2)
