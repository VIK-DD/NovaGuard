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
}


def findings_for(overrides=None, **kwargs):
    env = dict(HEALTHY)
    env.update(overrides or {})
    return check_config(env, file_exists=kwargs.get("file_exists", lambda path: True))


def names(findings, level=None):
    return {f.name for f in findings if level is None or f.level == level}


class HealthyConfigTests(unittest.TestCase):
    def test_a_complete_config_reports_no_problems(self):
        self.assertEqual(problems(findings_for()), [])

    def test_a_healthy_config_still_confirms_the_important_settings(self):
        self.assertEqual(names(findings_for(), OK), {"TOKEN", "BACKUP_REMOTE_DEST"})


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

    def test_a_missing_cookies_file_is_warned_about(self):
        found = findings_for(
            {"MUSIC_YTDLP_COOKIES_FILE": "/home/ubuntu/cookies.txt"},
            file_exists=lambda path: False,
        )

        self.assertIn("MUSIC_YTDLP_COOKIES_FILE", names(found, WARN))

    def test_an_existing_cookies_file_is_not_flagged(self):
        found = findings_for({"MUSIC_YTDLP_COOKIES_FILE": "/home/ubuntu/cookies.txt"})

        self.assertNotIn("MUSIC_YTDLP_COOKIES_FILE", names(found))

    def test_a_socks_proxy_is_flagged_because_ffmpeg_cannot_use_it(self):
        found = findings_for({"MUSIC_YTDLP_PROXY": "socks5://proxy.test:1080"})

        self.assertIn("MUSIC_YTDLP_PROXY", names(found, WARN))

    def test_an_http_proxy_is_accepted(self):
        found = findings_for({"MUSIC_YTDLP_PROXY": "http://user:pass@proxy.test:3128"})

        self.assertNotIn("MUSIC_YTDLP_PROXY", names(found))

    def test_a_missing_guild_id_only_warns_about_slow_sync(self):
        found = findings_for({"GUILD_ID": ""})

        self.assertIn("GUILD_ID", names(found, WARN))
        self.assertEqual(names(found, CRITICAL), set())


class LavalinkBackendTests(unittest.TestCase):
    def test_the_default_lavalink_password_is_flagged(self):
        found = findings_for(
            {"MUSIC_BACKEND": "lavalink", "LAVALINK_PASSWORD": "youshallnotpass"}
        )

        self.assertIn("LAVALINK_PASSWORD", names(found, WARN))

    def test_a_custom_lavalink_password_passes(self):
        found = findings_for({"MUSIC_BACKEND": "lavalink", "LAVALINK_PASSWORD": "long-random"})

        self.assertNotIn("LAVALINK_PASSWORD", names(found))

    def test_lavalink_settings_are_ignored_on_the_ytdlp_backend(self):
        found = findings_for({"MUSIC_BACKEND": "yt-dlp", "LAVALINK_PASSWORD": "youshallnotpass"})

        self.assertNotIn("LAVALINK_PASSWORD", names(found))

    def test_an_unknown_backend_is_flagged(self):
        found = findings_for({"MUSIC_BACKEND": "sometypo"})

        self.assertIn("MUSIC_BACKEND", names(found, WARN))


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
