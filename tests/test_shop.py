"""Tests for the shop: what a purchase costs, grants, and refuses."""

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import shop  # noqa: E402

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def wallet(coins=0, **overrides):
    return {
        "coins": coins,
        "daily_streak": 0,
        "last_daily": None,
        "last_work": None,
        "trophies": [],
        **overrides,
    }


class FixedRandom:
    """Picks a chosen row from the crate table, so the reward is not a guess."""

    def __init__(self, index):
        self.index = index

    def choices(self, population, weights=None, k=1):
        return [population[self.index]] * k


class CatalogTests(unittest.TestCase):
    def test_every_item_has_what_the_shop_needs_to_display_it(self):
        for key, spec in shop.SHOP_ITEMS.items():
            with self.subTest(item=key):
                self.assertIn("label", spec)
                self.assertIn("kind", spec)
                self.assertGreater(spec["price"], 0)

    def test_the_original_trophies_still_exist_at_their_old_keys(self):
        # Wallets bought under the old shop keep what they paid for.
        for key in ("star", "rocket", "gem", "crown", "trophy"):
            with self.subTest(item=key):
                self.assertEqual(shop.item(key)["kind"], shop.TROPHY)

    def test_the_catalogue_can_be_narrowed_to_one_kind(self):
        titles = shop.catalog(shop.TITLE)

        self.assertTrue(titles)
        self.assertTrue(all(entry["kind"] == shop.TITLE for entry in titles))

    def test_the_catalogue_is_ordered_cheapest_first(self):
        prices = [entry["price"] for entry in shop.catalog()]

        self.assertEqual(prices, sorted(prices))

    def test_an_unknown_item_is_not_invented(self):
        self.assertIsNone(shop.item("does_not_exist"))

    def test_every_crate_reward_points_at_a_real_item(self):
        for reward in shop.CRATE_TABLE:
            with self.subTest(reward=reward["label"]):
                if reward["kind"] == "item":
                    self.assertIsNotNone(shop.item(reward["item"]))
                else:
                    self.assertGreater(reward["amount"], 0)


class PurchaseTests(unittest.TestCase):
    def test_buying_charges_the_price_and_hands_over_the_item(self):
        holder = wallet(2000)

        result = shop.purchase(holder, "star", NOW)

        self.assertTrue(result.ok)
        self.assertEqual(holder["coins"], 1000)
        self.assertIn("star", holder["trophies"])

    def test_a_refused_purchase_never_charges(self):
        # The wallet must be untouched, or a member ends up paying for a
        # refusal.
        holder = wallet(10)

        result = shop.purchase(holder, "star", NOW)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "poor")
        self.assertEqual(holder["coins"], 10)
        self.assertEqual(holder["trophies"], [])

    def test_being_short_says_how_short(self):
        result = shop.purchase(wallet(900), "star", NOW)

        self.assertEqual(result.spent, 100)

    def test_a_one_off_cannot_be_bought_twice(self):
        holder = wallet(5000, trophies=["star"])

        result = shop.purchase(holder, "star", NOW)

        self.assertEqual(result.error, "owned")
        self.assertEqual(holder["coins"], 5000)

    def test_an_unknown_item_is_refused(self):
        self.assertEqual(shop.purchase(wallet(99999), "nonsense", NOW).error, "unknown")

    def test_a_crate_cannot_be_bought_through_the_normal_path(self):
        # Charging and rolling belong together, so /crate owns both.
        self.assertEqual(shop.purchase(wallet(99999), shop.CRATE, NOW).error, "crate")


