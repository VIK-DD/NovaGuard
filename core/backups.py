"""Safe backup helpers for NovaGuard state."""

import shutil
import sqlite3
import zipfile
from datetime import UTC, datetime

from .config import BASE_DIR, GITHUB_STATE_FILE, UPDATE_STATE_FILE
from .database import DB_PATH, init_database
from .storage import DATA_DIR

BACKUP_DIR = BASE_DIR / "backups"
MAX_BACKUPS = 10


def backup_timestamp():
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


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


def create_backup(label="auto"):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(char for char in label.lower() if char.isalnum() or char in {"-", "_"}) or "backup"
    backup_path = BACKUP_DIR / f"novaguard-backup-{backup_timestamp()}-{safe_label}.zip"
    temp_db = BACKUP_DIR / f".novaguard-backup-{backup_timestamp()}.sqlite3"

    included = []
    try:
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
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
    finally:
        if temp_db.exists():
            temp_db.unlink()

    prune_old_backups()
    return {
        "path": str(backup_path),
        "name": backup_path.name,
        "size": backup_path.stat().st_size if backup_path.exists() else 0,
        "included": included,
    }


def restore_backup_to_temp(backup_path):
    """Basic integrity check used by config export/tests."""
    target_dir = BACKUP_DIR / "restore-check"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup_path) as zip_file:
        zip_file.extractall(target_dir)
    return target_dir
