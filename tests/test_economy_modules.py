"""Direct contracts for the extracted economy helpers."""

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

import cogs.economy as economy_cog
from core import economy_helpers, economy_presenters


class FakeGuild:
    def __init__(self, guild_id, members=None):
        self.id = guild_id
        self._members = members or {}

    def get_member(self, user_id):
        name = self._members.get(user_id)
        return SimpleNamespace(display_name=name) if name else None


class FakeTarget:
    def __init__(self, display_name="Victor"):
        self.display_name = display_name
        self.display_avatar = SimpleNamespace(url="https://example.com/avatar.png")


class EconomyCompatibilityTests(unittest.TestCase):
    def test_cog_reexports_moved_helpers(self):
        for name in (
            "CURRENCY",
            "SLOT_REELS",
            "SlotOutcome",
            "parse_saved_datetime",
            "get_wallet",
            "wallet_snapshot",
            "economy_status_payload",
            "ranked_wallets",
            "slot_outcome",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(economy_cog, name), getattr(economy_helpers, name))

        for name in (
            "build_balance_embed",
            "build_richest_embed",
            "build_shop_embed",
            "build_inventory_embed",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(economy_cog, name), getattr(economy_presenters, name))


class EconomyWalletHelperTests(unittest.TestCase):
    def test_saved_datetimes_are_normalized_to_utc(self):
        naive = economy_helpers.parse_saved_datetime("2026-08-27T12:00:00")
        offset = economy_helpers.parse_saved_datetime("2026-08-27T15:00:00+03:00")

        self.assertEqual(naive, datetime(2026, 8, 27, 12, tzinfo=UTC))
        self.assertEqual(offset, datetime(2026, 8, 27, 12, tzinfo=UTC))
        self.assertIsNone(economy_helpers.parse_saved_datetime("broken"))

    def test_wallet_creation_and_snapshot_have_distinct_side_effects(self):
        data = {}

        self.assertIsNone(economy_helpers.wallet_snapshot(data, 1, 2))
        self.assertEqual(data, {})

        created = economy_helpers.get_wallet(data, 1, 2)

        self.assertEqual(created["coins"], 0)
        self.assertIs(economy_helpers.get_wallet(data, "1", "2"), created)
        self.assertIs(economy_helpers.wallet_snapshot(data, 1, 2), created)

    def test_dashboard_payload_is_sanitized_and_does_not_create_wallets(self):
        data = {
            "7": {
                "10": {"coins": 250, "daily_streak": 4},
                "11": {"coins": -50, "daily_streak": -2},
                "legacy": {"coins": "not-a-number", "daily_streak": None},
                "ignored": "not a wallet",
            }
        }
        before = {guild_id: dict(wallets) for guild_id, wallets in data.items()}

        payload = economy_helpers.economy_status_payload(
            data,
            FakeGuild(7, {10: "Ada"}),
        )

        self.assertEqual(payload["tracked_wallets"], 3)
        self.assertEqual(payload["total_coins"], 250)
        self.assertEqual(payload["leaderboard"][0]["display_name"], "Ada")
        self.assertEqual(payload["leaderboard"][0]["coins"], 250)
        self.assertEqual(payload["leaderboard"][1]["coins"], 0)
        self.assertGreater(len(payload["shop"]), 0)
        self.assertEqual(data, before)

    def test_ranking_ignores_empty_negative_and_malformed_wallets(self):
        data = {
            "7": {
                "10": {"coins": 50},
                "11": {"coins": "250"},
                "12": {"coins": -1},
                "13": {"coins": "broken"},
                "ignored": None,
            }
        }

        self.assertEqual(
            economy_helpers.ranked_wallets(data, 7),
            [("11", 250), ("10", 50)],
        )


