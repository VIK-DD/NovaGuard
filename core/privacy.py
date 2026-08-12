"""Privacy data inventory, export and erasure helpers.

The bot stores feature state in both SQLite and a few small JSON stores.  Data
subject requests must cover both; deleting only guild settings would leave XP,
voice, moderation and dashboard records behind.
"""

from __future__ import annotations

import copy
import os
import threading
from datetime import UTC, datetime, timedelta

from . import database, storage


_LOCK = threading.RLock()
_DELETED_ACTOR = "deleted-user"
_SUBJECT_ID_FIELDS = {"user_id", "member_id", "participant_id"}
_REFERENCE_ID_FIELDS = {
    "actor_id",
    "closed_by",
    "created_by",
    "host_id",
    "moderator_id",
    "opener_id",
    "winner_id",
}

RETENTION_DEFAULTS = {
    "PRIVACY_TICKET_KEEP_DAYS": 180,
    "PRIVACY_WARNING_KEEP_DAYS": 365,
    "PRIVACY_GIVEAWAY_KEEP_DAYS": 90,
    "PRIVACY_VOICE_KEEP_MONTHS": 13,
    "PRIVACY_ADMIN_AUDIT_KEEP_DAYS": 365,
    "PRIVACY_DASHBOARD_AUDIT_KEEP_DAYS": 90,
}


def _id(value) -> str:
    return str(value).strip()


def _json_path(name):
    return database.DATA_DIR / f"{name}.json"


def _load_json(name, default):
    return storage.load_json_file(_json_path(name), copy.deepcopy(default))


def _save_json(name, value):
    storage.save_json_file(_json_path(name), value)


def _table_exists(connection, table):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _rows(connection, query, params=()):
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def _decode_columns(rows, *columns):
    decoded = []
    for source in rows:
        row = dict(source)
        for column in columns:
            if column in row:
                row[column] = database.decode_value(row[column])
        decoded.append(row)
    return decoded


def _retention_value(env, name):
    try:
        value = int(str(env.get(name, RETENTION_DEFAULTS[name])).strip())
    except (TypeError, ValueError):
        return RETENTION_DEFAULTS[name]
    return max(1, min(value, 3650))


def retention_policy(env=None):
    """Return bounded retention settings without trusting malformed env input."""
    env = os.environ if env is None else env
    return {name: _retention_value(env, name) for name in RETENTION_DEFAULTS}


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _month_cutoff(now, keep_months):
    month_number = now.year * 12 + now.month - (keep_months - 1)
    year, zero_based_month = divmod(month_number - 1, 12)
    return f"{year:04d}-{zero_based_month + 1:02d}"


def _collect_user_references(value, user_id, path="$", matches=None):
    """Return only nested fragments that refer to ``user_id``.

    Voice state has several shapes (active sessions, queued reports and report
    history).  Keeping the path with each match makes the export useful without
    disclosing unrelated members from the same report.
    """
    matches = [] if matches is None else matches
    if isinstance(value, dict):
        if any(
            key in (_SUBJECT_ID_FIELDS | _REFERENCE_ID_FIELDS) and _id(item) == user_id
            for key, item in value.items()
            if item is not None
        ):
            matches.append({"path": path, "value": copy.deepcopy(value)})
            return matches
        for key, item in value.items():
            if _id(key) == user_id:
                matches.append({"path": f"{path}.{key}", "value": copy.deepcopy(item)})
            else:
                _collect_user_references(item, user_id, f"{path}.{key}", matches)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, (dict, list)) and _id(item) == user_id:
                matches.append({"path": f"{path}[{index}]", "value": copy.deepcopy(item)})
            else:
                _collect_user_references(item, user_id, f"{path}[{index}]", matches)
    return matches


def _scrub_user_references(value, user_id):
    """Remove a subject and anonymise references inside arbitrary state.

    The boolean return value tells a parent list/dict to remove an object whose
    primary subject is the deleted user.  References such as host/moderator are
    retained as ``None`` so other people's records remain structurally valid.
    """
    removed = 0
    if isinstance(value, dict):
        if any(
            key in _SUBJECT_ID_FIELDS and item is not None and _id(item) == user_id
            for key, item in value.items()
        ):
            return None, 1, True

        result = {}
        for key, item in value.items():
            if _id(key) == user_id:
                removed += 1
                continue
            if key in _REFERENCE_ID_FIELDS and item is not None and _id(item) == user_id:
                result[key] = None
                removed += 1
                continue
            cleaned, count, drop = _scrub_user_references(item, user_id)
            removed += count
            if not drop:
                result[key] = cleaned
        return result, removed, False

    if isinstance(value, list):
        result = []
        for item in value:
            if not isinstance(item, (dict, list)) and _id(item) == user_id:
                removed += 1
                continue
            cleaned, count, drop = _scrub_user_references(item, user_id)
            removed += count
            if not drop:
                result.append(cleaned)
        return result, removed, False

    return value, 0, False


