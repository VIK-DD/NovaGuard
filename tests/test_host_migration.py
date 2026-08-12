"""Tests for the portable single-file host migration."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.host_migration import (
    HostMigrationError,
    export_host_sql,
    import_host_sql,
    readable_host_sql,
    verify_host_sql,
)
from core.privacy_ledger import ensure_deletion_ledger, record_deletion
from core.secure_files import decrypt_file, is_encrypted_file


class HostMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.old_backup_key = os.environ.get("BACKUP_ENCRYPTION_KEY")
        os.environ["BACKUP_ENCRYPTION_KEY"] = "host-migration-test-key-2026-xxxxxxxxxxxxxx"
        self.data = self.root / "data"
        self.data.mkdir()
        self.database = self.data / "novaguard.sqlite3"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE level_records (guild_id TEXT, user_id TEXT, xp INTEGER)")
            connection.execute("INSERT INTO level_records VALUES ('guild-1', 'user-1', 4200)")
            connection.commit()
        (self.data / "maintenance.json").write_text(
            json.dumps({"enabled": True, "reason": "upgrade"}), encoding="utf-8"
        )
        (self.root / ".update_state.json").write_text(
            json.dumps({"release": "2.0"}), encoding="utf-8"
        )
        (self.root / ".env").write_text("DISCORD_TOKEN=never-export-this", encoding="utf-8")
        ensure_deletion_ledger(self.root / ".privacy_deletions.json")

    def tearDown(self):
        if self.old_backup_key is None:
            os.environ.pop("BACKUP_ENCRYPTION_KEY", None)
        else:
            os.environ["BACKUP_ENCRYPTION_KEY"] = self.old_backup_key
        self.temporary.cleanup()

    def test_export_verify_and_import_round_trip_every_portable_state_file(self):
        migration = self.root / "transfer.sql.ngbackup"
        result = export_host_sql(migration, base_dir=self.root, db_path=self.database)

        self.assertGreater(result["size"], 0)
        self.assertEqual(result["auxiliary_files"], 2)
        self.assertTrue(is_encrypted_file(migration))
        with readable_host_sql(migration) as clear_sql:
            sql = clear_sql.read_text(encoding="utf-8")
            self.assertIn("NovaGuard portable host migration", sql)
            self.assertNotIn("never-export-this", sql)
        verified = verify_host_sql(migration)
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["tables"], 1)
        self.assertEqual(verified["rows"], 1)
        self.assertEqual(verified["row_counts"], {"level_records": 1})

        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("DELETE FROM level_records")
            connection.commit()
        (self.data / "maintenance.json").write_text("{}", encoding="utf-8")
        (self.root / ".update_state.json").write_text("{}", encoding="utf-8")

        imported = import_host_sql(
            migration,
            confirm_replace=True,
            base_dir=self.root,
            db_path=self.database,
        )

        self.assertTrue(imported["ok"])
        self.assertTrue(Path(imported["safety_backup"]).exists())
        safety_clear = self.root / "safety.zip"
        decrypt_file(imported["safety_backup"], safety_clear)
        with zipfile.ZipFile(safety_clear) as archive:
            self.assertIn("data/novaguard.sqlite3", archive.namelist())
        with closing(sqlite3.connect(self.database)) as connection:
            row = connection.execute("SELECT guild_id, user_id, xp FROM level_records").fetchone()
            internal_tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE '__novaguard_host_%'"
            ).fetchall()
        self.assertEqual(row, ("guild-1", "user-1", 4200))
        self.assertEqual(internal_tables, [])
        self.assertEqual(
            json.loads((self.data / "maintenance.json").read_text(encoding="utf-8"))["reason"],
            "upgrade",
        )
        self.assertEqual(
            json.loads((self.root / ".update_state.json").read_text(encoding="utf-8"))["release"],
            "2.0",
        )

    def test_verify_rejects_tampered_embedded_file(self):
        migration = self.root / "transfer.sql.ngbackup"
        export_host_sql(migration, base_dir=self.root, db_path=self.database)
        plaintext = self.root / "tampered.sql"
        decrypt_file(migration, plaintext)
        with plaintext.open("a", encoding="utf-8") as file:
            file.write("UPDATE __novaguard_host_files SET content = '{}';\n")

        with self.assertRaisesRegex(HostMigrationError, "Checksum mismatch"):
            verify_host_sql(plaintext, allow_plaintext=True)

    def test_import_requires_explicit_confirmation(self):
        migration = self.root / "transfer.sql.ngbackup"
        export_host_sql(migration, base_dir=self.root, db_path=self.database)

        with self.assertRaisesRegex(HostMigrationError, "--confirm-replace"):
            import_host_sql(migration, base_dir=self.root, db_path=self.database)

    def test_plaintext_migration_requires_an_explicit_legacy_override(self):
        migration = self.root / "transfer.sql.ngbackup"
        export_host_sql(migration, base_dir=self.root, db_path=self.database)
        plaintext = self.root / "legacy.sql"
        decrypt_file(migration, plaintext)

        with self.assertRaisesRegex(HostMigrationError, "Plaintext host migration refused"):
            verify_host_sql(plaintext)
        self.assertTrue(verify_host_sql(plaintext, allow_plaintext=True)["ok"])

    def test_import_reapplies_deletions_recorded_after_export(self):
        migration = self.root / "transfer.sql.ngbackup"
        export_host_sql(migration, base_dir=self.root, db_path=self.database)
        record_deletion("user", "user-1", path=self.root / ".privacy_deletions.json")

        imported = import_host_sql(
            migration,
            confirm_replace=True,
            base_dir=self.root,
            db_path=self.database,
        )

        self.assertGreater(imported["privacy"]["removed_or_anonymised"], 0)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertIsNone(
                connection.execute("SELECT user_id FROM level_records").fetchone()
            )


if __name__ == "__main__":
    unittest.main()
