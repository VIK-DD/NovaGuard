"""Reminders: written to disk by one command, fired later by a loop.

The failure mode here is the quietest in the project. Nobody reports the
message they did not receive, so a reminder that is dropped — or written in a
shape the loop cannot read — simply never happens and never produces a
complaint.

Delivery is deliberately at-most-once: the store is rewritten without the due
reminders *before* they are sent, so a permanently broken channel cannot make
the loop retry forever. The cost of that choice is that a single failed send
loses the reminder, which is defensible, and is exactly why it must not also
be silent.
"""

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord  # noqa: E402

from core import storage  # noqa: E402

GUILD = 1
USER = 100
CHANNEL = 55


def reminder(due_at, *, message="stand up", channel_id=CHANNEL, reminder_id="a1b2c3d4"):
    return {
        "id": reminder_id,
        "user_id": USER,
        "guild_id": GUILD,
        "channel_id": channel_id,
        "message": message,
        "due_at": due_at.isoformat() if hasattr(due_at, "isoformat") else due_at,
    }


class FakeChannel:
    def __init__(self, *, fails=False):
        self.sent = []
        self.fails = fails

    async def send(self, content=None, embed=None, **kwargs):
        if self.fails:
            raise discord.HTTPException(mock.Mock(status=500), "channel is gone")
        self.sent.append((content, embed))


class FakeBot:
    def __init__(self, channels):
        self.channels = channels

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id):
        raise discord.HTTPException(mock.Mock(status=404), "not found")


class ReminderTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._old_dir = storage.DATA_DIR
        storage.DATA_DIR = Path(self._temp.name)
        self.addCleanup(self._restore)

        import cogs.utility as utility_module

        self.utility = utility_module

    def _restore(self):
        storage.DATA_DIR = self._old_dir
        self._temp.cleanup()

    async def asyncSetUp(self):
        self.channel = FakeChannel()
        self.cog = self.utility.Utility(FakeBot({CHANNEL: self.channel}))

    def stored(self):
        return storage.load_data("reminders", [])

    def store(self, items):
        storage.save_data("reminders", items)

    async def tick(self):
        await self.cog.reminder_loop.coro(self.cog)

    def past(self, minutes=5):
        return datetime.now(UTC) - timedelta(minutes=minutes)

    def future(self, minutes=5):
        return datetime.now(UTC) + timedelta(minutes=minutes)


class DeliveryTests(ReminderTestCase):
    async def test_a_due_reminder_is_delivered(self):
        self.store([reminder(self.past())])

        await self.tick()

        self.assertEqual(len(self.channel.sent), 1)
        content, embed = self.channel.sent[0]
        self.assertIn(str(USER), content)
        self.assertIn("stand up", embed.description)

    async def test_a_delivered_reminder_is_not_delivered_again(self):
        self.store([reminder(self.past())])

        await self.tick()
        await self.tick()

        self.assertEqual(len(self.channel.sent), 1)
        self.assertEqual(self.stored(), [])

    async def test_a_reminder_that_is_not_due_is_left_alone(self):
        self.store([reminder(self.future())])

        await self.tick()

        self.assertEqual(self.channel.sent, [])
        self.assertEqual(len(self.stored()), 1)

    async def test_an_empty_store_writes_nothing(self):
        self.store([])

        with mock.patch.object(self.utility, "save_data") as write:
            await self.tick()

        write.assert_not_called()

    async def test_a_store_with_nothing_due_is_not_rewritten(self):
        # Rewriting the file every twenty seconds for no reason is how a JSON
        # store gets truncated by an unlucky restart.
        self.store([reminder(self.future())])

        with mock.patch.object(self.utility, "save_data") as write:
            await self.tick()

        write.assert_not_called()

    async def test_only_the_due_one_is_removed(self):
        self.store(
            [
                reminder(self.past(), reminder_id="due"),
                reminder(self.future(), reminder_id="later"),
            ]
        )

        await self.tick()

        self.assertEqual([item["id"] for item in self.stored()], ["later"])