def scrub_user_state(value, user_id):
    """Public runtime-cache counterpart to the persisted-state scrubber."""
    cleaned, removed, _ = _scrub_user_references(value, _id(user_id))
    return cleaned, removed


def _voice_payloads(connection):
    if not _table_exists(connection, "voice_state"):
        return {}
    return {
        row["store"]: database.decode_value(row["payload"])
        for row in connection.execute("SELECT store, payload FROM voice_state")
    }


def _export_json_user_data(user_id):
    warnings_as_subject = []
    warnings_as_moderator = []
    warns = _load_json("warns", {})
    if isinstance(warns, dict):
        for guild_id, members in warns.items():
            if not isinstance(members, dict):
                continue
            own = members.get(user_id)
            if isinstance(own, list):
                warnings_as_subject.append(
                    {
                        "guild_id": _id(guild_id),
                        "warnings": [
                            {key: value for key, value in entry.items() if key != "moderator_id"}
                            for entry in own if isinstance(entry, dict)
                        ],
                    }
                )
            for entries in members.values():
                if not isinstance(entries, list):
                    continue
                issued = [
                    entry for entry in entries
                    if isinstance(entry, dict) and _id(entry.get("moderator_id")) == user_id
                ]
                if issued:
                    warnings_as_moderator.append(
                        {
                            "guild_id": _id(guild_id),
                            "warnings": [
                                {key: value for key, value in entry.items() if key != "moderator_id"}
                                for entry in issued
                            ],
                        }
                    )

    reminders = [
        item for item in _load_json("reminders", [])
        if isinstance(item, dict) and _id(item.get("user_id")) == user_id
    ]
    giveaways = []
    for entry in _load_json("giveaways", []):
        if not isinstance(entry, dict):
            continue
        hosted = _id(entry.get("host_id")) == user_id
        entered = any(_id(member_id) == user_id for member_id in entry.get("entrants", []))
        won = any(_id(member_id) == user_id for member_id in entry.get("winner_ids", []))
        if hosted or entered or won:
            giveaways.append(
                {
                    key: copy.deepcopy(entry[key])
                    for key in (
                        "guild_id",
                        "message_id",
                        "channel_id",
                        "prize",
                        "winners",
                        "ends_at",
                        "ended",
                    )
                    if key in entry
                }
                | {
                    "relationship": {"hosted": hosted, "entered": entered, "won": won},
                    "entrant_count": len(entry.get("entrants", [])),
                }
            )

    return {
        "warnings_received": warnings_as_subject,
        "warnings_issued": warnings_as_moderator,
        "reminders": reminders,
        "giveaways": giveaways,
    }


