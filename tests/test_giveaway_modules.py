"""Direct contracts for the extracted giveaway helpers and presenters."""

import unittest

import cogs.giveaways as giveaway_cog
from core import giveaway_helpers, giveaway_presenters


def entry(*, entrants=None, winners=2):
    return {
        "message_id": 900,
        "channel_id": 55,
        "guild_id": 1,
        "prize": "One month of Nitro",
        "winners": winners,
        "entrants": list(entrants or []),
        "ended": False,
        "winner_ids": [],
        "ends_at": "2026-08-28T18:00:00+00:00",
        "host_name": "VIK",
    }


class GiveawayCompatibilityTests(unittest.TestCase):
    def test_cog_reexports_moved_helpers_and_presenters(self):
        for name in ("draw_winners", "validate_giveaway_input"):
            with self.subTest(name=name):
                self.assertIs(getattr(giveaway_cog, name), getattr(giveaway_helpers, name))

        for name in (
            "build_giveaway_embed",
            "build_giveaway_result_embed",
            "build_giveaway_reroll_announcement_embed",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(giveaway_cog, name), getattr(giveaway_presenters, name))


class GiveawayHelperTests(unittest.TestCase):
    def test_draw_is_unique_and_never_exceeds_the_available_entrants(self):
        winners = giveaway_helpers.draw_winners([1, 1, 2, 3], 10)

        self.assertEqual(set(winners), {1, 2, 3})
        self.assertEqual(len(winners), 3)

    def test_reroll_avoids_previous_winners_when_fresh_people_are_available(self):
        winners = giveaway_helpers.draw_winners([1, 2, 3, 4], 2, exclude=[1, 2])

        self.assertEqual(set(winners), {3, 4})

    def test_reroll_uses_previous_winners_only_to_fill_advertised_slots(self):
        winners = giveaway_helpers.draw_winners([1, 2, 3], 2, exclude=[1, 2])

        self.assertEqual(len(winners), 2)
        self.assertIn(3, winners)
        self.assertEqual(len(set(winners)), 2)

    def test_validation_normalizes_shared_dashboard_and_slash_input(self):
        duration, prize, winners, errors = giveaway_helpers.validate_giveaway_input(
            "1h 30m",
            "  Nitro   prize ",
            2,
        )

        self.assertEqual(int(duration.total_seconds()), 5400)
        self.assertEqual(prize, "Nitro prize")
        self.assertEqual(winners, 2)
        self.assertEqual(errors, [])

    def test_validation_rejects_boolean_winner_counts(self):
        *_, errors = giveaway_helpers.validate_giveaway_input("1h", "Prize", True)

        self.assertTrue(any("winners" in error for error in errors))


class GiveawayPresenterTests(unittest.TestCase):
    def test_active_card_reports_schedule_winners_and_entry_count(self):
        embed = giveaway_presenters.build_giveaway_embed(
            entry(entrants=[10, 20, 30], winners=2)
        )

        self.assertEqual(embed.title, "🎁 GIVEAWAY")
        self.assertIn("One month of Nitro", embed.description)
        self.assertIn("Winners: `2`", embed.description)
        self.assertIn("Entries: `3`", embed.description)

    def test_ended_card_names_every_winner(self):
        embed = giveaway_presenters.build_giveaway_embed(
            entry(entrants=[10, 20]),
            ended=True,
            winner_ids=[10, 20],
        )

        self.assertEqual(embed.title, "🏁 GIVEAWAY ENDED")
        self.assertIn("Winners", embed.description)
        self.assertIn("<@10>", embed.description)
        self.assertIn("<@20>", embed.description)

    def test_ended_card_is_truthful_when_nobody_entered(self):
        embed = giveaway_presenters.build_giveaway_embed(entry(), ended=True, winner_ids=[])

        self.assertIn("No valid entries", embed.description)

    def test_result_and_reroll_cards_keep_prize_and_mentions(self):
        giveaway = entry(entrants=[10, 20])

        result = giveaway_presenters.build_giveaway_result_embed(giveaway, [10])
        reroll = giveaway_presenters.build_giveaway_reroll_announcement_embed(
            giveaway,
            [10, 20],
        )

        self.assertIn("<@10>", result.description)
        self.assertIn("One month of Nitro", result.description)
        self.assertIn("<@10>", reroll.description)
        self.assertIn("<@20>", reroll.description)
        self.assertIn("One month of Nitro", reroll.description)


if __name__ == "__main__":
    unittest.main()
