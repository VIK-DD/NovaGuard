"""Privacy disclosures appear before optional processing is enabled or used."""

import unittest

from cogs.ai import AI
from cogs.privacy import PRIVACY_ADMIN_NOTICE_URL, PRIVACY_CONTROLS_TEXT
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

    def test_policy_help_lists_every_privacy_control_and_admin_notice(self):
        for command in (
            "/privacy export",
            "/privacy delete",
            "/privacy server-export",
            "/privacy server-delete",
        ):
            with self.subTest(command=command):
                self.assertIn(command, PRIVACY_CONTROLS_TEXT)
        self.assertEqual(PRIVACY_ADMIN_NOTICE_URL, "https://novaguard.fun/server-admin-notice")


if __name__ == "__main__":
    unittest.main()
