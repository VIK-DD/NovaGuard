"""Unit tests for NovaGuard backup integrity helpers."""

from contextlib import closing
from datetime import UTC, datetime
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

# Keep this standalone test runnable with `python tests/test_backups.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.backups as backups


class BackupIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_backup_dir = backups.BACKUP_DIR
        self.old_restore_dir = backups.RESTORE_CHECK_DIR
        self.old_env = {
            key: os.environ.get(key)
            for key in (
                "BACKUP_REMOTE_DEST",
                "BACKUP_REMOTE_FULL_PREFIX",
                "BACKUP_REMOTE_GUILD_PREFIX",
                "BACKUP_REMOTE_FULL_KEEP_DAYS",
                "BACKUP_REMOTE_GUILD_KEEP_DAYS",
                "BACKUP_REMOTE_RETENTION_ENABLED",
                "BACKUP_RCLONE_BIN",
                "BACKUP_REMOTE_TIMEOUT_SECONDS",
                "BACKUP_SCHEDULE",
                "BACKUP_TIMEZONE",
                "BACKUP_ENCRYPTION_KEY",
            )
        }
        self.db_counter = 0
        backups.BACKUP_DIR = self.root / "backups"
        backups.RESTORE_CHECK_DIR = backups.BACKUP_DIR / "restore-check"
        backups.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        os.environ["BACKUP_ENCRYPTION_KEY"] = "test-only-backup-encryption-key-2026-xxxxxxxx"

    def tearDown(self):
        backups.BACKUP_DIR = self.old_backup_dir
        backups.RESTORE_CHECK_DIR = self.old_restore_dir
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()

    def write_sqlite(self):
        self.db_counter += 1
        db_path = self.root / f"novaguard-{self.db_counter}.sqlite3"
        with closing(sqlite3.connect(db_path)) as connection:
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

    def write_encrypted_backup(self, name="novaguard-backup-test.zip.ngbackup", *, bad_json=False):
        clear_path = self.write_backup(name.removesuffix(".ngbackup"), bad_json=bad_json)
        encrypted_path = backups.BACKUP_DIR / name
        backups.encrypt_file(clear_path, encrypted_path)
        clear_path.unlink()
        return encrypted_path

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

    def test_encrypted_backup_is_decrypted_verified_and_extracted(self):
        backup_path = self.write_encrypted_backup()

        report = backups.inspect_backup(backup_path, extract=True)

        self.assertTrue(report["ok"])
        self.assertTrue(report["encrypted"])
        self.assertEqual(report["sqlite"], "ok")
        self.assertTrue((backups.RESTORE_CHECK_DIR / "data" / "novaguard.sqlite3").exists())
        self.assertEqual((backups.RESTORE_CHECK_DIR / "data" / "novaguard.sqlite3").stat().st_mode & 0o777, 0o600)

    def test_wrong_backup_key_fails_integrity_without_plaintext_output(self):
        backup_path = self.write_encrypted_backup()
        os.environ["BACKUP_ENCRYPTION_KEY"] = "wrong-test-backup-encryption-key-2026-xxxx"

        report = backups.inspect_backup(backup_path, extract=True)

        self.assertFalse(report["ok"])
        self.assertIn("authentication failed", report["errors"][0])
        self.assertFalse(backups.RESTORE_CHECK_DIR.exists())

    def test_restore_rejects_archive_path_traversal(self):
        clear_path = backups.BACKUP_DIR / "unsafe.zip"
        with zipfile.ZipFile(clear_path, "w") as archive:
            archive.writestr("../../escaped.txt", "private")
        encrypted_path = backups.BACKUP_DIR / "unsafe.zip.ngbackup"
        backups.encrypt_file(clear_path, encrypted_path)
        clear_path.unlink()

        report = backups.inspect_backup(encrypted_path, extract=True)

        self.assertFalse(report["ok"])
        self.assertIn("Unsafe backup path", report["errors"][0])
        self.assertFalse((self.root / "escaped.txt").exists())
        self.assertFalse(backups.RESTORE_CHECK_DIR.exists())

    def test_restore_rejects_symbolic_links(self):
        clear_path = backups.BACKUP_DIR / "symlink.zip"
        link = zipfile.ZipInfo("data/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(clear_path, "w") as archive:
            archive.writestr(link, "../../escaped.txt")
        encrypted_path = backups.BACKUP_DIR / "symlink.zip.ngbackup"
        backups.encrypt_file(clear_path, encrypted_path)
        clear_path.unlink()

        report = backups.inspect_backup(encrypted_path, extract=True)

        self.assertFalse(report["ok"])
        self.assertIn("symbolic link", report["errors"][0])
        self.assertFalse(backups.RESTORE_CHECK_DIR.exists())

    def test_list_backups_returns_newest_first_with_human_sizes(self):
        old_backup = self.write_backup("novaguard-backup-old.zip")
        new_backup = self.write_backup("novaguard-full-new.zip")
        old_time = datetime(2026, 7, 30, 10, tzinfo=UTC).timestamp()
        new_time = datetime(2026, 7, 31, 10, tzinfo=UTC).timestamp()
        os.utime(old_backup, (old_time, old_time))
        os.utime(new_backup, (new_time, new_time))

        listed = backups.list_backups()

        self.assertEqual([item["name"] for item in listed], ["novaguard-full-new.zip", "novaguard-backup-old.zip"])
        self.assertTrue(listed[0]["size_text"].endswith(("B", "KB")))

    def test_remote_paths_are_grouped_by_full_and_guild_folders(self):
        when = datetime(2026, 8, 1, 4, 5, 6, tzinfo=UTC)
        backup_path = self.write_encrypted_backup("novaguard-full-2026-08-01_04-05-06-auto.zip.ngbackup")

        full_path = backups.remote_full_backup_path(backup_path, when)
        guild_path = backups.guild_export_relative_path("1328794007748476939", "MadCats - RPG B-HOOD!", when)

        self.assertEqual(full_path, "full/2026/08/novaguard-full-2026-08-01_04-05-06-auto.zip.ngbackup")
        self.assertEqual(
            guild_path,
            "guilds/MadCats-RPG-B-HOOD-1328794007748476939/2026/08/2026-08-01_04-05-06.json.ngbackup",
        )

    def test_remote_upload_is_skipped_when_not_configured(self):
        os.environ.pop("BACKUP_REMOTE_DEST", None)
        backup_path = self.write_encrypted_backup()

        result = backups.upload_backup_to_remote(backup_path)

        self.assertFalse(result["configured"])
        self.assertTrue(result["skipped"])
        self.assertFalse(result["ok"])

    def test_remote_upload_uses_rclone_and_saves_status(self):
        backup_path = self.write_encrypted_backup()
        fake_rclone = self.root / "rclone"
        args_file = self.root / "rclone-args.txt"
        fake_rclone.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" > {args_file}\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_rclone.chmod(0o755)
        os.environ["BACKUP_REMOTE_DEST"] = "gdrive:NovaGuard/backups"
        os.environ["BACKUP_RCLONE_BIN"] = str(fake_rclone)

        result = backups.upload_backup_to_remote(backup_path)
        backups.save_remote_backup_state(
            {
                "configured": result["configured"],
                "destination": result["destination"],
                "latest": result,
                "updated_at": "2026-08-01T00:00:00+00:00",
            }
        )
        status = backups.remote_backup_status(backup_path.name)

        self.assertTrue(result["ok"])
        args = args_file.read_text(encoding="utf-8")
        self.assertIn("copyto", args)
        self.assertIn("gdrive:NovaGuard/backups/full/", args)
        self.assertEqual(status["latest"]["backup_name"], backup_path.name)
        self.assertTrue(status["matches_backup"])

    def test_remote_check_uses_rclone_size_json(self):
        fake_rclone = self.root / "rclone"
        fake_rclone.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"size\" ]; then\n"
            "  printf '{\"count\":1,\"bytes\":152701}\\n'\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        fake_rclone.chmod(0o755)
        os.environ["BACKUP_REMOTE_DEST"] = "gdrive:NovaGuard/backups"
        os.environ["BACKUP_RCLONE_BIN"] = str(fake_rclone)

        result = backups.check_remote_file("gdrive:NovaGuard/backups/full/backup.zip")

        self.assertTrue(result["ok"])
        self.assertTrue(result["exists"])
        self.assertEqual(result["bytes"], 152701)

    def test_remote_retention_deletes_old_full_and_guild_files(self):
        fake_rclone = self.root / "rclone"
        args_file = self.root / "rclone-args.txt"
        fake_rclone.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" >> {args_file}\n"
            "printf -- '---\\n' >> "
            f"{args_file}\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_rclone.chmod(0o755)
        os.environ["BACKUP_REMOTE_DEST"] = "gdrive:NovaGuard/backups"
        os.environ["BACKUP_RCLONE_BIN"] = str(fake_rclone)
        os.environ["BACKUP_REMOTE_FULL_KEEP_DAYS"] = "91"
        os.environ["BACKUP_REMOTE_GUILD_KEEP_DAYS"] = "45"

        result = backups.prune_remote_backups()

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["targets"]), 2)
        args = args_file.read_text(encoding="utf-8")
        self.assertIn("gdrive:NovaGuard/backups/full", args)
        self.assertIn("gdrive:NovaGuard/backups/guilds", args)
        self.assertIn("91d", args)
        self.assertIn("45d", args)
        self.assertIn("*.ngbackup", args)
        self.assertIn("*.zip", args)
        self.assertIn("*.json", args)

    def test_plaintext_backup_is_never_uploaded(self):
        os.environ["BACKUP_REMOTE_DEST"] = "gdrive:NovaGuard/backups"
        result = backups.upload_backup_to_remote(self.write_backup())

        self.assertFalse(result["ok"])
        self.assertIn("Plaintext backup upload refused", result["message"])

    def test_guild_json_is_encrypted_before_rclone_receives_it(self):
        fake_rclone = self.root / "rclone-encrypted"
        captured = self.root / "captured.ngbackup"
        fake_rclone.write_text(
            "#!/bin/sh\n"
            f"cp \"$2\" {captured}\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_rclone.chmod(0o755)
        os.environ["BACKUP_REMOTE_DEST"] = "gdrive:NovaGuard/backups"
        os.environ["BACKUP_RCLONE_BIN"] = str(fake_rclone)

        result = backups.upload_json_to_remote(
            {"guild_id": "111", "private": "member data"},
            "guilds/server/export.json.ngbackup",
        )

        self.assertTrue(result["ok"])
        self.assertTrue(backups.is_encrypted_file(captured))
        self.assertNotIn(b"member data", captured.read_bytes())

    def test_create_backup_writes_only_an_encrypted_archive(self):
        data_dir = self.root / "data"
        data_dir.mkdir()
        sqlite_path = self.write_sqlite()
        (data_dir / "warns.json").write_text('{"111": {"42": []}}', encoding="utf-8")
        os.environ.pop("BACKUP_REMOTE_DEST", None)
        with (
            mock.patch.object(backups, "DB_PATH", sqlite_path),
            mock.patch.object(backups, "DATA_DIR", data_dir),
            mock.patch.object(backups, "VOICE_STORE_FILES", {}),
            mock.patch.object(backups, "UPDATE_STATE_FILE", self.root / ".updates.json"),
            mock.patch.object(backups, "GITHUB_STATE_FILE", self.root / ".github.json"),
            mock.patch.object(backups, "init_database", return_value=None),
        ):
            result = backups.create_backup("test")

        archive = Path(result["path"])
        self.assertTrue(result["integrity"]["ok"])
        self.assertTrue(result["integrity"]["encrypted"])
        self.assertTrue(backups.is_encrypted_file(archive))
        self.assertEqual(list(backups.BACKUP_DIR.glob("novaguard-full-*.zip")), [])

    def test_backup_schedule_is_configurable(self):
        os.environ["BACKUP_SCHEDULE"] = "19:00,07:00,bad,25:10"
        os.environ["BACKUP_TIMEZONE"] = "Europe/Chisinau"

        self.assertEqual(backups.backup_schedule(), ((7, 0), (19, 0)))
        self.assertEqual(backups.backup_schedule_label(), "07:00, 19:00 Europe/Chisinau")
        self.assertEqual(backups.backup_max_expected_age_seconds(), 14 * 3600)


class RemoteRetentionTests(unittest.TestCase):
    """A folder that was never written to is not a retention failure."""

    def _result(self, ok, stderr="", stdout=""):
        return {"ok": ok, "stderr": stderr, "stdout": stdout}

    def test_a_folder_that_does_not_exist_yet_is_not_a_failure(self):
        # `guilds/` only appears after the first per-server export, so before
        # that rclone exits non-zero and nothing is actually wrong.
        completed = self._result(False, stderr="2026/08/09 ERROR : directory not found")

        self.assertTrue(backups._is_missing_remote_dir(completed))

    def test_a_successful_run_is_never_treated_as_missing(self):
        self.assertFalse(backups._is_missing_remote_dir(self._result(True)))

    def test_real_failures_still_count_as_failures(self):
        # These would otherwise be swallowed, and silent backup breakage is
        # exactly what the retention report exists to surface.
        for stderr in (
            "didn't find section in config file",
            "failed to authenticate: token expired",
            "quota exceeded",
        ):
            with self.subTest(stderr=stderr):
                self.assertFalse(backups._is_missing_remote_dir(self._result(False, stderr)))


if __name__ == "__main__":
    unittest.main()
