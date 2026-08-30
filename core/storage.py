"""Persistence helpers.

Most simple feature data still lives in JSON. Guild setup/config, levels and
economy are backed by SQLite so they can be managed safely from Discord.
"""

import json
import os
import tempfile
import threading
from copy import deepcopy
from pathlib import Path

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
    """Write JSON atomically, owner-only, without a shared scratch filename.

    Three things this has to get right, and the previous version got none of
    them:

    * The temp file used to be `<name>.tmp` - one fixed path for every writer.
      Two concurrent saves of the same file therefore raced on it: measured
      over 30 paired writes, 12 raised FileNotFoundError at `os.replace`
      because the other thread had already consumed the temp file, and each
      of those is a silently lost write. `mkstemp` gives every writer its own.
    * The mode was whatever the umask allowed - 0644 in practice. These files
      hold moderation warnings, giveaway entrant lists and reminder text
      members typed, which is the same class of data `core/database.py` takes
      care to keep at 0600. The file descriptor is created with 0600 before
      anything is written, so there is no window where it is readable.
    * There was no `fsync`, so a power cut between write and rename could
      leave a zero-length file - which `load_json_file` then reads as "no
      state at all" rather than as damage.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_directory(path.parent)

    payload = json.dumps(data, indent=2)
    handle, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _restrict_directory(directory):
    """Keep the state directory owner-only. Best effort, as elsewhere."""
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass


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


# Guild settings sit on hot paths: automod reads them for every message, and the
# levels cog now does too. Each read was a locked SQLite query, which on a
# Raspberry Pi is the most expensive part of handling a message. Cache per guild.
#
# A plain in-process dict is safe because there is only one process: the web API
# runs inside the bot and writes through update_guild_settings, so there is no
# second writer to go stale against. Anything reaching into the database
# directly has to call invalidate_guild_settings_cache.
_SETTINGS_CACHE = {}
_SETTINGS_CACHE_LOCK = threading.Lock()


def invalidate_guild_settings_cache(guild_id=None):
    """Drop one guild's cached settings, or every guild's when given nothing."""
    with _SETTINGS_CACHE_LOCK:
        if guild_id is None:
            _SETTINGS_CACHE.clear()
        else:
            _SETTINGS_CACHE.pop(str(guild_id), None)


def get_guild_settings(guild_id):
    if not guild_id:
        return {}
    key = str(guild_id)
    with _SETTINGS_CACHE_LOCK:
        cached = _SETTINGS_CACHE.get(key)
    if cached is not None:
        # A copy, because callers treat the result as their own and some mutate
        # it. Handing back the cached object would let one caller's edit leak
        # into every later reader.
        return deepcopy(cached)

    migrate_legacy_settings_json()
    settings = default_guild_settings(guild_id)
    settings.update(get_guild_settings_db(guild_id))
    with _SETTINGS_CACHE_LOCK:
        _SETTINGS_CACHE[key] = deepcopy(settings)
    return settings


def update_guild_settings(guild_id, **changes):
    if not guild_id:
        return {}
    migrate_legacy_settings_json()
    update_guild_settings_db(guild_id, **changes)
    invalidate_guild_settings_cache(guild_id)
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
    invalidate_guild_settings_cache(guild_id)
    return get_guild_settings(guild_id)
