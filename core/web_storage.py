"""Persistent dashboard sessions and audit records.

This module owns the dashboard-specific SQLite schema and OAuth-token
encryption. Keeping it outside the HTTP router makes the storage boundary
reviewable without walking through request handlers and Discord API logic.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from datetime import UTC, datetime

from .database import connect

try:  # at-rest token encryption is optional — degrade gracefully if unavailable
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - exercised only on minimal installs
    Fernet = None
    InvalidToken = Exception


CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
MAX_SESSIONS_PER_USER = 5
AUDIT_KEEP_DAYS = 90
TOKEN_PREFIX = "enc:"
SCHEMA_VERSION = 1

_DB_LOCK = threading.Lock()


def _cipher_from_secret(secret):
    """Derive a domain-separated Fernet key without storing the raw secret."""
    if Fernet is None or not secret:
        return None
    digest = hashlib.sha256(("novaguard-token::" + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _build_ciphers():
    """Prefer the dedicated key but retain read-only legacy compatibility."""
    dedicated_secret = os.getenv("WEB_TOKEN_KEY", "").strip()
    primary = _cipher_from_secret(dedicated_secret or CLIENT_SECRET)
    legacy = None
    if dedicated_secret and CLIENT_SECRET and dedicated_secret != CLIENT_SECRET:
        # Earlier versions always used the Discord client secret. Keep it only
        # for reading old rows; all subsequent writes use the dedicated key.
        legacy = _cipher_from_secret(CLIENT_SECRET)
    return primary, legacy


_CIPHER, _LEGACY_CIPHER = _build_ciphers()


def _encrypt_token(value):
    if value is None or _CIPHER is None:
        return value
    return TOKEN_PREFIX + _CIPHER.encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_token(value):
    if not isinstance(value, str) or not value.startswith(TOKEN_PREFIX):
        return value
    if _CIPHER is None:
        return None
    token = value[len(TOKEN_PREFIX) :].encode("ascii")
    for cipher in (_CIPHER, _LEGACY_CIPHER):
        if cipher is None:
            continue
        try:
            return cipher.decrypt(token).decode("utf-8")
        except InvalidToken:
            continue
    return None


def init_web_tables():
    with _DB_LOCK, connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS web_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS web_sessions (
                sid_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_json TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_expires_at REAL NOT NULL DEFAULT 0,
                guilds_json TEXT NOT NULL DEFAULT '{}',
                guilds_fetched_at REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                expires_at REAL NOT NULL,
                last_seen_at REAL NOT NULL DEFAULT 0
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS web_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                ip TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_web_audit_guild ON web_audit (guild_id, id DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions (user_id)")

        row = db.execute("SELECT value FROM web_meta WHERE key = 'schema_version'").fetchone()
        version = int(row["value"]) if row else 0
        # Future migrations are intentionally isolated to this web schema.
        if version != SCHEMA_VERSION:
            db.execute(
                "INSERT INTO web_meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )


def db_ping():
    """Return whether the dashboard database accepts a trivial query."""
    try:
        with _DB_LOCK, connect() as db:
            db.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def _hash_sid(sid):
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def db_save_session(sid, entry):
    with _DB_LOCK, connect() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO web_sessions
            (sid_hash, user_id, user_json, access_token, refresh_token, token_expires_at,
             guilds_json, guilds_fetched_at, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _hash_sid(sid),
                entry["user"]["id"],
                json.dumps(entry["user"]),
                _encrypt_token(entry["access_token"]),
                _encrypt_token(entry.get("refresh_token")),
                entry.get("token_expires_at", 0),
                json.dumps(entry.get("guilds", {})),
                entry.get("guilds_fetched_at", 0),
                entry.get("created_at") or datetime.now(UTC).isoformat(),
                entry["expires_at"],
                time.time(),
            ),
        )
        db.execute(
            """
            DELETE FROM web_sessions WHERE user_id = ? AND sid_hash NOT IN (
                SELECT sid_hash FROM web_sessions WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
            )
            """,
            (entry["user"]["id"], entry["user"]["id"], MAX_SESSIONS_PER_USER),
        )


def db_load_session(sid):
    with _DB_LOCK, connect() as db:
        row = db.execute(
            "SELECT * FROM web_sessions WHERE sid_hash = ?", (_hash_sid(sid),)
        ).fetchone()
    if row is None:
        return None
    entry = {
        "user": json.loads(row["user_json"]),
        "access_token": _decrypt_token(row["access_token"]),
        "refresh_token": _decrypt_token(row["refresh_token"]),
        "token_expires_at": row["token_expires_at"],
        "guilds": json.loads(row["guilds_json"]),
        "guilds_fetched_at": row["guilds_fetched_at"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_seen_at": row["last_seen_at"],
    }
    if entry["expires_at"] < time.time():
        db_delete_session(sid)
        return None
    return entry


def db_delete_session(sid):
    with _DB_LOCK, connect() as db:
        db.execute("DELETE FROM web_sessions WHERE sid_hash = ?", (_hash_sid(sid),))


def db_touch_session(sid, entry):
    with _DB_LOCK, connect() as db:
        db.execute(
            """
            UPDATE web_sessions SET access_token = ?, refresh_token = ?, token_expires_at = ?,
                   guilds_json = ?, guilds_fetched_at = ?, last_seen_at = ?
            WHERE sid_hash = ?
            """,
            (
                _encrypt_token(entry["access_token"]),
                _encrypt_token(entry.get("refresh_token")),
                entry.get("token_expires_at", 0),
                json.dumps(entry.get("guilds", {})),
                entry.get("guilds_fetched_at", 0),
                time.time(),
                _hash_sid(sid),
            ),
        )


def db_gc():
    cutoff = datetime.now(UTC).timestamp() - AUDIT_KEEP_DAYS * 86400
    with _DB_LOCK, connect() as db:
        db.execute("DELETE FROM web_sessions WHERE expires_at < ?", (time.time(),))
        db.execute(
            "DELETE FROM web_audit WHERE created_at < ?",
            (datetime.fromtimestamp(cutoff, UTC).isoformat(),),
        )


def db_add_audit(guild_id, user, action, changes, ip):
    with _DB_LOCK, connect() as db:
        db.execute(
            """
            INSERT INTO web_audit (guild_id, user_id, username, action, changes_json, ip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(guild_id),
                user["id"],
                user["username"],
                action,
                json.dumps(changes, ensure_ascii=False),
                ip,
                datetime.now(UTC).isoformat(),
            ),
        )


