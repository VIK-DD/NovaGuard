"""Regression tests for the shared AutoMod defaults."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.automod_settings import AUTOMOD_DEFAULTS, resolve_automod  # noqa: E402


class ResolveAutomodTests(unittest.TestCase):
    def test_defaults_for_missing_or_invalid_block(self):
        for settings in ({}, {"automod": None}, {"automod": "junk"}, None):
            config = resolve_automod(settings)
            self.assertEqual(config, {"invites": True, "spam": True, "badwords": []})

    def test_saved_values_override_defaults(self):
        config = resolve_automod({"automod": {"invites": False, "badwords": ["spamword"]}})
        self.assertFalse(config["invites"])
        self.assertTrue(config["spam"])
        self.assertEqual(config["badwords"], ["spamword"])

    def test_non_list_badwords_is_neutralised(self):
        config = resolve_automod({"automod": {"badwords": "oops"}})
        self.assertEqual(config["badwords"], [])

    def test_mutating_result_never_leaks_into_defaults_or_other_guilds(self):
        # The old dict(AUTOMOD_DEFAULTS) pattern shared the default badwords
        # list, so one guild's append leaked into every unconfigured guild.
        first = resolve_automod({})
        first["badwords"].append("leaked")
        self.assertEqual(AUTOMOD_DEFAULTS["badwords"], [])
        self.assertEqual(resolve_automod({})["badwords"], [])


if __name__ == "__main__":
    unittest.main()
