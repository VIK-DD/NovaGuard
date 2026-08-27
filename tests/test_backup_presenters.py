"""Presentation-level coverage for backup status and restore cards."""

import os
import sys
import unittest
from datetime import UTC, datetime
from unittest import mock

import discord

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cogs.setup as setup_cog  # noqa: E402
from core import backup_presenters as presenters  # noqa: E402


NOW = datetime.now(UTC)
LATEST = {
    "name": "novaguard-full-test.zip.ngbackup",
    "size_text": "4.2 MB",
    "mtime": NOW,
}
HEALTHY_REPORT = {
    "ok": True,
    "encrypted": True,
    "sqlite": "ok",
    "errors": [],
    "warnings": [],
    "included": ["data/novaguard.sqlite3", "data/settings.json"],
    "json_files": ["data/settings.json"],
    "extracted_files": 2,
    "ledger_applied": True,
    "ledger_entries": 3,
    "privacy_removed": 1,
    "post_restore_sqlite": "ok",
    "post_restore_foreign_keys": 0,
}
HEALTHY_REMOTE = {
    "configured": True,
    "destination": "drive:NovaGuard",
    "matches_backup": True,
    "latest": {
        "ok": True,
        "backup_name": LATEST["name"],
        "remote_path": f"drive:NovaGuard/full/{LATEST['name']}",
        "message": "uploaded",
        "uploaded_at": "2026-08-26T19:00:00+00:00",
    },
    "latest_remote_check": {
        "ok": True,
        "exists": True,
        "bytes": 4_200_000,
        "message": "exists",
        "checked_at": "2026-08-26T19:01:00+00:00",
    },
    "latest_guild_exports": {
        "uploaded": 6,
        "failed": 0,
        "skipped": 0,
        "exports": [],
    },
    "latest_retention": {
        "enabled": True,
        "ok": True,
        "targets": [{"ok": True}, {"ok": True}],
        "message": "complete",
    },
    "full_prefix": "full",
    "guild_prefix": "guilds",
    "full_keep_days": 91,
    "guild_keep_days": 45,
}


def field_value(embed, name):
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(f"missing field {name!r}; got {[field.name for field in embed.fields]}")


class CompatibilityTests(unittest.TestCase):
    def test_setup_cog_reexports_every_moved_presenter(self):
        names = (
            "backup_contents_text",
            "backup_errors_text",
            "backup_health_summary",
            "backup_inspect_embed",
            "backup_integrity_line",
            "backup_list_embed",
            "backup_remote_embed",
            "backup_remote_text",
            "backup_restore_plan_embed",
            "backup_status_embed",
            "backup_test_embed",
            "deletion_ledger_text",
        )

        for name in names:
            with self.subTest(name=name):
                self.assertIs(getattr(setup_cog, name), getattr(presenters, name))


class BackupTextTests(unittest.TestCase):
    def test_integrity_and_notes_use_safe_defaults(self):
        self.assertEqual(presenters.backup_integrity_line(None), "Not checked")
        self.assertEqual(
            presenters.backup_errors_text(None),
            "No integrity report available.",
        )
        self.assertEqual(
            presenters.backup_errors_text({"errors": [], "warnings": []}),
            "No issues found.",
        )

    def test_notes_and_contents_are_bounded_for_discord(self):
        errors = [f"error-{index}" for index in range(8)]
        included = [f"data/file-{index}.json" for index in range(15)]

        notes = presenters.backup_errors_text({"errors": errors, "warnings": []})
        contents = presenters.backup_contents_text({"included": included})

        self.assertEqual(notes.count("•"), 5)
        self.assertNotIn("error-5", notes)
        self.assertEqual(contents.count("•"), 13)
        self.assertIn("...and `3` more", contents)

    def test_remote_text_distinguishes_missing_stale_and_verified_copies(self):
        self.assertIn("Not configured", presenters.backup_remote_text(None))

        stale = {
            **HEALTHY_REMOTE,
            "matches_backup": False,
        }
        stale_text = presenters.backup_remote_text(stale)
        healthy_text = presenters.backup_remote_text(HEALTHY_REMOTE)

        self.assertIn("not been confirmed off-site", stale_text)
        self.assertNotIn("not been confirmed off-site", healthy_text)
        self.assertIn("Remote check: ✅ exists", healthy_text)
        self.assertIn("6` uploaded", healthy_text)


