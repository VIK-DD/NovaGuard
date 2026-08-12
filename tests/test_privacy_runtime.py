"""Privacy erasure also clears in-memory feature caches."""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs import privacy as privacy_cog  # noqa: E402


class FakeFeatureCog:
    def __init__(self, data):
        self.data = data
        self.dirty_keys = {("111", "42"), ("222", "99")}
        self.flush_lock = asyncio.Lock()


class FakeVoiceCog:
    def __init__(self):
        self.sessions = {"111": {"room": {"members": {"42": {}, "99": {}}}}, "222": {}}
        self.pending_reports = {"111": {"report": {"user_id": "42"}}, "222": {}}
        self.report_history = {"111": [{"session": {"members": {"42": {}, "99": {}}}}], "222": []}
        self._persist_lock = asyncio.Lock()
        self._pending_lock = asyncio.Lock()
        self._history_lock = asyncio.Lock()


class FakeBot:
    def __init__(self):
        self.cogs = {
            "Levels": FakeFeatureCog({"111": {"42": {"xp": 1}, "99": {"xp": 2}}, "222": {"99": {}}}),
            "Economy": FakeFeatureCog({"111": {"42": {"coins": 1}, "99": {"coins": 2}}, "222": {"99": {}}}),
            "VoiceReports": FakeVoiceCog(),
        }

    def get_cog(self, name):
        return self.cogs.get(name)


class PrivacyRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_erasure_cannot_be_undone_by_dirty_caches(self):
        bot = FakeBot()
        with mock.patch.object(privacy_cog, "erase_user_data", return_value={"counts": {}}):
            await privacy_cog.erase_live_user_data(bot, "42")

        self.assertNotIn("42", bot.cogs["Levels"].data["111"])
        self.assertNotIn(("111", "42"), bot.cogs["Levels"].dirty_keys)
        self.assertNotIn("42", bot.cogs["Economy"].data["111"])
        self.assertNotIn("42", bot.cogs["VoiceReports"].sessions["111"]["room"]["members"])
        self.assertEqual(bot.cogs["VoiceReports"].pending_reports["111"], {})

    async def test_guild_erasure_keeps_other_guild_caches(self):
        bot = FakeBot()
        with mock.patch.object(privacy_cog, "erase_guild_data", return_value={"counts": {}}):
            await privacy_cog.erase_live_guild_data(bot, 111)

        for cog_name in ("Levels", "Economy"):
            self.assertNotIn("111", bot.cogs[cog_name].data)
            self.assertIn("222", bot.cogs[cog_name].data)
        self.assertNotIn("111", bot.cogs["VoiceReports"].sessions)
        self.assertIn("222", bot.cogs["VoiceReports"].sessions)


if __name__ == "__main__":
    unittest.main()