def export_user_data(user_id):
    """Export every live NovaGuard record that can be tied to one Discord ID.

    OAuth secrets and session hashes are deliberately excluded.  The export
    contains the profile/cache metadata held for the user, never credentials.
    """
    user_id = _id(user_id)
    if not user_id:
        raise ValueError("user_id is required")

    database.init_database()
    with _LOCK, database.connect() as connection:
        levels = _rows(connection, "SELECT * FROM level_records WHERE user_id = ?", (user_id,))
        economy = _decode_columns(
            _rows(connection, "SELECT * FROM economy_wallets WHERE user_id = ?", (user_id,)),
            "trophies",
            "extras",
        )
        voice = _rows(connection, "SELECT * FROM voice_minutes WHERE user_id = ?", (user_id,))
        ticket_rows = _rows(
            connection,
            "SELECT * FROM ticket_records WHERE opener_id = ? OR closed_by = ?",
            (user_id, user_id),
        )
        tickets = []
        for row in ticket_rows:
            if _id(row.get("opener_id")) == user_id:
                tickets.append(
                    {key: value for key, value in row.items() if key != "closed_by"}
                    | {"relationship": "opened"}
                )
            else:
                tickets.append(
                    {
                        key: row[key]
                        for key in (
                            "thread_id",
                            "guild_id",
                            "parent_channel_id",
                            "created_at",
                            "closed_at",
                        )
                    }
                    | {"relationship": "closed"}
                )
        role_panels = _decode_columns(
            _rows(connection, "SELECT * FROM role_panels WHERE created_by = ?", (user_id,)),
            "role_ids",
        )
        admin_audit = _rows(
            connection,
            "SELECT created_at, actor_id, actor_name, action, outcome"
            " FROM admin_audit WHERE actor_id = ? ORDER BY id",
            (user_id,),
        )

        dashboard_sessions = []
        if _table_exists(connection, "web_sessions"):
            session_rows = _rows(
                connection,
                "SELECT user_json, guilds_json, created_at, expires_at, last_seen_at"
                " FROM web_sessions WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            )
            dashboard_sessions = _decode_columns(session_rows, "user_json", "guilds_json")
        dashboard_audit = []
        if _table_exists(connection, "web_audit"):
            dashboard_audit = _decode_columns(
                _rows(
                    connection,
                    "SELECT guild_id, user_id, username, action, changes_json, ip, created_at"
                    " FROM web_audit WHERE user_id = ? ORDER BY id",
                    (user_id,),
                ),
                "changes_json",
            )

        voice_state = {}
        for store_name, payload in _voice_payloads(connection).items():
            matches = _collect_user_references(payload, user_id)
            if matches:
                voice_state[store_name] = matches

    json_data = _export_json_user_data(user_id)
    payload = {
        "user_id": user_id,
        "exported_at": database.utc_now(),
        "levels": levels,
        "economy": economy,
        "voice_minutes": voice,
        "voice_state": voice_state,
        "tickets": tickets,
        "role_panels_created": role_panels,
        "admin_audit": admin_audit,
        "dashboard_sessions": dashboard_sessions,
        "dashboard_audit": dashboard_audit,
        **json_data,
    }
    payload["counts"] = {
        key: len(value) if isinstance(value, list) else sum(len(items) for items in value.values())
        for key, value in payload.items()
        if key not in {"user_id", "exported_at", "counts"} and isinstance(value, (list, dict))
    }
    return payload


def export_guild_data(guild_id):
    """Extend the existing per-guild export with every privacy-relevant store."""
    guild_id = _id(guild_id)
    if not guild_id:
        raise ValueError("guild_id is required")

    payload = database.export_guild_data(guild_id)
    with _LOCK, database.connect() as connection:
        voice_state = {
            store_name: copy.deepcopy(store_payload.get(guild_id))
            for store_name, store_payload in _voice_payloads(connection).items()
            if isinstance(store_payload, dict) and guild_id in store_payload
        }
        dashboard_audit = []
        if _table_exists(connection, "web_audit"):
            dashboard_audit = _decode_columns(
                _rows(
                    connection,
                    "SELECT user_id, username, action, changes_json, ip, created_at"
                    " FROM web_audit WHERE guild_id = ? ORDER BY id",
                    (guild_id,),
                ),
                "changes_json",
            )

    warns = _load_json("warns", {})
    reminders = _load_json("reminders", [])
    payload["warnings"] = copy.deepcopy(warns.get(guild_id, {})) if isinstance(warns, dict) else {}
    payload["reminders"] = [
        item for item in reminders
        if isinstance(item, dict) and _id(item.get("guild_id")) == guild_id
    ] if isinstance(reminders, list) else []
    payload["voice_state"] = voice_state
    payload["dashboard_audit"] = dashboard_audit
    payload["counts"].update(
        {
            "warnings": sum(len(items) for items in payload["warnings"].values()),
            "reminders": len(payload["reminders"]),
            "voice_state": len(voice_state),
            "dashboard_audit": len(dashboard_audit),
        }
    )
    return payload


def _erase_json_user_data(user_id):
    counts = {"warnings": 0, "reminders": 0, "giveaways": 0, "legacy": 0}

    warns = _load_json("warns", {})
    if isinstance(warns, dict):
        for guild_id in list(warns):
            members = warns.get(guild_id)
            if not isinstance(members, dict):
                continue
            counts["warnings"] += len(members.pop(user_id, []))
            for entries in members.values():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, dict) and _id(entry.get("moderator_id")) == user_id:
                        entry["moderator_id"] = None
                        counts["warnings"] += 1
            if not members:
                warns.pop(guild_id, None)
        _save_json("warns", warns)

    reminders = _load_json("reminders", [])
    if isinstance(reminders, list):
        kept = [
            item for item in reminders
            if not (isinstance(item, dict) and _id(item.get("user_id")) == user_id)
        ]
        counts["reminders"] = len(reminders) - len(kept)
        _save_json("reminders", kept)

    giveaways = _load_json("giveaways", [])
    if isinstance(giveaways, list):
        for entry in giveaways:
            if not isinstance(entry, dict):
                continue
            if _id(entry.get("host_id")) == user_id:
                entry["host_id"] = None
                entry["host_name"] = "Deleted member"
                counts["giveaways"] += 1
            for field in ("entrants", "winner_ids"):
                values = entry.get(field)
                if isinstance(values, list):
                    filtered = [value for value in values if _id(value) != user_id]
                    counts["giveaways"] += len(values) - len(filtered)
                    entry[field] = filtered
        _save_json("giveaways", giveaways)

    for name in ("levels", "economy"):
        legacy = _load_json(name, {})
        if not isinstance(legacy, dict):
            continue
        changed = False
        for members in legacy.values():
            if isinstance(members, dict) and user_id in members:
                members.pop(user_id, None)
                counts["legacy"] += 1
                changed = True
        if changed:
            _save_json(name, legacy)
    return counts


