"""How the JSON state files are written, and who can read them afterwards.

`save_json_file` backs the moderation warnings, giveaway entrant lists,
reminder text and voice state. It had three defects at once:

* one fixed scratch filename, `<name>.tmp`, shared by every writer. Two
  concurrent saves of the same file raced on it - measured over 30 paired
  writes, 12 raised FileNotFoundError at `os.replace` because the other thread
  had already consumed the temp file, and every one of those is a lost write;
* no mode, so the result was 0644 - world-readable, beside a SQLite file the
  same package takes care to keep at 0600 and a `production_check` that treats
  a readable database as CRITICAL;
* no fsync, so a power cut between write and rename could leave a zero-length
  file, which `load_json_file` reads as "no state" rather than as damage.
"""

import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import load_json_file, save_json_file  # noqa: E402


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.dir = Path(self._temp.name)
        self.path = self.dir / "state.json"

    def test_a_simple_write_round_trips(self):
        save_json_file(self.path, {"hello": "world"})
        self.assertEqual(load_json_file(self.path, None), {"hello": "world"})

    def test_concurrent_writers_never_lose_a_write_to_an_exception(self):
        # The regression. Every thread must get its own scratch file.
        errors = []

        def write(payload):
            try:
                save_json_file(self.path, payload)
            except Exception as error:  # noqa: BLE001 - the point is to catch any
                errors.append(error)

        for _ in range(30):
            threads = [
                threading.Thread(target=write, args=({"who": "A", "pad": "a" * 2000},)),
                threading.Thread(target=write, args=({"who": "B", "pad": "b" * 2000},)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(errors, [], f"{len(errors)} concurrent writes raised")

    def test_the_file_is_always_readable_json_after_concurrent_writes(self):
        def write(payload):
            try:
                save_json_file(self.path, payload)
            except Exception:  # noqa: BLE001
                pass

        for _ in range(30):
            threads = [
                threading.Thread(target=write, args=({"who": "A", "pad": "a" * 4000},)),
                threading.Thread(target=write, args=({"who": "B", "pad": "b" * 4000},)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertIn(data.get("who"), ("A", "B"), "a torn write was observed")

    def test_no_scratch_files_are_left_behind(self):
        save_json_file(self.path, {"x": 1})
        leftovers = [item.name for item in self.dir.iterdir() if item.name != "state.json"]
        self.assertEqual(leftovers, [])

    def test_a_failed_write_leaves_no_scratch_file_and_no_damage(self):
        save_json_file(self.path, {"good": True})

        class Unserialisable:
            pass

        with self.assertRaises(TypeError):
            save_json_file(self.path, {"bad": Unserialisable()})

        # The previous good content survives, and nothing is left over.
        self.assertEqual(load_json_file(self.path, None), {"good": True})
        leftovers = [item.name for item in self.dir.iterdir() if item.name != "state.json"]
        self.assertEqual(leftovers, [])


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.dir = Path(self._temp.name) / "data"
        self.path = self.dir / "warns.json"

    def test_the_written_file_is_owner_only(self):
        save_json_file(self.path, {"guild": {"member": ["a reason"]}})
        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(
            mode & 0o077, 0, f"state file is group/world readable: {oct(mode)}"
        )

    def test_the_directory_is_owner_only(self):
        save_json_file(self.path, {"x": 1})
        mode = stat.S_IMODE(self.dir.stat().st_mode)
        self.assertEqual(mode & 0o077, 0, f"data directory is traversable: {oct(mode)}")

    def test_an_overwrite_keeps_the_restricted_mode(self):
        save_json_file(self.path, {"x": 1})
        os.chmod(self.path, 0o644)
        save_json_file(self.path, {"x": 2})
        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(mode & 0o077, 0, "a rewrite reopened the file to everyone")


class GuildSettingsTransactionTests(unittest.TestCase):
    """A settings patch from the dashboard applies whole, or not at all."""

    def test_a_multi_key_patch_is_written_in_one_transaction(self):
        # Source inspection rather than a fault-injection harness: the property
        # is structural - one connect(), one commit, for the whole patch.
        import inspect

        from core import database

        source = inspect.getsource(database.update_guild_settings_db)
        self.assertEqual(
            source.count("connect()"), 1, "a settings patch still opens one connection per key"
        )
        self.assertNotIn(
            "set_guild_setting(", source, "the patch still delegates key by key"
        )

    def test_a_patch_still_applies_every_key(self):
        import tempfile as _tempfile
        from unittest import mock

        from core import database

        with _tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "novaguard.sqlite3"
            with (
                mock.patch.object(database, "DB_PATH", path),
                mock.patch.object(database, "DATA_DIR", path.parent),
                mock.patch.object(database, "_INITIALIZED", False),
            ):
                database.update_guild_settings_db(
                    "1", welcome_channel=123, log_channel=456, autorole=None
                )
                saved = database.get_guild_settings_db("1")
        self.assertEqual(saved.get("welcome_channel"), 123)
        self.assertEqual(saved.get("log_channel"), 456)
        self.assertNotIn("autorole", saved)


if __name__ == "__main__":
    unittest.main()
