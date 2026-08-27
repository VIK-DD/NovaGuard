"""The operator restore drill enforces privacy erasures without touching live data."""

import os
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from core import backups
from core.privacy_ledger import ensure_deletion_ledger, record_deletion
from core.restore_drill import run_restore_drill


class RestoreDrillTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_backup_dir = backups.BACKUP_DIR
        self.old_key = os.environ.get("BACKUP_ENCRYPTION_KEY")
        backups.BACKUP_DIR = self.root / "backups"
        backups.BACKUP_DIR.mkdir()
        os.environ["BACKUP_ENCRYPTION_KEY"] = (
            "test-only-restore-drill-encryption-key-2026-xxxxxxxx"
        )
        self.ledger_path = self.root / ".privacy_deletions.json"
        ensure_deletion_ledger(self.ledger_path)

    def tearDown(self):
        backups.BACKUP_DIR = self.old_backup_dir
        if self.old_key is None:
            os.environ.pop("BACKUP_ENCRYPTION_KEY", None)
        else:
            os.environ["BACKUP_ENCRYPTION_KEY"] = self.old_key
        self.temp_dir.cleanup()

    def write_backup(self, *, guild_id=42):
        db_path = self.root / "novaguard.sqlite3"
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "CREATE TABLE guild_settings (guild_id INTEGER PRIMARY KEY, settings_json TEXT)"
            )
            connection.execute(
                "INSERT INTO guild_settings VALUES (?, '{}')", (guild_id,)
            )
            connection.commit()

        clear_path = backups.BACKUP_DIR / "novaguard-full-drill.zip"
        with zipfile.ZipFile(clear_path, "w") as archive:
            archive.write(db_path, "data/novaguard.sqlite3")
            archive.writestr("data/settings.json", '{"guild_id": 42}')
            archive.writestr(
                ".backup_manifest.json",
                '{"created_at":"2026-08-26T10:00:00+00:00"}',
            )
        encrypted_path = clear_path.with_suffix(".zip.ngbackup")
        backups.encrypt_file(clear_path, encrypted_path)
        clear_path.unlink()
        return encrypted_path

    def drill_directories(self):
        return list(backups.BACKUP_DIR.glob("novaguard-restore-drill-*"))

    def test_drill_applies_later_deletion_and_removes_plaintext(self):
        backup_path = self.write_backup()
        record_deletion(
            "guild",
            42,
            path=self.ledger_path,
            deleted_at="2026-08-27T10:00:00+00:00",
        )

        report = run_restore_drill(backup_path, ledger_path=self.ledger_path)

        self.assertTrue(report["ok"])
        self.assertTrue(report["ledger_applied"])
        self.assertEqual(report["ledger_entries"], 1)
        self.assertGreaterEqual(report["privacy_removed"], 1)
        self.assertEqual(report["post_restore_sqlite"], "ok")
        self.assertEqual(report["post_restore_foreign_keys"], 0)
        self.assertGreater(report["extracted_files"], 0)
        self.assertEqual(self.drill_directories(), [])

    def test_drill_fails_closed_when_ledger_is_missing(self):
        backup_path = self.write_backup()
        self.ledger_path.unlink()

        report = run_restore_drill(backup_path, ledger_path=self.ledger_path)

        self.assertFalse(report["ok"])
        self.assertFalse(report["ledger_applied"])
        self.assertTrue(any("does not exist" in error for error in report["errors"]))
        self.assertEqual(self.drill_directories(), [])


if __name__ == "__main__":
    unittest.main()