def erase_user_data(user_id):
    """Erase one Discord user's data without deleting other members' records."""
    user_id = _id(user_id)
    if not user_id:
        raise ValueError("user_id is required")

    database.init_database()
    counts = {}
    with _LOCK, database._LOCK, database.connect() as connection:
        for label, query, params in (
            ("levels", "DELETE FROM level_records WHERE user_id = ?", (user_id,)),
            ("economy", "DELETE FROM economy_wallets WHERE user_id = ?", (user_id,)),
            ("voice_minutes", "DELETE FROM voice_minutes WHERE user_id = ?", (user_id,)),
            ("tickets_opened", "DELETE FROM ticket_records WHERE opener_id = ?", (user_id,)),
            ("role_panels", "UPDATE role_panels SET created_by = NULL WHERE created_by = ?", (user_id,)),
            ("tickets_closed", "UPDATE ticket_records SET closed_by = NULL WHERE closed_by = ?", (user_id,)),
        ):
            counts[label] = connection.execute(query, params).rowcount

        counts["admin_audit"] = connection.execute(
            "UPDATE admin_audit SET actor_id = ?, actor_name = NULL WHERE actor_id = ?",
            (_DELETED_ACTOR, user_id),
        ).rowcount
        if _table_exists(connection, "web_sessions"):
            counts["dashboard_sessions"] = connection.execute(
                "DELETE FROM web_sessions WHERE user_id = ?", (user_id,)
            ).rowcount
        if _table_exists(connection, "web_audit"):
            counts["dashboard_audit"] = connection.execute(
                "DELETE FROM web_audit WHERE user_id = ?", (user_id,)
            ).rowcount

        voice_count = 0
        for store_name, payload in _voice_payloads(connection).items():
            cleaned, removed, _ = _scrub_user_references(payload, user_id)
            if removed:
                connection.execute(
                    "UPDATE voice_state SET payload = ?, updated_at = ? WHERE store = ?",
                    (database.encode_value(cleaned), database.utc_now(), store_name),
                )
                voice_count += removed
        counts["voice_state"] = voice_count
        connection.commit()

    counts.update(_erase_json_user_data(user_id))
    return {"user_id": user_id, "erased_at": database.utc_now(), "counts": counts}


def erase_guild_data(guild_id):
    """Delete all live data scoped to a guild and leave other guilds intact."""
    guild_id = _id(guild_id)
    if not guild_id:
        raise ValueError("guild_id is required")

    database.init_database()
    counts = {}
    with _LOCK, database._LOCK, database.connect() as connection:
        for table in (
            "guild_settings",
            "level_records",
            "economy_wallets",
            "voice_minutes",
            "ticket_records",
            "role_panels",
        ):
            counts[table] = connection.execute(
                f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,)
            ).rowcount
        if _table_exists(connection, "web_audit"):
            counts["dashboard_audit"] = connection.execute(
                "DELETE FROM web_audit WHERE guild_id = ?", (guild_id,)
            ).rowcount

        voice_count = 0
        for store_name, payload in _voice_payloads(connection).items():
            if isinstance(payload, dict) and guild_id in payload:
                payload.pop(guild_id, None)
                connection.execute(
                    "UPDATE voice_state SET payload = ?, updated_at = ? WHERE store = ?",
                    (database.encode_value(payload), database.utc_now(), store_name),
                )
                voice_count += 1
        counts["voice_state"] = voice_count
        connection.commit()

    warns = _load_json("warns", {})
    if isinstance(warns, dict):
        counts["warnings"] = len(warns.pop(guild_id, {}))
        _save_json("warns", warns)

    for name in ("reminders", "giveaways"):
        entries = _load_json(name, [])
        if not isinstance(entries, list):
            continue
        kept = [
            entry for entry in entries
            if not (isinstance(entry, dict) and _id(entry.get("guild_id")) == guild_id)
        ]
        counts[name] = len(entries) - len(kept)
        _save_json(name, kept)

    legacy_count = 0
    for name in ("settings", "levels", "economy"):
        legacy = _load_json(name, {})
        if isinstance(legacy, dict) and guild_id in legacy:
            legacy.pop(guild_id, None)
            _save_json(name, legacy)
            legacy_count += 1
    counts["legacy"] = legacy_count

    storage.invalidate_guild_settings_cache(guild_id)
    return {"guild_id": guild_id, "erased_at": database.utc_now(), "counts": counts}


