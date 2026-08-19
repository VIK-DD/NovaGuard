"""What the update engine watches, and what it must never watch.

The engine fingerprints a set of files, and any change to that set becomes a
release note on Discord and on the website. Which makes the choice of files a
correctness question rather than a matter of taste — one wrong entry and the
bot announces itself in a loop, forever, with nobody able to tell why from
the message.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.updates import BASE_DIR, humanize_areas, tracked_files  # noqa: E402


def tracked_names():
    return {str(path.relative_to(BASE_DIR)) for path in tracked_files()}


class TrackedSourceTests(unittest.TestCase):
    def test_the_bot_is_still_watched(self):
        names = tracked_names()

        self.assertIn("bot.py", names)
        self.assertIn("cogs/setup.py", names)
        self.assertIn("core/updates.py", names)

    def test_the_website_is_watched_too(self):
        # Without this the site published the bot's changelog and stayed
        # silent about its own changes.
        names = tracked_names()

        self.assertIn("website-3/src/pages/commands.astro", names)
        self.assertIn("website-3/src/components/Footer.astro", names)
        self.assertIn("website-3/src/data/commands.json", names)

    # --- the loop, and why this file exists ------------------------------

    def test_the_generated_archive_is_never_watched(self):
        # website-3/src/data/updates-archive.json is committed to git AND
        # rewritten at every build from the feed the engine itself produces.
        # Watching it would mean: a release changes the archive, the changed
        # archive reads as a change, that announces a release, which changes
        # the archive. There is no natural end to that, and the release notes
        # would give no clue what was happening.
        archive = BASE_DIR / "website-3" / "src" / "data" / "updates-archive.json"

        self.assertTrue(archive.exists(), "the archive moved; this guard needs updating")
        self.assertNotIn("website-3/src/data/updates-archive.json", tracked_names())

    def test_nothing_generated_or_installed_is_watched(self):
        for name in tracked_names():
            self.assertNotIn("node_modules", name)
            self.assertNotIn("website-3/dist/", name)
            self.assertNotIn(".astro/", name)

    def test_tests_are_not_watched(self):
        # A changed test is not news. The bot's own tests/ are already left
        # out; the website's belong out for the same reason.
        for name in tracked_names():
            self.assertNotIn(".test.", name)
            self.assertNotIn(".spec.", name)

    # --- the paths have to survive being read ----------------------------

    def test_every_watched_file_exists_and_is_readable(self):
        for path in tracked_files():
            with self.subTest(path=str(path)):
                self.assertTrue(path.is_file())
                path.read_text(encoding="utf-8")

    def test_no_file_is_watched_twice(self):
        paths = tracked_files()

        self.assertEqual(len(paths), len(set(paths)))

    # --- and the notes have to read like English -------------------------

    def test_website_changes_are_described_in_words_not_paths(self):
        text = humanize_areas(["website-3/src/pages/commands.astro"])

        self.assertNotIn("website-3", text)
        self.assertNotIn(".astro", text)


if __name__ == "__main__":
    unittest.main()
