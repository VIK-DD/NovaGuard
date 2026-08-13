"""Removal schedules erasure; only a closed grace window actually erases."""

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs import privacy as privacy_cog  # noqa: E402
from core import database, guild_grace, storage  # noqa: E402


class FakeBot:
    """A bot present in the given guilds and holding no feature cogs."""

    def __init__(self, guild_ids=()):
        self.guilds = [SimpleNamespace(id=int(guild_id)) for guild_id in guild_ids]

    def get_cog(self, name):
        return None


def _pending():
    return [entry["guild_id"] for entry in guild_grace.pending_guild_deletions()]


class GuildGraceFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        patches = [
            mock.patch.object(database, "DATA_DIR", self.root),
            mock.patch.object(database, "DB_PATH", self.root / "novaguard.sqlite3"),
            mock.patch.object(database, "_INITIALIZED", False),
            mock.patch.object(storage, "DATA_DIR", self.root),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        database.init_database()
        self.now = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)

    async def test_removal_schedules_erasure_instead_of_performing_it(self):
        cog = privacy_cog.Privacy(FakeBot())
        erase = mock.AsyncMock()

        with mock.patch.object(privacy_cog, "erase_live_guild_data", erase):
            await cog.on_guild_remove(SimpleNamespace(id=111))

        erase.assert_not_awaited()
        self.assertEqual(_pending(), ["111"])

    async def test_an_explicit_server_delete_is_not_downgraded_to_pending(self):
        # /privacy server-delete erases, then leaves, which fires this listener.
        # Converting that into a pending deletion would defy the owner.
        cog = privacy_cog.Privacy(FakeBot())
        cog._erased_on_request.add(111)

        await cog.on_guild_remove(SimpleNamespace(id=111))

        self.assertEqual(_pending(), [])

    async def test_adding_the_bot_back_cancels_the_scheduled_erasure(self):
        guild_grace.schedule_guild_deletion(111, now=self.now, env={})
        cog = privacy_cog.Privacy(FakeBot([111]))

        await cog.on_guild_join(SimpleNamespace(id=111))

        self.assertEqual(_pending(), [])

    async def test_reconciliation_schedules_a_server_removed_while_offline(self):
        # on_guild_remove never fires if the bot is down, so without this the
        # server's data would sit on disk forever.
        bot = FakeBot([222])

        with mock.patch.object(
            privacy_cog, "all_guild_settings", return_value={"111": {}, "222": {}}
        ):
            await privacy_cog.reconcile_guild_deletions(bot)

        self.assertEqual(_pending(), ["111"])

    async def test_reconciliation_clears_a_marker_for_a_server_still_present(self):
        # This direction is what makes a spuriously created marker self-correct.
        guild_grace.schedule_guild_deletion(111, now=self.now, env={})
        bot = FakeBot([111])

        with mock.patch.object(
            privacy_cog, "all_guild_settings", return_value={"111": {}}
        ):
            await privacy_cog.reconcile_guild_deletions(bot)

        self.assertEqual(_pending(), [])

    async def test_an_empty_guild_list_schedules_nothing(self):
        # A gateway that hands back no guilds is a failed connect, not proof
        # that every server removed NovaGuard at once. Marking them all would
        # self-correct on the next healthy connect, but the loop should never
        # depend on that recovery in the first place.
        bot = FakeBot()

        with mock.patch.object(
            privacy_cog, "all_guild_settings", return_value={"111": {}, "222": {}}
        ):
            await privacy_cog.reconcile_guild_deletions(bot)

        self.assertEqual(_pending(), [])

    async def test_only_a_closed_window_erases(self):
        guild_grace.schedule_guild_deletion(
            "expired", now=self.now - timedelta(days=31), env={}
        )
        guild_grace.schedule_guild_deletion("fresh", now=self.now, env={})
        bot = FakeBot()
        erase = mock.AsyncMock()

        with mock.patch.object(privacy_cog, "erase_live_guild_data", erase):
            erased = await privacy_cog.process_due_guild_deletions(bot, now=self.now)

        self.assertEqual(erased, ["expired"])
        erase.assert_awaited_once_with(bot, "expired")
        self.assertEqual(_pending(), ["fresh"])

    async def test_the_daily_loop_reconciles_before_it_erases(self):
        # A server added back on the last day of its window must have its marker
        # cleared before the deletion pass reads it. Reversing these two lines
        # would erase a server that had already come back.
        calls = []
        cog = privacy_cog.Privacy(FakeBot())

        async def reconcile(_bot):
            calls.append("reconcile")
            return {"scheduled": [], "cancelled": []}

        async def process(_bot):
            calls.append("process")
            return []

        with (
            mock.patch.object(privacy_cog, "reconcile_guild_deletions", reconcile),
            mock.patch.object(privacy_cog, "process_due_guild_deletions", process),
            mock.patch.object(
                privacy_cog, "run_retention_cleanup", return_value={"counts": {}}
            ),
            mock.patch.object(
                privacy_cog, "_sync_current_privacy_ledger", mock.AsyncMock()
            ),
        ):
            await cog.retention_loop.coro(cog)

        self.assertEqual(calls, ["reconcile", "process"])

    async def test_one_failed_erasure_does_not_strand_the_next_server(self):
        guild_grace.schedule_guild_deletion(
            "broken", now=self.now - timedelta(days=40), env={}
        )
        guild_grace.schedule_guild_deletion(
            "healthy", now=self.now - timedelta(days=39), env={}
        )
        bot = FakeBot()

        async def erase(_bot, guild_id):
            if guild_id == "broken":
                raise RuntimeError("database is locked")

        with (
            mock.patch.object(privacy_cog, "erase_live_guild_data", erase),
            mock.patch.object(privacy_cog, "send_error_digest", mock.AsyncMock()),
        ):
            erased = await privacy_cog.process_due_guild_deletions(bot, now=self.now)

        self.assertEqual(erased, ["healthy"])
        # The failure keeps its marker, so the next run retries rather than
        # silently leaving the data behind with nothing scheduled to remove it.
        self.assertEqual(_pending(), ["broken"])


if __name__ == "__main__":
    unittest.main()