def run_retention_cleanup(*, now=None, env=None):
    """Delete expired operational records according to the public policy.

    Cumulative XP and economy balances intentionally have no time-based expiry:
    they remain useful while a server keeps the feature enabled, and the
    explicit user/guild erasure paths remove them on request.
    """
    now = now or datetime.now(UTC)
    now = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    policy = retention_policy(env)
    counts = {}

    cutoffs = {
        "tickets": now - timedelta(days=policy["PRIVACY_TICKET_KEEP_DAYS"]),
        "admin_audit": now - timedelta(days=policy["PRIVACY_ADMIN_AUDIT_KEEP_DAYS"]),
        "dashboard_audit": now - timedelta(
            days=policy["PRIVACY_DASHBOARD_AUDIT_KEEP_DAYS"]
        ),
    }
    voice_cutoff = _month_cutoff(now, policy["PRIVACY_VOICE_KEEP_MONTHS"])

    database.init_database()
    with _LOCK, database._LOCK, database.connect() as connection:
        counts["tickets"] = connection.execute(
            "DELETE FROM ticket_records WHERE closed_at IS NOT NULL AND closed_at < ?",
            (cutoffs["tickets"].isoformat(),),
        ).rowcount
        counts["voice_months"] = connection.execute(
            "DELETE FROM voice_minutes WHERE month < ?", (voice_cutoff,)
        ).rowcount
        counts["admin_audit"] = connection.execute(
            "DELETE FROM admin_audit WHERE created_at < ?",
            (cutoffs["admin_audit"].isoformat(),),
        ).rowcount
        if _table_exists(connection, "web_sessions"):
            counts["dashboard_sessions"] = connection.execute(
                "DELETE FROM web_sessions WHERE expires_at < ?", (now.timestamp(),)
            ).rowcount
        if _table_exists(connection, "web_audit"):
            counts["dashboard_audit"] = connection.execute(
                "DELETE FROM web_audit WHERE created_at < ?",
                (cutoffs["dashboard_audit"].isoformat(),),
            ).rowcount
        connection.commit()

    warning_cutoff = now - timedelta(days=policy["PRIVACY_WARNING_KEEP_DAYS"])
    warnings = _load_json("warns", {})
    warning_count = 0
    if isinstance(warnings, dict):
        for guild_id in list(warnings):
            members = warnings.get(guild_id)
            if not isinstance(members, dict):
                warnings.pop(guild_id, None)
                warning_count += 1
                continue
            for user_id in list(members):
                entries = members.get(user_id)
                if not isinstance(entries, list):
                    members.pop(user_id, None)
                    warning_count += 1
                    continue
                kept = [
                    entry for entry in entries
                    if isinstance(entry, dict)
                    and (created_at := _parse_time(entry.get("created_at"))) is not None
                    and created_at >= warning_cutoff
                ]
                warning_count += len(entries) - len(kept)
                if kept:
                    members[user_id] = kept
                else:
                    members.pop(user_id, None)
            if not members:
                warnings.pop(guild_id, None)
        _save_json("warns", warnings)
    counts["warnings"] = warning_count

    giveaway_cutoff = now - timedelta(days=policy["PRIVACY_GIVEAWAY_KEEP_DAYS"])
    giveaways = _load_json("giveaways", [])
    if isinstance(giveaways, list):
        kept = []
        for entry in giveaways:
            if not isinstance(entry, dict):
                continue
            ended_at = _parse_time(entry.get("ends_at"))
            expired = bool(entry.get("ended")) and (ended_at is None or ended_at < giveaway_cutoff)
            if not expired:
                kept.append(entry)
        counts["giveaways"] = len(giveaways) - len(kept)
        _save_json("giveaways", kept)
    else:
        counts["giveaways"] = 0

    return {
        "cleaned_at": now.isoformat(),
        "policy": policy,
        "counts": counts,
    }
