"""Regression tests for the shared AutoMod defaults."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.automod import compile_badwords  # noqa: E402
from core.automod_settings import (  # noqa: E402
    AUTOMOD_DEFAULTS,
    is_automod_exempt,
    resolve_automod,
    validate_automod,
)


class ResolveAutomodTests(unittest.TestCase):
    def test_defaults_for_missing_or_invalid_block(self):
        for settings in ({}, {"automod": None}, {"automod": "junk"}, None):
            config = resolve_automod(settings)
            self.assertEqual(config, AUTOMOD_DEFAULTS)

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

    def test_invalid_saved_advanced_values_fall_back_individually(self):
        config = resolve_automod(
            {
                "automod": {
                    "spam_messages": 2,
                    "spam_window_seconds": "6",
                    "spam_timeout_seconds": True,
                    "ignored_channels": "123",
                    "ignored_roles": ["7", "7", 8],
                }
            }
        )
        self.assertEqual(config["spam_messages"], 6)
        self.assertEqual(config["spam_window_seconds"], 6)
        self.assertEqual(config["spam_timeout_seconds"], 60)
        self.assertEqual(config["ignored_channels"], [])
        self.assertEqual(config["ignored_roles"], ["7", "8"])

    def test_valid_patch_merges_and_normalizes(self):
        config, errors = validate_automod(
            {
                "spam_messages": 8,
                "spam_window_seconds": 12,
                "spam_timeout_seconds": 300,
                "ignored_channels": ["11", "11"],
                "ignored_roles": ["21"],
                "badwords": [" Spoiler ", "spoiler"],
            },
            resolve_automod({}),
            {"11", "12"},
            {"21", "22"},
        )
        self.assertEqual(errors, [])
        self.assertEqual(config["spam_messages"], 8)
        self.assertEqual(config["ignored_channels"], ["11"])
        self.assertEqual(config["ignored_roles"], ["21"])
        self.assertEqual(config["badwords"], ["spoiler"])

    def test_patch_rejects_wrong_types_ranges_and_foreign_ids(self):
        _, errors = validate_automod(
            {
                "invites": "false",
                "spam_messages": 21,
                "ignored_channels": ["999"],
                "ignored_roles": ["888"],
                "future": True,
            },
            resolve_automod({}),
            {"11"},
            {"21"},
        )
        self.assertTrue(any("invites" in error for error in errors))
        self.assertTrue(any("spam_messages" in error for error in errors))
        self.assertTrue(any("ignored_channels" in error for error in errors))
        self.assertTrue(any("ignored_roles" in error for error in errors))
        self.assertTrue(any("future" in error for error in errors))

    def test_channel_parent_and_role_exemptions_match_as_strings(self):
        config = resolve_automod(
            {"automod": {"ignored_channels": ["11"], "ignored_roles": ["21"]}}
        )
        self.assertTrue(is_automod_exempt(config, channel_ids=[11]))
        self.assertTrue(is_automod_exempt(config, channel_ids=[99, 11]))
        self.assertTrue(is_automod_exempt(config, role_ids=[21]))
        self.assertFalse(is_automod_exempt(config, channel_ids=[12], role_ids=[22]))


class BlockedWordMatchingTests(unittest.TestCase):
    """Whole-word matching that also works in the alphabet this bot is used in."""

    def matches(self, words, text):
        return any(pattern.search(text.lower()) for pattern in compile_badwords(words))

    def test_a_blocked_word_matches_on_its_own(self):
        self.assertTrue(self.matches(["cur"], "ce cur mare"))
        self.assertTrue(self.matches(["cur"], "cur!"))
        self.assertTrue(self.matches(["naspa"], "NASPA"))

    def test_a_longer_word_that_merely_starts_with_it_does_not(self):
        self.assertFalse(self.matches(["prost"], "prostie"))
        self.assertFalse(self.matches(["cur"], "curand vine vara"))

    def test_a_following_accented_letter_is_still_part_of_the_word(self):
        # The bug \b had. Python's \w counts accented letters as word
        # characters, so "cur" + "â" is not a boundary and never matched -
        # which quietly made the filter unreliable in Romanian.
        self.assertFalse(self.matches(["cur"], "curând vine vara"))

    def test_an_accented_blocked_word_matches(self):
        self.assertTrue(self.matches(["ăla"], "ăla de acolo"))
        self.assertTrue(self.matches(["ăla"], "ăsta ăla"))

    def test_regex_metacharacters_are_literal(self):
        self.assertTrue(self.matches(["a.b"], "a.b"))
        self.assertFalse(self.matches(["a.b"], "axb"))

    def test_patterns_are_compiled_once_per_word_list(self):
        # They used to be rebuilt inside the message loop, up to a hundred per
        # message per guild, which overflowed the re module's own cache.
        self.assertIs(compile_badwords(["alpha"]), compile_badwords(["alpha"]))
        self.assertIsNot(compile_badwords(["alpha"]), compile_badwords(["beta"]))

    def test_changing_the_list_produces_a_new_set(self):
        first = compile_badwords(["alpha"])
        second = compile_badwords(["alpha", "beta"])
        self.assertIsNot(first, second)
        self.assertEqual(len(second), 2)


if __name__ == "__main__":
    unittest.main()
