"""Tests for how the changelog engine words a release.

Covers the two rules that decide whether a release note is honest and
readable: a feature highlight fires only the first time the feature appears,
and internal work is described by area rather than by file path.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.updates import (  # noqa: E402
    feature_just_arrived,
    humanize_areas,
    summarize_changes,
    summarize_feature_highlights,
)

BACKUPS_WITH_FEATURE = "def create_backup(label):\n    return {}\n"
BACKUPS_WITHOUT_FEATURE = "def prune_old_backups():\n    pass\n"


class FeatureJustArrivedTests(unittest.TestCase):
    def test_true_only_when_the_marker_is_new(self):
        old = {"core/backups.py": BACKUPS_WITHOUT_FEATURE}
        new = {"core/backups.py": BACKUPS_WITH_FEATURE}
        self.assertTrue(feature_just_arrived(old, new, "core/backups.py", "create_backup"))

    def test_false_when_the_marker_was_already_there(self):
        # The regression: editing a file that already has the feature used to
        # re-announce it as brand new.
        old = {"core/backups.py": BACKUPS_WITH_FEATURE}
        new = {"core/backups.py": BACKUPS_WITH_FEATURE + "# a later, unrelated edit\n"}
        self.assertFalse(feature_just_arrived(old, new, "core/backups.py", "create_backup"))

    def test_false_when_the_marker_is_missing_from_the_new_snapshot(self):
        old = {"core/backups.py": BACKUPS_WITH_FEATURE}
        new = {"core/backups.py": BACKUPS_WITHOUT_FEATURE}
        self.assertFalse(feature_just_arrived(old, new, "core/backups.py", "create_backup"))

    def test_a_half_built_feature_announces_when_it_is_completed(self):
        # Markers describe the finished feature, so a release that adds the
        # missing half is the release that delivered it.
        old = {"cogs/system.py": "HIGH_LAG_ALERT_MS = 3000\n"}
        new = {"cogs/system.py": "HIGH_LAG_ALERT_MS = 3000\ndef loop_lag_snapshot(): pass\n"}
        self.assertTrue(
            feature_just_arrived(
                old, new, "cogs/system.py", "HIGH_LAG_ALERT_MS", "loop_lag_snapshot"
            )
        )


class FeatureHighlightTests(unittest.TestCase):
    def test_shipped_features_are_not_re_announced_on_a_later_edit(self):
        source = BACKUPS_WITH_FEATURE
        old = {"core/backups.py": source}
        new = {"core/backups.py": source + "# unrelated tweak\n"}
        self.assertEqual(summarize_feature_highlights(old, new), [])

    def test_a_genuinely_new_feature_is_announced_once(self):
        old = {"core/backups.py": BACKUPS_WITHOUT_FEATURE}
        new = {"core/backups.py": BACKUPS_WITH_FEATURE}
        highlights = summarize_feature_highlights(old, new)
        self.assertEqual(len(highlights), 1)
        self.assertIn("Automatic backups", highlights[0])


class WordingTests(unittest.TestCase):
    def test_areas_read_as_features_not_file_paths(self):
        text = humanize_areas(["cogs/voice.py", "core/webserver.py"])
        self.assertEqual(text, "voice session reports and the web dashboard")
        self.assertNotIn(".py", text)

    def test_unmapped_files_still_produce_readable_text(self):
        self.assertEqual(humanize_areas(["cogs/brand_new_thing.py"]), "brand new thing")

    def test_internal_change_bullet_names_areas_instead_of_paths(self):
        old = {"cogs/voice.py": "a", "core/webserver.py": "x"}
        new = {"cogs/voice.py": "b", "core/webserver.py": "y"}
        summary, _, _ = summarize_changes(old, new)
        bullet = next(line for line in summary if line.startswith("Behind-the-scenes"))
        self.assertIn("voice session reports", bullet)
        self.assertNotIn(".py", bullet)


if __name__ == "__main__":
    unittest.main()
