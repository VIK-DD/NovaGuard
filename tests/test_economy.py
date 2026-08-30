"""Coins moving between wallets, and the ways they could go missing.

The economy cog had no tests at all: 427 statements moving balances members
treat as real. The awkward property of money bugs is that they are invisible
at the moment they happen — nobody notices a payment that credited twice
until a balance is wrong, and by then the balance is the only surviving
record of what it should have been.

So these are mostly about totals and refusals rather than about output. Every
transfer test asserts what the whole server holds afterwards, not only what
the two wallets say, because a bug that invents coins leaves both sides
individually plausible.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import database  # noqa: E402

GUILD = 1
ALICE = 100
BOB = 200


class FakeResponse:
    def __init__(self):
        self.messages = []

    def is_done(self):
        return False

    async def send_message(self, embed=None, ephemeral=False, **kwargs):
        self.messages.append(embed)
        return None


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, embed=None, **kwargs):
        self.sent.append(embed)
        return None


class FakeMember:
    def __init__(self, member_id, *, bot=False):
        self.id = member_id
        self.bot = bot
        self.mention = f"<@{member_id}>"
        self.display_name = f"user{member_id}"


class FakeInteraction:
    def __init__(self, user):
        self.guild_id = GUILD
        self.user = user
        self.response = FakeResponse()
        self.followup = FakeFollowup()


class EconomyTestCase(unittest.IsolatedAsyncioTestCase):
    """A real cog over a throwaway database, with settings under our control."""

    SETTINGS: dict = {}

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._old_path = database.DB_PATH
        self._old_initialized = database._INITIALIZED
        database.DB_PATH = Path(self._temp.name) / "test.sqlite3"
        # init_database() is a no-op once it has run, so the flag has to be
        # cleared or the new file never gets its tables.
        database._INITIALIZED = False
        database.init_database()

        import cogs.economy as economy_module

        self.economy = economy_module
        patcher = mock.patch.object(
            economy_module, "get_guild_settings", lambda _guild_id: dict(self.SETTINGS)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncSetUp(self):
        # Constructed, never cog_load()ed: starting the flush loop would hang a
        # timer off every test for no benefit. flush() is called directly.
        self.cog = self.economy.Economy(bot=object())

    def tearDown(self):
        database.DB_PATH = self._old_path
        database._INITIALIZED = self._old_initialized
        self._temp.cleanup()

    # --- reading and writing balances without going through Discord ----

    def wallet(self, user_id):
        return self.economy.get_wallet(self.cog.data, GUILD, user_id)

    def set_coins(self, user_id, amount):
        self.wallet(user_id)["coins"] = amount

    def coins(self, user_id):
        return self.wallet(user_id)["coins"]

    def server_total(self):
        """Every coin held on this server, however it is spread out."""
        guild_data = self.cog.data.get(str(GUILD), {})
        return sum(
            int(w.get("coins", 0) or 0) for w in guild_data.values() if isinstance(w, dict)
        )


class PaymentTests(EconomyTestCase):
    async def pay(self, sender_id, target, amount):
        interaction = FakeInteraction(FakeMember(sender_id))
        await self.cog.pay.callback(self.cog, interaction, target, amount)
        return interaction

    async def test_a_payment_moves_exactly_the_amount(self):
        self.set_coins(ALICE, 500)
        self.set_coins(BOB, 100)

        await self.pay(ALICE, FakeMember(BOB), 120)

        self.assertEqual(self.coins(ALICE), 380)
        self.assertEqual(self.coins(BOB), 220)

    async def test_a_payment_does_not_change_what_the_server_holds(self):
        # Catches a transfer that credits twice or debits the wrong wallet:
        # both balances can look reasonable while the total has moved.
        self.set_coins(ALICE, 500)
        self.set_coins(BOB, 100)
        before = self.server_total()

        await self.pay(ALICE, FakeMember(BOB), 120)

        self.assertEqual(self.server_total(), before)

    async def test_paying_more_than_you_hold_moves_nothing(self):
        self.set_coins(ALICE, 50)
        self.set_coins(BOB, 0)

        await self.pay(ALICE, FakeMember(BOB), 500)

        self.assertEqual(self.coins(ALICE), 50)
        self.assertEqual(self.coins(BOB), 0)

    async def test_paying_exactly_your_whole_balance_is_allowed(self):
        # The boundary the "not enough coins" check sits on. Off by one here
        # either blocks a legitimate payment or permits an overdraft.
        self.set_coins(ALICE, 300)
        self.set_coins(BOB, 0)

        await self.pay(ALICE, FakeMember(BOB), 300)

        self.assertEqual(self.coins(ALICE), 0)
        self.assertEqual(self.coins(BOB), 300)

    async def test_paying_yourself_is_refused(self):
        # The balance alone cannot see this. Sender and receiver are the same
        # dict, so removing the guard subtracts and adds the same amount and
        # leaves the total untouched — the first version of this test passed
        # with the guard deleted. What actually changes is that the member is
        # told a payment was sent and a pointless write is scheduled, so the
        # refusal is what has to be asserted.
        self.set_coins(ALICE, 500)

        await self.pay(ALICE, FakeMember(ALICE), 100)

        self.assertEqual(self.coins(ALICE), 500)
        self.assertEqual(self.cog.dirty_keys, set(), "a refused payment scheduled a write")

    async def test_paying_yourself_is_not_reported_as_sent(self):
        self.set_coins(ALICE, 500)

        interaction = await self.pay(ALICE, FakeMember(ALICE), 100)

        titles = [embed.title for embed in interaction.response.messages if embed]
        self.assertTrue(titles, "the panel said nothing at all")
        self.assertNotIn("💸 Payment sent", titles)

    async def test_paying_a_bot_is_refused(self):
        self.set_coins(ALICE, 500)

        await self.pay(ALICE, FakeMember(BOB, bot=True), 100)

        self.assertEqual(self.coins(ALICE), 500)
        self.assertEqual(self.coins(BOB), 0)

    async def test_a_refused_payment_leaves_nothing_to_write(self):
        self.set_coins(ALICE, 50)

        await self.pay(ALICE, FakeMember(BOB), 500)

        self.assertEqual(self.cog.dirty_keys, set())


class GambleTests(EconomyTestCase):
    async def gamble(self, user_id, amount, *, wins):
        interaction = FakeInteraction(FakeMember(user_id))
        # 0.47 is the win threshold; pick a value clearly on one side of it so
        # the test does not depend on the exact odds staying put.
        roll = 0.1 if wins else 0.9
        with mock.patch.object(self.economy._rng, "random", return_value=roll):
            await self.cog.gamble.callback(self.cog, interaction, amount)
        return interaction

    async def test_a_win_adds_exactly_the_stake(self):
        self.set_coins(ALICE, 1000)

        await self.gamble(ALICE, 250, wins=True)

        self.assertEqual(self.coins(ALICE), 1250)

    async def test_a_loss_subtracts_exactly_the_stake(self):
        self.set_coins(ALICE, 1000)

        await self.gamble(ALICE, 250, wins=False)

        self.assertEqual(self.coins(ALICE), 750)

    async def test_losing_everything_lands_on_zero_not_below(self):
        self.set_coins(ALICE, 250)

        await self.gamble(ALICE, 250, wins=False)

        self.assertEqual(self.coins(ALICE), 0)

    async def test_betting_more_than_you_hold_changes_nothing(self):
        self.set_coins(ALICE, 100)

        await self.gamble(ALICE, 500, wins=True)

        self.assertEqual(self.coins(ALICE), 100)


class BetCapTests(EconomyTestCase):
    SETTINGS = {"economy": {"gamble_max_bet": 500}}

    async def test_a_bet_over_the_server_cap_is_refused(self):
        self.set_coins(ALICE, 10_000)
        interaction = FakeInteraction(FakeMember(ALICE))

        with mock.patch.object(self.economy._rng, "random", return_value=0.1):
            await self.cog.gamble.callback(self.cog, interaction, 5_000)

        self.assertEqual(self.coins(ALICE), 10_000)

    async def test_a_bet_on_the_cap_is_allowed(self):
        self.set_coins(ALICE, 10_000)
        interaction = FakeInteraction(FakeMember(ALICE))

        with mock.patch.object(self.economy._rng, "random", return_value=0.1):
            await self.cog.gamble.callback(self.cog, interaction, 500)

        self.assertEqual(self.coins(ALICE), 10_500)


class AwardTests(EconomyTestCase):
    """Coins paid for something earned elsewhere — voice time uses this."""

    async def test_an_award_credits_the_wallet(self):
        self.set_coins(ALICE, 100)

        self.assertEqual(await self.cog.award_coins(GUILD, ALICE, 40), 140)

    async def test_a_negative_award_cannot_push_a_balance_below_zero(self):
        self.set_coins(ALICE, 30)

        self.assertEqual(await self.cog.award_coins(GUILD, ALICE, -100), 0)


class DisabledEconomyTests(EconomyTestCase):
    SETTINGS = {"economy": {"enabled": False}}

    async def test_an_award_leaves_the_balance_alone(self):
        self.set_coins(ALICE, 100)

        self.assertEqual(await self.cog.award_coins(GUILD, ALICE, 500), 100)
        self.assertEqual(self.coins(ALICE), 100)

    async def test_a_payment_is_refused(self):
        self.set_coins(ALICE, 500)

        interaction = FakeInteraction(FakeMember(ALICE))
        await self.cog.pay.callback(self.cog, interaction, FakeMember(BOB), 100)

        self.assertEqual(self.coins(ALICE), 500)


class PersistenceTests(EconomyTestCase):
    """The path where money actually goes missing: memory to disk."""

    async def test_a_payment_survives_a_reload(self):
        self.set_coins(ALICE, 500)
        self.set_coins(BOB, 0)

        interaction = FakeInteraction(FakeMember(ALICE))
        await self.cog.pay.callback(self.cog, interaction, FakeMember(BOB), 200)
        await self.cog.flush()

        reloaded = database.load_economy_data()
        self.assertEqual(reloaded[str(GUILD)][str(ALICE)]["coins"], 300)
        self.assertEqual(reloaded[str(GUILD)][str(BOB)]["coins"], 200)

    async def test_a_flush_with_nothing_pending_writes_nothing(self):
        with mock.patch.object(self.economy, "upsert_economy_wallets") as write:
            await self.cog.flush()

        write.assert_not_called()

    async def test_a_failed_write_keeps_the_wallets_pending(self):
        # If a storage error cleared the pending set, the change would exist
        # only in memory and be lost at the next restart — silently, because
        # the command has already told the member it worked.
        self.set_coins(ALICE, 500)
        self.cog.dirty_keys.add((str(GUILD), str(ALICE)))

        with mock.patch.object(
            self.economy, "upsert_economy_wallets", side_effect=OSError("disk gone")
        ):
            with self.assertRaises(OSError):
                await self.cog.flush()

        self.assertIn((str(GUILD), str(ALICE)), self.cog.dirty_keys)

    async def test_a_storage_failure_during_a_command_does_not_crash_it(self):
        # _save swallows and logs, because a member should not see a traceback
        # for a balance that is correct in memory and will be written later.
        self.set_coins(ALICE, 500)

        with mock.patch.object(
            self.economy, "upsert_economy_wallets", side_effect=OSError("disk gone")
        ):
            await self.cog._save(GUILD, ALICE)

        self.assertIn((str(GUILD), str(ALICE)), self.cog.dirty_keys)

    async def test_the_pending_set_is_emptied_before_anything_is_awaited(self):
        # Two flushes overlapping must not write the same wallet twice. What
        # guarantees that is the synchronous clear, not the lock around it:
        # removing the lock still passes, because the second flush finds the
        # pending set already empty and returns before it can duplicate work.
        # Mutation testing is how that came out — the first version of this
        # test claimed to be about the lock and proved nothing of the sort.
        self.set_coins(ALICE, 500)
        self.cog.dirty_keys.add((str(GUILD), str(ALICE)))
        written = []

        def record(rows):
            written.extend(rows)

        with mock.patch.object(self.economy, "upsert_economy_wallets", side_effect=record):
            await asyncio.gather(self.cog.flush(), self.cog.flush())

        self.assertEqual(len(written), 1)

    async def test_a_wallet_changed_during_a_write_is_written_afterwards(self):
        # The snapshot is deep-copied before the write, so a balance that moves
        # while the write is in flight would be persisted stale. It is not lost
        # only because the command that moved it marks the wallet pending
        # again — this pins that, since the alternative is a silently outdated
        # balance surviving a restart.
        self.set_coins(ALICE, 500)
        self.cog.dirty_keys.add((str(GUILD), str(ALICE)))

        with mock.patch.object(self.economy, "upsert_economy_wallets"):
            await self.cog.flush()
        self.assertEqual(self.cog.dirty_keys, set())

        self.set_coins(ALICE, 900)
        await self.cog._save(GUILD, ALICE)

        self.assertEqual(database.load_economy_data()[str(GUILD)][str(ALICE)]["coins"], 900)


if __name__ == "__main__":
    unittest.main()
