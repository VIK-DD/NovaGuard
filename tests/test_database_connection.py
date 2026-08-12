"""SQLite context management releases file handles deterministically."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from core import database


class DatabaseConnectionTests(unittest.TestCase):
    def test_context_manager_commits_and_closes_the_connection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "novaguard.sqlite3"
            with mock.patch.object(database, "DB_PATH", path), mock.patch.object(
                database, "DATA_DIR", path.parent
            ):
                with database.connect() as connection:
                    connection.execute("CREATE TABLE sample (value TEXT)")
                    connection.execute("INSERT INTO sample VALUES ('saved')")

                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")
                with closing(sqlite3.connect(path)) as verification:
                    self.assertEqual(
                        verification.execute("SELECT value FROM sample").fetchone(),
                        ("saved",),
                    )


if __name__ == "__main__":
    unittest.main()