class BackupHealthTests(unittest.TestCase):
    def test_complete_backup_evidence_scores_one_hundred(self):
        with (
            mock.patch.object(
                presenters,
                "backup_max_expected_age_seconds",
                return_value=24 * 3600,
            ),
            mock.patch.object(
                presenters,
                "backup_schedule_label",
                return_value="07:00, 19:00 Europe/Chisinau",
            ),
        ):
            score, label, lines = presenters.backup_health_summary(
                LATEST,
                HEALTHY_REPORT,
                HEALTHY_REMOTE,
            )

        self.assertEqual(score, 100)
        self.assertEqual(label, "Healthy")
        self.assertEqual(len(lines), 6)
        self.assertIn("✅ Encrypted local archive exists", lines)
        self.assertIn("✅ Per-server exports uploaded", lines)

    def test_missing_local_and_remote_evidence_is_risk(self):
        score, label, lines = presenters.backup_health_summary(None)

        self.assertEqual(score, 0)
        self.assertEqual(label, "Risk")
        self.assertIn("⚠️ No local archive found", lines)
        self.assertIn("⚠️ Off-site Drive backup is not configured", lines)


class BackupEmbedTests(unittest.TestCase):
    def test_remote_embed_exposes_upload_check_retention_and_exports(self):
        embed = presenters.backup_remote_embed(HEALTHY_REMOTE)

        self.assertIsInstance(embed, discord.Embed)
        self.assertEqual(embed.title, "☁️ Backup remote")
        self.assertIn("drive:NovaGuard", embed.description)
        self.assertIn("Status: `ok`", field_value(embed, "Latest full upload"))
        self.assertIn("Exists: `yes`", field_value(embed, "Remote existence check"))
        self.assertIn("Targets: `2` checked", field_value(embed, "Retention"))
        self.assertIn("Uploaded: `6`", field_value(embed, "Latest server exports"))

    def test_status_embed_uses_the_remote_evidence_for_health(self):
        with (
            mock.patch.object(
                presenters,
                "remote_backup_status",
                return_value=HEALTHY_REMOTE,
            ),
            mock.patch.object(
                presenters,
                "backup_max_expected_age_seconds",
                return_value=24 * 3600,
            ),
        ):
            embed = presenters.backup_status_embed(LATEST, HEALTHY_REPORT)

        self.assertEqual(embed.title, "🧳 Backup status")
        self.assertIn("`100/100`", field_value(embed, "Health score"))
        self.assertIn("Ready to restore", field_value(embed, "Integrity"))
        self.assertIn("uploaded", field_value(embed, "Off-site copy"))

    def test_list_test_and_inspect_cards_keep_their_operational_details(self):
        list_embed = presenters.backup_list_embed([LATEST])
        test_embed = presenters.backup_test_embed(LATEST, HEALTHY_REPORT)
        inspect_embed = presenters.backup_inspect_embed(LATEST, HEALTHY_REPORT)

        self.assertIn(LATEST["name"], field_value(list_embed, "Latest first"))
        self.assertIn("nothing decrypted is left", field_value(test_embed, "Result"))
        self.assertIn("Deletion ledger: `enforced`", field_value(test_embed, "Result"))
        self.assertIn("SQLite after ledger: `ok`", field_value(test_embed, "Result"))
        self.assertIn("foreign-key violations: `0`", field_value(test_embed, "Result"))
        self.assertIn("data/settings.json", field_value(inspect_embed, "Contents"))
        self.assertIn("SQLite integrity: `ok`", field_value(inspect_embed, "Archive"))


if __name__ == "__main__":
    unittest.main()
