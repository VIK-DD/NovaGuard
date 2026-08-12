"""Launch preflight fails closed on missing legal, privacy or recovery state."""

import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from core import backups
from core.config_check import CRITICAL
from core.privacy_ledger import ensure_deletion_ledger
from core.production_check import production_findings
from core.secure_files import encrypt_file


KEY = "production-check-test-backup-key-2026-xxxxxxxx"
HEALTHY_ENV = {
    "TOKEN": "discord-token",
    "GUILD_ID": "123",
    "BACKUP_REMOTE_DEST": "gdrive:NovaGuard/backups",
    "BACKUP_ENCRYPTION_KEY": KEY,
    "WEB_ENABLED": "true",
    "DISCORD_CLIENT_ID": "123",
    "DISCORD_CLIENT_SECRET": "discord-oauth-secret",
    "WEB_TOKEN_KEY": "dedicated-web-token-key-2026-xxxxxxxxxxxx",
    "WEB_COOKIE_SECURE": "true",
    "WEB_OAUTH_REDIRECT": "https://api.novaguard.fun/api/v1/auth/callback",
    "WEB_AFTER_LOGIN": "https://novaguard.fun/dashboard/",
    "WEB_CORS_ORIGIN": "https://novaguard.fun",
    "WEB_TRUST_PROXY": "true",
    "WEB_HOST": "127.0.0.1",
    "LEGAL_OPERATOR_NAME": "Test Operator",
    "LEGAL_OPERATOR_ADDRESS": "Test Address",
    "LEGAL_OPERATOR_COUNTRY": "Test Country",
    "PRIVACY_CONTACT_EMAIL": "privacy@example.test",
}


class ProductionCheckTests(unittest.TestCase):
    def _healthy_state(self, root):
        env_file = root / ".env"
        env_file.write_text("TOKEN=not-read-by-test\n", encoding="utf-8")
        env_file.chmod(0o600)

        data = root / "data"
        data.mkdir()
        db_path = data / "novaguard.sqlite3"
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO metadata VALUES ('version', 'test')")
            connection.commit()
        db_path.chmod(0o600)
        ensure_deletion_ledger(root / ".privacy_deletions.json")

        backup_dir = root / "backups"
        backup_dir.mkdir()
        clear_zip = root / "backup.zip"
        with zipfile.ZipFile(clear_zip, "w") as archive:
            archive.write(db_path, "data/novaguard.sqlite3")
            archive.writestr("data/settings.json", json.dumps({"padding": "x" * 300}))
            archive.writestr(
                ".backup_manifest.json",
                json.dumps({"created_at": datetime.now(UTC).isoformat()}),
            )
        archive_path = backup_dir / "novaguard-full-test.zip.ngbackup"
        encrypt_file(clear_zip, archive_path)
        archive_path.chmod(0o600)
        (backup_dir / backups.OFFSITE_STATE_FILENAME).write_text(
            json.dumps(
                {
                    "latest": {
                        "ok": True,
                        "backup_name": archive_path.name,
                        "check": {"ok": True},
                    }
                }
            ),
            encoding="utf-8",
        )
        return db_path, backup_dir

    def test_hardened_host_has_no_critical_findings(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ, HEALTHY_ENV, clear=True
        ):
            root = Path(temp_dir)
            db_path, backup_dir = self._healthy_state(root)
            with mock.patch.object(backups, "BACKUP_DIR", backup_dir), mock.patch.object(
                backups, "RESTORE_CHECK_DIR", backup_dir / "restore-check"
            ):
                findings = production_findings(
                    HEALTHY_ENV,
                    base_dir=root,
                    db_path=db_path,
                    backup_dir=backup_dir,
                )

        self.assertEqual([item.name for item in findings if item.level == CRITICAL], [])

    def test_missing_legal_and_recovery_state_blocks_launch(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"BACKUP_ENCRYPTION_KEY": KEY},
            clear=True,
        ):
            root = Path(temp_dir)
            findings = production_findings(
                {"BACKUP_ENCRYPTION_KEY": KEY},
                base_dir=root,
                db_path=root / "missing.sqlite3",
                backup_dir=root / "backups",
            )

        critical = {item.name for item in findings if item.level == CRITICAL}
        self.assertIn("LEGAL_OPERATOR_NAME", critical)
        self.assertIn("PRIVACY_CONTACT_EMAIL", critical)
        self.assertIn("database", critical)
        self.assertIn("deletion ledger", critical)
        self.assertIn("latest backup", critical)
        self.assertIn("off-site backup", critical)


if __name__ == "__main__":
    unittest.main()
