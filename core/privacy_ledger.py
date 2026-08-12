"""Pseudonymous deletion ledger and restore-time privacy enforcement.

Backups intentionally outlive some live records.  The ledger stays outside
those backups and remembers deletions as keyed hashes, so restoring an older
snapshot cannot silently resurrect a user or guild that was erased later.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .config import BASE_DIR
from .secure_files import encryption_secret


LEDGER_PATH = BASE_DIR / ".privacy_deletions.json"
REMOTE_LEDGER_PATH = "privacy/deletion-ledger.json.ngbackup"
LEDGER_VERSION = 1
_LOCK = threading.RLock()
_KINDS = {"user": "users", "guild": "guilds"}
_SUBJECT_FIELDS = {"user_id", "member_id", "participant_id"}
_REFERENCE_FIELDS = {
    "actor_id",
    "closed_by",
    "created_by",
    "host_id",
    "moderator_id",
    "opener_id",
    "winner_id",
}
_VERIFIER_MESSAGE = b"NovaGuard deletion ledger key verifier v1"
_SIGNATURE_MESSAGE = b"NovaGuard deletion ledger contents v1\0"


class PrivacyLedgerError(RuntimeError):
    """Raised when the deletion ledger is absent, invalid or cannot be applied."""


def _key_verifier(secret):
    return hmac.new(secret, _VERIFIER_MESSAGE, hashlib.sha256).hexdigest()


def _ledger_signature(payload, secret):
    signed = {key: value for key, value in payload.items() if key != "integrity"}
    canonical = json.dumps(
        signed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hmac.new(secret, _SIGNATURE_MESSAGE + canonical, hashlib.sha256).hexdigest()


def _seal_ledger(payload, secret):
    payload["key_verifier"] = _key_verifier(secret)
    payload["integrity"] = _ledger_signature(payload, secret)
    return payload


def _empty_ledger(secret):
    now = datetime.now(UTC).isoformat()
    return _seal_ledger({
        "version": LEDGER_VERSION,
        "created_at": now,
        "updated_at": now,
        "key_verifier": _key_verifier(secret),
        "users": {},
        "guilds": {},
    }, secret)


def _identifier_digest(kind, identifier, *, secret=None):
    if kind not in _KINDS:
        raise ValueError(f"Unsupported deletion kind: {kind}")
    identifier = str(identifier).strip()
    if not identifier:
        raise ValueError("Deletion identifier is required")
    secret = encryption_secret() if secret is None else bytes(secret)
    message = f"NovaGuard deletion ledger v1\0{kind}\0{identifier}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _validate_ledger(payload, *, secret=None):
    if not isinstance(payload, dict) or payload.get("version") != LEDGER_VERSION:
        raise PrivacyLedgerError("Deletion ledger has an unsupported format")
    verifier = payload.get("key_verifier")
    if not isinstance(verifier, str) or len(verifier) != 64:
        raise PrivacyLedgerError("Deletion ledger key verifier is missing or invalid")
    if secret is not None and not hmac.compare_digest(verifier, _key_verifier(secret)):
        raise PrivacyLedgerError("Deletion ledger does not match BACKUP_ENCRYPTION_KEY")
    integrity = payload.get("integrity")
    if not isinstance(integrity, str) or len(integrity) != 64:
        raise PrivacyLedgerError("Deletion ledger integrity signature is missing or invalid")
    if secret is not None and not hmac.compare_digest(
        integrity, _ledger_signature(payload, secret)
    ):
        raise PrivacyLedgerError("Deletion ledger integrity check failed")
    for collection in _KINDS.values():
        entries = payload.get(collection)
        if not isinstance(entries, dict):
            raise PrivacyLedgerError(f"Deletion ledger field {collection} is invalid")
        for digest, deleted_at in entries.items():
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or not isinstance(deleted_at, str)
            ):
                raise PrivacyLedgerError(f"Deletion ledger contains an invalid {collection} entry")
            try:
                datetime.fromisoformat(deleted_at.replace("Z", "+00:00"))
            except ValueError as error:
                raise PrivacyLedgerError(
                    f"Deletion ledger contains an invalid timestamp in {collection}"
                ) from error
    return payload


def load_deletion_ledger(path=None, *, require=False, secret=None):
    path = Path(path or LEDGER_PATH)
    secret = encryption_secret() if secret is None else bytes(secret)
    if not path.is_file():
        if require:
            raise PrivacyLedgerError(f"Deletion ledger does not exist: {path}")
        return _empty_ledger(secret)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PrivacyLedgerError(f"Deletion ledger cannot be read safely: {error}") from error
    return _validate_ledger(payload, secret=secret)


def _save_deletion_ledger(payload, path=None):
    path = Path(path or LEDGER_PATH)
    secret = encryption_secret()
    _seal_ledger(payload, secret)
    _validate_ledger(payload, secret=secret)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            json.dump(payload, output, indent=2, ensure_ascii=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return path


def ensure_deletion_ledger(path=None):
    """Create the independent ledger after proving its HMAC key is configured."""
    secret = encryption_secret()
    with _LOCK:
        path = Path(path or LEDGER_PATH)
        payload = load_deletion_ledger(path, secret=secret)
        if not path.exists():
            _save_deletion_ledger(payload, path)
    return payload


def record_deletion(kind, identifier, *, path=None, deleted_at=None):
    """Persist a deletion locally before any live records are changed."""
    digest = _identifier_digest(kind, identifier)
    path = Path(path or LEDGER_PATH)
    with _LOCK:
        payload = load_deletion_ledger(path)
        deleted_at = deleted_at or datetime.now(UTC).isoformat()
        payload[_KINDS[kind]][digest] = deleted_at
        payload["updated_at"] = deleted_at
        _save_deletion_ledger(payload, path)
    return {
        "kind": kind,
        "recorded_at": deleted_at,
        "ledger_path": str(path),
        "entries": sum(len(payload[name]) for name in _KINDS.values()),
    }


def sync_deletion_ledger(path=None):
    """Replace the encrypted off-site ledger without exposing raw identifiers."""
    payload = load_deletion_ledger(path, require=True)
    from .backups import upload_json_to_remote  # Avoid a module import cycle.

    return upload_json_to_remote(payload, REMOTE_LEDGER_PATH)


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _active_digests(ledger, collection, snapshot_created_at):
    snapshot_time = _parse_time(snapshot_created_at)
    if snapshot_time is None:
        return set(ledger[collection])
    return {
        digest
        for digest, deleted_at in ledger[collection].items()
        if (deletion_time := _parse_time(deleted_at)) is None or deletion_time > snapshot_time
    }


def _matcher(kind, digests, secret):
    def matches(value):
        if value is None:
            return False
        try:
            return _identifier_digest(kind, value, secret=secret) in digests
        except ValueError:
            return False

    return matches


def _table_exists(connection, table):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _column_exists(connection, table, column):
    return _table_exists(connection, table) and column in {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})")
    }


def _matching_values(connection, table, column, matches):
    if not _column_exists(connection, table, column):
        return []
    return [
        row[0]
        for row in connection.execute(
            f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL"
        )
        if matches(row[0])
    ]


def _delete_matches(connection, table, column, matches):
    removed = 0
    for value in _matching_values(connection, table, column, matches):
        removed += connection.execute(
            f"DELETE FROM {table} WHERE {column} = ?", (value,)
        ).rowcount
    return removed


def _null_matches(connection, table, column, matches, *, companion=None):
    changed = 0
    for value in _matching_values(connection, table, column, matches):
        assignments = f"{column} = NULL"
        if companion and _column_exists(connection, table, companion):
            assignments += f", {companion} = NULL"
        changed += connection.execute(
            f"UPDATE {table} SET {assignments} WHERE {column} = ?", (value,)
        ).rowcount
    return changed


def _scrub_user_tree(value, user_matches):
    removed = 0
    if isinstance(value, dict):
        if any(
            field in _SUBJECT_FIELDS and user_matches(item)
            for field, item in value.items()
        ):
            return None, 1, True
        result = {}
        for key, item in value.items():
            if user_matches(key):
                removed += 1
                continue
            if key in _REFERENCE_FIELDS and user_matches(item):
                result[key] = None
                removed += 1
                continue
            cleaned, count, drop = _scrub_user_tree(item, user_matches)
            removed += count
            if not drop:
                result[key] = cleaned
        return result, removed, False
    if isinstance(value, list):
        result = []
        for item in value:
            if not isinstance(item, (dict, list)) and user_matches(item):
                removed += 1
                continue
            cleaned, count, drop = _scrub_user_tree(item, user_matches)
            removed += count
            if not drop:
                result.append(cleaned)
        return result, removed, False
    return value, 0, False


def _scrub_sqlite(db_path, guild_matches, user_matches):
    counts = {}
    if not db_path.is_file():
        return counts
    connection = sqlite3.connect(db_path)
    try:
        for table in (
            "guild_settings",
            "level_records",
            "economy_wallets",
            "voice_minutes",
            "ticket_records",
            "role_panels",
            "web_audit",
        ):
            removed = _delete_matches(connection, table, "guild_id", guild_matches)
            if removed:
                counts[f"{table}.guild"] = removed

        for table in ("level_records", "economy_wallets", "voice_minutes", "web_sessions", "web_audit"):
            removed = _delete_matches(connection, table, "user_id", user_matches)
            if removed:
                counts[f"{table}.user"] = removed
        removed = _delete_matches(connection, "ticket_records", "opener_id", user_matches)
        if removed:
            counts["ticket_records.user"] = removed
        for table, column, companion in (
            ("ticket_records", "closed_by", None),
            ("role_panels", "created_by", None),
        ):
            changed = _null_matches(
                connection, table, column, user_matches, companion=companion
            )
            if changed:
                counts[f"{table}.anonymised"] = changed
        changed = 0
        for value in _matching_values(connection, "admin_audit", "actor_id", user_matches):
            changed += connection.execute(
                "UPDATE admin_audit SET actor_id = 'deleted-user', actor_name = NULL"
                " WHERE actor_id = ?",
                (value,),
            ).rowcount
        if changed:
            counts["admin_audit.anonymised"] = changed

        if _table_exists(connection, "voice_state"):
            changed = 0
            rows = connection.execute("SELECT store, payload FROM voice_state").fetchall()
            for store, raw_payload in rows:
                try:
                    payload = json.loads(raw_payload)
                except (TypeError, json.JSONDecodeError):
                    continue
                row_changed = 0
                if isinstance(payload, dict):
                    for key in list(payload):
                        if guild_matches(key):
                            payload.pop(key, None)
                            row_changed += 1
                payload, removed, _ = _scrub_user_tree(payload, user_matches)
                row_changed += removed
                if row_changed:
                    connection.execute(
                        "UPDATE voice_state SET payload = ? WHERE store = ?",
                        (json.dumps(payload, separators=(",", ":")), store),
                    )
                    changed += row_changed
            if changed:
                counts["voice_state"] = changed

        if _column_exists(connection, "web_sessions", "guilds_json"):
            changed = 0
            rows = connection.execute(
                "SELECT rowid, guilds_json FROM web_sessions"
            ).fetchall()
            for rowid, raw_payload in rows:
                try:
                    payload = json.loads(raw_payload)
                except (TypeError, json.JSONDecodeError):
                    continue
                original = copy.deepcopy(payload)
                if isinstance(payload, dict):
                    for key in list(payload):
                        if guild_matches(key):
                            payload.pop(key, None)
                elif isinstance(payload, list):
                    payload = [
                        item
                        for item in payload
                        if not (isinstance(item, dict) and guild_matches(item.get("id")))
                    ]
                if payload != original:
                    connection.execute(
                        "UPDATE web_sessions SET guilds_json = ? WHERE rowid = ?",
                        (json.dumps(payload, separators=(",", ":")), rowid),
                    )
                    changed += 1
            if changed:
                counts["web_sessions.guild_cache"] = changed
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise PrivacyLedgerError("Restored SQLite database failed integrity after privacy scrub")
    finally:
        connection.close()
    return counts


def _write_json(path, payload):
    temporary = path.with_name(f".{path.name}.privacy.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            json.dump(payload, output, indent=2, ensure_ascii=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _scrub_json_files(data_dir, guild_matches, user_matches):
    counts = {}
    for path in data_dir.glob("*.json") if data_dir.is_dir() else ():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        original = copy.deepcopy(payload)

        if path.name in {"settings.json", "levels.json", "economy.json", "warns.json"}:
            if isinstance(payload, dict):
                for guild_id in list(payload):
                    if guild_matches(guild_id):
                        payload.pop(guild_id, None)
                        continue
                    members = payload.get(guild_id)
                    if isinstance(members, dict) and path.name != "settings.json":
                        for user_id in list(members):
                            if user_matches(user_id):
                                members.pop(user_id, None)
                        if path.name == "warns.json":
                            for entries in members.values():
                                if not isinstance(entries, list):
                                    continue
                                for entry in entries:
                                    if isinstance(entry, dict) and user_matches(entry.get("moderator_id")):
                                        entry["moderator_id"] = None
        elif path.name in {"reminders.json", "giveaways.json"} and isinstance(payload, list):
            kept = []
            for entry in payload:
                if not isinstance(entry, dict):
                    kept.append(entry)
                    continue
                if guild_matches(entry.get("guild_id")) or user_matches(entry.get("user_id")):
                    continue
                if user_matches(entry.get("host_id")):
                    entry["host_id"] = None
                    entry["host_name"] = "Deleted member"
                for field in ("entrants", "winner_ids"):
                    if isinstance(entry.get(field), list):
                        entry[field] = [item for item in entry[field] if not user_matches(item)]
                kept.append(entry)
            payload = kept
        elif path.name.startswith("voice_"):
            if isinstance(payload, dict):
                for guild_id in list(payload):
                    if guild_matches(guild_id):
                        payload.pop(guild_id, None)
            payload, _, _ = _scrub_user_tree(payload, user_matches)

        if payload != original:
            _write_json(path, payload)
            counts[path.name] = 1
    return counts


def apply_deletion_ledger(
    restore_root,
    *,
    ledger_path=None,
    snapshot_created_at=None,
    secret=None,
):
    """Remove records deleted after the restored snapshot was created."""
    restore_root = Path(restore_root)
    secret = encryption_secret() if secret is None else bytes(secret)
    ledger = load_deletion_ledger(ledger_path, require=True, secret=secret)
    user_digests = _active_digests(ledger, "users", snapshot_created_at)
    guild_digests = _active_digests(ledger, "guilds", snapshot_created_at)
    user_matches = _matcher("user", user_digests, secret)
    guild_matches = _matcher("guild", guild_digests, secret)

    counts = _scrub_sqlite(
        restore_root / "data" / "novaguard.sqlite3", guild_matches, user_matches
    )
    counts.update(_scrub_json_files(restore_root / "data", guild_matches, user_matches))
    return {
        "snapshot_created_at": snapshot_created_at,
        "active_user_deletions": len(user_digests),
        "active_guild_deletions": len(guild_digests),
        "counts": counts,
        "removed_or_anonymised": sum(counts.values()),
    }
