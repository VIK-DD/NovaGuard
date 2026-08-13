"""Removing NovaGuard from a server schedules erasure instead of performing it."""

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import database, guild_grace  # noqa: E402


class GuildGraceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        patches = [
            mock.patch.object(database, "DATA_DIR", self.root),
            mock.patch.object(database, "DB_PATH", self.root / "novaguard.sqlite3"),
            mock.patch.object(database, "_INITIALIZED", False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        database.init_database()
        self.now = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)

    def test_scheduling_stores_a_deadline_one_grace_window_away(self):
        row = guild_grace.schedule_guild_deletion("111", now=self.now, env={})

        self.assertEqual(row["guild_id"], "111")
        self.assertEqual(row["scheduled_at"], self.now.isoformat())
        self.assertEqual(row["deadline"], (self.now + timedelta(days=30)).isoformat())
        self.assertEqual(
            [entry["guild_id"] for entry in guild_grace.pending_guild_deletions()],
            ["111"],
        )

    def test_a_numeric_guild_id_is_stored_as_text(self):
        # discord.py hands over guild.id as an int while every table stores TEXT.
        # A mismatch here would silently never match on the way out.
        guild_grace.schedule_guild_deletion(111, now=self.now, env={})

        self.assertEqual(
            [entry["guild_id"] for entry in guild_grace.pending_guild_deletions()],
            ["111"],
        )
        self.assertTrue(guild_grace.cancel_guild_deletion("111"))

    def test_rescheduling_keeps_the_original_deadline(self):
        # Otherwise a repeated kick/re-add cycle would push the deadline forward
        # forever and the data would never actually be erased.
        first = guild_grace.schedule_guild_deletion("111", now=self.now, env={})
        second = guild_grace.schedule_guild_deletion(
            "111", now=self.now + timedelta(days=10), env={}
        )

        self.assertEqual(second["deadline"], first["deadline"])
        self.assertEqual(second["scheduled_at"], first["scheduled_at"])
        self.assertEqual(len(guild_grace.pending_guild_deletions()), 1)

    def test_cancelling_removes_the_row_and_reports_whether_one_existed(self):
        guild_grace.schedule_guild_deletion("111", now=self.now, env={})

        self.assertTrue(guild_grace.cancel_guild_deletion("111"))
        self.assertEqual(guild_grace.pending_guild_deletions(), [])
        self.assertFalse(guild_grace.cancel_guild_deletion("111"))

    def test_only_guilds_past_their_deadline_are_due(self):
        guild_grace.schedule_guild_deletion("expired", now=self.now, env={})
        guild_grace.schedule_guild_deletion(
            "current", now=self.now + timedelta(days=20), env={}
        )

        due = guild_grace.due_guild_deletions(now=self.now + timedelta(days=31))

        self.assertEqual(due, ["expired"])

    def test_nothing_is_due_before_the_window_closes(self):
        guild_grace.schedule_guild_deletion("111", now=self.now, env={})

        due = guild_grace.due_guild_deletions(now=self.now + timedelta(days=29))

        self.assertEqual(due, [])

    def test_a_malformed_grace_window_falls_back_to_the_default(self):
        row = guild_grace.schedule_guild_deletion(
            "111", now=self.now, env={guild_grace.GRACE_DAYS_KEY: "not a number"}
        )

        self.assertEqual(row["deadline"], (self.now + timedelta(days=30)).isoformat())

    def test_the_grace_window_is_clamped_to_a_sane_range(self):
        guild_grace.schedule_guild_deletion(
            "low", now=self.now, env={guild_grace.GRACE_DAYS_KEY: "0"}
        )
        guild_grace.schedule_guild_deletion(
            "high", now=self.now, env={guild_grace.GRACE_DAYS_KEY: "999999"}
        )

        deadlines = {
            entry["guild_id"]: entry["deadline"]
            for entry in guild_grace.pending_guild_deletions()
        }
        self.assertEqual(deadlines["low"], (self.now + timedelta(days=1)).isoformat())
        self.assertEqual(
            deadlines["high"], (self.now + timedelta(days=3650)).isoformat()
        )

    def test_a_configured_window_is_honoured(self):
        row = guild_grace.schedule_guild_deletion(
            "111", now=self.now, env={guild_grace.GRACE_DAYS_KEY: "7"}
        )

        self.assertEqual(row["deadline"], (self.now + timedelta(days=7)).isoformat())


if __name__ == "__main__":
    unittest.main()
