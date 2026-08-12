"""Data subject export and erasure cover every NovaGuard persistence layer."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import database, privacy, storage  # noqa: E402


class PrivacyDataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.patches = [
            mock.patch.object(database, "DATA_DIR", self.root),
            mock.patch.object(database, "DB_PATH", self.root / "novaguard.sqlite3"),
            mock.patch.object(
                database,
                "VOICE_STORE_FILES",
                {
                    "voice_sessions": self.root / "voice_sessions.json",
                    "voice_pending_reports": self.root / "voice_pending_reports.json",
                    "voice_report_history": self.root / "voice_report_history.json",
                },
            ),
            mock.patch.object(database, "_INITIALIZED", False),
            mock.patch.object(storage, "DATA_DIR", self.root),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        storage.invalidate_guild_settings_cache()
        database.init_database()
        self._seed_database()
        self._seed_json()

    def _seed_database(self):
        stamp = "2026-08-12T00:00:00+00:00"
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO guild_settings VALUES ('111', 'log_channel', '\"10\"', ?)",
                (stamp,),
            )
            for guild_id, user_id in (("111", "42"), ("222", "99")):
                connection.execute(
                    "INSERT INTO level_records VALUES (?, ?, 120, 8, ?, ?)",
                    (guild_id, user_id, stamp, stamp),
                )
                connection.execute(
                    "INSERT INTO economy_wallets"
                    " (guild_id, user_id, coins, daily_streak, trophies, updated_at, extras)"
                    " VALUES (?, ?, 50, 1, '[]', ?, '{}')",
                    (guild_id, user_id, stamp),
                )
                connection.execute(
                    "INSERT INTO voice_minutes VALUES (?, ?, '2026-08', 60, 1, ?)",
                    (guild_id, user_id, stamp),
                )
            connection.execute(
                "INSERT INTO ticket_records"
                " (thread_id, guild_id, parent_channel_id, opener_id, opener_name, created_at)"
                " VALUES ('ticket-1', '111', '10', '42', 'Victor', ?)",
                (stamp,),
            )
            connection.execute(
                "INSERT INTO ticket_records"
                " (thread_id, guild_id, parent_channel_id, opener_id, opener_name, created_at, closed_by)"
                " VALUES ('ticket-2', '222', '20', '99', 'Other', ?, '42')",
                (stamp,),
            )
            connection.execute(
                "INSERT INTO role_panels"
                " (message_id, guild_id, channel_id, title, description, role_ids, created_by, created_at, updated_at)"
                " VALUES ('panel-1', '111', '10', 'Roles', 'Pick', '[]', '42', ?, ?)",
                (stamp, stamp),
            )
            connection.execute(
                "INSERT INTO admin_audit"
                " (created_at, actor_id, actor_name, action, outcome)"
                " VALUES (?, '42', 'Victor', 'backup.create', 'ok')",
                (stamp,),
            )
            connection.execute(
                "INSERT INTO voice_state VALUES ('voice_sessions', ?, ?)",
                (json.dumps({"111": {"room": {"members": {"42": {"joined_at": stamp}}}}, "222": {"room": {"members": {"99": {}}}}}), stamp),
            )
            connection.execute(
                "CREATE TABLE web_sessions"
                " (sid_hash TEXT, user_id TEXT, user_json TEXT, access_token TEXT, refresh_token TEXT,"
                " token_expires_at REAL, guilds_json TEXT, guilds_fetched_at REAL, created_at TEXT,"
                " expires_at REAL, last_seen_at REAL)"
            )
            connection.execute(
                "INSERT INTO web_sessions VALUES"
                " ('secret-hash', '42', '{\"id\": \"42\", \"username\": \"Victor\"}',"
                " 'secret-token', NULL, 0, '{\"111\": {\"name\": \"Nova\"}}', 0, ?, 9, 8)",
                (stamp,),
            )
            connection.execute(
                "CREATE TABLE web_audit"
                " (id INTEGER PRIMARY KEY, guild_id TEXT, user_id TEXT, username TEXT, action TEXT,"
                " changes_json TEXT, ip TEXT, created_at TEXT)"
            )
            connection.execute(
                "INSERT INTO web_audit VALUES"
                " (1, '111', '42', 'Victor', 'config_update', '{\"levels\": true}', '127.0.0.1', ?)",
                (stamp,),
            )
            connection.commit()

    def _seed_json(self):
        fixtures = {
            "warns": {
                "111": {"42": [{"reason": "spam", "moderator_id": 99}]},
                "222": {"99": [{"reason": "caps", "moderator_id": 42}]},
            },
            "reminders": [
                {"id": "a", "user_id": 42, "guild_id": 111, "message": "mine"},
                {"id": "b", "user_id": 99, "guild_id": 222, "message": "other"},
            ],
            "giveaways": [
                {"guild_id": 111, "host_id": 42, "host_name": "Victor", "entrants": [42, 99]},
                {"guild_id": 222, "host_id": 99, "host_name": "Other", "entrants": [99]},
            ],
            "levels": {"111": {"42": {"xp": 1}}, "222": {"99": {"xp": 2}}},
            "economy": {"111": {"42": {"coins": 1}}, "222": {"99": {"coins": 2}}},
            "settings": {"111": {"legacy": True}, "222": {"legacy": True}},
        }
        for name, value in fixtures.items():
            (self.root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")

    def test_user_export_is_complete_and_never_exports_credentials(self):
        exported = privacy.export_user_data("42")
        blob = json.dumps(exported)

        self.assertEqual(exported["user_id"], "42")
        self.assertEqual(exported["levels"][0]["guild_id"], "111")
        self.assertEqual(exported["warnings_received"][0]["guild_id"], "111")
        self.assertEqual(exported["warnings_issued"][0]["guild_id"], "222")
        self.assertEqual(exported["reminders"][0]["message"], "mine")
        self.assertIn("voice_sessions", exported["voice_state"])
        self.assertNotIn("secret-token", blob)
        self.assertNotIn("secret-hash", blob)
        self.assertNotIn('"opener_id": "99"', blob)
        self.assertNotIn('"moderator_id": 99', blob)
        self.assertNotIn('"entrants"', blob)

    def test_user_erasure_removes_subject_and_anonymises_references(self):
        report = privacy.erase_user_data(42)

        self.assertGreater(sum(report["counts"].values()), 0)
        self.assertEqual(privacy.export_user_data(42)["counts"]["levels"], 0)
        with database.connect() as connection:
            self.assertIsNone(
                connection.execute("SELECT closed_by FROM ticket_records WHERE thread_id='ticket-2'").fetchone()[0]
            )
            actor = connection.execute("SELECT actor_id, actor_name FROM admin_audit").fetchone()
            self.assertEqual(tuple(actor), ("deleted-user", None))
            voice = database.decode_value(
                connection.execute("SELECT payload FROM voice_state").fetchone()[0]
            )
            self.assertNotIn("42", voice["111"]["room"]["members"])
        warns = json.loads((self.root / "warns.json").read_text())
        self.assertNotIn("42", warns.get("111", {}))
        self.assertIsNone(warns["222"]["99"][0]["moderator_id"])
        giveaways = json.loads((self.root / "giveaways.json").read_text())
        self.assertEqual(giveaways[0]["host_name"], "Deleted member")
        self.assertNotIn(42, giveaways[0]["entrants"])

    def test_guild_export_includes_every_guild_scoped_store(self):
        exported = privacy.export_guild_data(111)

        self.assertEqual(exported["warnings"]["42"][0]["reason"], "spam")
        self.assertEqual(exported["reminders"][0]["message"], "mine")
        self.assertIn("voice_sessions", exported["voice_state"])
        self.assertEqual(exported["dashboard_audit"][0]["ip"], "127.0.0.1")
        self.assertNotIn("222", json.dumps(exported))

    def test_guild_erasure_is_complete_and_keeps_other_guilds(self):
        report = privacy.erase_guild_data("111")

        self.assertGreater(sum(report["counts"].values()), 0)
        erased = privacy.export_guild_data("111")
        self.assertEqual(sum(erased["counts"].values()), 0)
        other = privacy.export_guild_data("222")
        self.assertEqual(other["levels"][0]["user_id"], "99")
        self.assertEqual(other["reminders"][0]["message"], "other")
        self.assertIn("voice_sessions", other["voice_state"])
        legacy = json.loads((self.root / "settings.json").read_text())
        self.assertNotIn("111", legacy)
        self.assertIn("222", legacy)


if __name__ == "__main__":
    unittest.main()
