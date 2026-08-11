"""SQLite foundation for guild configuration.

Feature data can still live in JSON while server setup/config moves into a
proper database. This keeps the migration safe and incremental.
"""

import json
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime

from .config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "novaguard.sqlite3"
LEGACY_SETTINGS_FILE = DATA_DIR / "settings.json"
LEGACY_LEVELS_FILE = DATA_DIR / "levels.json"
LEGACY_ECONOMY_FILE = DATA_DIR / "economy.json"
VOICE_STORE_FILES = {
    "voice_sessions": DATA_DIR / "voice_sessions.json",
    "voice_pending_reports": DATA_DIR / "voice_pending_reports.json",
    "voice_report_history": DATA_DIR / "voice_report_history.json",
}

_LOCK = threading.RLock()
_INITIALIZED = False


def utc_now():
    return datetime.now(UTC).isoformat()


def _restrict_permissions():
    """Keep the database (encrypted tokens, sessions, audit) readable only by
    the owner. Best-effort — silently ignored on filesystems without POSIX modes."""
    for suffix in ("", "-wal", "-shm"):
        try:
            os.chmod(f"{DB_PATH}{suffix}", 0o600)
        except OSError:
            pass


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    _restrict_permissions()
    return connection


def init_database():
    global _INITIALIZED
    if _INITIALIZED:
        return

    with _LOCK, connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, key)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS level_records (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                messages INTEGER NOT NULL DEFAULT 0,
                last_gain TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS economy_wallets (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                coins INTEGER NOT NULL DEFAULT 0,
                daily_streak INTEGER NOT NULL DEFAULT 0,
                last_daily TEXT,
                last_work TEXT,
                trophies TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_state (
                store TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Voice time that survives the session it was earned in. voice_state
        # holds the live session and is emptied when the channel is; this is
        # the running per-member total /vh reads. Months are local months -
        # see core.voice_hours for why.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_minutes (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                month TEXT NOT NULL,
                seconds REAL NOT NULL DEFAULT 0,
                sessions INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, month)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_minutes_board"
            " ON voice_minutes (guild_id, month, seconds DESC)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS music_cache (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_music_cache_expiry ON music_cache (expires_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_records (
                thread_id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                parent_channel_id TEXT NOT NULL,
                opener_id TEXT NOT NULL,
                opener_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                closed_at TEXT,
                closed_by TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ticket_records_guild_open"
            " ON ticket_records (guild_id, closed_at, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ticket_records_member_open"
            " ON ticket_records (guild_id, opener_id, closed_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS role_panels (
                message_id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                role_ids TEXT NOT NULL,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_panels_guild_updated"
            " ON role_panels (guild_id, updated_at DESC)"
        )
        # Only the hash of the admin key is ever stored. A leaked database
        # must not hand anyone the key itself; the plaintext exists only in
        # the operator's password manager.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_key (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                key_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT
            )
            """
        )
        # Append-only trail of privileged actions. Without it, "who ran that
        # restore?" has no answer after the fact.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                actor_name TEXT,
                action TEXT NOT NULL,
                target TEXT,
                outcome TEXT NOT NULL,
                detail TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_audit_time ON admin_audit (created_at DESC)"
        )
        _add_missing_columns(connection)
        connection.commit()
    _INITIALIZED = True


# Columns added after a table shipped. CREATE TABLE IF NOT EXISTS does nothing
# to a database that already has the table, so a new column has to be added
# explicitly or every existing install would keep the old shape.
_ADDED_COLUMNS = {
    # The shop grew from five labels into items that expire and perks the rest
    # of the bot reads. One JSON column holds all of it, so adding an item
    # later is not another migration.
    "economy_wallets": (("extras", "TEXT NOT NULL DEFAULT '{}'"),),
}


def _add_missing_columns(connection):
    for table, columns in _ADDED_COLUMNS.items():
        existing = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        for name, definition in columns:
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def export_guild_data(guild_id):
    """Everything the bot stores for one guild, and nothing from any other.

    This is what a server owner is entitled to: their settings, their
    members' levels and wallets. Every query filters on guild_id, so no full
    archive of the database has to leave the host to satisfy them.
    """
    init_database()
    key = str(guild_id)
    with connect() as connection:
        settings = {
            row["key"]: decode_value(row["value"])
            for row in connection.execute(
                "SELECT key, value FROM guild_settings WHERE guild_id = ?", (key,)
            )
        }
        levels = [
            dict(row)
            for row in connection.execute(
                "SELECT user_id, xp, messages, last_gain FROM level_records"
                " WHERE guild_id = ? ORDER BY xp DESC",
                (key,),
            )
        ]
        wallets = [
            dict(row)
            for row in connection.execute(
                "SELECT user_id, coins, daily_streak, last_daily, last_work, trophies"
                " FROM economy_wallets WHERE guild_id = ? ORDER BY coins DESC",
                (key,),
            )
        ]
        voice = [
            dict(row)
            for row in connection.execute(
                "SELECT user_id, month, seconds, sessions FROM voice_minutes"
                " WHERE guild_id = ? ORDER BY month DESC, seconds DESC",
                (key,),
            )
        ]
        tickets = [
            dict(row)
            for row in connection.execute(
                "SELECT thread_id, parent_channel_id, opener_id, opener_name, created_at,"
                " closed_at, closed_by FROM ticket_records"
                " WHERE guild_id = ? ORDER BY created_at DESC",
                (key,),
            )
        ]
        role_panels = [
            _decode_role_panel_row(row)
            for row in connection.execute(
                "SELECT * FROM role_panels WHERE guild_id = ? ORDER BY updated_at DESC",
                (key,),
            )
        ]

    return {
        "guild_id": key,
        "exported_at": utc_now(),
        "settings": settings,
        "levels": levels,
        "economy": wallets,
        "voice": voice,
        "tickets": tickets,
        "role_panels": role_panels,
        "counts": {
            "settings": len(settings),
            "levels": len(levels),
            "economy": len(wallets),
            "voice": len(voice),
            "tickets": len(tickets),
            "role_panels": len(role_panels),
        },
    }


def create_ticket_record(guild_id, thread_id, parent_channel_id, opener_id, opener_name):
    init_database()
    created_at = utc_now()
    with _LOCK, connect() as connection:
        connection.execute(
            """
            INSERT INTO ticket_records
                (thread_id, guild_id, parent_channel_id, opener_id, opener_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                parent_channel_id = excluded.parent_channel_id,
                opener_id = excluded.opener_id,
                opener_name = excluded.opener_name,
                created_at = excluded.created_at,
                closed_at = NULL,
                closed_by = NULL
            """,
            (
                str(thread_id),
                str(guild_id),
                str(parent_channel_id),
                str(opener_id),
                str(opener_name)[:100],
                created_at,
            ),
        )
        connection.commit()
    return created_at


def close_ticket_record(thread_id, closed_by=None):
    init_database()
    with _LOCK, connect() as connection:
        cursor = connection.execute(
            "UPDATE ticket_records SET closed_at = ?, closed_by = ?"
            " WHERE thread_id = ? AND closed_at IS NULL",
            (utc_now(), str(closed_by) if closed_by is not None else None, str(thread_id)),
        )
        connection.commit()
    return cursor.rowcount > 0


def open_ticket_for_member(guild_id, opener_id):
    init_database()
    with _LOCK, connect() as connection:
        row = connection.execute(
            "SELECT * FROM ticket_records"
            " WHERE guild_id = ? AND opener_id = ? AND closed_at IS NULL"
            " ORDER BY created_at DESC LIMIT 1",
            (str(guild_id), str(opener_id)),
        ).fetchone()
    return dict(row) if row else None


def list_ticket_records(guild_id, *, open_only=False, limit=20):
    init_database()
    limit = min(max(int(limit), 1), 100)
    where = "guild_id = ? AND closed_at IS NULL" if open_only else "guild_id = ?"
    with _LOCK, connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM ticket_records WHERE {where} ORDER BY created_at DESC LIMIT ?",
            (str(guild_id), limit),
        ).fetchall()
    return [dict(row) for row in rows]


def count_open_tickets(guild_id):
    """Return the exact number of open tickets, independent of list pagination."""
    init_database()
    with _LOCK, connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM ticket_records"
            " WHERE guild_id = ? AND closed_at IS NULL",
            (str(guild_id),),
        ).fetchone()
    return int(row["count"])


def _decode_role_panel_row(row):
    payload = dict(row)
    try:
        role_ids = json.loads(payload.get("role_ids") or "[]")
    except (TypeError, json.JSONDecodeError):
        role_ids = []
    payload["role_ids"] = [str(role_id) for role_id in role_ids]
    return payload


def save_role_panel_record(
    guild_id,
    message_id,
    channel_id,
    title,
    description,
    role_ids,
    *,
    created_by=None,
    previous_message_id=None,
):
    """Insert/update a panel, replacing a missing Discord message atomically."""
    init_database()
    now = utc_now()
    encoded_roles = json.dumps([str(role_id) for role_id in role_ids], ensure_ascii=True)
    with _LOCK, connect() as connection:
        if previous_message_id and str(previous_message_id) != str(message_id):
            connection.execute(
                "DELETE FROM role_panels WHERE guild_id = ? AND message_id = ?",
                (str(guild_id), str(previous_message_id)),
            )
        connection.execute(
            """
            INSERT INTO role_panels
                (message_id, guild_id, channel_id, title, description, role_ids,
                 created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                title = excluded.title,
                description = excluded.description,
                role_ids = excluded.role_ids,
                updated_at = excluded.updated_at
            """,
            (
                str(message_id),
                str(guild_id),
                str(channel_id),
                str(title),
                str(description),
                encoded_roles,
                str(created_by) if created_by is not None else None,
                now,
                now,
            ),
        )
        connection.commit()
    return get_role_panel_record(guild_id, message_id)


def get_role_panel_record(guild_id, message_id):
    init_database()
    with _LOCK, connect() as connection:
        row = connection.execute(
            "SELECT * FROM role_panels WHERE guild_id = ? AND message_id = ?",
            (str(guild_id), str(message_id)),
        ).fetchone()
    return _decode_role_panel_row(row) if row else None


def list_role_panel_records(guild_id, *, limit=20):
    init_database()
    limit = min(max(int(limit), 1), 100)
    with _LOCK, connect() as connection:
        rows = connection.execute(
            "SELECT * FROM role_panels WHERE guild_id = ? ORDER BY updated_at DESC LIMIT ?",
            (str(guild_id), limit),
        ).fetchall()
    return [_decode_role_panel_row(row) for row in rows]


def encode_value(value):
    return json.dumps(value, ensure_ascii=True)


def decode_value(raw_value):
    try:
        return json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return raw_value


def get_metadata(key):
    init_database()
    with _LOCK, connect() as connection:
        row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return decode_value(row["value"]) if row else None


def set_metadata(key, value):
    init_database()
    with _LOCK, connect() as connection:
        connection.execute(
            """
            INSERT INTO metadata (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, encode_value(value), utc_now()),
        )
        connection.commit()


def set_guild_setting(guild_id, key, value):
    init_database()
    guild_id = str(guild_id)

    with _LOCK, connect() as connection:
        if value is None:
            connection.execute(
                "DELETE FROM guild_settings WHERE guild_id = ? AND key = ?",
                (guild_id, key),
            )
        else:
            connection.execute(
                """
                INSERT INTO guild_settings (guild_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (guild_id, key, encode_value(value), utc_now()),
            )
        connection.commit()


def update_guild_settings_db(guild_id, **changes):
    for key, value in changes.items():
        set_guild_setting(guild_id, key, value)
    return get_guild_settings_db(guild_id)


def delete_guild_settings_db(guild_id):
    init_database()
    with _LOCK, connect() as connection:
        connection.execute("DELETE FROM guild_settings WHERE guild_id = ?", (str(guild_id),))
        connection.commit()


def get_guild_settings_db(guild_id):
    init_database()
    guild_id = str(guild_id)
    with _LOCK, connect() as connection:
        rows = connection.execute(
            "SELECT key, value FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
    return {row["key"]: decode_value(row["value"]) for row in rows}


def get_all_guild_settings_db():
    init_database()
    with _LOCK, connect() as connection:
        rows = connection.execute(
            "SELECT guild_id, key, value FROM guild_settings ORDER BY guild_id, key"
        ).fetchall()

    settings = {}
    for row in rows:
        guild_settings = settings.setdefault(row["guild_id"], {})
        guild_settings[row["key"]] = decode_value(row["value"])
    return settings


def migrate_legacy_settings_json():
    """Import old data/settings.json once, keeping the JSON file as backup."""
    init_database()
    if get_metadata("legacy_settings_json_migrated"):
        return

    if not LEGACY_SETTINGS_FILE.exists():
        set_metadata("legacy_settings_json_migrated", True)
        return

    try:
        legacy_settings = json.loads(LEGACY_SETTINGS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        set_metadata("legacy_settings_json_migrated", "invalid_json_skipped")
        return

    if isinstance(legacy_settings, dict):
        for guild_id, guild_settings in legacy_settings.items():
            if not isinstance(guild_settings, dict):
                continue
            update_guild_settings_db(guild_id, **guild_settings)

    set_metadata("legacy_settings_json_migrated", True)


def load_legacy_json(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_voice_store(store, data):
    init_database()
    now = utc_now()
    with _LOCK, connect() as connection:
        connection.execute(
            """
            INSERT INTO voice_state (store, payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(store) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (str(store), encode_value(data if data is not None else {}), now),
        )
        connection.commit()


def migrate_legacy_voice_json(store):
    init_database()
    marker = f"legacy_{store}_json_migrated"
    if get_metadata(marker):
        return

    legacy_path = VOICE_STORE_FILES.get(store)
    if legacy_path and legacy_path.exists():
        legacy = load_legacy_json(legacy_path)
        if legacy:
            save_voice_store(store, legacy)
    set_metadata(marker, True)


def load_voice_store(store, default=None):
    migrate_legacy_voice_json(store)
    with _LOCK, connect() as connection:
        row = connection.execute("SELECT payload FROM voice_state WHERE store = ?", (str(store),)).fetchone()
    if row is None:
        return {} if default is None else default
    value = decode_value(row["payload"])
    return value if value is not None else ({} if default is None else default)


def add_voice_seconds(guild_id, user_id, buckets, *, sessions=0):
    """Add ``(month, seconds)`` pieces to one member's running voice total.

    ``sessions`` is credited to the first bucket only: one stretch of voice
    time is one session even when it straddles a month boundary, and counting
    it in both would make the totals disagree with themselves.
    """
    init_database()
    rows = [(str(month), float(seconds)) for month, seconds in (buckets or []) if seconds > 0]
    if not rows:
        return

    now = utc_now()
    with _LOCK, connect() as connection:
        for index, (month, seconds) in enumerate(rows):
            connection.execute(
                """
                INSERT INTO voice_minutes (guild_id, user_id, month, seconds, sessions, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id, month) DO UPDATE SET
                    seconds = voice_minutes.seconds + excluded.seconds,
                    sessions = voice_minutes.sessions + excluded.sessions,
                    updated_at = excluded.updated_at
                """,
                (
                    str(guild_id),
                    str(user_id),
                    month,
                    seconds,
                    int(sessions) if index == 0 else 0,
                    now,
                ),
            )
        connection.commit()


def voice_month_total(guild_id, user_id, month):
    """One member's ``{"seconds", "sessions"}`` for one month. Never ``None``:
    a member with no voice time has a real answer, and it is zero."""
    init_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT seconds, sessions FROM voice_minutes"
            " WHERE guild_id = ? AND user_id = ? AND month = ?",
            (str(guild_id), str(user_id), str(month)),
        ).fetchone()
    if not row:
        return {"seconds": 0.0, "sessions": 0}
    return {"seconds": float(row["seconds"] or 0), "sessions": int(row["sessions"] or 0)}


def voice_month_leaderboard(guild_id, month, limit=10):
    """The month's most active members, busiest first."""
    init_database()
    with connect() as connection:
        rows = connection.execute(
            "SELECT user_id, seconds, sessions FROM voice_minutes"
            " WHERE guild_id = ? AND month = ? AND seconds > 0"
            " ORDER BY seconds DESC LIMIT ?",
            (str(guild_id), str(month), int(limit)),
        ).fetchall()
    return [
        {
            "user_id": row["user_id"],
            "seconds": float(row["seconds"] or 0),
            "sessions": int(row["sessions"] or 0),
        }
        for row in rows
    ]


def voice_member_history(guild_id, user_id, limit=6):
    """A member's recent months, newest first, for the trend line on /vh."""
    init_database()
    with connect() as connection:
        rows = connection.execute(
            "SELECT month, seconds, sessions FROM voice_minutes"
            " WHERE guild_id = ? AND user_id = ?"
            " ORDER BY month DESC LIMIT ?",
            (str(guild_id), str(user_id), int(limit)),
        ).fetchall()
    return [
        {
            "month": row["month"],
            "seconds": float(row["seconds"] or 0),
            "sessions": int(row["sessions"] or 0),
        }
        for row in rows
    ]


def voice_month_summary(guild_id, month):
    """Server-wide totals for the month, so /vh can say where a member stands."""
    init_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS members, COALESCE(SUM(seconds), 0) AS seconds"
            " FROM voice_minutes WHERE guild_id = ? AND month = ? AND seconds > 0",
            (str(guild_id), str(month)),
        ).fetchone()
    return {"members": int(row["members"] or 0), "seconds": float(row["seconds"] or 0)}


