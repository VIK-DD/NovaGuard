"""Grace window between a server removing NovaGuard and its data being erased.

Removal is not an authenticated deletion request.  An accidental kick, a
permission change that evicts the bot and a deliberate cleanup all arrive as
the same event, and erasure here is final — it writes a deletion-ledger entry,
so restoring a backup will not bring the data back.  Erasure therefore waits,
and adding the bot back cancels it.

Explicit deletion through ``/privacy server-delete`` does not come through
here; that request is authenticated and stays immediate.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from . import database
from .privacy import retention_policy


GRACE_DAYS_KEY = "PRIVACY_GUILD_GRACE_DAYS"
_LOCK = threading.RLock()


def _id(value):
    return str(value).strip()


def _moment(value):
    if value is None:
        return datetime.now(UTC)
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def grace_days(env=None):
    """The configured window, bounded by the shared retention rules."""
    return retention_policy(env)[GRACE_DAYS_KEY]


def schedule_guild_deletion(guild_id, *, now=None, env=None):
    """Record a deletion deadline for a removed server and return the stored row.

    An existing deadline is kept rather than replaced.  Extending it on every
    removal would let a repeated kick/re-add cycle postpone erasure forever,
    which is the mirror image of the failure this module exists to prevent.
    """
    guild_id = _id(guild_id)
    moment = _moment(now)
    deadline = moment + timedelta(days=grace_days(env))
    database.init_database()
    with _LOCK, database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO pending_guild_deletions"
            " (guild_id, scheduled_at, deadline) VALUES (?, ?, ?)",
            (guild_id, moment.isoformat(), deadline.isoformat()),
        )
        connection.commit()
        row = connection.execute(
            "SELECT guild_id, scheduled_at, deadline FROM pending_guild_deletions"
            " WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
    return dict(row)


def cancel_guild_deletion(guild_id):
    """Drop a pending deletion, reporting whether one was actually there."""
    guild_id = _id(guild_id)
    database.init_database()
    with _LOCK, database.connect() as connection:
        removed = connection.execute(
            "DELETE FROM pending_guild_deletions WHERE guild_id = ?", (guild_id,)
        ).rowcount
        connection.commit()
    return bool(removed)


def pending_guild_deletions():
    """Every scheduled deletion, soonest deadline first."""
    database.init_database()
    with _LOCK, database.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT guild_id, scheduled_at, deadline FROM pending_guild_deletions"
                " ORDER BY deadline, guild_id"
            )
        ]


def due_guild_deletions(*, now=None):
    """Guild ids whose grace window has closed."""
    moment = _moment(now)
    database.init_database()
    with _LOCK, database.connect() as connection:
        return [
            row["guild_id"]
            for row in connection.execute(
                "SELECT guild_id FROM pending_guild_deletions WHERE deadline <= ?"
                " ORDER BY deadline, guild_id",
                (moment.isoformat(),),
            )
        ]
