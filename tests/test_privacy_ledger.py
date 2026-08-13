"""Deletion ledger prevents old restores from reviving erased subjects."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from core.privacy_ledger import (
    PrivacyLedgerError,
    apply_deletion_ledger,
    load_deletion_ledger,
    record_deletion,
)


TEST_KEY = "privacy-ledger-test-key-2026-xxxxxxxxxxxxxxxx"


class PrivacyLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ledger = self.root / ".privacy_deletions.json"
        self.old_key = os.environ.get("BACKUP_ENCRYPTION_KEY")
        os.environ["BACKUP_ENCRYPTION_KEY"] = TEST_KEY
        self.addCleanup(self._restore_key)

    def _restore_key(self):
        if self.old_key is None:
            os.environ.pop("BACKUP_ENCRYPTION_KEY", None)
        else:
            os.environ["BACKUP_ENCRYPTION_KEY"] = self.old_key

    def _restore_tree(self):
        restore = self.root / "restore"
        data = restore / "data"
        data.mkdir(parents=True)
        database = data / "novaguard.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript(
                """
                CREATE TABLE level_records (guild_id TEXT, user_id TEXT, xp INTEGER);
                CREATE TABLE economy_wallets (guild_id TEXT, user_id TEXT, coins INTEGER);
                CREATE TABLE voice_minutes (guild_id TEXT, user_id TEXT, month TEXT);
                CREATE TABLE ticket_records (
                    thread_id TEXT, guild_id TEXT, opener_id TEXT, closed_by TEXT
                );
                CREATE TABLE role_panels (message_id TEXT, guild_id TEXT, created_by TEXT);
                CREATE TABLE admin_audit (
                    id INTEGER, actor_id TEXT NOT NULL, actor_name TEXT
                );
                CREATE TABLE voice_state (store TEXT, payload TEXT);
                CREATE TABLE web_sessions (
                    sid_hash TEXT, user_id TEXT, guilds_json TEXT
                );
                CREATE TABLE web_audit (id INTEGER, guild_id TEXT, user_id TEXT);
                CREATE TABLE pending_guild_deletions (
                    guild_id TEXT PRIMARY KEY, scheduled_at TEXT, deadline TEXT
                );

                INSERT INTO level_records VALUES ('111', '42', 500), ('222', '99', 800);
                INSERT INTO economy_wallets VALUES ('111', '42', 50), ('222', '99', 80);
                INSERT INTO voice_minutes VALUES ('111', '42', '2026-08'), ('222', '99', '2026-08');
                INSERT INTO ticket_records VALUES ('a', '111', '42', NULL);
                INSERT INTO ticket_records VALUES ('b', '222', '99', '42');
                INSERT INTO role_panels VALUES ('panel', '222', '42');
                INSERT INTO admin_audit VALUES (1, '42', 'Victor');
                INSERT INTO web_sessions VALUES ('mine', '42', '{"111": {}, "222": {}}');
                INSERT INTO web_sessions VALUES ('other', '99', '{"111": {}, "222": {}}');
                INSERT INTO web_audit VALUES (1, '111', '99'), (2, '222', '42'), (3, '222', '99');
                INSERT INTO pending_guild_deletions VALUES
                    ('111', '2026-08-10T00:00:00+00:00', '2026-09-09T00:00:00+00:00'),
                    ('222', '2026-08-10T00:00:00+00:00', '2026-09-09T00:00:00+00:00');
                """
            )
            connection.execute(
                "INSERT INTO voice_state VALUES (?, ?)",
                (
                    "voice_sessions",
                    json.dumps(
                        {
                            "111": {"room": {"members": {"42": {}}}},
                            "222": {"room": {"members": {"42": {}, "99": {}}}},
                        }
                    ),
                ),
            )
            connection.commit()

        fixtures = {
            "settings.json": {"111": {"enabled": True}, "222": {"enabled": True}},
            "warns.json": {
                "111": {"42": [{"reason": "old"}]},
                "222": {"99": [{"moderator_id": "42"}]},
            },
            "giveaways.json": [
                {"guild_id": "111", "host_id": "99", "entrants": ["99"]},
                {
                    "guild_id": "222",
                    "host_id": "42",
                    "host_name": "Victor",
                    "entrants": ["42", "99"],
                },
            ],
        }
        for name, payload in fixtures.items():
            (data / name).write_text(json.dumps(payload), encoding="utf-8")
        return restore, database

    def test_ledger_never_stores_raw_discord_ids_and_detects_wrong_key(self):
        record_deletion(
            "user", "123456789012345678", path=self.ledger,
            deleted_at="2026-08-12T01:00:00+00:00",
        )

        raw = self.ledger.read_text(encoding="utf-8")
        payload = load_deletion_ledger(self.ledger, require=True)

        self.assertNotIn("123456789012345678", raw)
        self.assertEqual(len(payload["users"]), 1)
        self.assertEqual(self.ledger.stat().st_mode & 0o777, 0o600)
        with mock.patch.dict(
            os.environ,
            {"BACKUP_ENCRYPTION_KEY": "different-privacy-ledger-key-xxxxxxxxxxxx"},
        ):
            with self.assertRaisesRegex(PrivacyLedgerError, "does not match"):
                load_deletion_ledger(self.ledger, require=True)

    def test_ledger_tampering_is_detected_before_restore(self):
        record_deletion(
            "user", "42", path=self.ledger,
            deleted_at="2026-08-12T01:00:00+00:00",
        )
        payload = json.loads(self.ledger.read_text(encoding="utf-8"))
        payload["users"].clear()
        self.ledger.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(PrivacyLedgerError, "integrity check failed"):
            load_deletion_ledger(self.ledger, require=True)

    def test_restoring_a_snapshot_cannot_revive_a_marker_for_an_erased_guild(self):
        # A snapshot taken while a server was inside its grace window still
        # holds that marker. If the server was erased for real afterwards, the
        # restored marker would describe a deletion that already happened.
        record_deletion(
            "guild", "111", path=self.ledger,
            deleted_at="2026-08-12T02:00:00+00:00",
        )
        restore, database = self._restore_tree()

        apply_deletion_ledger(
            restore,
            ledger_path=self.ledger,
            snapshot_created_at="2026-08-11T00:00:00+00:00",
        )

        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT guild_id FROM pending_guild_deletions"
                ).fetchall(),
                [("222",)],
            )

    def test_old_snapshot_is_scrubbed_without_touching_other_subjects(self):
        record_deletion(
            "user", "42", path=self.ledger,
            deleted_at="2026-08-12T01:00:00+00:00",
        )
        record_deletion(
            "guild", "111", path=self.ledger,
            deleted_at="2026-08-12T02:00:00+00:00",
        )
        restore, database = self._restore_tree()

        report = apply_deletion_ledger(
            restore,
            ledger_path=self.ledger,
            snapshot_created_at="2026-08-11T00:00:00+00:00",
        )

        self.assertGreater(report["removed_or_anonymised"], 0)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(
                connection.execute("SELECT guild_id, user_id FROM level_records").fetchall(),
                [("222", "99")],
            )
            self.assertEqual(
                connection.execute("SELECT actor_id, actor_name FROM admin_audit").fetchone(),
                ("deleted-user", None),
            )
            self.assertIsNone(
                connection.execute("SELECT closed_by FROM ticket_records WHERE thread_id='b'").fetchone()[0]
            )
            self.assertEqual(
                json.loads(
                    connection.execute(
                        "SELECT guilds_json FROM web_sessions WHERE sid_hash='other'"
                    ).fetchone()[0]
                ),
                {"222": {}},
            )
            voice = json.loads(connection.execute("SELECT payload FROM voice_state").fetchone()[0])
        self.assertNotIn("111", voice)
        self.assertNotIn("42", voice["222"]["room"]["members"])
        self.assertIn("99", voice["222"]["room"]["members"])

        settings = json.loads((restore / "data" / "settings.json").read_text())
        warnings = json.loads((restore / "data" / "warns.json").read_text())
        giveaways = json.loads((restore / "data" / "giveaways.json").read_text())
        self.assertNotIn("111", settings)
        self.assertIsNone(warnings["222"]["99"][0]["moderator_id"])
        self.assertEqual(len(giveaways), 1)
        self.assertIsNone(giveaways[0]["host_id"])
        self.assertEqual(giveaways[0]["entrants"], ["99"])

    def test_snapshot_created_after_deletion_keeps_new_voluntary_data(self):
        record_deletion(
            "user", "42", path=self.ledger,
            deleted_at="2026-08-10T00:00:00+00:00",
        )
        restore, database = self._restore_tree()

        report = apply_deletion_ledger(
            restore,
            ledger_path=self.ledger,
            snapshot_created_at="2026-08-11T00:00:00+00:00",
        )

        self.assertEqual(report["active_user_deletions"], 0)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(
                connection.execute("SELECT xp FROM level_records WHERE user_id='42'").fetchone(),
                (500,),
            )


if __name__ == "__main__":
    unittest.main()
