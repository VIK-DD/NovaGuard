"""The operational privacy register stays aligned with enforced defaults."""

import unittest
from pathlib import Path

from core.privacy import RETENTION_DEFAULTS


ROOT = Path(__file__).resolve().parents[1]


class PrivacyOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.register = (ROOT / "docs" / "PRIVACY-OPERATIONS.md").read_text(encoding="utf-8")

    def test_register_covers_every_configurable_retention_default(self):
        expected_periods = {
            "PRIVACY_TICKET_KEEP_DAYS": "Closed tickets 180 days",
            "PRIVACY_WARNING_KEEP_DAYS": "warnings 365 days",
            "PRIVACY_GIVEAWAY_KEEP_DAYS": "completed giveaways 90 days",
            "PRIVACY_VOICE_KEEP_MONTHS": "voice history 13 months",
            "PRIVACY_ADMIN_AUDIT_KEEP_DAYS": "privileged bot audit 365 days",
            "PRIVACY_DASHBOARD_AUDIT_KEEP_DAYS": "dashboard audit/IP 90 days",
        }
        self.assertEqual(set(expected_periods), set(RETENTION_DEFAULTS))
        for env_name, disclosure in expected_periods.items():
            with self.subTest(env_name=env_name):
                self.assertIn(disclosure, self.register)
                self.assertIn(str(RETENTION_DEFAULTS[env_name]), disclosure)

    def test_register_covers_processors_rights_and_deletion_safety(self):
        for required in (
            "Discord",
            "Cloudflare",
            "Oracle",
            "GitHub",
            "Anthropic",
            "/privacy export",
            "/privacy delete",
            "deletion token",
            "data-protection impact assessment",
            "human review",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.register)


if __name__ == "__main__":
    unittest.main()
