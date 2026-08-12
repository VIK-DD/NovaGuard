"""Automated retention uses bounded, documented windows."""

import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import database, privacy, storage  # noqa: E402


class PrivacyRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        patches = [
            mock.patch.object(database, "DATA_DIR", self.root),
            mock.patch.object(database, "DB_PATH", self.root / "novaguard.sqlite3"),
            mock.patch.object(database, "_INITIALIZED", False),
            mock.patch.object(storage, "DATA_DIR", self.root),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        database.init_database()
        self.now = datetime(2026, 8, 12, tzinfo=UTC)
        self._seed_database()
        self._seed_json()

    def _seed_database(self):
        with database.connect() as connection:
            for thread_id, closed_at in (
                ("expired", "2025-01-01T00:00:00+00:00"),
                ("current", "2026-08-01T00:00:00+00:00"),
                ("open", None),
            ):
                connection.execute(
                    "INSERT INTO ticket_records"
                    " (thread_id, guild_id, parent_channel_id, opener_id, opener_name, created_at, closed_at)"
                    " VALUES (?, '111', '10', '42', 'Member', '2025-01-01T00:00:00+00:00', ?)",
                    (thread_id, closed_at),
                )
            for month in ("2024-12", "2025-08", "2026-08"):
                connection.execute(
                    "INSERT INTO voice_minutes VALUES ('111', ?, ?, 60, 1, ?)",
                    (month, month, self.now.isoformat()),
                )
            for actor_id, created_at in (
                ("old", "2025-01-01T00:00:00+00:00"),
                ("new", "2026-08-01T00:00:00+00:00"),
            ):
                connection.execute(
                    "INSERT INTO admin_audit (created_at, actor_id, action, outcome)"
                    " VALUES (?, ?, 'test', 'ok')",
                    (created_at, actor_id),
                )
            connection.execute(
                "CREATE TABLE web_sessions (user_id TEXT, expires_at REAL)"
            )
            connection.execute("INSERT INTO web_sessions VALUES ('old', 1), ('new', 9999999999)")
            connection.execute(
                "CREATE TABLE web_audit (guild_id TEXT, user_id TEXT, created_at TEXT)"
            )
            connection.execute(
                "INSERT INTO web_audit VALUES"
                " ('111', 'old', '2025-01-01T00:00:00+00:00'),"
                " ('111', 'new', '2026-08-01T00:00:00+00:00')"
            )
            connection.commit()

    def _seed_json(self):
        (self.root / "warns.json").write_text(
            json.dumps(
                {
                    "111": {
                        "42": [
                            {"reason": "old", "created_at": "2025-01-01T00:00:00+00:00"},
                            {"reason": "new", "created_at": "2026-08-01T00:00:00+00:00"},
                            {"reason": "invalid", "created_at": "unknown"},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.root / "giveaways.json").write_text(
            json.dumps(
                [
                    {"message_id": "old", "ended": True, "ends_at": "2025-01-01T00:00:00+00:00"},
                    {"message_id": "new", "ended": True, "ends_at": "2026-08-01T00:00:00+00:00"},
                    {"message_id": "active", "ended": False, "ends_at": "2025-01-01T00:00:00+00:00"},
                ]
            ),
            encoding="utf-8",
        )

    def test_cleanup_removes_only_expired_records(self):
        report = privacy.run_retention_cleanup(now=self.now, env={})

        self.assertEqual(report["counts"]["tickets"], 1)
        self.assertEqual(report["counts"]["voice_months"], 1)
        self.assertEqual(report["counts"]["admin_audit"], 1)
        self.assertEqual(report["counts"]["dashboard_sessions"], 1)
        self.assertEqual(report["counts"]["dashboard_audit"], 1)
        self.assertEqual(report["counts"]["warnings"], 2)
        self.assertEqual(report["counts"]["giveaways"], 1)

        with database.connect() as connection:
            tickets = {row[0] for row in connection.execute("SELECT thread_id FROM ticket_records")}
            months = {row[0] for row in connection.execute("SELECT month FROM voice_minutes")}
        self.assertEqual(tickets, {"current", "open"})
        self.assertEqual(months, {"2025-08", "2026-08"})
        warnings = json.loads((self.root / "warns.json").read_text())
        self.assertEqual([item["reason"] for item in warnings["111"]["42"]], ["new"])
        giveaways = json.loads((self.root / "giveaways.json").read_text())
        self.assertEqual({item["message_id"] for item in giveaways}, {"new", "active"})

    def test_environment_values_are_bounded_and_invalid_values_use_defaults(self):
        policy = privacy.retention_policy(
            {
                "PRIVACY_TICKET_KEEP_DAYS": "0",
                "PRIVACY_WARNING_KEEP_DAYS": "invalid",
                "PRIVACY_GIVEAWAY_KEEP_DAYS": "99999",
            }
        )

        self.assertEqual(policy["PRIVACY_TICKET_KEEP_DAYS"], 1)
        self.assertEqual(policy["PRIVACY_WARNING_KEEP_DAYS"], 365)
        self.assertEqual(policy["PRIVACY_GIVEAWAY_KEEP_DAYS"], 3650)


if __name__ == "__main__":
    unittest.main()