def voice_month_rank(guild_id, user_id, month):
    """Where a member sits in the month, or ``None`` if they have no time yet."""
    init_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT seconds FROM voice_minutes"
            " WHERE guild_id = ? AND user_id = ? AND month = ?",
            (str(guild_id), str(user_id), str(month)),
        ).fetchone()
        if not row or not float(row["seconds"] or 0):
            return None
        ahead = connection.execute(
            "SELECT COUNT(*) AS ahead FROM voice_minutes"
            " WHERE guild_id = ? AND month = ? AND seconds > ?",
            (str(guild_id), str(month), float(row["seconds"])),
        ).fetchone()
    return int(ahead["ahead"] or 0) + 1


def get_voice_store_status():
    init_database()
    with _LOCK, connect() as connection:
        rows = connection.execute("SELECT store, payload, updated_at FROM voice_state ORDER BY store").fetchall()

    status = {}
    for row in rows:
        payload = decode_value(row["payload"])
        if isinstance(payload, dict):
            guild_count = len(payload)
            item_count = sum(len(value) if isinstance(value, (dict, list)) else 1 for value in payload.values())
        elif isinstance(payload, list):
            guild_count = 0
            item_count = len(payload)
        else:
            guild_count = 0
            item_count = 0
        status[row["store"]] = {
            "updated_at": row["updated_at"],
            "guild_count": guild_count,
            "item_count": item_count,
        }
    return status


