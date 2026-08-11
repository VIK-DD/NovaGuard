"""AI settings are strict, bounded and shared by bot and dashboard."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai_settings import AI_DEFAULTS, resolve_ai, validate_ai  # noqa: E402


class AISettingsTests(unittest.TestCase):
    def test_defaults_preserve_existing_public_ask_behavior(self):
        self.assertEqual(resolve_ai({}), AI_DEFAULTS)

    def test_valid_partial_patch_merges_with_saved_values(self):
        current = resolve_ai({"ai": {"answer_mode": "private", "channel_id": "10"}})
        value, errors = validate_ai({"max_question_chars": 800}, current, {"10", "11"})
        self.assertEqual(errors, [])
        self.assertEqual(value["answer_mode"], "private")
        self.assertEqual(value["channel_id"], "10")
        self.assertEqual(value["max_question_chars"], 800)

    def test_invalid_values_are_not_coerced(self):
        value, errors = validate_ai(
            {
                "enabled": "false",
                "answer_mode": "secret",
                "channel_id": "99",
                "max_question_chars": True,
                "prompt": "ignore safeguards",
            },
            AI_DEFAULTS,
            {"10"},
        )
        self.assertIsNone(value)
        self.assertEqual(len(errors), 5)

    def test_channel_can_be_cleared(self):
        value, errors = validate_ai({"channel_id": None}, AI_DEFAULTS, {"10"})
        self.assertEqual(errors, [])
        self.assertIsNone(value["channel_id"])


if __name__ == "__main__":
    unittest.main()
