"""SQLite foundation for guild configuration.

Feature data can still live in JSON while server setup/config moves into a
proper database. This keeps the migration safe and incremental.
"""

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime

from .config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "novaguard.sqlite3"
LEGACY_SETTINGS_FILE = DATA_DIR / "settings.json"
LEGACY_LEVELS_FILE = DATA_DIR / "levels.json"
LEGACY_ECONOMY_FILE = DATA_DIR / "economy.json"

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
        connection.commit()
    _INITIALIZED = True


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
                        guild_id, user_id, coins, daily_streak, last_daily, last_work, trophies, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(guild_id),
                        str(user_id),
                        int(wallet.get("coins", 0) or 0),
                        int(wallet.get("daily_streak", 0) or 0),
                        wallet.get("last_daily"),
                        wallet.get("last_work"),
                        encode_value(wallet.get("trophies", [])),
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
            SELECT guild_id, user_id, coins, daily_streak, last_daily, last_work, trophies
            FROM economy_wallets
            """
        ).fetchall()

    data = {}
    for row in rows:
        guild_data = data.setdefault(row["guild_id"], {})
        guild_data[row["user_id"]] = {
            "coins": int(row["coins"] or 0),
            "daily_streak": int(row["daily_streak"] or 0),
            "last_daily": row["last_daily"],
            "last_work": row["last_work"],
            "trophies": decode_value(row["trophies"]) or [],
        }
    return data
