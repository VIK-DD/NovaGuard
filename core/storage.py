"""Persistence helpers.

Most simple feature data still lives in JSON. Guild setup/config, levels and
economy are backed by SQLite so they can be managed safely from Discord.
"""

import json
import os

from .config import BASE_DIR, ERROR_LOG_CHANNEL_ID, GUILD_ID, github_config
from .database import (
    delete_guild_settings_db,
    get_all_guild_settings_db,
    get_guild_settings_db,
    migrate_legacy_settings_json,
    update_guild_settings_db,
)

DATA_DIR = BASE_DIR / "data"


def load_json_file(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def load_data(name, default):
    return load_json_file(DATA_DIR / f"{name}.json", default)


def save_data(name, data):
    save_json_file(DATA_DIR / f"{name}.json", data)


def default_guild_settings(guild_id):
    defaults = {}
    try:
        guild_id_int = int(guild_id)
    except (TypeError, ValueError):
        return defaults

    if GUILD_ID and guild_id_int == GUILD_ID:
        if github_config.update_channel_id:
            defaults["update_channel"] = github_config.update_channel_id
        if github_config.event_channel_id:
            defaults["github_event_channel"] = github_config.event_channel_id
        if ERROR_LOG_CHANNEL_ID:
            defaults["error_log_channel"] = ERROR_LOG_CHANNEL_ID
    return defaults


def get_guild_settings(guild_id):
    if not guild_id:
        return {}
    migrate_legacy_settings_json()
    settings = default_guild_settings(guild_id)
    settings.update(get_guild_settings_db(guild_id))
    return settings


def update_guild_settings(guild_id, **changes):
    if not guild_id:
        return {}
    migrate_legacy_settings_json()
    update_guild_settings_db(guild_id, **changes)
    return get_guild_settings(guild_id)


def all_guild_settings():
    migrate_legacy_settings_json()
    settings = get_all_guild_settings_db()
    if GUILD_ID:
        current = settings.setdefault(str(GUILD_ID), {})
        current.update({**default_guild_settings(GUILD_ID), **current})
    return settings


def reset_guild_settings(guild_id):
    if not guild_id:
        return {}
    migrate_legacy_settings_json()
    delete_guild_settings_db(guild_id)
    return get_guild_settings(guild_id)
