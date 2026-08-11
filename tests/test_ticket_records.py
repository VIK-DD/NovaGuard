"""Ticket state stays isolated, durable and idempotent in SQLite."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as database  # noqa: E402


class TicketRecordTests(unittest.TestCase):
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

    def test_open_lookup_and_close_lifecycle(self):
        created_at = database.create_ticket_record("1", "10", "100", "7", "Victor")
        open_record = database.open_ticket_for_member("1", "7")

        self.assertEqual(open_record["thread_id"], "10")
        self.assertEqual(open_record["created_at"], created_at)
        self.assertEqual(database.count_open_tickets("1"), 1)
        self.assertTrue(database.close_ticket_record("10", "9"))
        self.assertFalse(database.close_ticket_record("10", "9"))
        self.assertIsNone(database.open_ticket_for_member("1", "7"))
        self.assertEqual(database.count_open_tickets("1"), 0)

        closed = database.list_ticket_records("1")[0]
        self.assertIsNotNone(closed["closed_at"])
        self.assertEqual(closed["closed_by"], "9")

    def test_guilds_never_see_each_others_tickets(self):
        database.create_ticket_record("1", "10", "100", "7", "One")
        database.create_ticket_record("2", "20", "200", "7", "Two")

        self.assertEqual([row["thread_id"] for row in database.list_ticket_records("1")], ["10"])
        self.assertEqual([row["thread_id"] for row in database.list_ticket_records("2")], ["20"])

    def test_reopening_the_same_thread_resets_stale_closed_state(self):
        database.create_ticket_record("1", "10", "100", "7", "Old name")
        database.close_ticket_record("10", "9")
        database.create_ticket_record("1", "10", "100", "7", "New name")

        record = database.open_ticket_for_member("1", "7")
        self.assertEqual(record["opener_name"], "New name")
        self.assertIsNone(record["closed_at"])


if __name__ == "__main__":
    unittest.main()
