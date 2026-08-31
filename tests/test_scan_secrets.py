"""The secret scanner: it has to catch real credentials and ignore this tree.

Both halves matter equally. A scanner that misses a Discord token is useless;
one that flags the SHA-256 hashes in worker/inline-hashes.js or the
--generate-hashes lines in requirements.lock gets an exclusion list, then a
bigger one, and then somebody turns it off. This project already wrote that
lesson down in deploy-website.yml.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.scan_secrets import (  # noqa: E402
    scan_text,
    scan_working_tree,
)

# Shaped like the real thing, structurally invalid, and never issued. Split so
# the scanner's own test file cannot be mistaken for a leak by a third-party
# tool reading it out of context.
FAKE = {
    "Discord bot token": "MTA" + "1" * 21 + "." + "GaBcDe" + "." + "z" * 30,
    "GitHub personal access token": "ghp_" + "A" * 36,
    "GitHub fine-grained token": "github_pat_" + "B" * 72,
    "Anthropic API key": "sk-ant-" + "C" * 24,
    "OpenAI API key": "sk-proj-" + "D" * 24,
    "AWS access key id": "AKIA" + "E" * 16,
    "Google API key": "AIza" + "F" * 35,
    "Slack token": "xoxb-" + "1" * 12 + "-abcdef",
    "Cloudflare API token": "v1.0-" + "G" * 40,
    "Private key block": "-----BEGIN OPENSSH PRIVATE KEY-----",
}


class DetectionTests(unittest.TestCase):
    def test_every_pattern_catches_its_own_credential(self):
        for kind, sample in FAKE.items():
            with self.subTest(kind=kind):
                found = scan_text(f"TOKEN={sample}", "fixture")
                self.assertTrue(found, f"{kind} was not detected")
                self.assertEqual(found[0].kind, kind)

    def test_a_discord_webhook_url_is_caught(self):
        url = "https://discord.com/api/webhooks/123456789012345678/" + "h" * 68
        self.assertTrue(scan_text(url, "fixture"))

    def test_a_finding_never_prints_the_secret(self):
        found = scan_text(f"TOKEN={FAKE['GitHub personal access token']}", "fixture")
        self.assertNotIn("ghp_", str(found[0]))

    def test_history_mode_reads_added_lines_only(self):
        diff = (
            "--- a/.env\n"
            "+++ b/.env\n"
            f"-TOKEN={FAKE['Anthropic API key']}\n"
            "+TOKEN=redacted\n"
        )
        # A removed line is history, not a new leak; the added one is clean.
        self.assertEqual(scan_text(diff, "history", added_only=True), [])

        adding = f"+++ b/.env\n+TOKEN={FAKE['Anthropic API key']}\n"
        self.assertTrue(scan_text(adding, "history", added_only=True))


class FalsePositiveTests(unittest.TestCase):
    """The half that decides whether anyone leaves this gate switched on."""

    def test_placeholders_from_env_example_are_not_credentials(self):
        for placeholder in (
            "TOKEN=your_discord_bot_token_here",
            "GITHUB_TOKEN=your_github_token_here",
            "ANTHROPIC_API_KEY=",
            "DISCORD_CLIENT_SECRET=",
            "LAVALINK_PASSWORD=",
        ):
            with self.subTest(placeholder=placeholder):
                self.assertEqual(scan_text(placeholder, "fixture"), [])

    def test_csp_hashes_are_not_credentials(self):
        line = '  "sha256-0sxvQxDRjMb7eB222IpJeYAAONlOtkPqLWI5sDsYzvE=",'
        self.assertEqual(scan_text(line, "fixture"), [])

    def test_pip_lock_hashes_are_not_credentials(self):
        line = "    --hash=sha256:a1b2c3d4e5f60718293a4b5c6d7e8f901234567890abcdef1234567890abcdef"
        self.assertEqual(scan_text(line, "fixture"), [])

    def test_a_fernet_token_in_a_fixture_is_not_a_credential(self):
        line = "enc:gAAAAABm" + "x" * 80
        self.assertEqual(scan_text(line, "fixture"), [])

    def test_a_git_sha_is_not_a_credential(self):
        line = "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
        self.assertEqual(scan_text(line, "fixture"), [])

    def test_the_repository_itself_is_clean(self):
        # The assertion the CI job exists to make. If this ever fails, the fix
        # is to rotate the credential - deleting the line does not help, the
        # object stays reachable in every clone.
        findings = scan_working_tree()
        self.assertEqual([str(f) for f in findings], [])


if __name__ == "__main__":
    unittest.main()
