"""Several threads writing at once, and the rule that keeps them apart.

Every flush loop in the bot writes through asyncio.to_thread, so real threads
reach SQLite at the same moment. What stops them colliding is a single
process-wide lock that every writer takes, with WAL and a thirty second busy
timeout underneath it.

Nothing here is currently broken — all thirteen writers hold the lock. That
is exactly why it is worth a test: the fourteenth is the one that will not,
and the symptom would be an intermittent "database is locked" under load,
which is close to unreproducible once it reaches a live host.
"""

import ast
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import database  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GUILD = 1


class LockDisciplineTests(unittest.TestCase):
    """Read from the source, not from memory of how it is meant to work."""

    def setUp(self):
        self.source = (ROOT / "core" / "database.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    @staticmethod
    def _writes(node):
        for inner in ast.walk(node):
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                head = inner.value.strip().upper()
                if head.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
                    return True
        return False

    @staticmethod
    def _takes_lock(node):
        for inner in ast.walk(node):
            if isinstance(inner, ast.With):
                for item in inner.items:
                    if "_LOCK" in ast.unparse(item.context_expr):
                        return True
        return False

    def _writers(self):
        return [
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and self._writes(node)
        ]

    def test_every_writer_takes_the_lock(self):
        offenders = [node.name for node in self._writers() if not self._takes_lock(node)]

        self.assertEqual(offenders, [], "these write without holding _LOCK")

    def test_there_are_writers_to_check_at_all(self):
        # Without this the test above passes trivially if the detection ever
        # breaks — a guard that silently stops guarding is worse than none.
        self.assertGreater(len(self._writers()), 5)

    def test_the_connection_is_opened_for_concurrent_use(self):
        # WAL lets readers continue during a write; the busy timeout makes a
        # contended writer wait instead of failing immediately.
        self.assertIn("journal_mode=WAL", self.source)
        self.assertIn("timeout=30", self.source)


class ConcurrentWriteTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._old_path = database.DB_PATH
        self._old_initialized = database._INITIALIZED
        database.DB_PATH = Path(self._temp.name) / "test.sqlite3"
        database._INITIALIZED = False
        database.init_database()

    def tearDown(self):
        database.DB_PATH = self._old_path
        database._INITIALIZED = self._old_initialized
        self._temp.cleanup()

    def run_together(self, jobs):
        """Start every job at the same moment and collect what went wrong."""
        errors = []
        start = threading.Barrier(len(jobs))

        def wrapped(job):
            def run():
                start.wait()
                try:
                    job()
                except Exception as error:  # noqa: BLE001 - seeing it is the point
                    errors.append(error)

            return run

        threads = [threading.Thread(target=wrapped(job)) for job in jobs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        return errors

    def test_twenty_writers_at_once_all_land(self):
        jobs = [
            (lambda n=n: database.set_guild_setting(GUILD, f"key_{n}", f"value_{n}"))
            for n in range(20)
        ]

        errors = self.run_together(jobs)

        self.assertEqual(errors, [])
        saved = database.get_guild_settings_db(GUILD)
        self.assertEqual(len(saved), 20)
        self.assertEqual(saved["key_7"], "value_7")

    def test_writers_and_readers_together_never_see_a_locked_database(self):
        # This failure is intermittent and load-dependent, which makes it
        # nearly unreproducible once it reaches a live host.
        jobs = []
        for n in range(10):
            jobs.append(lambda n=n: database.set_guild_setting(GUILD, f"k{n}", str(n)))
            jobs.append(lambda: database.get_guild_settings_db(GUILD))

        errors = self.run_together(jobs)

        locked = [e for e in errors if isinstance(e, sqlite3.OperationalError)]
        self.assertEqual(locked, [], f"database reported a lock conflict: {locked}")
        self.assertEqual(errors, [])

    def test_the_same_key_written_by_everyone_ends_on_one_of_the_values(self):
        # Last write wins is the accepted outcome. What must not happen is a
        # crash, or a row left holding something nobody wrote.
        jobs = [
            (lambda n=n: database.set_guild_setting(GUILD, "shared", f"v{n}")) for n in range(15)
        ]

        errors = self.run_together(jobs)

        self.assertEqual(errors, [])
        final = database.get_guild_settings_db(GUILD)["shared"]
        self.assertIn(final, {f"v{n}" for n in range(15)})

    def test_wallet_and_level_flushes_can_run_at_the_same_time(self):
        # Two separate loops in the live bot, on their own schedules, and they
        # do overlap.
        wallets = [
            (
                str(GUILD),
                str(uid),
                {
                    "coins": uid,
                    "daily_streak": 0,
                    "last_daily": None,
                    "last_work": None,
                    "trophies": [],
                },
            )
            for uid in range(100, 110)
        ]
        records = [
            (str(GUILD), str(uid), {"xp": uid, "level": 1, "messages": uid})
            for uid in range(200, 210)
        ]

        errors = self.run_together(
            [
                lambda: database.upsert_economy_wallets(wallets),
                lambda: database.upsert_level_records(records),
                lambda: database.set_guild_setting(GUILD, "while_flushing", "ok"),
            ]
        )

        self.assertEqual(errors, [])
        self.assertEqual(database.load_economy_data()[str(GUILD)]["105"]["coins"], 105)
        self.assertEqual(database.get_guild_settings_db(GUILD)["while_flushing"], "ok")

    def test_a_repeated_flush_of_the_same_rows_does_not_duplicate_them(self):
        # The upserts are the hot path and run every minute. A missing
        # conflict clause would grow the table forever without ever failing.
        wallets = [
            (
                str(GUILD),
                "100",
                {
                    "coins": 5,
                    "daily_streak": 0,
                    "last_daily": None,
                    "last_work": None,
                    "trophies": [],
                },
            )
        ]

        errors = self.run_together([lambda: database.upsert_economy_wallets(wallets)] * 8)

        self.assertEqual(errors, [])
        with database.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM economy_wallets").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
