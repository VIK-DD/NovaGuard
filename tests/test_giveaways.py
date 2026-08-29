"""Giveaway input, entries, and the draw.

Two people press the button in the same second and one of them is silently
left out of the draw: that is the bug the store lock was added for, and until
now nothing proved the lock still does its job. Entering is a
load-mutate-save against a JSON file across a real await, so without
serialisation both clicks read the same list and the second save drops the
first one's entrant.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import storage  # noqa: E402

from cogs.giveaways import validate_giveaway_input  # noqa: E402


class GiveawayInputTests(unittest.TestCase):
    def test_valid_input_is_normalized(self):
        delta, prize, winners, errors = validate_giveaway_input(
            "1h 30m", "  Nitro   for one month ", 2
        )
        self.assertEqual(int(delta.total_seconds()), 5400)
        self.assertEqual(prize, "Nitro for one month")
        self.assertEqual(winners, 2)
        self.assertEqual(errors, [])

    def test_duration_rejects_partial_or_out_of_range_values(self):
        for duration in ("1h later", "59s", "31d", ""):
            with self.subTest(duration=duration):
                *_, errors = validate_giveaway_input(duration, "Prize", 1)
                self.assertTrue(any("duration" in error for error in errors))

    def test_prize_and_winners_are_bounded_without_coercion(self):
        *_, errors = validate_giveaway_input("1h", "", "2")
        self.assertTrue(any("prize" in error for error in errors))
        self.assertTrue(any("winners" in error for error in errors))


GUILD = 1
CHANNEL = 55
MESSAGE = 900


def giveaway(*, entrants=None, winners=1, ended=False):
    return {
        "message_id": MESSAGE,
        "channel_id": CHANNEL,
        "guild_id": GUILD,
        "prize": "Nitro",
        "winners": winners,
        "entrants": list(entrants or []),
        "ended": ended,
        "winner_ids": [],
        "ends_at": "2026-08-20T12:00:00+00:00",
        "host_id": 7,
    }


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.edits = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append(content)

    async def edit_message(self, **kwargs):
        self.edits.append(kwargs)


class FakeInteraction:
    def __init__(self, user_id):
        self.user = mock.Mock(id=user_id)
        self.guild_id = GUILD
        self.response = FakeResponse()
        self.followup = mock.AsyncMock()


class GiveawayStoreTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._old_dir = storage.DATA_DIR
        storage.DATA_DIR = Path(self._temp.name)
        self.addCleanup(self._restore)

        import cogs.giveaways as giveaways_module

        self.giveaways = giveaways_module
        # The anti-spam window lives on the class, so it outlives an instance
        # and would otherwise leak between tests as a mysterious refusal.
        giveaways_module.GiveawayButton._cooldown.clear()
        # The store lock is created at import and binds to the first loop that
        # takes it. Production has one loop for the life of the process;
        # IsolatedAsyncioTestCase builds a new one per test, so it needs a
        # fresh lock or the second test to touch it raises.
        self._old_lock = giveaways_module._STORE_LOCK
        giveaways_module._STORE_LOCK = asyncio.Lock()

    def _restore(self):
        storage.DATA_DIR = self._old_dir
        self.giveaways._STORE_LOCK = self._old_lock
        self._temp.cleanup()

    def store(self, entries):
        storage.save_data("giveaways", entries)

    def stored(self):
        return storage.load_data("giveaways", [])

    def entrants(self):
        return self.stored()[0]["entrants"]

    async def press(self, user_id, message_id=MESSAGE):
        button = self.giveaways.GiveawayButton(message_id)
        interaction = FakeInteraction(user_id)
        await button.callback(interaction)
        return interaction


class EntryTests(GiveawayStoreTestCase):
    async def test_pressing_the_button_enters_you(self):
        self.store([giveaway()])

        await self.press(100)

        self.assertEqual(self.entrants(), [100])

    async def test_pressing_it_again_takes_you_back_out(self):
        self.store([giveaway(entrants=[100])])

        await self.press(100)

        self.assertEqual(self.entrants(), [])

    async def test_an_ended_giveaway_cannot_be_entered(self):
        self.store([giveaway(ended=True)])

        await self.press(100)

        self.assertEqual(self.entrants(), [])

    async def test_two_people_entering_at_once_are_both_recorded(self):
        # The reason the store lock exists. Entering is load -> mutate -> save
        # across a real await, so without serialisation both clicks read the
        # same list and whichever saves second erases the other's entrant —
        # invisibly, because both people are told they are in.
        self.store([giveaway()])

        await asyncio.gather(self.press(100), self.press(200))

        self.assertEqual(sorted(self.entrants()), [100, 200])

    async def test_entering_one_giveaway_does_not_lock_you_out_of_another(self):
        # The anti-spam window is meant to stop someone hammering one button.
        # Keyed on the member alone it also refused their first press on a
        # different giveaway, which reads as the bot being broken — they
        # clicked once and were told to slow down.
        second = 901
        self.store([giveaway(), giveaway() | {"message_id": second}])

        await self.press(100, MESSAGE)
        await self.press(100, second)

        entered = {g["message_id"]: g["entrants"] for g in self.stored()}
        self.assertEqual(entered[MESSAGE], [100])
        self.assertEqual(entered[second], [100])

    async def test_hammering_the_same_giveaway_is_still_refused(self):
        self.store([giveaway()])

        await self.press(100)
        await self.press(100)

        # The second press inside the window is ignored, so the entry stands
        # rather than being toggled straight back off.
        self.assertEqual(self.entrants(), [100])

    async def test_a_crowd_entering_at_once_loses_nobody(self):
        self.store([giveaway()])
        people = list(range(1000, 1012))

        await asyncio.gather(*(self.press(user_id) for user_id in people))

        self.assertEqual(sorted(self.entrants()), people)


class DrawTests(GiveawayStoreTestCase):
    async def asyncSetUp(self):
        self.cog = self.giveaways.Giveaways(mock.Mock())
        patcher = mock.patch.object(
            self.giveaways.Giveaways, "_fetch_entry_channel", mock.AsyncMock(return_value=None)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_it_draws_the_number_of_winners_asked_for(self):
        self.store([giveaway(entrants=[1, 2, 3, 4, 5], winners=3)])

        entry = await self.cog.finish_giveaway(MESSAGE)

        self.assertEqual(len(entry["winner_ids"]), 3)

    async def test_winners_are_drawn_only_from_the_entrants(self):
        self.store([giveaway(entrants=[1, 2, 3], winners=2)])

        entry = await self.cog.finish_giveaway(MESSAGE)

        self.assertTrue(set(entry["winner_ids"]) <= {1, 2, 3})

    async def test_nobody_wins_twice(self):
        self.store([giveaway(entrants=[1, 2, 3], winners=3)])

        entry = await self.cog.finish_giveaway(MESSAGE)

        self.assertEqual(len(set(entry["winner_ids"])), 3)

    async def test_corrupt_duplicate_entries_cannot_win_twice(self):
        self.store([giveaway(entrants=[1, 1, 2, 3], winners=3)])

        entry = await self.cog.finish_giveaway(MESSAGE)

        self.assertEqual(sorted(entry["winner_ids"]), [1, 2, 3])

    async def test_fewer_entrants_than_prizes_draws_everyone_present(self):
        # random.sample raises when asked for more than the population holds,
        # which would end the giveaway watcher rather than the giveaway.
        self.store([giveaway(entrants=[1, 2], winners=5)])

        entry = await self.cog.finish_giveaway(MESSAGE)

        self.assertEqual(sorted(entry["winner_ids"]), [1, 2])

    async def test_a_giveaway_nobody_entered_ends_without_winners(self):
        self.store([giveaway(entrants=[], winners=2)])

        entry = await self.cog.finish_giveaway(MESSAGE)

        self.assertEqual(entry["winner_ids"], [])
        self.assertTrue(entry["ended"])

    async def test_a_finished_giveaway_is_not_drawn_a_second_time(self):
        self.store([giveaway(entrants=[1, 2, 3], winners=1)])

        first = await self.cog.finish_giveaway(MESSAGE)
        again = await self.cog.finish_giveaway(MESSAGE)

        self.assertIsNotNone(first)
        self.assertIsNone(again, "a second draw would hand out the prize twice")

    async def test_an_unknown_giveaway_is_not_invented(self):
        self.store([giveaway()])

        self.assertIsNone(await self.cog.finish_giveaway(12345))

    async def test_the_result_is_written_down_not_only_returned(self):
        self.store([giveaway(entrants=[1, 2, 3], winners=2)])

        entry = await self.cog.finish_giveaway(MESSAGE)

        saved = self.stored()[0]
        self.assertTrue(saved["ended"])
        self.assertEqual(saved["winner_ids"], entry["winner_ids"])

    async def test_reroll_prefers_people_who_did_not_already_win(self):
        entry = giveaway(entrants=[1, 2, 3, 4], winners=2, ended=True)
        entry["winner_ids"] = [1, 2]
        self.store([entry])

        rerolled, winner_ids, _ = await self.cog.reroll_giveaway(MESSAGE)

        self.assertEqual(set(winner_ids), {3, 4})
        self.assertEqual(rerolled["winner_ids"], winner_ids)


if __name__ == "__main__":
    unittest.main()
