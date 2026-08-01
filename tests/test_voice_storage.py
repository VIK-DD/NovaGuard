"""Tests for SQLite-backed voice report state."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as database


class VoiceStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_data_dir = database.DATA_DIR
        self.old_db_path = database.DB_PATH
        self.old_voice_store_files = database.VOICE_STORE_FILES
        self.old_initialized = database._INITIALIZED

        database.DATA_DIR = self.root / "data"
        database.DB_PATH = database.DATA_DIR / "novaguard.sqlite3"
        database.VOICE_STORE_FILES = {
            "voice_sessions": database.DATA_DIR / "voice_sessions.json",
            "voice_pending_reports": database.DATA_DIR / "voice_pending_reports.json",
            "voice_report_history": database.DATA_DIR / "voice_report_history.json",
        }
        database._INITIALIZED = False
        database.DATA_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        database.DATA_DIR = self.old_data_dir
        database.DB_PATH = self.old_db_path
        database.VOICE_STORE_FILES = self.old_voice_store_files
        database._INITIALIZED = self.old_initialized
        self.temp_dir.cleanup()

    def test_legacy_voice_json_migrates_to_sqlite_once(self):
        database.VOICE_STORE_FILES["voice_sessions"].write_text(
            '{"123": {"456": {"channel_id": "456", "members": {}}}}',
            encoding="utf-8",
        )

        loaded = database.load_voice_store("voice_sessions", {})
        database.VOICE_STORE_FILES["voice_sessions"].write_text('{"123": {"999": {}}}', encoding="utf-8")
        loaded_again = database.load_voice_store("voice_sessions", {})

        self.assertIn("456", loaded["123"])
        self.assertEqual(loaded_again, loaded)

    def test_voice_store_round_trips_through_sqlite(self):
        payload = {"123": {"report-1": {"attempts": 2, "last_error": "timeout"}}}

        database.save_voice_store("voice_pending_reports", payload)
        loaded = database.load_voice_store("voice_pending_reports", {})
        status = database.get_voice_store_status()

        self.assertEqual(loaded, payload)
        self.assertEqual(status["voice_pending_reports"]["guild_count"], 1)
        self.assertEqual(status["voice_pending_reports"]["item_count"], 1)


if __name__ == "__main__":
    unittest.main()
