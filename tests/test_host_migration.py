"""Tests for the portable single-file host migration."""

import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.host_migration import (
    HostMigrationError,
    export_host_sql,
    import_host_sql,
    verify_host_sql,
)


class HostMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.database = self.data / "novaguard.sqlite3"
        with sqlite3.connect(self.database) as connection:
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

    def tearDown(self):
        self.temporary.cleanup()

    def test_export_verify_and_import_round_trip_every_portable_state_file(self):
        migration = self.root / "transfer.sql"
        result = export_host_sql(migration, base_dir=self.root, db_path=self.database)

        self.assertGreater(result["size"], 0)
        self.assertEqual(result["auxiliary_files"], 2)
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("NovaGuard portable host migration", sql)
        self.assertNotIn("never-export-this", sql)
        verified = verify_host_sql(migration)
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["tables"], 1)
        self.assertEqual(verified["rows"], 1)
        self.assertEqual(verified["row_counts"], {"level_records": 1})

        with sqlite3.connect(self.database) as connection:
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
        with zipfile.ZipFile(imported["safety_backup"]) as archive:
            self.assertIn("data/novaguard.sqlite3", archive.namelist())
        with sqlite3.connect(self.database) as connection:
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
        migration = self.root / "transfer.sql"
        export_host_sql(migration, base_dir=self.root, db_path=self.database)
        with migration.open("a", encoding="utf-8") as file:
            file.write("UPDATE __novaguard_host_files SET content = '{}';\n")

        with self.assertRaisesRegex(HostMigrationError, "Checksum mismatch"):
            verify_host_sql(migration)

    def test_import_requires_explicit_confirmation(self):
        migration = self.root / "transfer.sql"
        export_host_sql(migration, base_dir=self.root, db_path=self.database)

        with self.assertRaisesRegex(HostMigrationError, "--confirm-replace"):
            import_host_sql(migration, base_dir=self.root, db_path=self.database)


if __name__ == "__main__":
    unittest.main()
