"""Evidence that a rights request was served, without naming who made it."""

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import database, privacy, privacy_ledger, privacy_requests, storage  # noqa: E402


TEST_KEY = "privacy-request-log-test-key-xxxxxxxxxxxx"


class PrivacyRequestLogTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        patches = [
            mock.patch.object(database, "DATA_DIR", self.root),
            mock.patch.object(database, "DB_PATH", self.root / "novaguard.sqlite3"),
            mock.patch.object(database, "_INITIALIZED", False),
            mock.patch.object(storage, "DATA_DIR", self.root),
            mock.patch.dict(os.environ, {"BACKUP_ENCRYPTION_KEY": TEST_KEY}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        database.init_database()
        self.now = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)

    def test_a_served_request_is_recorded_with_its_kind_and_time(self):
        privacy_requests.record_privacy_request(
            "user_export", "123456789012345678", now=self.now
        )

        entries = privacy_requests.privacy_request_log()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "user_export")
        self.assertEqual(entries[0]["outcome"], "served")
        self.assertEqual(entries[0]["created_at"], self.now.isoformat())

    def test_the_log_never_stores_a_raw_discord_id(self):
        # The objection to keeping this log at all was that it becomes a list
        # of who exercised a privacy right. It must not be readable as one.
        privacy_requests.record_privacy_request(
            "user_delete", "123456789012345678", now=self.now
        )

        entries = privacy_requests.privacy_request_log()
        self.assertNotIn("123456789012345678", str(entries))
        self.assertEqual(len(entries[0]["subject_digest"]), 64)

    def test_the_same_subject_is_recognisable_across_requests(self):
        # Someone claiming "I asked and got nothing" can be matched only by
        # presenting their own id, which is the point of a keyed digest.
        privacy_requests.record_privacy_request("user_export", "42", now=self.now)
        privacy_requests.record_privacy_request("user_delete", "42", now=self.now)
        privacy_requests.record_privacy_request("user_export", "99", now=self.now)

        digests = [
            entry["subject_digest"] for entry in privacy_requests.privacy_request_log()
        ]

        self.assertEqual(digests[0], digests[1])
        self.assertNotEqual(digests[0], digests[2])
        self.assertEqual(privacy_requests.subject_digest("42"), digests[0])

    def test_the_request_digest_cannot_be_matched_against_the_deletion_ledger(self):
        # Two pseudonymous stores keyed identically would let anyone holding
        # both correlate them, undoing the pseudonymity of each.
        request = privacy_requests.subject_digest("42")
        deletion = privacy_ledger._identifier_digest("user", "42")

        self.assertNotEqual(request, deletion)

    def test_a_request_that_could_not_be_delivered_is_recorded_as_such(self):
        privacy_requests.record_privacy_request(
            "user_export", "42", outcome="undeliverable", now=self.now
        )

        self.assertEqual(
            privacy_requests.privacy_request_log()[0]["outcome"], "undeliverable"
        )

    def test_expired_entries_are_removed_by_the_retention_run(self):
        privacy_requests.record_privacy_request(
            "user_export", "old", now=self.now - timedelta(days=400)
        )
        privacy_requests.record_privacy_request(
            "user_export", "recent", now=self.now - timedelta(days=10)
        )

        report = privacy.run_retention_cleanup(now=self.now, env={})

        self.assertEqual(report["counts"]["privacy_requests"], 1)
        self.assertEqual(len(privacy_requests.privacy_request_log()), 1)


class PrivacyCommandLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        patches = [
            mock.patch.object(database, "DATA_DIR", self.root),
            mock.patch.object(database, "DB_PATH", self.root / "novaguard.sqlite3"),
            mock.patch.object(database, "_INITIALIZED", False),
            mock.patch.object(storage, "DATA_DIR", self.root),
            mock.patch.dict(os.environ, {"BACKUP_ENCRYPTION_KEY": TEST_KEY}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        database.init_database()

    def _interaction(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            user=SimpleNamespace(id=42),
            guild=None,
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )

    async def test_a_served_export_is_recorded(self):
        from cogs import privacy as privacy_cog

        interaction = self._interaction()
        cog = privacy_cog.Privacy(SimpleNamespace(get_cog=lambda name: None))

        with (
            mock.patch.object(privacy_cog, "flush_live_privacy_state", mock.AsyncMock()),
            mock.patch.object(privacy_cog, "export_user_data", return_value={"a": 1}),
            mock.patch.object(privacy_cog, "defer_interaction", mock.AsyncMock()),
        ):
            await cog.privacy_export.callback(cog, interaction)

        entries = privacy_requests.privacy_request_log()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "user_export")
        self.assertEqual(entries[0]["outcome"], "served")

    async def test_a_logging_failure_never_withholds_the_export(self):
        # The log is evidence, not a gate. Failing to write proof must not
        # deny someone the data they are entitled to.
        from cogs import privacy as privacy_cog

        interaction = self._interaction()
        cog = privacy_cog.Privacy(SimpleNamespace(get_cog=lambda name: None))

        def explode(*args, **kwargs):
            raise RuntimeError("evidence store unavailable")

        with (
            mock.patch.object(privacy_cog, "flush_live_privacy_state", mock.AsyncMock()),
            mock.patch.object(privacy_cog, "export_user_data", return_value={"a": 1}),
            mock.patch.object(privacy_cog, "defer_interaction", mock.AsyncMock()),
            mock.patch.object(privacy_cog, "record_privacy_request", explode),
        ):
            await cog.privacy_export.callback(cog, interaction)

        interaction.followup.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