def db_get_audit(
    guild_id,
    limit,
    *,
    cursor=None,
    kind=None,
    action=None,
    actor=None,
    after=None,
    before=None,
):
    clauses = ["guild_id = ?"]
    params = [str(guild_id)]
    if cursor is not None:
        clauses.append("id < ?")
        params.append(cursor)
    if kind == "settings":
        clauses.append("(action = 'config_update' OR action LIKE 'update_%')")
    elif kind == "actions":
        clauses.append("action LIKE 'dashboard_%'")
    elif kind == "login":
        clauses.append("action = 'login'")
    if action:
        clauses.append("action = ?")
        params.append(action)
    if actor:
        clauses.append("(username LIKE ? OR user_id = ?)")
        params.extend((f"%{actor}%", actor))
    if after:
        clauses.append("created_at >= ?")
        params.append(after)
    if before:
        clauses.append("created_at < ?")
        params.append(before)

    # Fetch one extra row so callers can advertise a real next page instead
    # of making the client issue an empty request at the end of the trail.
    params.append(limit + 1)
    with _DB_LOCK, connect() as db:
        rows = db.execute(
            f"""
            SELECT id, username, user_id, action, changes_json, created_at
            FROM web_audit
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC LIMIT ?
            """,
            params,
        ).fetchall()
    has_more = len(rows) > limit
    entries = [
        {
            "id": row["id"],
            "username": row["username"],
            "user_id": row["user_id"],
            "action": row["action"],
            "changes": json.loads(row["changes_json"]),
            "created_at": row["created_at"],
        }
        for row in rows[:limit]
    ]
    next_cursor = entries[-1]["id"] if has_more and entries else None
    return entries, next_cursor
