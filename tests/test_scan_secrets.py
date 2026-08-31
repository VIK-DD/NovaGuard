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
    scan_history,
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
    # Assembled rather than written out, like the rest: a literal header here
    # is the one string in this file that any scanner would flag on sight.
    "Private key block": "-----BEGIN " + "OPENSSH PRIVATE KEY" + "-----",
    "npm access token": "npm_" + "A" * 36,
    "PyPI API token": "pypi-AgEIcHlwaS5vcmc" + "B" * 50,
    "Slack webhook": "https://hooks.slack.com/services/T0000000/B0000000/" + "c" * 24,
    "Stripe secret key": "sk_live_" + "D" * 24,
    "SendGrid API key": "SG." + "E" * 22 + "." + "F" * 43,
    "JSON Web Token": "eyJ" + "a" * 20 + ".eyJ" + "b" * 20 + "." + "c" * 43,
    "Database URL with credentials": "postgresql://novaguard:" + "s3cretpw" * 2 + "@db.internal/ng",
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


class OwnSecretTests(unittest.TestCase):
    """The keys with no vendor prefix - the ones worth the most.

    `WEB_TOKEN_KEY` decrypts every OAuth token at rest, `BACKUP_ENCRYPTION_KEY`
    every archive. Both are random bytes, so no shape rule can recognise them
    and the scanner was blind to exactly the secrets that matter most here.
    What *is* recognisable is the name sitting next to the value.
    """

    def test_a_filled_in_env_line_is_caught(self):
        for name in (
            "TOKEN",
            "WEB_TOKEN_KEY",
            "GATE_SIGNING_KEY",
            "BACKUP_ENCRYPTION_KEY",
            "LITESTREAM_SECRET_ACCESS_KEY",
            "DISCORD_CLIENT_SECRET",
        ):
            with self.subTest(name=name):
                line = f"{name}=8Jq2Vn5rTb9wKd3mXz7pLc4hRf6yGs1A"
                found = scan_text(line, "fixture")
                self.assertTrue(found, f"{name} with a real-looking value was missed")

    def test_the_blank_and_placeholder_forms_are_not_credentials(self):
        # .env.example must stay scannable without an exclusion, or the
        # exclusion becomes the hiding place.
        for line in (
            "WEB_TOKEN_KEY=",
            "TOKEN=your_discord_bot_token_here",
            "BACKUP_ENCRYPTION_KEY=change-me-to-32-random-bytes-abc",
            "GATE_SIGNING_KEY=<32 random bytes, base64url>",
            "AUTH_PASSWORD=xxxxxxxxxxxxxxxxxxxxxxxx",
        ):
            with self.subTest(line=line):
                self.assertEqual(scan_text(line, "fixture"), [])

    def test_documentation_and_code_that_names_a_secret_are_not_hits(self):
        # These forms appear all over the tree. If they flagged, the job would
        # be red on every run and someone would switch it off.
        for line in (
            'WEB_TOKEN_KEY=$(openssl rand -base64 32)',
            'key = os.getenv("WEB_TOKEN_KEY", "")',
            "GATE_SIGNING_KEY: ${{ secrets.GATE_SIGNING_KEY }}",
            'wrangler secret put GATE_SIGNING_KEY   # 32+ random bytes',
            'ANTHROPIC_API_KEY=sk-ant-your-key-here',
        ):
            with self.subTest(line=line):
                self.assertEqual(scan_text(line, "fixture"), [])

    def test_the_finding_still_never_prints_the_value(self):
        found = scan_text("WEB_TOKEN_KEY=8Jq2Vn5rTb9wKd3mXz7pLc4hRf6yGs1A", "fixture")
        self.assertNotIn("8Jq2Vn5r", str(found[0]))


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


class HistoryScopeTests(unittest.TestCase):
    """Exclusions have to mean the same thing in a diff as in the tree."""

    def test_an_excluded_path_is_excluded_in_history_too(self):
        # Without this the scanner reports its own fixtures on every run, the
        # job is permanently red, and a permanently red job gets switched off.
        diff = (
            "diff --git a/tests/test_scan_secrets.py b/tests/test_scan_secrets.py\n"
            "+++ b/tests/test_scan_secrets.py\n"
            f"+FAKE_TOKEN = \"{FAKE['GitHub personal access token']}\"\n"
        )
        self.assertEqual(scan_text(diff, "history", added_only=True), [])

    def test_the_same_line_in_any_other_file_is_reported(self):
        diff = (
            "diff --git a/core/config.py b/core/config.py\n"
            "+++ b/core/config.py\n"
            f"+TOKEN = \"{FAKE['GitHub personal access token']}\"\n"
        )
        found = scan_text(diff, "history", added_only=True)
        self.assertTrue(found)
        self.assertIn("core/config.py", found[0].location)

    def test_a_deleted_file_header_does_not_carry_the_previous_path(self):
        diff = (
            "+++ b/tests/test_scan_secrets.py\n"
            "+++ /dev/null\n"
            f"+TOKEN = \"{FAKE['Anthropic API key']}\"\n"
        )
        # /dev/null clears the path, so the line is scanned rather than
        # inheriting the exclusion from the hunk above it.
        self.assertTrue(scan_text(diff, "history", added_only=True))

    def test_the_history_is_clean(self):
        findings = scan_history()
        self.assertEqual([str(f) for f in findings], [])


if __name__ == "__main__":
    unittest.main()
