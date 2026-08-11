"""Role panel input, publishing and SQLite records stay consistent."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as database  # noqa: E402
from cogs.roles import publish_role_panel, validate_role_panel_input  # noqa: E402


class FakeRole:
    def __init__(self, role_id, name):
        self.id = role_id
        self.name = name
        self.mention = f"<@&{role_id}>"


class FakeMessage:
    def __init__(self, message_id=500):
        self.id = message_id
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class FakeChannel:
    def __init__(self):
        self.messages = {}
        self.sent = []

    async def send(self, **kwargs):
        message = FakeMessage()
        self.messages[message.id] = message
        self.sent.append(kwargs)
        return message

    async def fetch_message(self, message_id):
        return self.messages[message_id]


class RolePanelTests(unittest.IsolatedAsyncioTestCase):
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

    def test_validation_normalizes_text_and_deduplicates_roles(self):
        title, description, roles, errors = validate_role_panel_input(
            "  Game   roles ", " Pick   your team ", [1, "1", 2]
        )
        self.assertEqual((title, description), ("Game roles", "Pick your team"))
        self.assertEqual(roles, ["1", "2"])
        self.assertEqual(errors, [])

    def test_validation_rejects_empty_and_oversized_payloads(self):
        *_, errors = validate_role_panel_input("", "", list(range(6)))
        self.assertEqual(len(errors), 3)

    async def test_publish_updates_the_existing_message(self):
        channel = FakeChannel()
        roles = [FakeRole(1, "News")]
        message, created = await publish_role_panel(channel, "Updates", "Choose", roles)
        updated, created_again = await publish_role_panel(
            channel, "Updates", "Choose again", roles, message.id
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertIs(updated, message)
        self.assertEqual(len(channel.sent), 1)
        self.assertEqual(len(message.edits), 1)

    def test_database_replaces_a_missing_message_without_leaving_a_ghost(self):
        database.save_role_panel_record("1", "10", "100", "One", "First", [7])
        database.save_role_panel_record(
            "1", "11", "100", "Two", "Second", [8, 9], previous_message_id="10"
        )
        panels = database.list_role_panel_records("1")
        self.assertEqual([panel["message_id"] for panel in panels], ["11"])
        self.assertEqual(panels[0]["role_ids"], ["8", "9"])
        self.assertIsNone(database.get_role_panel_record("1", "10"))

    def test_database_isolates_guilds(self):
        database.save_role_panel_record("1", "10", "100", "One", "First", [7])
        database.save_role_panel_record("2", "20", "200", "Two", "Second", [8])
        self.assertEqual(len(database.list_role_panel_records("1")), 1)
        self.assertEqual(len(database.list_role_panel_records("2")), 1)
        self.assertIsNone(database.get_role_panel_record("1", "20"))


if __name__ == "__main__":
    unittest.main()
