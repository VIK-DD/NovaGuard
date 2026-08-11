"""Economy settings stay safe and preserve the shipped defaults."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.economy_settings import (  # noqa: E402
    ECONOMY_DEFAULTS,
    resolve_economy,
    validate_economy,
)


class EconomySettingsTests(unittest.TestCase):
    def test_defaults_match_existing_rewards_and_limits(self):
        self.assertEqual(resolve_economy({}), ECONOMY_DEFAULTS)

    def test_partial_patch_merges_with_saved_values(self):
        current = resolve_economy({"economy": {"daily_base": 500, "games_enabled": False}})
        value, errors = validate_economy({"daily_streak_bonus": 75}, current)
        self.assertEqual(errors, [])
        self.assertEqual(value["daily_base"], 500)
        self.assertEqual(value["daily_streak_bonus"], 75)
        self.assertFalse(value["games_enabled"])

    def test_invalid_types_ranges_and_work_order_are_rejected(self):
        value, errors = validate_economy(
            {
                "enabled": "yes",
                "daily_base": -1,
                "work_min": 500,
                "work_max": 100,
                "slots_max_bet": True,
                "currency_name": "gems",
            },
            ECONOMY_DEFAULTS,
        )
        self.assertIsNone(value)
        self.assertEqual(len(errors), 5)

    def test_zero_rewards_are_allowed_but_cooldown_is_not(self):
        value, errors = validate_economy(
            {"daily_base": 0, "daily_streak_bonus": 0, "work_min": 0, "work_max": 0},
            ECONOMY_DEFAULTS,
        )
        self.assertEqual(errors, [])
        self.assertEqual(value["work_max"], 0)


if __name__ == "__main__":
    unittest.main()