class EconomySlotHelperTests(unittest.TestCase):
    def test_sevens_pay_ten_times_including_the_returned_stake(self):
        result = economy_helpers.slot_outcome(["7️⃣", "7️⃣", "7️⃣"], 100)

        self.assertEqual(result, economy_helpers.SlotOutcome("jackpot", 900, 10))

    def test_regular_triple_and_pair_keep_existing_payouts(self):
        triple = economy_helpers.slot_outcome(["🍒", "🍒", "🍒"], 101)
        pair = economy_helpers.slot_outcome(["🍋", "🍇", "🍋"], 101)

        self.assertEqual(triple, economy_helpers.SlotOutcome("jackpot", 404, 5))
        self.assertEqual(pair, economy_helpers.SlotOutcome("pair", 50))

    def test_loss_removes_the_stake(self):
        result = economy_helpers.slot_outcome(["🍒", "🍋", "🍇"], 100)

        self.assertEqual(result, economy_helpers.SlotOutcome("loss", -100))

    def test_invalid_spin_shape_and_negative_stake_are_rejected(self):
        with self.assertRaises(ValueError):
            economy_helpers.slot_outcome(["🍒", "🍋"], 100)
        with self.assertRaises(ValueError):
            economy_helpers.slot_outcome(["🍒", "🍋", "🍇"], -1)


class EconomyPresenterTests(unittest.TestCase):
    def rich_wallet(self):
        return {
            "coins": 12_500,
            "daily_streak": 7,
            "streak_shields": 2,
            "trophies": ["star"],
            "titles": ["title_legend"],
            "title": "title_legend",
            "effects": {
                "xp_boost": {
                    "item": "xp_boost",
                    "value": 1.5,
                    "expires_at": "2099-01-01T00:00:00+00:00",
                }
            },
        }

    def test_balance_card_keeps_title_collectibles_and_active_effects(self):
        embed = economy_presenters.build_balance_embed(FakeTarget(), self.rich_wallet())
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "💰 Victor's wallet")
        self.assertIn("12,500", embed.description)
        self.assertEqual(embed.author.name, "Legend · Victor")
        self.assertEqual(embed.thumbnail.url, "https://example.com/avatar.png")
        self.assertEqual(fields["🛡️ Streak shields"], "`2`")
        self.assertEqual(fields["🏆 Trophy shelf"], "⭐")
        self.assertIn("XP Boost", fields["✨ Active"])

    def test_richest_card_handles_empty_and_ranked_wallets(self):
        guild = SimpleNamespace(name="Nova")

        empty = economy_presenters.build_richest_embed(guild, [])
        ranked = economy_presenters.build_richest_embed(
            guild,
            [("10", 500), ("11", 250), ("12", 100)],
        )

        self.assertEqual(empty.title, "🌱 Nothing yet")
        self.assertEqual(ranked.title, "💰 Richest • Nova")
        self.assertIn("🥇 <@10>", ranked.description)
        self.assertIn("🥉 <@12>", ranked.description)

    def test_shop_card_groups_catalog_and_marks_owned_items(self):
        embed = economy_presenters.build_shop_embed(self.rich_wallet())
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "🛍️ Shop")
        self.assertEqual(
            list(fields),
            ["⚡ Boosters", "🛠️ Perks", "🎖️ Titles", "🏆 Trophies", "📦 Crates"],
        )
        self.assertIn("Legend", fields["🎖️ Titles"])
        self.assertIn("*(owned)*", fields["🎖️ Titles"])
        self.assertIn("*(owned)*", fields["🏆 Trophies"])

    def test_inventory_card_has_safe_empty_and_populated_states(self):
        empty = economy_presenters.build_inventory_embed(FakeTarget(), {"coins": 0})
        populated = economy_presenters.build_inventory_embed(FakeTarget(), self.rich_wallet())
        empty_fields = {field.name: field.value for field in empty.fields}
        populated_fields = {field.name: field.value for field in populated.fields}

        self.assertEqual(empty.description, "No title worn.")
        self.assertEqual(empty_fields["✨ Running now"], "-# Nothing active.")
        self.assertEqual(empty_fields["📦 Owned"], "-# Nothing yet.")
        self.assertEqual(populated.description, "Wearing **Legend**.")
        self.assertIn("XP Boost", populated_fields["✨ Running now"])
        self.assertIn("Legend", populated_fields["📦 Owned"])
        self.assertEqual(populated_fields["🛡️ Streak shields"], "`2`")


if __name__ == "__main__":
    unittest.main()