class EffectTests(unittest.TestCase):
    def test_a_booster_starts_running_when_bought(self):
        holder = wallet(5000)

        result = shop.purchase(holder, shop.XP_BOOST, NOW)

        self.assertTrue(result.ok)
        self.assertEqual(shop.effect_value(holder, shop.XP_BOOST, NOW), 1.5)
        self.assertEqual(result.expires_at, NOW + timedelta(hours=shop.XP_BOOST_HOURS))

    def test_no_booster_means_no_multiplier_rather_than_no_answer(self):
        # Callers multiply by this, so it has to be 1.0, never None.
        self.assertEqual(shop.effect_value(wallet(), shop.XP_BOOST, NOW), 1.0)

    def test_a_booster_stops_applying_once_it_expires(self):
        holder = wallet(5000)
        shop.purchase(holder, shop.XP_BOOST, NOW)

        later = NOW + timedelta(hours=shop.XP_BOOST_HOURS, seconds=1)

        self.assertEqual(shop.effect_value(holder, shop.XP_BOOST, later), 1.0)
        self.assertEqual(shop.active_effects(holder, later), {})

    def test_buying_a_second_booster_extends_instead_of_replacing(self):
        # Throwing away the hours already paid for would be a quiet refund of
        # nothing.
        holder = wallet(5000)
        shop.purchase(holder, shop.XP_BOOST, NOW)
        result = shop.purchase(holder, shop.XP_BOOST, NOW + timedelta(hours=1))

        self.assertEqual(result.expires_at, NOW + timedelta(hours=shop.XP_BOOST_HOURS * 2))

    def test_an_expired_booster_does_not_extend_from_the_past(self):
        holder = wallet(5000)
        shop.purchase(holder, shop.XP_BOOST, NOW)
        much_later = NOW + timedelta(days=3)
        result = shop.purchase(holder, shop.XP_BOOST, much_later)

        self.assertEqual(result.expires_at, much_later + timedelta(hours=shop.XP_BOOST_HOURS))

    def test_the_work_perk_is_a_discount_not_a_multiplier(self):
        holder = wallet(5000)
        shop.purchase(holder, shop.WORK_RUSH, NOW)

        self.assertEqual(shop.effect_value(holder, shop.WORK_RUSH, NOW, default=1.0), 0.5)

    def test_pruning_clears_only_what_has_expired(self):
        holder = wallet(9000)
        shop.purchase(holder, shop.XP_BOOST, NOW)
        shop.purchase(holder, shop.WORK_RUSH, NOW)

        midway = NOW + timedelta(hours=shop.XP_BOOST_HOURS + 1)

        self.assertTrue(shop.prune_effects(holder, midway))
        self.assertEqual(list(holder["effects"]), [shop.WORK_RUSH])
        self.assertFalse(shop.prune_effects(holder, midway))

    def test_a_corrupt_effect_record_does_not_crash_a_reader(self):
        holder = wallet(0, effects={shop.XP_BOOST: {"expires_at": "not a date"}})

        self.assertEqual(shop.effect_value(holder, shop.XP_BOOST, NOW), 1.0)


class ShieldTests(unittest.TestCase):
    def test_shields_stack(self):
        holder = wallet(9000)
        shop.purchase(holder, "streak_shield", NOW)
        shop.purchase(holder, "streak_shield", NOW)

        self.assertEqual(shop.shields(holder), 2)

    def test_a_wallet_with_no_shields_reports_zero(self):
        self.assertEqual(shop.shields(wallet()), 0)

    def test_nonsense_in_storage_is_read_as_none(self):
        self.assertEqual(shop.shields(wallet(0, streak_shields="lots")), 0)
        self.assertEqual(shop.shields(wallet(0, streak_shields=-4)), 0)


class TitleTests(unittest.TestCase):
    def test_a_title_must_be_owned_before_it_can_be_worn(self):
        holder = wallet(0)

        self.assertFalse(shop.equip_title(holder, "title_legend"))
        self.assertIsNone(shop.worn_title(holder))

    def test_buying_then_wearing_a_title_shows_it(self):
        holder = wallet(9000)
        shop.purchase(holder, "title_veteran", NOW)

        self.assertTrue(shop.equip_title(holder, "title_veteran"))
        self.assertEqual(shop.worn_title(holder), "Veteran")

    def test_a_title_can_be_taken_off(self):
        holder = wallet(9000)
        shop.purchase(holder, "title_veteran", NOW)
        shop.equip_title(holder, "title_veteran")

        self.assertTrue(shop.equip_title(holder, None))
        self.assertIsNone(shop.worn_title(holder))

    def test_a_worn_title_that_is_no_longer_owned_is_not_shown(self):
        # Defends the display against a wallet edited or restored by hand.
        holder = wallet(0, title="title_legend", titles=[])

        self.assertIsNone(shop.worn_title(holder))

    def test_a_trophy_cannot_be_worn_as_a_title(self):
        holder = wallet(0, trophies=["crown"], titles=[])

        self.assertFalse(shop.equip_title(holder, "crown"))


