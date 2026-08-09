"""Tests for the public release numbering shown on the website."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.release_versions import (  # noqa: E402
    ALPHA_SLOTS,
    BETA_PHASE,
    UPDATES_PER_VERSION,
    alpha_slot_sizes,
    assign_releases,
    clean_text,
    current_release,
    is_significant,
    release_groups,
)

FEATURE = "\U0001F680 Setup wizard upgraded with select menus"
CHORE = "Tidied internal helpers"


ALPHA_DAY = "2026-01-{:02d}T00:00:00+00:00"
BETA_DAY = "2026-09-{:02d}T00:00:00+00:00"
HISTORICAL_BUILDS = 31


def entry(build, highlights=None, created_at=None):
    """An update. Dated before the cutoff unless told otherwise."""
    return {
        "build": build,
        "highlights": list(highlights or []),
        "created_at": created_at or ALPHA_DAY.format(min(build, 28)),
    }


def beta_entry(offset, highlights=None):
    """An update dated after the cutoff, so it lands in open beta."""
    return entry(
        HISTORICAL_BUILDS + offset,
        highlights,
        created_at=BETA_DAY.format(min(offset, 28)),
    )


def history(count, start=1, highlights=None):
    return [entry(build, highlights) for build in range(start, start + count)]


class SignificanceTests(unittest.TestCase):
    def test_a_feature_highlight_counts(self):
        self.assertTrue(is_significant(entry(1, [FEATURE])))

    def test_new_commands_count(self):
        self.assertTrue(is_significant(entry(1, ["New commands ready to try: /filter"])))

    def test_ordinary_work_does_not_count(self):
        # It still gets published - it just must not move the version.
        for text in (CHORE, "Fixed a typo in an embed", "Updated documentation"):
            with self.subTest(text=text):
                self.assertFalse(is_significant(entry(1, [text])))

    def test_an_update_with_no_highlights_does_not_count(self):
        self.assertFalse(is_significant(entry(1)))
        self.assertFalse(is_significant({}))


class AlphaTests(unittest.TestCase):
    def test_history_is_spread_across_exactly_ten_versions(self):
        stamped = assign_releases(history(HISTORICAL_BUILDS))
        versions = {item["release"] for item in stamped}

        self.assertEqual(len(versions), ALPHA_SLOTS)
        self.assertIn("1.0", versions)
        self.assertIn("1.9", versions)

    def test_every_historical_build_is_alpha(self):
        stamped = assign_releases(history(HISTORICAL_BUILDS))

        self.assertTrue(all(item["phase"] == "alpha" for item in stamped))

    def test_slot_sizes_stay_even_and_account_for_everything(self):
        for total in (0, 1, 9, 10, 31, 47):
            with self.subTest(total=total):
                sizes = alpha_slot_sizes(total)
                self.assertEqual(sum(sizes), total)
                self.assertEqual(len(sizes), ALPHA_SLOTS)
                self.assertLessEqual(max(sizes) - min(sizes), 1)

    def test_alpha_numbering_never_shifts_when_new_builds_land(self):
        # The whole reason the cutoff is frozen: a visitor who read
        # "1.3" yesterday must find the same updates there tomorrow.
        before = {
            item["build"]: item["release"] for item in assign_releases(history(HISTORICAL_BUILDS))
        }
        after = {
            item["build"]: item["release"]
            for item in assign_releases(history(HISTORICAL_BUILDS) + [beta_entry(i) for i in range(1, 21)])
            if item["build"] <= HISTORICAL_BUILDS
        }

        self.assertEqual(before, after)


class PhaseBoundaryTests(unittest.TestCase):
    """The date decides the phase, never the build number.

    Build numbers repeat across changelog engine resets, and the bot's
    archive and the website's have drifted apart, so the same number means
    different updates depending on which file you read. A timestamp does not
    have that problem.
    """

    def test_an_old_update_with_a_high_build_number_is_still_alpha(self):
        stamped = assign_releases([entry(9999, [FEATURE], created_at=ALPHA_DAY.format(3))])

        self.assertEqual(stamped[0]["phase"], "alpha")

    def test_a_new_update_with_a_low_build_number_is_open_beta(self):
        stamped = assign_releases([entry(1, [FEATURE], created_at=BETA_DAY.format(3))])

        self.assertEqual(stamped[0]["phase"], BETA_PHASE)

    def test_repeated_build_numbers_do_not_collide(self):
        # Two updates numbered 5, from different engine eras, must both
        # survive and land in the right phase.
        entries = [
            entry(5, [FEATURE], created_at=ALPHA_DAY.format(5)),
            entry(5, [FEATURE], created_at=BETA_DAY.format(5)),
        ]
        stamped = assign_releases(entries)

        self.assertEqual(len(stamped), 2)
        self.assertEqual([item["phase"] for item in stamped], ["alpha", BETA_PHASE])

    def test_ordering_follows_dates_not_build_numbers(self):
        entries = [
            entry(100, [CHORE], created_at=ALPHA_DAY.format(2)),
            entry(1, [CHORE], created_at=ALPHA_DAY.format(1)),
        ]

        self.assertEqual([item["build"] for item in assign_releases(entries)], [1, 100])


class OpenBetaTests(unittest.TestCase):
    def _beta(self, entries):
        return [item for item in assign_releases(entries) if item["phase"] == BETA_PHASE]

    def test_open_beta_starts_at_two_zero(self):
        entries = history(HISTORICAL_BUILDS) + [beta_entry(1, [FEATURE])]

        self.assertEqual(self._beta(entries)[0]["release"], "2.0")

    def test_a_version_holds_the_agreed_number_of_significant_updates(self):
        entries = history(HISTORICAL_BUILDS) + [
            beta_entry(offset, [FEATURE])
            for offset in range(1, UPDATES_PER_VERSION + 2)
        ]
        beta = self._beta(entries)

        self.assertEqual(
            [item["release"] for item in beta[:UPDATES_PER_VERSION]],
            ["2.0"] * UPDATES_PER_VERSION,
        )
        self.assertEqual(beta[UPDATES_PER_VERSION]["release"], "2.1")

    def test_small_changes_never_push_the_version(self):
        # Twenty chores in a row keep the same version number.
        entries = history(HISTORICAL_BUILDS) + [
            beta_entry(offset, [CHORE]) for offset in range(1, 21)
        ]

        self.assertEqual({item["release"] for item in self._beta(entries)}, {"2.0"})

    def test_small_changes_are_still_published(self):
        entries = history(HISTORICAL_BUILDS) + [beta_entry(1, [CHORE])]
        beta = self._beta(entries)

        self.assertEqual(len(beta), 1)
        self.assertFalse(beta[0]["significant"])


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.entries = history(HISTORICAL_BUILDS) + [
            beta_entry(offset, [FEATURE if offset % 2 else CHORE])
            for offset in range(1, 8)
        ]

    def test_the_newest_version_comes_first_and_is_marked_current(self):
        groups = release_groups(self.entries)

        self.assertTrue(groups[0]["current"])
        self.assertFalse(any(group["current"] for group in groups[1:]))

    def test_updates_inside_a_version_are_newest_first(self):
        group = release_groups(self.entries)[0]
        builds = [item["build"] for item in group["updates"]]

        self.assertEqual(builds, sorted(builds, reverse=True))

    def test_a_group_reports_what_it_contains(self):
        group = release_groups(self.entries)[-1]

        self.assertEqual(group["update_count"], len(group["updates"]))
        self.assertLessEqual(group["build_first"], group["build_last"])
        self.assertEqual(group["phase_label"], "Alpha")

    def test_every_update_lands_in_exactly_one_version(self):
        groups = release_groups(self.entries)
        placed = [item["build"] for group in groups for item in group["updates"]]

        self.assertEqual(sorted(placed), sorted(item["build"] for item in self.entries))

    def test_current_release_names_the_live_version(self):
        live = current_release(self.entries)

        self.assertEqual(live["version"], release_groups(self.entries)[0]["version"])
        self.assertEqual(live["phase_label"], "Open Beta")

    def test_an_empty_history_still_reports_a_starting_version(self):
        self.assertEqual(release_groups([]), [])
        self.assertEqual(current_release([])["version"], "2.0")


class PresentationTests(unittest.TestCase):
    def test_emoji_are_stripped_from_everything_shown(self):
        stamped = assign_releases([entry(1, [FEATURE])])

        self.assertNotIn("\U0001F680", stamped[0]["highlights"][0])
        self.assertIn("Setup wizard upgraded", stamped[0]["highlights"][0])

    def test_stripping_emoji_never_empties_a_real_sentence(self):
        self.assertEqual(clean_text("\U0001F680 Backups now upload"), "Backups now upload")

    def test_decoration_only_highlights_disappear_instead_of_leaving_blanks(self):
        stamped = assign_releases([entry(1, ["\U0001F680", "", "Real change"])])

        self.assertEqual(stamped[0]["highlights"], ["Real change"])

    def test_significance_survives_the_emoji_being_stripped(self):
        # Detection reads the raw text, so cleaning the display must not
        # quietly turn a feature into a chore.
        stamped = assign_releases([entry(1, [FEATURE])])

        self.assertTrue(stamped[0]["significant"])


if __name__ == "__main__":
    unittest.main()