class CorruptDataTests(ReminderTestCase):
    async def test_a_reminder_with_an_unreadable_time_is_dropped(self):
        # An unhandled exception in a tasks.loop ends it permanently, so one
        # bad row must not stop every future reminder on every server.
        self.store([reminder("not a timestamp", reminder_id="broken")])

        await self.tick()

        self.assertEqual(self.stored(), [])

    async def test_a_bad_row_does_not_stop_the_good_ones(self):
        self.store(
            [
                reminder("not a timestamp", reminder_id="broken"),
                reminder(self.past(), reminder_id="due"),
            ]
        )

        await self.tick()

        self.assertEqual(len(self.channel.sent), 1)

    async def test_a_reminder_missing_its_time_is_dropped_rather_than_raising(self):
        broken = reminder(datetime.now(UTC))
        del broken["due_at"]
        self.store([broken])

        await self.tick()

        self.assertEqual(self.stored(), [])


class FailedDeliveryTests(ReminderTestCase):
    async def asyncSetUp(self):
        self.channel = FakeChannel(fails=True)
        self.cog = self.utility.Utility(FakeBot({CHANNEL: self.channel}))

    async def test_a_failed_send_is_recorded_rather_than_swallowed(self):
        # Delivery is at-most-once by design: the store is rewritten before the
        # send, so a failure loses the reminder for good. That is a reasonable
        # trade against retrying into a dead channel forever — but it has to
        # leave a trace, or the only symptom is a message that never arrived
        # and nobody is able to report.
        self.store([reminder(self.past())])

        with self.assertLogs("cogs.utility", level="WARNING") as captured:
            await self.tick()

        self.assertTrue(any("a1b2c3d4" in line for line in captured.output))

    async def test_an_unreachable_channel_is_recorded_too(self):
        self.cog = self.utility.Utility(FakeBot({}))
        self.store([reminder(self.past(), channel_id=999)])

        with self.assertLogs("cogs.utility", level="WARNING") as captured:
            await self.tick()

        self.assertTrue(any("999" in line for line in captured.output))


class FakeResponse:
    def __init__(self):
        self.messages = []

    def is_done(self):
        return False

    async def send_message(self, embed=None, ephemeral=False, **kwargs):
        self.messages.append(embed)
        return None


class FakeInteraction:
    def __init__(self):
        self.guild_id = GUILD
        self.channel_id = CHANNEL
        self.user = mock.Mock(id=USER)
        self.response = FakeResponse()
        self.followup = mock.AsyncMock()


class RemindCommandTests(ReminderTestCase):
    """The writer half of the contract the loop above reads."""

    async def remind(self, duration, message="stand up"):
        interaction = FakeInteraction()
        await self.cog.remind.callback(self.cog, interaction, duration, message)
        return interaction

    async def test_a_saved_reminder_has_every_field_the_loop_reads(self):
        # The two halves are written apart and only meet at runtime. If the
        # command stopped writing channel_id, nothing would fail until a
        # reminder came due and quietly went nowhere.
        await self.remind("10m")

        saved = self.stored()[0]
        for field in ("id", "user_id", "guild_id", "channel_id", "message", "due_at"):
            with self.subTest(field=field):
                self.assertIn(field, saved)
        datetime.fromisoformat(saved["due_at"])

    async def test_an_unreadable_duration_saves_nothing(self):
        await self.remind("whenever")

        self.assertEqual(self.stored(), [])

    async def test_a_duration_beyond_the_limit_saves_nothing(self):
        await self.remind("200d")

        self.assertEqual(self.stored(), [])

    async def test_a_second_reminder_does_not_replace_the_first(self):
        await self.remind("10m", "first")
        await self.remind("20m", "second")

        self.assertEqual([item["message"] for item in self.stored()], ["first", "second"])

    async def test_a_reminder_just_written_is_delivered_when_it_comes_due(self):
        # The round trip, end to end: what the command writes is exactly what
        # the loop can read back and act on.
        await self.remind("10m", "drink water")
        saved = self.stored()[0]
        saved["due_at"] = self.past().isoformat()
        self.store([saved])

        await self.tick()

        self.assertEqual(len(self.channel.sent), 1)
        self.assertIn("drink water", self.channel.sent[0][1].description)


if __name__ == "__main__":
    unittest.main()