class CrateTests(unittest.TestCase):
    def test_a_crate_costs_its_price_and_pays_out(self):
        holder = wallet(1000)

        result = shop.open_crate(holder, NOW, rng=FixedRandom(0))

        self.assertTrue(result.ok)
        # 1000 - 500 for the crate, + 250 from the first row of the table.
        self.assertEqual(holder["coins"], 750)
        self.assertEqual(result.granted, ["250 coins"])

    def test_a_crate_can_pay_out_an_item(self):
        holder = wallet(1000)
        index = next(i for i, row in enumerate(shop.CRATE_TABLE) if row["kind"] == "item")

        result = shop.open_crate(holder, NOW, rng=FixedRandom(index))

        self.assertTrue(result.ok)
        self.assertTrue(result.granted)

    def test_a_crate_that_cannot_be_afforded_is_not_opened(self):
        holder = wallet(10)

        result = shop.open_crate(holder, NOW, rng=FixedRandom(0))

        self.assertFalse(result.ok)
        self.assertEqual(holder["coins"], 10)

    def test_a_duplicate_reward_still_reads_as_something(self):
        # Granting an item already owned changes nothing; the crate must not
        # then look empty.
        index = next(i for i, row in enumerate(shop.CRATE_TABLE) if row["kind"] == "item")
        duplicate = shop.CRATE_TABLE[index]["item"]
        holder = wallet(1000, trophies=[duplicate], titles=[duplicate])

        result = shop.open_crate(holder, NOW, rng=FixedRandom(index))

        self.assertTrue(result.granted)


class PerkApplicationTests(unittest.TestCase):
    """The perks are only worth buying if the rest of the bot reads them."""

    def test_the_work_cooldown_is_untouched_without_the_perk(self):
        self.assertEqual(shop.work_cooldown(wallet(), timedelta(hours=1), NOW), timedelta(hours=1))

    def test_the_work_perk_halves_the_cooldown(self):
        holder = wallet(5000)
        shop.purchase(holder, shop.WORK_RUSH, NOW)

        self.assertEqual(
            shop.work_cooldown(holder, timedelta(hours=1), NOW), timedelta(minutes=30)
        )

    def test_the_cooldown_returns_to_normal_when_the_perk_expires(self):
        holder = wallet(5000)
        shop.purchase(holder, shop.WORK_RUSH, NOW)
        later = NOW + timedelta(hours=shop.WORK_RUSH_HOURS, minutes=1)

        self.assertEqual(shop.work_cooldown(holder, timedelta(hours=1), later), timedelta(hours=1))

    def test_a_shield_is_spent_once(self):
        holder = wallet(0, streak_shields=1)

        self.assertTrue(shop.use_shield(holder))
        self.assertFalse(shop.use_shield(holder))
        self.assertEqual(shop.shields(holder), 0)

    def test_a_booster_multiplies_xp_as_the_levels_cog_applies_it(self):
        from cogs.levels import boosted_xp

        holder = wallet(5000)
        shop.purchase(holder, shop.XP_BOOST, NOW)
        multiplier = shop.effect_value(holder, shop.XP_BOOST, NOW)

        self.assertEqual(boosted_xp(10, multiplier), 15)

    def test_xp_is_never_reduced_by_a_bad_multiplier(self):
        from cogs.levels import boosted_xp

        # Whatever ends up in storage, a message must not earn less than the
        # roll it started with.
        for bad in (0, 0.5, -3, None, "fast"):
            with self.subTest(multiplier=bad):
                self.assertGreaterEqual(boosted_xp(10, bad), 10)

    def test_a_boosted_gain_is_rounded_rather_than_floored(self):
        from cogs.levels import boosted_xp

        # 5 * 1.5 is 7.5. Flooring it would hand back less than half of what
        # the booster promised on small rolls.
        self.assertEqual(boosted_xp(5, 1.5), 8)

    def test_a_message_always_earns_something(self):
        from cogs.levels import boosted_xp

        self.assertEqual(boosted_xp(0, 1.5), 1)


