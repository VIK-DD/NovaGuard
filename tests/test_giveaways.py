"""Giveaway dashboard input is strict and predictable."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


if __name__ == "__main__":
    unittest.main()
