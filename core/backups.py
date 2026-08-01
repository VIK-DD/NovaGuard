"""Safe backup helpers for NovaGuard state."""

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .config import BASE_DIR, GITHUB_STATE_FILE, UPDATE_STATE_FILE
from .database import DB_PATH, init_database
from .storage import DATA_DIR

BACKUP_DIR = BASE_DIR / "backups"
OFFSITE_STATE_FILENAME = "offsite_state.json"
MAX_BACKUPS = 10
MIN_BACKUP_BYTES = 200
RESTORE_CHECK_DIR = BACKUP_DIR / "restore-check"


def env_int(name, default):
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def remote_backup_config():
    destination = os.getenv("BACKUP_REMOTE_DEST", "").strip()
    return {
        "configured": bool(destination),
        "destination": destination,
        "rclone_bin": os.getenv("BACKUP_RCLONE_BIN", "rclone").strip() or "rclone",
        "timeout_seconds": max(env_int("BACKUP_REMOTE_TIMEOUT_SECONDS", 300), 30),
    }


def backup_timestamp():
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


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
    backups = sorted(BACKUP_DIR.glob("novaguard-backup-*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old_backup in backups[MAX_BACKUPS:]:
        try:
            old_backup.unlink()
        except OSError:
            pass


def list_backups(limit=None):
    if not BACKUP_DIR.exists():
        return []

    backups = []
    for path in sorted(BACKUP_DIR.glob("novaguard-backup-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
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


def remote_backup_status(backup_name=None):
    config = remote_backup_config()
    state = load_remote_backup_state()
    latest = state.get("latest") if isinstance(state.get("latest"), dict) else {}
    return {
        "configured": config["configured"],
        "destination": config["destination"],
        "latest": latest,
        "matches_backup": bool(backup_name and latest.get("backup_name") == backup_name),
    }


def upload_backup_to_remote(backup_path):
    config = remote_backup_config()
    backup_path = Path(backup_path)
    result = {
        "configured": config["configured"],
        "ok": False,
        "skipped": False,
        "backup_name": backup_path.name,
        "destination": config["destination"],
        "uploaded_at": None,
        "message": "",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }

    if not config["configured"]:
        result["skipped"] = True
        result["message"] = "BACKUP_REMOTE_DEST is not configured."
        return result
    if not backup_path.exists():
        result["message"] = "Backup archive does not exist."
        return result

    destination = config["destination"]
    remote_path = (
        f"{destination}{backup_path.name}"
        if destination.endswith(("/", ":"))
        else f"{destination}/{backup_path.name}"
    )
    command = [
        config["rclone_bin"],
        "copyto",
        str(backup_path),
        remote_path,
        "--checksum",
        "--retries",
        "3",
        "--low-level-retries",
        "10",
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=config["timeout_seconds"],
            check=False,
        )
    except FileNotFoundError:
        result["message"] = f"{config['rclone_bin']} was not found."
        return result
    except subprocess.TimeoutExpired:
        result["message"] = f"Upload timed out after {config['timeout_seconds']}s."
        return result

    result["returncode"] = completed.returncode
    result["stdout"] = (completed.stdout or "").strip()[-500:]
    result["stderr"] = (completed.stderr or "").strip()[-500:]
    result["ok"] = completed.returncode == 0
    result["uploaded_at"] = datetime.now(UTC).isoformat() if result["ok"] else None
    result["message"] = "Uploaded to off-site storage." if result["ok"] else (result["stderr"] or "rclone upload failed.")
    return result


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
    safe_label = "".join(char for char in label.lower() if char.isalnum() or char in {"-", "_"}) or "backup"
    backup_path = BACKUP_DIR / f"novaguard-backup-{backup_timestamp()}-{safe_label}.zip"
    temp_db = BACKUP_DIR / f".novaguard-backup-{backup_timestamp()}.sqlite3"

    included = []
    try:
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zip_file:
            if DB_PATH.exists():
                backup_sqlite_to(temp_db)
                zip_file.write(temp_db, "data/novaguard.sqlite3")
                included.append("data/novaguard.sqlite3")

            for json_file in sorted(DATA_DIR.glob("*.json")) if DATA_DIR.exists() else []:
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
                "created_at": datetime.now(UTC).isoformat(),
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
        remote = upload_backup_to_remote(backup_path)
    else:
        config = remote_backup_config()
        remote = {
            "configured": config["configured"],
            "ok": False,
            "skipped": True,
            "backup_name": backup_path.name,
            "destination": config["destination"],
            "uploaded_at": None,
            "message": "Local backup integrity check failed; off-site upload skipped.",
            "returncode": None,
            "stdout": "",
            "stderr": "",
        }
    save_remote_backup_state(
        {
            "configured": remote["configured"],
            "destination": remote["destination"],
            "latest": remote,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    return {
        "path": str(backup_path),
        "name": backup_path.name,
        "size": backup_path.stat().st_size if backup_path.exists() else 0,
        "size_text": human_size(backup_path.stat().st_size if backup_path.exists() else 0),
        "included": included,
        "integrity": integrity,
        "remote": remote,
    }


def restore_backup_to_temp(backup_path):
    """Basic integrity check used by config export/tests."""
    report = inspect_backup(backup_path, extract=True)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    return RESTORE_CHECK_DIR