class WalletStorageTests(unittest.TestCase):
    """Shop state has to survive a restart, including on an old database."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

        import core.database as database

        self.db = database
        for patch in (
            mock.patch.object(database, "DATA_DIR", Path(self._dir.name)),
            mock.patch.object(database, "DB_PATH", Path(self._dir.name) / "test.sqlite3"),
            mock.patch.object(database, "_INITIALIZED", False),
        ):
            patch.start()
            self.addCleanup(patch.stop)

        database.init_database()

    def test_effects_titles_and_shields_survive_a_round_trip(self):
        holder = wallet(9000)
        shop.purchase(holder, shop.XP_BOOST, NOW)
        shop.purchase(holder, "title_veteran", NOW)
        shop.equip_title(holder, "title_veteran")
        shop.purchase(holder, "streak_shield", NOW)

        self.db.upsert_economy_wallets([("111", "a", holder)])
        restored = self.db.load_economy_data()["111"]["a"]

        self.assertEqual(restored["coins"], holder["coins"])
        self.assertEqual(shop.worn_title(restored), "Veteran")
        self.assertEqual(shop.shields(restored), 1)
        self.assertEqual(shop.effect_value(restored, shop.XP_BOOST, NOW), 1.5)

    def test_a_wallet_written_before_the_shop_grew_still_loads(self):
        # An install upgrading in place has rows with no extras at all.
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO economy_wallets"
                " (guild_id, user_id, coins, daily_streak, trophies, extras, updated_at)"
                " VALUES ('111', 'old', 500, 3, '[\"star\"]', '', '2026-01-01T00:00:00+00:00')"
            )
            connection.commit()

        restored = self.db.load_economy_data()["111"]["old"]

        self.assertEqual(restored["coins"], 500)
        self.assertEqual(restored["trophies"], ["star"])
        self.assertEqual(shop.shields(restored), 0)
        self.assertIsNone(shop.worn_title(restored))

    def test_the_extras_column_is_added_to_a_database_that_predates_it(self):
        # Recreate the pre-shop table, then let init_database migrate it.
        with self.db.connect() as connection:
            connection.execute("DROP TABLE economy_wallets")
            connection.execute(
                "CREATE TABLE economy_wallets ("
                " guild_id TEXT NOT NULL, user_id TEXT NOT NULL,"
                " coins INTEGER NOT NULL DEFAULT 0, daily_streak INTEGER NOT NULL DEFAULT 0,"
                " last_daily TEXT, last_work TEXT, trophies TEXT NOT NULL DEFAULT '[]',"
                " updated_at TEXT NOT NULL, PRIMARY KEY (guild_id, user_id))"
            )
            connection.execute(
                "INSERT INTO economy_wallets"
                " (guild_id, user_id, coins, trophies, updated_at)"
                " VALUES ('111', 'legacy', 77, '[]', '2026-01-01T00:00:00+00:00')"
            )
            connection.commit()

        with mock.patch.object(self.db, "_INITIALIZED", False):
            self.db.init_database()

        with self.db.connect() as connection:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(economy_wallets)")
            }

        self.assertIn("extras", columns)
        self.assertEqual(self.db.load_economy_data()["111"]["legacy"]["coins"], 77)

    def test_migrating_twice_is_harmless(self):
        for _ in range(2):
            with mock.patch.object(self.db, "_INITIALIZED", False):
                self.db.init_database()

        self.assertEqual(self.db.load_economy_data(), {})


if __name__ == "__main__":
    unittest.main()
