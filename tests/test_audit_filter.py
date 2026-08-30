"""The audit trail's actor filter matches what was typed, and only that.

`%` and `_` are LIKE wildcards. The filter interpolated the typed value into
a pattern without escaping them, so searching for `%` returned every row
rather than the rows containing a percent sign. Only someone already
authorized to read their own guild's audit log could do it, which is why this
was untidy rather than a boundary - but a filter that quietly means something
other than what was typed is still wrong, and "quietly means something else"
is how a real one starts.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import database, web_storage


class AuditActorFilterTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        path = Path(self._temp.name) / "novaguard.sqlite3"

        patches = [
            mock.patch.object(database, "DB_PATH", path),
            mock.patch.object(database, "DATA_DIR", path.parent),
            mock.patch.object(database, "_INITIALIZED", False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

        web_storage.init_web_tables()
        for username in ("vik", "100%pure", "under_score", "plain"):
            web_storage.db_add_audit(
                "1", {"id": f"id-{username}", "username": username}, "config_update", {}, ""
            )

    def _actors(self, actor):
        entries, _ = web_storage.db_get_audit("1", 50, actor=actor)
        return {entry["username"] for entry in entries}

    def test_an_ordinary_substring_still_matches(self):
        self.assertEqual(self._actors("vik"), {"vik"})

    def test_a_percent_matches_the_literal_character_not_everything(self):
        # The regression. Unescaped, this returned all four rows.
        self.assertEqual(self._actors("%"), {"100%pure"})

    def test_an_underscore_matches_the_literal_character_not_any_character(self):
        # Unescaped, `_` is LIKE's single-character wildcard, so this matched
        # every name of two or more characters.
        self.assertEqual(self._actors("_"), {"under_score"})

    def test_a_backslash_does_not_break_the_pattern(self):
        # The escape character itself has to survive being searched for.
        self.assertEqual(self._actors("\\"), set())

    def test_matching_by_exact_user_id_is_unaffected(self):
        self.assertEqual(self._actors("id-plain"), {"plain"})

    def test_a_filter_that_matches_nothing_returns_nothing(self):
        self.assertEqual(self._actors("nobody-by-that-name"), set())

    def test_no_filter_still_returns_the_whole_trail(self):
        entries, _ = web_storage.db_get_audit("1", 50)
        self.assertEqual(len(entries), 4)


if __name__ == "__main__":
    unittest.main()