def save_levels_data(data):
    init_database()
    now = utc_now()
    with _LOCK, connect() as connection:
        connection.execute("DELETE FROM level_records")
        for guild_id, guild_data in (data or {}).items():
            if not isinstance(guild_data, dict):
                continue
            for user_id, record in guild_data.items():
                if not isinstance(record, dict):
                    continue
                connection.execute(
                    """
                    INSERT INTO level_records (guild_id, user_id, xp, messages, last_gain, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(guild_id),
                        str(user_id),
                        int(record.get("xp", 0) or 0),
                        int(record.get("messages", 0) or 0),
                        record.get("last_gain"),
                        now,
                    ),
                )
        connection.commit()


def upsert_level_records(rows):
    """Write only the given ``(guild_id, user_id, record)`` rows.

    The hot path: the Levels cog tracks which members changed and flushes just
    those rows, instead of rewriting every guild's records via save_levels_data
    (which stays for migration and full rebuilds).
    """
    init_database()
    now = utc_now()
    with _LOCK, connect() as connection:
        for guild_id, user_id, record in rows:
            connection.execute(
                """
                INSERT INTO level_records (guild_id, user_id, xp, messages, last_gain, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    xp = excluded.xp,
                    messages = excluded.messages,
                    last_gain = excluded.last_gain,
                    updated_at = excluded.updated_at
                """,
                (
                    str(guild_id),
                    str(user_id),
                    int(record.get("xp", 0) or 0),
                    int(record.get("messages", 0) or 0),
                    record.get("last_gain"),
                    now,
                ),
            )
        connection.commit()


def migrate_legacy_levels_json():
    init_database()
    if get_metadata("legacy_levels_json_migrated"):
        return
    legacy = load_legacy_json(LEGACY_LEVELS_FILE)
    if legacy:
        save_levels_data(legacy)
    set_metadata("legacy_levels_json_migrated", True)


def load_levels_data():
    migrate_legacy_levels_json()
    with _LOCK, connect() as connection:
        rows = connection.execute(
            "SELECT guild_id, user_id, xp, messages, last_gain FROM level_records"
        ).fetchall()

    data = {}
    for row in rows:
        guild_data = data.setdefault(row["guild_id"], {})
        guild_data[row["user_id"]] = {
            "xp": int(row["xp"] or 0),
            "messages": int(row["messages"] or 0),
            "last_gain": row["last_gain"],
        }
    return data


# Wallet keys that have their own column. Everything else a wallet carries -
# effects, titles, shields - goes into the extras blob, so the shop can grow
# without a schema change every time.
_WALLET_COLUMNS = ("coins", "daily_streak", "last_daily", "last_work", "trophies")


def _wallet_extras(wallet):
    return encode_value(
        {key: value for key, value in wallet.items() if key not in _WALLET_COLUMNS}
    )


def save_economy_data(data):
    init_database()
    now = utc_now()
    with _LOCK, connect() as connection:
        connection.execute("DELETE FROM economy_wallets")
        for guild_id, guild_data in (data or {}).items():
            if not isinstance(guild_data, dict):
                continue
            for user_id, wallet in guild_data.items():
                if not isinstance(wallet, dict):
                    continue
                connection.execute(
                    """
                    INSERT INTO economy_wallets (
                        guild_id, user_id, coins, daily_streak, last_daily, last_work,
                        trophies, extras, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(guild_id),
                        str(user_id),
                        int(wallet.get("coins", 0) or 0),
                        int(wallet.get("daily_streak", 0) or 0),
                        wallet.get("last_daily"),
                        wallet.get("last_work"),
                        encode_value(wallet.get("trophies", [])),
                        _wallet_extras(wallet),
                        now,
                    ),
                )
        connection.commit()


def upsert_economy_wallets(rows):
    """Write only the given ``(guild_id, user_id, wallet)`` rows.

    Same shape as upsert_level_records: the Economy cog flushes changed wallets
    row by row; save_economy_data stays for migration and full rebuilds.
    """
    init_database()
    now = utc_now()
    with _LOCK, connect() as connection:
        for guild_id, user_id, wallet in rows:
            connection.execute(
                """
                INSERT INTO economy_wallets (
                    guild_id, user_id, coins, daily_streak, last_daily, last_work,
                    trophies, extras, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    coins = excluded.coins,
                    daily_streak = excluded.daily_streak,
                    last_daily = excluded.last_daily,
                    last_work = excluded.last_work,
                    trophies = excluded.trophies,
                    extras = excluded.extras,
                    updated_at = excluded.updated_at
                """,
                (
                    str(guild_id),
                    str(user_id),
                    int(wallet.get("coins", 0) or 0),
                    int(wallet.get("daily_streak", 0) or 0),
                    wallet.get("last_daily"),
                    wallet.get("last_work"),
                    encode_value(wallet.get("trophies", [])),
                    _wallet_extras(wallet),
                    now,
                ),
            )
        connection.commit()


def migrate_legacy_economy_json():
    init_database()
    if get_metadata("legacy_economy_json_migrated"):
        return
    legacy = load_legacy_json(LEGACY_ECONOMY_FILE)
    if legacy:
        save_economy_data(legacy)
    set_metadata("legacy_economy_json_migrated", True)


def load_economy_data():
    migrate_legacy_economy_json()
    with _LOCK, connect() as connection:
        rows = connection.execute(
            """
            SELECT guild_id, user_id, coins, daily_streak, last_daily, last_work, trophies, extras
            FROM economy_wallets
            """
        ).fetchall()

    data = {}
    for row in rows:
        guild_data = data.setdefault(row["guild_id"], {})
        extras = decode_value(row["extras"])
        guild_data[row["user_id"]] = {
            "coins": int(row["coins"] or 0),
            "daily_streak": int(row["daily_streak"] or 0),
            "last_daily": row["last_daily"],
            "last_work": row["last_work"],
            "trophies": decode_value(row["trophies"]) or [],
            # Wallets written before the shop grew have no extras, and a
            # corrupt blob must not take the whole economy down with it.
            **(extras if isinstance(extras, dict) else {}),
        }
    return data


# ── music cache ──────────────────────────────────────────────────────
#
# Search results and track metadata, keyed by a normalised query or URL.
# Purely an optimisation: any entry may vanish without affecting correctness,
# which is why expiry is checked on read instead of swept on a schedule.


def cache_put(key, payload, ttl_seconds):
    init_database()
    expires_at = time.time() + ttl_seconds
    with _LOCK, connect() as connection:
        connection.execute(
            """
            INSERT INTO music_cache (key, payload, expires_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                payload = excluded.payload,
                expires_at = excluded.expires_at
            """,
            (str(key), encode_value(payload), expires_at),
        )
        connection.commit()


def cache_get(key):
    init_database()
    with _LOCK, connect() as connection:
        row = connection.execute(
            "SELECT payload, expires_at FROM music_cache WHERE key = ?", (str(key),)
        ).fetchone()
    if row is None or row["expires_at"] < time.time():
        return None
    return decode_value(row["payload"])


def cache_prefix_search(prefix, limit):
    """Live entries whose key starts with ``prefix``, newest expiry first.

    Backs autocomplete, which must answer inside Discord's three seconds and
    so can never reach for yt-dlp. LIKE wildcards in the user's text are
    escaped: a query containing ``%`` would otherwise match everything.
    """
    init_database()
    escaped = str(prefix).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with _LOCK, connect() as connection:
        rows = connection.execute(
            """
            SELECT key, payload FROM music_cache
            WHERE key LIKE ? ESCAPE '\\' AND expires_at >= ?
            ORDER BY expires_at DESC LIMIT ?
            """,
            (escaped + "%", time.time(), int(limit)),
        ).fetchall()
    return [(row["key"], decode_value(row["payload"])) for row in rows]


def cache_purge_expired():
    init_database()
    with _LOCK, connect() as connection:
        cursor = connection.execute("DELETE FROM music_cache WHERE expires_at < ?", (time.time(),))
        connection.commit()
        return cursor.rowcount
