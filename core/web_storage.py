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


# scrypt over a fixed, domain-separating salt. A per-key random salt would be
# better, but there is nowhere to keep one: this key must be derivable from the
# environment alone at import, with no stored state to consult. The fixed salt
# therefore buys domain separation rather than per-install uniqueness, and the
# work factor is what does the real work.
#
# 2**14 costs ~16 MB and tens of milliseconds, paid once per process at import
# and never per request - so it is bounded by the smallest host this runs on
# rather than by throughput.
_KDF_SALT = b"novaguard-token-kdf-v2"
_KDF_N = 2**14
_KDF_R = 8
_KDF_P = 1


def _cipher_from_secret(secret, *, legacy=False):
    """Derive a domain-separated Fernet key without storing the raw secret.

    `legacy=True` reproduces the original single-SHA-256 derivation. One round
    of SHA-256 is not a key-derivation function: it is fast by design, which is
    exactly wrong for a value an operator might reasonably set to a passphrase
    rather than to 32 random bytes. It survives only so tokens written by
    earlier versions can still be read, and then rewritten under the new key.
    """
    if Fernet is None or not secret:
        return None
    if legacy:
        digest = hashlib.sha256(("novaguard-token::" + secret).encode()).digest()
    else:
        digest = hashlib.scrypt(
            secret.encode("utf-8"),
            salt=_KDF_SALT,
            n=_KDF_N,
            r=_KDF_R,
            p=_KDF_P,
            dklen=32,
            maxmem=64 * 1024 * 1024,
        )
    return Fernet(base64.urlsafe_b64encode(digest))


def _build_ciphers():
    """The key used for writing, plus every older one still worth reading.

    Changing a derivation would otherwise log the whole estate out at once:
    existing rows are Fernet tokens under the old key, and a key that cannot
    decrypt them makes every session look expired. Old derivations stay as
    read-only fallbacks, and `db_touch_session` rewrites a row under the
    current key the first time that session is used - so installs migrate
    themselves as people browse, rather than in one flush.
    """
    dedicated_secret = os.getenv("WEB_TOKEN_KEY", "").strip()
    active_secret = dedicated_secret or CLIENT_SECRET
    primary = _cipher_from_secret(active_secret)

    legacy = [_cipher_from_secret(active_secret, legacy=True)]
    if dedicated_secret and CLIENT_SECRET and dedicated_secret != CLIENT_SECRET:
        # Older still: before WEB_TOKEN_KEY existed the Discord client secret
        # was always the key.
        legacy.append(_cipher_from_secret(CLIENT_SECRET))
        legacy.append(_cipher_from_secret(CLIENT_SECRET, legacy=True))
    return primary, tuple(cipher for cipher in legacy if cipher is not None)


_CIPHER, _LEGACY_CIPHERS = _build_ciphers()


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
    for cipher in (_CIPHER, *_LEGACY_CIPHERS):
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


def _escape_like(value):
    """Make a user-typed string match literally inside a LIKE pattern.

    The backslash escape has to be declared per-clause with ESCAPE, because
    SQLite has no default escape character - without it the backslashes added
    here would themselves be matched as ordinary text.
    """
    return str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
        # `%` and `_` are LIKE wildcards, so an unescaped filter of "%" matched
        # the whole trail instead of the literal character someone typed. Only
        # a reader already authorized for this guild's audit log could do it,
        # which is why it was untidy rather than a boundary - but a filter that
        # quietly means something other than what was typed is still wrong.
        clauses.append("(username LIKE ? ESCAPE '\\' OR user_id = ?)")
        params.extend((f"%{_escape_like(actor)}%", actor))
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
        # Every clause joined into WHERE is a module literal chosen above;
        # every value, including the actor filter, is a bound parameter.
        query = (
            "SELECT id, username, user_id, action, changes_json, created_at "
            "FROM web_audit "
            # literal clauses, bound values
            f"WHERE {' AND '.join(clauses)} "  # nosec B608
            "ORDER BY id DESC LIMIT ?"
        )
        rows = db.execute(query, params).fetchall()
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
