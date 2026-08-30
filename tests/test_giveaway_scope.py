"""A giveaway belongs to the guild it was started in.

`data/giveaways.json` is one file for every guild the bot serves, and a
message id is public to anyone who can see the channel. `finish_giveaway` and
`reroll_giveaway` matched on that id alone, so a manager in their own throwaway
server could run `/giveaway end message_id:<id from another server>` and end -
then repeatedly reroll - a giveaway running somewhere they have no standing at
all, with the new winner announced in the victim's own channel.

The dashboard path already knew this mattered: `_giveaway_for_guild` in
core/webserver.py filters on guild_id before acting. The slash commands did
not, which is what makes this an oversight rather than a decision.

Rerolling had a second problem. `exclude=entry.get("winner_ids", [])` is only
the *previous* draw, so each reroll put everyone except the last winners back
in the pool - a determined roller could keep going until a chosen account came
up. Exclusions now accumulate.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs import giveaways as giveaways_cog  # noqa: E402

VICTIM_GUILD = 111111111111111111
ATTACKER_GUILD = 222222222222222222
MESSAGE_ID = 999999999999999999


def a_giveaway(**overrides):
    entry = {
        "message_id": str(MESSAGE_ID),
        "channel_id": "555",
        "guild_id": str(VICTIM_GUILD),
        "prize": "Nitro Classic (12 months)",
        "winners": 1,
        "host_id": "1",
        "host_name": "victim staff",
        "ends_at": "2099-01-01T00:00:00+00:00",
        "entrants": [1001, 1002, 1003, 1004],
        "ended": False,
    }
    entry.update(overrides)
    return entry


class GiveawayGuildScopeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.path = Path(self._temp.name) / "giveaways.json"

        def load():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except OSError:
                return []

        def save(entries):
            self.path.write_text(json.dumps(entries), encoding="utf-8")

        patches = [
            mock.patch.object(giveaways_cog, "load_giveaways", load),
            mock.patch.object(giveaways_cog, "save_giveaways", save),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

        save([a_giveaway()])
        self.cog = giveaways_cog.Giveaways.__new__(giveaways_cog.Giveaways)
        self.cog.bot = mock.Mock()
        # The Discord half of these methods runs after the store lock; stub it
        # so the test is about the lookup, not about sending messages.
        self.cog._fetch_entry_channel = mock.AsyncMock(return_value=None)

    def stored(self):
        return json.loads(self.path.read_text(encoding="utf-8"))[0]

    # ── the regression ───────────────────────────────────────────────

    async def test_a_foreign_guild_cannot_end_someone_elses_giveaway(self):
        result = await self.cog.finish_giveaway(MESSAGE_ID, guild_id=ATTACKER_GUILD)
        self.assertIsNone(result, "a foreign guild ended another server's giveaway")
        self.assertFalse(self.stored()["ended"], "the victim's giveaway was modified")

    async def test_a_foreign_guild_cannot_reroll_someone_elses_giveaway(self):
        self.path.write_text(
            json.dumps([a_giveaway(ended=True, winner_ids=[1001])]), encoding="utf-8"
        )
        entry, winners, announced = await self.cog.reroll_giveaway(
            MESSAGE_ID, guild_id=ATTACKER_GUILD
        )
        self.assertIsNone(entry)
        self.assertFalse(announced)
        self.assertEqual(self.stored()["winner_ids"], [1001], "the draw was overwritten")

    async def test_the_prize_is_not_disclosed_to_a_foreign_guild(self):
        # finish_giveaway's return value is what the command echoes back.
        self.assertIsNone(await self.cog.finish_giveaway(MESSAGE_ID, guild_id=ATTACKER_GUILD))

    # ── the owning guild still works ─────────────────────────────────

    async def test_the_owning_guild_can_still_end_its_own(self):
        entry = await self.cog.finish_giveaway(MESSAGE_ID, guild_id=VICTIM_GUILD)
        self.assertIsNotNone(entry)
        self.assertTrue(self.stored()["ended"])

    async def test_the_expiry_sweep_still_reaches_every_guild(self):
        # The scheduled watcher iterates the whole store and passes no guild.
        entry = await self.cog.finish_giveaway(MESSAGE_ID)
        self.assertIsNotNone(entry, "the expiry sweep must not be guild-scoped")


class RerollExclusionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.path = Path(self._temp.name) / "giveaways.json"

        def load():
            return json.loads(self.path.read_text(encoding="utf-8"))

        def save(entries):
            self.path.write_text(json.dumps(entries), encoding="utf-8")

        for patch in (
            mock.patch.object(giveaways_cog, "load_giveaways", load),
            mock.patch.object(giveaways_cog, "save_giveaways", save),
        ):
            patch.start()
            self.addCleanup(patch.stop)

        save([a_giveaway(ended=True, winner_ids=[1001])])
        self.cog = giveaways_cog.Giveaways.__new__(giveaways_cog.Giveaways)
        self.cog.bot = mock.Mock()
        self.cog._fetch_entry_channel = mock.AsyncMock(return_value=None)

    async def test_rerolling_never_puts_an_earlier_winner_back_in_the_pool(self):
        seen = {1001}
        for _ in range(3):
            _entry, winners, _announced = await self.cog.reroll_giveaway(
                MESSAGE_ID, guild_id=VICTIM_GUILD
            )
            if not winners:
                break
            for winner in winners:
                self.assertNotIn(
                    winner, seen, "a previous winner was drawn again on reroll"
                )
                seen.add(winner)

    async def test_the_exclusion_list_is_persisted_between_rerolls(self):
        await self.cog.reroll_giveaway(MESSAGE_ID, guild_id=VICTIM_GUILD)
        stored = json.loads(self.path.read_text(encoding="utf-8"))[0]
        self.assertIn("past_winner_ids", stored)
        self.assertIn(1001, stored["past_winner_ids"])

    async def test_every_fresh_entrant_is_used_before_anyone_repeats(self):
        # draw_winners deliberately falls back to previous winners once the
        # fresh pool is empty - "preferring entrants not picked previously",
        # not refusing to draw at all. The property that matters is that the
        # fallback is genuinely last: with four entrants and one prior winner,
        # the next three rerolls must each produce someone new.
        drawn = [1001]
        for _ in range(3):
            _entry, winners, _announced = await self.cog.reroll_giveaway(
                MESSAGE_ID, guild_id=VICTIM_GUILD
            )
            self.assertTrue(winners)
            for winner in winners:
                self.assertNotIn(winner, drawn, "an entrant repeated while fresh ones remained")
                drawn.append(winner)
        self.assertEqual(sorted(drawn), [1001, 1002, 1003, 1004])


if __name__ == "__main__":
    unittest.main()
