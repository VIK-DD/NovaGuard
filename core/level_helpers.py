"""Deterministic level, message and historical-backfill helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


MIN_XP_MESSAGE_CHARS = 4
BACKFILL_DEFAULT_DAYS = 700
BACKFILL_MAX_DAYS = 700
BACKFILL_DEFAULT_XP_PER_MESSAGE = 2
BACKFILL_DEFAULT_CAP_PER_USER = 20_000


def parse_saved_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def meaningful_message(message):
    content = (message.content or "").strip()
    if len(content) >= MIN_XP_MESSAGE_CHARS:
        return True
    return bool(message.attachments or message.stickers)


def meaningful_historical_message(message):
    if message.content:
        return meaningful_message(message)
    return True


def rank_position(guild_data, user_id):
    ordered = sorted(guild_data.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)
    position = next(
        (index for index, (uid, _) in enumerate(ordered, 1) if uid == str(user_id)),
        0,
    )
    return position, len(ordered)


def backfill_window(days, now=None):
    """Return the exact recent calendar window, hard-capped at 700 days."""
    before = now or datetime.now(UTC)
    bounded_days = min(max(int(days), 1), BACKFILL_MAX_DAYS)
    return before - timedelta(days=bounded_days), before


def boosted_xp(base, multiplier):
    """Apply a paid XP booster without truncating small-message gains."""
    try:
        factor = max(1.0, float(multiplier))
    except (TypeError, ValueError):
        factor = 1.0
    return max(1, round(int(base) * factor))


def xp_from_message_counts(message_counts, xp_per_message, cap_per_user):
    return {
        user_id: min(count * xp_per_message, cap_per_user)
        for user_id, count in message_counts.items()
        if count > 0
    }


def replace_backfill_for_guild(guild_data, message_counts, xp_by_user):
    """Replace a guild's XP data with one complete historical scan."""
    applied_xp = 0
    applied_messages = 0

    guild_data.clear()
    for user_id, xp_amount in xp_by_user.items():
        if xp_amount <= 0:
            continue
        record = {
            "xp": int(xp_amount),
            "messages": int(message_counts.get(user_id, 0)),
            "last_gain": None,
        }
        guild_data[user_id] = record
        applied_xp += int(xp_amount)
        applied_messages += int(message_counts.get(user_id, 0))

    return applied_xp, applied_messages
