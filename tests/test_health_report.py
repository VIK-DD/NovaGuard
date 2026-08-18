"""The lines /doctor prints about storage health.

Written against the behaviour as it stood inside cogs/system.py, so the move
out of that file had to preserve it rather than merely compile. The command
sits at 5% coverage inside a 1,300-line cog, which is exactly why this logic
is worth having somewhere it can be exercised on its own.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import health_report  # noqa: E402
from core.health_report import (  # noqa: E402
    clamp_field,
    fail_line,
    info_line,
    json_file_status,
    ok_line,
    storage_health_lines,
    warn_line,
)


class StatusLineTests(unittest.TestCase):
    def test_a_bare_label_carries_no_dash(self):
        self.assertEqual(ok_line("SQLite database"), "✅ **SQLite database**")

    def test_details_are_appended_after_a_dash(self):
        self.assertEqual(ok_line("data/", "writable"), "✅ **data/** — writable")

    def test_each_severity_has_its_own_mark(self):
        self.assertTrue(warn_line("x").startswith("⚠️"))
        self.assertTrue(info_line("x").startswith("ℹ️"))
        self.assertTrue(fail_line("x").startswith("❌"))

    def test_an_empty_detail_is_treated_as_no_detail(self):
        self.assertEqual(fail_line("x", ""), "❌ **x**")


class ClampFieldTests(unittest.TestCase):
    def test_lines_are_joined_one_per_row(self):
        self.assertEqual(clamp_field(["a", "b"]), "a\nb")

    def test_nothing_to_report_says_so_rather_than_returning_empty(self):
        # Discord rejects an empty embed field value outright.
        self.assertEqual(clamp_field([]), "No checks were run.")

    def test_a_long_value_is_truncated_to_fit_the_field(self):
        value = clamp_field(["x" * 5000])

        self.assertEqual(len(value), 1010)
        self.assertTrue(value.endswith("..."))

    def test_a_value_exactly_on_the_limit_is_left_alone(self):
        value = clamp_field(["x" * 1010])

        self.assertEqual(len(value), 1010)
        self.assertFalse(value.endswith("..."))


class JsonFileStatusTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.dir = Path(self._temp.name)

    def test_a_missing_file_is_a_warning_not_a_failure(self):
        # A state file that has never been written is normal on a fresh host.
        line = json_file_status(self.dir / "absent.json", "state")

        self.assertTrue(line.startswith("⚠️"))
        self.assertIn("not created yet", line)

    def test_valid_json_reports_ok(self):
        path = self.dir / "state.json"
        path.write_text(json.dumps({"events": {}}), encoding="utf-8")

        self.assertTrue(json_file_status(path, "state").startswith("✅"))

    def test_malformed_json_is_a_failure(self):
        path = self.dir / "state.json"
        path.write_text("{ not json", encoding="utf-8")

        line = json_file_status(path, "state")

        self.assertTrue(line.startswith("❌"))
        self.assertIn("invalid JSON", line)

    def test_an_unreadable_file_is_reported_rather_than_raising(self):
        path = self.dir / "state.json"
        path.write_text("{}", encoding="utf-8")

        with mock.patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            line = json_file_status(path, "state")

        self.assertTrue(line.startswith("❌"))
        self.assertIn("permission denied", line)


class StorageHealthTests(unittest.TestCase):
    """The whole report, against a data directory built for the occasion."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.dir = Path(self._temp.name)

        for name, replacement in (
            ("DATA_DIR", self.dir),
            ("DB_PATH", self.dir / "novaguard.sqlite3"),
            ("UPDATE_STATE_FILE", self.dir / ".update_state.json"),
            ("GITHUB_STATE_FILE", self.dir / ".github_state.json"),
            ("BACKUP_DIR", self.dir / "backups"),
            ("list_backups", lambda: []),
            ("latest_backup", lambda: None),
            ("backup_schedule_label", lambda: "daily at 04:00"),
        ):
            patcher = mock.patch.object(health_report, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def report(self):
        return "\n".join(storage_health_lines())

    def test_a_missing_database_is_expected_on_a_fresh_install(self):
        self.assertIn("will be created on first setup", self.report())

    def test_an_existing_database_reads_as_ready(self):
        (self.dir / "novaguard.sqlite3").write_bytes(b"")

        self.assertIn("✅ **SQLite database** — ready", self.report())

    def test_the_data_directory_is_probed_for_writes(self):
        self.assertIn("✅ **data/** — writable", self.report())

    def test_the_write_probe_leaves_nothing_behind(self):
        self.report()

        self.assertEqual(list(self.dir.glob(".doctor_write_test*")), [])

    def test_no_feature_data_yet_is_a_warning(self):
        self.assertIn("no JSON files yet", self.report())

    def test_valid_feature_data_is_counted(self):
        (self.dir / "warns.json").write_text("{}", encoding="utf-8")
        (self.dir / "reminders.json").write_text("[]", encoding="utf-8")

        self.assertIn("2 JSON file(s) valid", self.report())

    def test_a_corrupt_feature_file_is_named(self):
        (self.dir / "warns.json").write_text("{ broken", encoding="utf-8")

        report = self.report()

        self.assertIn("❌ **feature data**", report)
        self.assertIn("warns.json", report)

    def test_having_no_backups_yet_still_names_the_schedule(self):
        # Needs at least one feature file to get past the early return below.
        (self.dir / "warns.json").write_text("{}", encoding="utf-8")

        report = self.report()

        self.assertIn("⚠️ **backups** — none yet", report)
        self.assertIn("daily at 04:00", report)

    def test_an_empty_data_directory_stops_the_report_before_backups(self):
        # Current behaviour, recorded rather than changed: with no feature JSON
        # yet, storage_health_lines returns early, so /doctor says nothing at
        # all about backups on a fresh install — even though backups do not
        # depend on feature data. Worth revisiting on its own, not inside a
        # refactor whose job is to keep behaviour identical.
        report = self.report()

        self.assertIn("no JSON files yet", report)
        self.assertNotIn("backups", report)


if __name__ == "__main__":
    unittest.main()
