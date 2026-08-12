"""Privacy disclosures appear before optional processing is enabled or used."""

import unittest

from cogs.ai import AI
from cogs.setup import SETUP_PRIVACY_NOTICE


class PrivacyNoticeTests(unittest.TestCase):
    def test_setup_names_optional_disclosures_and_member_controls(self):
        self.assertIn("Server Logs", SETUP_PRIVACY_NOTICE)
        self.assertIn("Anthropic", SETUP_PRIVACY_NOTICE)
        self.assertIn("/privacy export", SETUP_PRIVACY_NOTICE)
        self.assertIn("/privacy delete", SETUP_PRIVACY_NOTICE)

    def test_ask_command_names_the_external_provider_before_submission(self):
        self.assertIn("Anthropic", AI.ask.description)
        parameter = next(item for item in AI.ask.parameters if item.name == "question")
        self.assertIn("Anthropic", parameter.description)


if __name__ == "__main__":
    unittest.main()
