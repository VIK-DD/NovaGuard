"""Pseudonymous evidence that a rights request was answered.

Article 5(2) asks an operator to be able to demonstrate compliance, which for
access and erasure means showing the request was served.  Keeping a readable
list of who asked would answer that by creating exactly the kind of record data
minimisation exists to prevent, so the subject is stored as a keyed digest: the
log proves what happened and how often, and points at a person only for someone
who already holds their Discord ID and can present it.

The digest uses a message prefix distinct from the deletion ledger's, so anyone
holding both stores still cannot line them up against each other.

This log is evidence, never a gate.  A failure to record must not stop an export
or an erasure — see the callers in ``cogs/privacy.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
from datetime import UTC, datetime

from . import database
from .secure_files import encryption_secret


KINDS = ("user_export", "user_delete", "guild_export", "guild_delete")
OUTCOMES = ("served", "undeliverable")
_DIGEST_MESSAGE = "NovaGuard privacy request log v1\0"
_LOCK = threading.RLock()


def _moment(value):
    if value is None:
        return datetime.now(UTC)
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def subject_digest(identifier, *, secret=None):
    """A stable keyed digest of a Discord ID, never reversible to the ID."""
    identifier = str(identifier).strip()
    if not identifier:
        raise ValueError("A request subject is required")
    secret = encryption_secret() if secret is None else bytes(secret)
    message = f"{_DIGEST_MESSAGE}{identifier}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def record_privacy_request(kind, subject_id, *, outcome="served", now=None):
    """Record that a rights request was handled, and how it ended."""
    if kind not in KINDS:
        raise ValueError(f"Unsupported request kind: {kind}")
    if outcome not in OUTCOMES:
        raise ValueError(f"Unsupported request outcome: {outcome}")
    created_at = _moment(now).isoformat()
    digest = subject_digest(subject_id)
    database.init_database()
    with _LOCK, database.connect() as connection:
        connection.execute(
            "INSERT INTO privacy_requests (created_at, kind, subject_digest, outcome)"
            " VALUES (?, ?, ?, ?)",
            (created_at, kind, digest, outcome),
        )
        connection.commit()
    return {"created_at": created_at, "kind": kind, "outcome": outcome}


def privacy_request_log(*, limit=None):
    """The recorded requests, oldest first."""
    database.init_database()
    query = (
        "SELECT created_at, kind, subject_digest, outcome FROM privacy_requests"
        " ORDER BY id"
    )
    parameters = ()
    if limit is not None:
        query += " LIMIT ?"
        parameters = (int(limit),)
    with _LOCK, database.connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def purge_privacy_requests(cutoff):
    """Drop entries recorded before ``cutoff``, returning how many went."""
    cutoff = _moment(cutoff).isoformat()
    database.init_database()
    with _LOCK, database.connect() as connection:
        removed = connection.execute(
            "DELETE FROM privacy_requests WHERE created_at < ?", (cutoff,)
        ).rowcount
        connection.commit()
    return removed
