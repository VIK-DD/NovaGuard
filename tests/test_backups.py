"""Unit tests for NovaGuard backup integrity helpers."""

from datetime import UTC, datetime
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

# Keep this standalone test runnable with `python tests/test_backups.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.backups as backups


class BackupIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_backup_dir = backups.BACKUP_DIR
        self.old_restore_dir = backups.RESTORE_CHECK_DIR
        self.db_counter = 0
        backups.BACKUP_DIR = self.root / "backups"
        backups.RESTORE_CHECK_DIR = backups.BACKUP_DIR / "restore-check"
        backups.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        backups.BACKUP_DIR = self.old_backup_dir
        backups.RESTORE_CHECK_DIR = self.old_restore_dir
        self.temp_dir.cleanup()

    def write_sqlite(self):
        self.db_counter += 1
        db_path = self.root / f"novaguard-{self.db_counter}.sqlite3"
        with sqlite3.connect(db_path) as connection:
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO metadata VALUES ('version', 'test')")
            connection.commit()
        return db_path

    def write_backup(self, name="novaguard-backup-test.zip", *, bad_json=False):
        backup_path = backups.BACKUP_DIR / name
        sqlite_path = self.write_sqlite()
        with zipfile.ZipFile(backup_path, "w") as archive:
            archive.write(sqlite_path, "data/novaguard.sqlite3")
            archive.writestr("data/settings.json", "{broken" if bad_json else '{"ok": true}')
            archive.writestr(".backup_manifest.json", '{"label": "test"}')
        return backup_path

    def test_inspect_backup_validates_zip_json_sqlite_and_extracts_safely(self):
        backup_path = self.write_backup()

        report = backups.inspect_backup(backup_path, extract=True)

        self.assertTrue(report["ok"])
        self.assertEqual(report["sqlite"], "ok")
        self.assertIn("data/settings.json", report["json_files"])
        self.assertTrue((backups.RESTORE_CHECK_DIR / "data" / "novaguard.sqlite3").exists())

    def test_inspect_backup_reports_invalid_json(self):
        backup_path = self.write_backup(bad_json=True)

        report = backups.inspect_backup(backup_path)

        self.assertFalse(report["ok"])
        self.assertIn("data/settings.json is not valid JSON", report["errors"][0])

    def test_list_backups_returns_newest_first_with_human_sizes(self):
        old_backup = self.write_backup("novaguard-backup-old.zip")
        new_backup = self.write_backup("novaguard-backup-new.zip")
        old_time = datetime(2026, 7, 30, 10, tzinfo=UTC).timestamp()
        new_time = datetime(2026, 7, 31, 10, tzinfo=UTC).timestamp()
        os.utime(old_backup, (old_time, old_time))
        os.utime(new_backup, (new_time, new_time))

        listed = backups.list_backups()

        self.assertEqual([item["name"] for item in listed], ["novaguard-backup-new.zip", "novaguard-backup-old.zip"])
        self.assertTrue(listed[0]["size_text"].endswith(("B", "KB")))


if __name__ == "__main__":
    unittest.main()
