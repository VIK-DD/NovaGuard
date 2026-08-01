"""Safe backup helpers for NovaGuard state."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import BASE_DIR, GITHUB_STATE_FILE, UPDATE_STATE_FILE
from .database import DB_PATH, VOICE_STORE_FILES, init_database, load_voice_store
from .storage import DATA_DIR

BACKUP_DIR = BASE_DIR / "backups"
OFFSITE_STATE_FILENAME = "offsite_state.json"
MAX_BACKUPS = 10
MIN_BACKUP_BYTES = 200
RESTORE_CHECK_DIR = BACKUP_DIR / "restore-check"
BACKUP_PATTERNS = ("novaguard-backup-*.zip", "novaguard-full-*.zip")
DEFAULT_BACKUP_SCHEDULE = ((7, 0), (19, 0))


def env_int(name, default):
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def env_bool(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def remote_backup_config():
    destination = os.getenv("BACKUP_REMOTE_DEST", "").strip()
    return {
        "configured": bool(destination),
        "destination": destination,
        "full_prefix": os.getenv("BACKUP_REMOTE_FULL_PREFIX", "full").strip().strip("/"),
        "guild_prefix": os.getenv("BACKUP_REMOTE_GUILD_PREFIX", "guilds").strip().strip("/"),
        "full_keep_days": max(env_int("BACKUP_REMOTE_FULL_KEEP_DAYS", 90), 1),
        "guild_keep_days": max(env_int("BACKUP_REMOTE_GUILD_KEEP_DAYS", 60), 1),
        "retention_enabled": env_bool("BACKUP_REMOTE_RETENTION_ENABLED", True),
        "rclone_bin": os.getenv("BACKUP_RCLONE_BIN", "rclone").strip() or "rclone",
        "timeout_seconds": max(env_int("BACKUP_REMOTE_TIMEOUT_SECONDS", 300), 30),
    }


def parse_backup_schedule(raw_value):
    slots = []
    for item in (raw_value or "").split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        hour_text, minute_text = item.split(":", 1)
        try:
            hour = int(hour_text)
            minute = int(minute_text)
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            slots.append((hour, minute))
    return tuple(sorted(set(slots))) or DEFAULT_BACKUP_SCHEDULE


def backup_schedule():
    return parse_backup_schedule(os.getenv("BACKUP_SCHEDULE", "07:00,19:00"))


def backup_timezone_name():
    return os.getenv("BACKUP_TIMEZONE", "Europe/Chisinau").strip() or "Europe/Chisinau"


def backup_timezone():
    try:
        return ZoneInfo(backup_timezone_name())
    except ZoneInfoNotFoundError:
        return UTC


def backup_schedule_label():
    times = ", ".join(f"{hour:02d}:{minute:02d}" for hour, minute in backup_schedule())
    return f"{times} {backup_timezone_name()}"


def backup_max_expected_age_seconds():
    minutes = sorted(hour * 60 + minute for hour, minute in backup_schedule())
    if len(minutes) == 1:
        return 26 * 3600
    gaps = []
    for index, minute in enumerate(minutes):
        next_minute = minutes[(index + 1) % len(minutes)]
        gap = (next_minute - minute) % (24 * 60)
        gaps.append(gap or 24 * 60)
    return (max(gaps) * 60) + (2 * 3600)


def backup_timestamp(when=None):
    when = when or datetime.now(UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%d_%H-%M-%S")


def human_size(size):
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024


def backup_sqlite_to(path):
    init_database()
    source = sqlite3.connect(DB_PATH)
    target = sqlite3.connect(path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def add_if_exists(zip_file, source_path, archive_name):
    if source_path.exists():
        zip_file.write(source_path, archive_name)
        return True
    return False


def prune_old_backups():
    backups = sorted(iter_backup_paths(), key=lambda path: path.stat().st_mtime, reverse=True)
    for old_backup in backups[MAX_BACKUPS:]:
        try:
            old_backup.unlink()
        except OSError:
            pass


def iter_backup_paths():
    if not BACKUP_DIR.exists():
        return []
    paths = []
    for pattern in BACKUP_PATTERNS:
        paths.extend(BACKUP_DIR.glob(pattern))
    return sorted(set(paths), key=lambda path: path.stat().st_mtime, reverse=True)


def list_backups(limit=None):
    if not BACKUP_DIR.exists():
        return []

    backups = []
    for path in iter_backup_paths():
        stat = path.stat()
        backups.append(
            {
                "path": str(path),
                "name": path.name,
                "size": stat.st_size,
                "size_text": human_size(stat.st_size),
                "mtime": datetime.fromtimestamp(stat.st_mtime, UTC),
            }
        )
        if limit and len(backups) >= limit:
            break
    return backups


def latest_backup():
    backups = list_backups(limit=1)
    return backups[0] if backups else None


def offsite_state_file():
    return BACKUP_DIR / OFFSITE_STATE_FILENAME


def load_remote_backup_state():
    state_file = offsite_state_file()
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_remote_backup_state(state):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    state_file = offsite_state_file()
    tmp_path = state_file.with_name(state_file.name + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(tmp_path, state_file)


def update_remote_backup_state(**changes):
    state = load_remote_backup_state()
    state.update(changes)
    state["updated_at"] = datetime.now(UTC).isoformat()
    save_remote_backup_state(state)


def remote_backup_status(backup_name=None):
    config = remote_backup_config()
    state = load_remote_backup_state()
    latest = state.get("latest") if isinstance(state.get("latest"), dict) else {}
    latest_guild_exports = state.get("latest_guild_exports") if isinstance(state.get("latest_guild_exports"), dict) else {}
    return {
        "configured": config["configured"],
        "destination": config["destination"],
        "full_prefix": config["full_prefix"],
        "guild_prefix": config["guild_prefix"],
        "full_keep_days": config["full_keep_days"],
        "guild_keep_days": config["guild_keep_days"],
        "retention_enabled": config["retention_enabled"],
        "latest": latest,
        "latest_guild_exports": latest_guild_exports,
        "latest_retention": state.get("latest_retention") if isinstance(state.get("latest_retention"), dict) else {},
        "latest_remote_check": state.get("latest_remote_check") if isinstance(state.get("latest_remote_check"), dict) else {},
        "matches_backup": bool(backup_name and latest.get("backup_name") == backup_name),
    }


def remote_join(destination, relative_path):
    relative_path = str(relative_path or "").strip("/")
    if not relative_path:
        return destination
    separator = "" if destination.endswith(("/", ":")) else "/"
    return f"{destination}{separator}{relative_path}"


def remote_full_backup_path(backup_path, created_at=None):
    config = remote_backup_config()
    created_at = created_at or datetime.now(UTC)
    parts = [
        config["full_prefix"],
        created_at.astimezone(UTC).strftime("%Y"),
        created_at.astimezone(UTC).strftime("%m"),
        Path(backup_path).name,
    ]
    return "/".join(part for part in parts if part)


def sanitize_remote_segment(value, fallback="unknown"):
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text[:80] or fallback


def guild_export_relative_path(guild_id, guild_name, created_at=None):
    config = remote_backup_config()
    created_at = created_at or datetime.now(UTC)
    folder = f"{sanitize_remote_segment(guild_name, 'guild')}-{guild_id}"
    filename = f"{backup_timestamp(created_at)}.json"
    parts = [config["guild_prefix"], folder, created_at.astimezone(UTC).strftime("%Y"), created_at.astimezone(UTC).strftime("%m"), filename]
    return "/".join(part for part in parts if part)


def _empty_remote_result(name, *, remote_relative_path=None):
    config = remote_backup_config()
    return {
        "configured": config["configured"],
        "ok": False,
        "skipped": False,
        "backup_name": name,
        "destination": config["destination"],
        "remote_path": remote_join(config["destination"], remote_relative_path) if config["configured"] and remote_relative_path else None,
        "uploaded_at": None,
        "message": "",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }


def _run_rclone(args, *, action, timeout_seconds=None):
    config = remote_backup_config()
    result = {
        "action": action,
        "ok": False,
        "message": "",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    command = [config["rclone_bin"], *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds or config["timeout_seconds"],
            check=False,
        )
    except FileNotFoundError:
        result["message"] = f"{config['rclone_bin']} was not found."
        return result
    except subprocess.TimeoutExpired:
        result["message"] = f"{action} timed out after {timeout_seconds or config['timeout_seconds']}s."
        return result

    result["returncode"] = completed.returncode
    result["stdout"] = (completed.stdout or "").strip()[-1000:]
    result["stderr"] = (completed.stderr or "").strip()[-1000:]
    result["ok"] = completed.returncode == 0
    result["message"] = "ok" if result["ok"] else (result["stderr"] or f"rclone {action} failed.")
    return result


def upload_file_to_remote(source_path, remote_relative_path=None):
    config = remote_backup_config()
    source_path = Path(source_path)
    remote_relative_path = remote_relative_path or source_path.name
    result = _empty_remote_result(source_path.name, remote_relative_path=remote_relative_path)

    if not config["configured"]:
        result["skipped"] = True
        result["message"] = "BACKUP_REMOTE_DEST is not configured."
        return result
    if not source_path.exists():
        result["message"] = "Backup archive does not exist."
        return result

    remote_path = result["remote_path"]
    completed = _run_rclone(
        [
            "copyto",
            str(source_path),
            remote_path,
            "--checksum",
            "--retries",
            "3",
            "--low-level-retries",
            "10",
        ],
        action="upload",
    )

    result["returncode"] = completed["returncode"]
    result["stdout"] = completed["stdout"]
    result["stderr"] = completed["stderr"]
    result["ok"] = completed["ok"]
    result["uploaded_at"] = datetime.now(UTC).isoformat() if result["ok"] else None
    result["message"] = "Uploaded to off-site storage." if result["ok"] else completed["message"]
    return result


def upload_backup_to_remote(backup_path, created_at=None):
    return upload_file_to_remote(backup_path, remote_full_backup_path(backup_path, created_at))


def upload_json_to_remote(payload, remote_relative_path):
    config = remote_backup_config()
    name = Path(remote_relative_path).name
    result = _empty_remote_result(name, remote_relative_path=remote_relative_path)
    if not config["configured"]:
        result["skipped"] = True
        result["message"] = "BACKUP_REMOTE_DEST is not configured."
        return result

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="novaguard-guild-export-", dir=BACKUP_DIR) as temp_dir:
        export_path = Path(temp_dir) / name
        export_path.write_bytes(json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8"))
        return upload_file_to_remote(export_path, remote_relative_path)


def check_remote_file(remote_path):
    config = remote_backup_config()
    result = {
        "configured": config["configured"],
        "ok": False,
        "exists": False,
        "remote_path": remote_path,
        "checked_at": datetime.now(UTC).isoformat(),
        "bytes": 0,
        "count": 0,
        "message": "",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    if not config["configured"]:
        result["message"] = "BACKUP_REMOTE_DEST is not configured."
        return result
    if not remote_path:
        result["message"] = "No remote path is recorded for the latest backup."
        return result

    completed = _run_rclone(["size", remote_path, "--json"], action="remote check")
    result["returncode"] = completed["returncode"]
    result["stdout"] = completed["stdout"]
    result["stderr"] = completed["stderr"]
    if not completed["ok"]:
        result["message"] = completed["message"]
        return result

    try:
        payload = json.loads(completed["stdout"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    result["bytes"] = int(payload.get("bytes", 0) or 0)
    result["count"] = int(payload.get("count", 0) or 0)
    result["exists"] = result["count"] >= 1
    result["ok"] = result["exists"]
    result["message"] = "Remote file exists." if result["exists"] else "Remote file was not found."
    return result


def refresh_latest_remote_check(backup_name=None):
    state = load_remote_backup_state()
    latest = state.get("latest") if isinstance(state.get("latest"), dict) else {}
    check = check_remote_file(latest.get("remote_path"))
    if latest:
        latest["check"] = check
    update_remote_backup_state(latest=latest, latest_remote_check=check)
    return remote_backup_status(backup_name or (latest.get("backup_name") if latest else None))


def prune_remote_backups():
    config = remote_backup_config()
    summary = {
        "configured": config["configured"],
        "enabled": config["retention_enabled"],
        "ok": False,
        "ran_at": datetime.now(UTC).isoformat(),
        "full_keep_days": config["full_keep_days"],
        "guild_keep_days": config["guild_keep_days"],
        "targets": [],
        "message": "",
    }
    if not config["configured"]:
        summary["message"] = "BACKUP_REMOTE_DEST is not configured."
        return summary
    if not config["retention_enabled"]:
        summary["ok"] = True
        summary["message"] = "Remote retention is disabled."
        return summary

    targets = [
        (config["full_prefix"], "*.zip", config["full_keep_days"]),
        (config["guild_prefix"], "*.json", config["guild_keep_days"]),
    ]
    all_ok = True
    for prefix, pattern, keep_days in targets:
        if not prefix:
            continue
        remote_path = remote_join(config["destination"], prefix)
        completed = _run_rclone(
            [
                "delete",
                remote_path,
                "--min-age",
                f"{keep_days}d",
                "--include",
                pattern,
            ],
            action=f"retention {prefix}",
        )
        target = {
            "prefix": prefix,
            "pattern": pattern,
            "keep_days": keep_days,
            "remote_path": remote_path,
            "ok": completed["ok"],
            "message": completed["message"],
            "returncode": completed["returncode"],
            "stdout": completed["stdout"],
            "stderr": completed["stderr"],
        }
        summary["targets"].append(target)
        all_ok = all_ok and completed["ok"]
    summary["ok"] = all_ok
    summary["message"] = "Remote retention completed." if all_ok else "Remote retention finished with errors."
    update_remote_backup_state(latest_retention=summary)
    return summary


def _safe_extract(zip_file, target_dir):
    target_dir = Path(target_dir).resolve()
    for member in zip_file.infolist():
        member_path = (target_dir / member.filename).resolve()
        if target_dir not in member_path.parents and member_path != target_dir:
            raise ValueError(f"Unsafe backup path: {member.filename}")
    zip_file.extractall(target_dir)


def _sqlite_integrity_from_zip(zip_file, archive_name):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="novaguard-backup-check-", dir=BACKUP_DIR) as temp_dir:
        db_copy = Path(temp_dir) / "novaguard.sqlite3"
        db_copy.write_bytes(zip_file.read(archive_name))
        with sqlite3.connect(db_copy) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
    return result[0] if result else "no result"


def inspect_backup(backup_path, *, extract=False):
    backup_path = Path(backup_path)
    report = {
        "path": str(backup_path),
        "name": backup_path.name,
        "size": backup_path.stat().st_size if backup_path.exists() else 0,
        "size_text": human_size(backup_path.stat().st_size) if backup_path.exists() else "0 B",
        "checked_at": datetime.now(UTC).isoformat(),
        "included": [],
        "json_files": [],
        "sqlite": None,
        "extract_path": None,
        "warnings": [],
        "errors": [],
        "ok": False,
    }

    if not backup_path.exists():
        report["errors"].append("Backup file does not exist.")
        return report

    if report["size"] < MIN_BACKUP_BYTES:
        report["warnings"].append(f"Backup is unusually small ({report['size_text']}).")

    try:
        with zipfile.ZipFile(backup_path) as zip_file:
            bad_member = zip_file.testzip()
            if bad_member:
                report["errors"].append(f"Corrupt zip member: {bad_member}")

            names = zip_file.namelist()
            report["included"] = names
            if not names:
                report["errors"].append("Backup archive is empty.")

            for archive_name in names:
                if archive_name.endswith(".json"):
                    try:
                        json.loads(zip_file.read(archive_name).decode("utf-8"))
                        report["json_files"].append(archive_name)
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        report["errors"].append(f"{archive_name} is not valid JSON: {error}")

            if "data/novaguard.sqlite3" in names:
                integrity = _sqlite_integrity_from_zip(zip_file, "data/novaguard.sqlite3")
                report["sqlite"] = integrity
                if integrity != "ok":
                    report["errors"].append(f"SQLite integrity check failed: {integrity}")
            else:
                report["warnings"].append("SQLite database is not included yet.")

            if extract:
                if RESTORE_CHECK_DIR.exists():
                    shutil.rmtree(RESTORE_CHECK_DIR)
                RESTORE_CHECK_DIR.mkdir(parents=True, exist_ok=True)
                _safe_extract(zip_file, RESTORE_CHECK_DIR)
                report["extract_path"] = str(RESTORE_CHECK_DIR)
    except zipfile.BadZipFile as error:
        report["errors"].append(f"Invalid zip file: {error}")
    except (OSError, sqlite3.Error, ValueError) as error:
        report["errors"].append(str(error))

    report["ok"] = not report["errors"]
    return report


def create_backup(label="auto"):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC)
    safe_label = "".join(char for char in label.lower() if char.isalnum() or char in {"-", "_"}) or "backup"
    backup_path = BACKUP_DIR / f"novaguard-full-{backup_timestamp(created_at)}-{safe_label}.zip"
    temp_db = BACKUP_DIR / f".novaguard-backup-{backup_timestamp(created_at)}.sqlite3"
    for store in VOICE_STORE_FILES:
        load_voice_store(store, {})

    included = []
    try:
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zip_file:
            if DB_PATH.exists():
                backup_sqlite_to(temp_db)
                zip_file.write(temp_db, "data/novaguard.sqlite3")
                included.append("data/novaguard.sqlite3")

            legacy_voice_files = {path.resolve() for path in VOICE_STORE_FILES.values()}
            for json_file in sorted(DATA_DIR.glob("*.json")) if DATA_DIR.exists() else []:
                if json_file.resolve() in legacy_voice_files:
                    continue
                archive_name = f"data/{json_file.name}"
                zip_file.write(json_file, archive_name)
                included.append(archive_name)

            for source_path, archive_name in (
                (UPDATE_STATE_FILE, ".update_state.json"),
                (GITHUB_STATE_FILE, ".github_state.json"),
            ):
                if add_if_exists(zip_file, source_path, archive_name):
                    included.append(archive_name)

            manifest = {
                "created_at": created_at.isoformat(),
                "label": safe_label,
                "included": included,
            }
            zip_file.writestr(".backup_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True))
            included.append(".backup_manifest.json")
    finally:
        if temp_db.exists():
            temp_db.unlink()

    prune_old_backups()
    integrity = inspect_backup(backup_path)
    if integrity["ok"]:
        remote = upload_backup_to_remote(backup_path, created_at)
        if remote.get("ok"):
            remote["check"] = check_remote_file(remote.get("remote_path"))
    else:
        config = remote_backup_config()
        remote = {
            "configured": config["configured"],
            "ok": False,
            "skipped": True,
            "backup_name": backup_path.name,
            "destination": config["destination"],
            "remote_path": None,
            "uploaded_at": None,
            "message": "Local backup integrity check failed; off-site upload skipped.",
            "returncode": None,
            "stdout": "",
            "stderr": "",
        }
    retention = prune_remote_backups() if remote.get("configured") else {}
    update_remote_backup_state(
        configured=remote["configured"],
        destination=remote["destination"],
        latest=remote,
        latest_remote_check=remote.get("check") or {},
        latest_retention=retention,
    )
    return {
        "path": str(backup_path),
        "name": backup_path.name,
        "created_at": created_at.isoformat(),
        "size": backup_path.stat().st_size if backup_path.exists() else 0,
        "size_text": human_size(backup_path.stat().st_size if backup_path.exists() else 0),
        "included": included,
        "integrity": integrity,
        "remote": remote,
        "retention": retention,
    }


def restore_backup_to_temp(backup_path):
    """Basic integrity check used by config export/tests."""
    report = inspect_backup(backup_path, extract=True)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    return RESTORE_CHECK_DIR
