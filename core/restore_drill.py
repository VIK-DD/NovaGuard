"""Non-destructive restore drill with deletion-ledger enforcement."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from . import backups
from .privacy_ledger import (
    LEDGER_PATH,
    PrivacyLedgerError,
    apply_deletion_ledger,
    load_deletion_ledger,
)
from .secure_files import SecureFileError


def _sqlite_health(db_path):
    db_path = Path(db_path)
    if not db_path.is_file():
        raise ValueError("Restored backup does not contain data/novaguard.sqlite3")
    with closing(sqlite3.connect(db_path)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    return (integrity[0] if integrity else "no result"), len(foreign_keys)


def run_restore_drill(backup_path, *, ledger_path=None):
    """Exercise a full restore in disposable storage without touching live data."""
    report = backups.inspect_backup(backup_path)
    report.update(
        {
            "ledger_applied": False,
            "ledger_entries": 0,
            "privacy_removed": 0,
            "post_restore_sqlite": None,
            "post_restore_foreign_keys": None,
            "extracted_files": 0,
        }
    )
    if report["errors"]:
        report["ok"] = False
        return report
    if not report["encrypted"]:
        report["errors"].append(
            "Legacy plaintext archive is not acceptable for a production restore drill."
        )
        report["ok"] = False
        return report

    ledger_path = Path(ledger_path or LEDGER_PATH)
    try:
        ledger = load_deletion_ledger(ledger_path, require=True)
        report["ledger_entries"] = len(ledger["users"]) + len(ledger["guilds"])

        backups.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="novaguard-restore-drill-", dir=backups.BACKUP_DIR
        ) as temp_dir:
            restore_root = backups.extract_backup(backup_path, Path(temp_dir))
            report["extracted_files"] = sum(
                1 for path in restore_root.rglob("*") if path.is_file()
            )

            manifest_path = restore_root / ".backup_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            privacy_report = apply_deletion_ledger(
                restore_root,
                ledger_path=ledger_path,
                snapshot_created_at=manifest.get("created_at"),
            )
            report["ledger_applied"] = True
            report["privacy_removed"] = privacy_report["removed_or_anonymised"]

            integrity, foreign_keys = _sqlite_health(
                restore_root / "data" / "novaguard.sqlite3"
            )
            report["post_restore_sqlite"] = integrity
            report["post_restore_foreign_keys"] = foreign_keys
            if integrity != "ok":
                report["errors"].append(
                    f"Post-ledger SQLite integrity check failed: {integrity}"
                )
            if foreign_keys:
                report["errors"].append(
                    "Post-ledger SQLite foreign-key check found "
                    f"{foreign_keys} violation(s)."
                )
    except (
        json.JSONDecodeError,
        OSError,
        PrivacyLedgerError,
        SecureFileError,
        sqlite3.Error,
        ValueError,
    ) as error:
        report["errors"].append(str(error))

    report["ok"] = not report["errors"]
    return report
