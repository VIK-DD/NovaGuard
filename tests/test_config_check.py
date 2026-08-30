"""Tests for the startup configuration report."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config_check import (  # noqa: E402
    CRITICAL,
    OK,
    WARN,
    check_config,
    format_report,
    problems,
    report_config,
)

HEALTHY = {
    "TOKEN": "a-token",
    "GUILD_ID": "123",
    "BACKUP_REMOTE_DEST": "gdrive:NovaGuard",
    "BACKUP_ENCRYPTION_KEY": "a-long-random-backup-key-with-more-than-32-chars",
    "GITHUB_WATCH_REPOS": "owner/repo",
    "GITHUB_TOKEN": "a-github-token",
}


def findings_for(overrides=None):
    env = dict(HEALTHY)
    env.update(overrides or {})
    return check_config(env)


def names(findings, level=None):
    return {f.name for f in findings if level is None or f.level == level}


class HealthyConfigTests(unittest.TestCase):
    def test_a_complete_config_reports_no_problems(self):
        self.assertEqual(problems(findings_for()), [])

    def test_a_healthy_config_still_confirms_the_important_settings(self):
        self.assertEqual(
            names(findings_for(), OK),
            {
                "TOKEN",
                "BACKUP_REMOTE_DEST",
                "BACKUP_ENCRYPTION_KEY",
                "GITHUB_WATCH_REPOS",
            },
        )


class CriticalTests(unittest.TestCase):
    def test_a_missing_token_is_critical(self):
        found = findings_for({"TOKEN": ""})
        self.assertIn("TOKEN", names(found, CRITICAL))

    def test_blank_and_whitespace_tokens_are_both_missing(self):
        self.assertIn("TOKEN", names(findings_for({"TOKEN": "   "}), CRITICAL))


class SilentFailureTests(unittest.TestCase):
    def test_an_empty_backup_destination_is_warned_about(self):
        # The check that matters most: without it, backups sit on the host
        # and vanish with it, and nothing says so until the host is gone.
        found = findings_for({"BACKUP_REMOTE_DEST": ""})

        self.assertIn("BACKUP_REMOTE_DEST", names(found, WARN))
        detail = next(f.detail for f in found if f.name == "BACKUP_REMOTE_DEST")
        self.assertIn("DISASTER-RECOVERY", detail)

    def test_a_missing_or_short_backup_encryption_key_is_critical(self):
        for value in ("", "too-short"):
            with self.subTest(value=value):
                found = findings_for({"BACKUP_ENCRYPTION_KEY": value})
                self.assertIn("BACKUP_ENCRYPTION_KEY", names(found, CRITICAL))

    def test_a_missing_guild_id_only_warns_about_slow_sync(self):
        found = findings_for({"GUILD_ID": ""})

        self.assertIn("GUILD_ID", names(found, WARN))
        self.assertEqual(names(found, CRITICAL), set())


class WebServerTests(unittest.TestCase):
    def test_an_unsigned_dashboard_session_is_flagged(self):
        found = findings_for({"WEB_ENABLED": "true", "WEB_COOKIE_SECURE": "true"})

        self.assertIn("WEB_TOKEN_KEY", names(found, WARN))

    def test_insecure_cookies_are_flagged(self):
        found = findings_for(
            {"WEB_ENABLED": "true", "WEB_TOKEN_KEY": "key", "WEB_COOKIE_SECURE": "false"}
        )

        self.assertIn("WEB_COOKIE_SECURE", names(found, WARN))

    def test_web_checks_are_skipped_when_the_server_is_off(self):
        found = findings_for({"WEB_ENABLED": "false"})

        self.assertEqual(names(found) & {"WEB_TOKEN_KEY", "WEB_COOKIE_SECURE"}, set())

    def test_a_hardened_public_dashboard_has_no_web_findings(self):
        found = findings_for(
            {
                "WEB_ENABLED": "true",
                "DISCORD_CLIENT_ID": "123",
                "DISCORD_CLIENT_SECRET": "discord-client-secret",
                "WEB_TOKEN_KEY": "dedicated-dashboard-token-key-2026-xxxxxxxx",
                "WEB_COOKIE_SECURE": "true",
                "WEB_OAUTH_REDIRECT": "https://api.novaguard.fun/api/v1/auth/callback",
                "WEB_AFTER_LOGIN": "https://novaguard.fun/dashboard/",
                "WEB_CORS_ORIGIN": "https://novaguard.fun",
                "WEB_TRUST_PROXY": "true",
                "WEB_HOST": "127.0.0.1",
            }
        )

        web_names = {
            "DISCORD_CLIENT_ID",
            "DISCORD_CLIENT_SECRET",
            "WEB_TOKEN_KEY",
            "WEB_COOKIE_SECURE",
            "WEB_OAUTH_REDIRECT",
            "WEB_AFTER_LOGIN",
            "WEB_CORS_ORIGIN",
            "WEB_TRUST_PROXY",
            "WEB_HOST",
        }
        self.assertEqual(names(found, WARN) & web_names, set())
        self.assertEqual(names(found, CRITICAL) & web_names, set())

    def test_wildcard_or_path_cors_origins_are_critical(self):
        for origin in ("*", "https://novaguard.fun/dashboard", "http://novaguard.fun"):
            with self.subTest(origin=origin):
                found = findings_for(
                    {
                        "WEB_ENABLED": "true",
                        "WEB_CORS_ORIGIN": origin,
                    }
                )
                self.assertIn("WEB_CORS_ORIGIN", names(found, CRITICAL))

    def test_proxy_headers_are_critical_on_a_public_bind(self):
        found = findings_for(
            {
                "WEB_ENABLED": "true",
                "WEB_TRUST_PROXY": "true",
                "WEB_HOST": "0.0.0.0",
            }
        )

        self.assertIn("WEB_TRUST_PROXY", names(found, CRITICAL))


class GitHubTests(unittest.TestCase):
    """A feed that stays empty is indistinguishable from a quiet repository.

    The watcher returns immediately when no repository is named and logs
    nothing at all, so the only symptom is a channel where commits never
    appear — which looks exactly like nobody having pushed.
    """

    def names(self, findings):
        return {finding.name for finding in findings}

    def test_no_repository_named_is_reported_rather_than_silent(self):
        findings = problems(findings_for({"GITHUB_WATCH_REPOS": "", "GITHUB_PRIMARY_REPO": ""}))

        self.assertIn("GITHUB_WATCH_REPOS", self.names(findings))

    def test_a_primary_repository_alone_is_enough(self):
        # config.py falls back to the primary repo when the watch list is
        # empty, so warning here would be wrong.
        findings = problems(
            findings_for({"GITHUB_WATCH_REPOS": "", "GITHUB_PRIMARY_REPO": "owner/repo"})
        )

        self.assertNotIn("GITHUB_WATCH_REPOS", self.names(findings))

    def test_polling_without_a_token_is_worth_saying_out_loud(self):
        # 60 requests an hour per IP, and the events dropped while throttled
        # are never re-delivered.
        findings = problems(findings_for({"GITHUB_TOKEN": ""}))

        self.assertIn("GITHUB_TOKEN", self.names(findings))

    def test_a_configured_watcher_reports_ok_and_nothing_else(self):
        findings = findings_for()

        self.assertNotIn("GITHUB_WATCH_REPOS", self.names(problems(findings)))
        self.assertNotIn("GITHUB_TOKEN", self.names(problems(findings)))
        self.assertIn(
            "GITHUB_WATCH_REPOS",
            {f.name for f in findings if f.level == OK},
        )

    def test_the_repository_name_is_never_printed(self):
        # Same rule as every other check here: names, never values.
        text = format_report(findings_for({"GITHUB_WATCH_REPOS": "secret-org/private-repo"}))

        self.assertNotIn("secret-org", text)
        self.assertNotIn("private-repo", text)


class ReportTests(unittest.TestCase):
    def test_the_report_puts_the_worst_findings_first(self):
        # Missing token (CRITICAL), missing guild id (WARN) and a configured
        # backup destination (OK) - one of each level.
        lines = format_report(findings_for({"TOKEN": "", "GUILD_ID": ""}))

        self.assertIn("CRITICAL", lines[0])
        self.assertIn("WARN", lines[1])
        self.assertTrue(lines[-1].startswith("[config] OK"))

    def test_the_report_never_prints_secret_values(self):
        lines = format_report(findings_for({"TOKEN": "super-secret-token"}))

        self.assertNotIn("super-secret-token", " ".join(lines))

    def test_report_config_prints_and_summarises_problems(self):
        printed = []

        report_config({"TOKEN": "x"}, printer=printed.append)

        self.assertTrue(any("need attention" in line for line in printed))

    def test_a_healthy_config_prints_no_summary_line(self):
        printed = []

        report_config(dict(HEALTHY), printer=printed.append)

        self.assertFalse(any("need attention" in line for line in printed))


if __name__ == "__main__":
    unittest.main()
