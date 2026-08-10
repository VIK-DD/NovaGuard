"""Tests for the per-guild export a server owner can take of their own data."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class GuildExportTests(unittest.TestCase):
    """A server owner gets everything of theirs, and nothing of anyone else's.

    That isolation is the whole point: the /backup group archives every guild
    at once and belongs to the bot owner, so this is the path that lets a
    single server take its data out without exposing the rest.
    """

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

        import core.database as database

        self.database = database
        self._patches = [
            mock.patch.object(database, "DATA_DIR", Path(self._dir.name)),
            mock.patch.object(database, "DB_PATH", Path(self._dir.name) / "test.sqlite3"),
            mock.patch.object(database, "_INITIALIZED", False),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)

        database.init_database()
        self._seed()

    def _seed(self):
        with self.database.connect() as connection:
            for guild, key, value in (
                ("111", "welcome_channel", '"general"'),
                ("111", "log_channel", '"logs"'),
                ("222", "welcome_channel", '"other-server"'),
            ):
                connection.execute(
                    "INSERT INTO guild_settings (guild_id, key, value, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (guild, key, value, "2026-01-01T00:00:00+00:00"),
                )
            stamp = "2026-01-01T00:00:00+00:00"
            for guild, user, xp in (("111", "a", 500), ("111", "b", 100), ("222", "c", 999)):
                connection.execute(
                    "INSERT INTO level_records"
                    " (guild_id, user_id, xp, messages, last_gain, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (guild, user, xp, 10, stamp, stamp),
                )
            for guild, user, coins in (("111", "a", 50), ("222", "c", 7777)):
                connection.execute(
                    "INSERT INTO economy_wallets"
                    " (guild_id, user_id, coins, daily_streak, last_daily, last_work,"
                    " trophies, updated_at)"
                    " VALUES (?, ?, ?, 0, ?, ?, '[]', ?)",
                    (guild, user, coins, stamp, stamp, stamp),
                )
            connection.commit()

    def test_the_export_carries_this_guilds_own_data(self):
        payload = self.database.export_guild_data("111")

        self.assertEqual(payload["guild_id"], "111")
        self.assertEqual(payload["settings"]["welcome_channel"], "general")
        self.assertEqual({row["user_id"] for row in payload["levels"]}, {"a", "b"})
        self.assertEqual({row["user_id"] for row in payload["economy"]}, {"a"})

    def test_no_other_guild_leaks_into_the_export(self):
        blob = repr(self.database.export_guild_data("111"))

        self.assertNotIn("other-server", blob)
        self.assertNotIn("999", blob)
        self.assertNotIn("7777", blob)

    def test_counts_describe_what_was_exported(self):
        payload = self.database.export_guild_data("111")

        self.assertEqual(
            payload["counts"], {"settings": 2, "levels": 2, "economy": 1, "voice": 0}
        )

    def test_a_guild_with_no_data_exports_an_empty_shell(self):
        payload = self.database.export_guild_data("999999")

        self.assertEqual(payload["settings"], {})
        self.assertEqual(payload["levels"], [])
        self.assertEqual(payload["economy"], [])
        self.assertEqual(payload["voice"], [])

    def test_ids_are_accepted_as_numbers_too(self):
        self.assertEqual(
            self.database.export_guild_data(111)["counts"],
            self.database.export_guild_data("111")["counts"],
        )

    def test_the_export_is_timestamped(self):
        self.assertTrue(self.database.export_guild_data("111")["exported_at"])


if __name__ == "__main__":
    unittest.main()
