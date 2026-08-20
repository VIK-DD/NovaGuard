"""Turning GitHub payloads into the lines a repo card shows.

Low stakes next to money or auth — the worst outcome is a wrong number on a
card — but it is four hundred untested lines of arithmetic with thresholds,
ties and empty inputs, which is where quiet wrongness lives. Phase 5 of the
plan says cover before splitting, and this is the covering.

Two of these tests exist to record that a branch cannot be reached, rather
than to check that it works.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.developer import (  # noqa: E402
    build_languages_text,
    compute_health_score,
    detect_top_language,
    release_status_text,
    summarize_changed_files,
    summarize_recent_work,
    workflow_status_text,
)


def commit(message):
    return {"commit": {"message": message}}


class HealthScoreTests(unittest.TestCase):
    """A number people read as a verdict, so its edges matter."""

    def healthy(self, **overrides):
        base = dict(
            commits_last_week=12,
            open_prs=2,
            branch_data={"protected": True},
            workflow_run={"status": "completed", "conclusion": "success"},
            release={"tag_name": "v1"},
        )
        base.update(overrides)
        return compute_health_score(**base)

    def test_a_healthy_repository_scores_full_marks(self):
        score, label = self.healthy()

        self.assertEqual(score, 100)
        self.assertIn("Excellent", label)

    def test_a_silent_week_costs_twenty(self):
        self.assertEqual(self.healthy(commits_last_week=0)[0], 80)

    def test_a_failing_workflow_is_the_heaviest_single_penalty(self):
        self.assertEqual(
            self.healthy(workflow_run={"status": "completed", "conclusion": "failure"})[0], 75
        )

    def test_a_workflow_still_running_is_not_counted_against_it(self):
        # Only a completed run says anything. Penalising one in progress would
        # dip the score every time somebody pushed.
        #
        # The conclusion here is deliberately a failure. GitHub normally nulls
        # it while a run is in progress, and an earlier version of this test
        # relied on that — which meant it passed with the status check deleted,
        # since a null conclusion is not penalised either way. The check is
        # what must be proven, so the payload has to make it the only thing
        # standing between the run and a penalty.
        self.assertEqual(
            self.healthy(workflow_run={"status": "in_progress", "conclusion": "failure"})[0], 100
        )
        self.assertEqual(
            self.healthy(workflow_run={"status": "queued", "conclusion": "failure"})[0], 100
        )

    def test_a_completed_run_with_no_conclusion_is_not_a_failure(self):
        self.assertEqual(
            self.healthy(workflow_run={"status": "completed", "conclusion": None})[0], 100
        )

    def test_an_unprotected_default_branch_costs_ten(self):
        self.assertEqual(self.healthy(branch_data={"protected": False})[0], 90)

    def test_an_unknown_branch_is_not_punished_for_being_unknown(self):
        # A failed branch lookup is missing information, not a finding.
        self.assertEqual(self.healthy(branch_data=None)[0], 100)

    def test_a_pile_of_open_pull_requests_costs_ten(self):
        self.assertEqual(self.healthy(open_prs=16)[0], 90)
        self.assertEqual(self.healthy(open_prs=15)[0], 100)

    def test_never_having_released_costs_five(self):
        self.assertEqual(self.healthy(release=None)[0], 95)

    def test_the_labels_change_at_the_thresholds(self):
        self.assertIn("Excellent", self.healthy()[1])
        self.assertIn("Strong", self.healthy(commits_last_week=0, release=None)[1])
        self.assertIn(
            "Stable",
            self.healthy(
                commits_last_week=0,
                branch_data={"protected": False},
                release=None,
            )[1],
        )

    def test_everything_wrong_at_once_still_lands_above_the_floor(self):
        # The penalties total 70, so the worst achievable score is 30 and the
        # max(score, 10) floor never binds today. It is kept deliberately: it
        # is the invariant that a sixth penalty must not push the score
        # negative, and this records what the floor is there for.
        worst, label = compute_health_score(
            commits_last_week=0,
            open_prs=99,
            branch_data={"protected": False},
            workflow_run={"status": "completed", "conclusion": "failure"},
            release=None,
        )

        self.assertEqual(worst, 30)
        self.assertGreaterEqual(worst, 10)
        self.assertIn("Needs Attention", label)


class RecentWorkTests(unittest.TestCase):
    def test_nothing_to_summarise_says_so(self):
        self.assertEqual(summarize_recent_work([]), "No recent commits found.")

    def test_fixes_features_docs_and_the_rest_are_counted_apart(self):
        text = summarize_recent_work(
            [
                commit("fix: a crash"),
                commit("feat: something new"),
                commit("docs: README"),
                commit("bump version"),
            ]
        )

        for label in ("Fixes: 1", "Features: 1", "Docs: 1", "Chores: 1"):
            self.assertIn(label, text)

    def test_the_first_matching_category_wins(self):
        # "fix" is checked before "feat", so a commit mentioning both is a fix.
        self.assertIn("Fixes: 1", summarize_recent_work([commit("fix the new feature")]))

    def test_only_the_first_line_of_a_message_is_read(self):
        # A body explaining what was fixed must not recategorise a feature.
        text = summarize_recent_work([commit("feat: add panel\n\nthis also fixes a bug")])

        self.assertIn("Features: 1", text)
        self.assertNotIn("Fixes", text)

    def test_everything_lands_in_a_category(self):
        # Recording an unreachable branch rather than testing it: the else arm
        # catches whatever the first three miss, so the "Mixed internal work."
        # fallback below it can never be produced. Anything that changes that
        # should fail here first.
        text = summarize_recent_work([commit("qqq"), commit("zzz")])

        self.assertEqual(text, "Chores: 2")
        self.assertNotIn("Mixed internal work", text)


class LanguageTests(unittest.TestCase):
    def test_no_data_says_so_rather_than_drawing_an_empty_bar(self):
        self.assertEqual(build_languages_text({}), "No language data yet.")
        self.assertEqual(build_languages_text(None), "No language data yet.")

    def test_a_single_language_fills_the_bar(self):
        text = build_languages_text({"Python": 100})

        self.assertIn("100%", text)
        self.assertIn("▰" * 10, text)

    def test_shares_are_percentages_of_the_whole(self):
        text = build_languages_text({"Python": 750, "CSS": 250})

        self.assertIn("75%", text)
        self.assertIn("25%", text)

    def test_a_sliver_still_shows_one_block(self):
        # Rounding to zero would draw an empty bar beside a real language.
        text = build_languages_text({"Python": 999, "Assembly": 1})

        self.assertIn("▰", text.splitlines()[-1])

    def test_only_the_four_largest_are_listed(self):
        text = build_languages_text({name: 10 for name in "abcdefgh"})

        self.assertEqual(len(text.splitlines()), 4)

    def test_the_most_common_language_across_repos_is_found(self):
        repos = [{"language": "Python"}, {"language": "Go"}, {"language": "Python"}]

        self.assertEqual(detect_top_language(repos), "Python")

    def test_repositories_without_a_language_are_ignored(self):
        self.assertIsNone(detect_top_language([{"language": None}, {}]))
        self.assertIsNone(detect_top_language([]))


class StatusTextTests(unittest.TestCase):
    def test_a_missing_workflow_is_reported_as_missing(self):
        self.assertEqual(workflow_status_text(None), "No workflow runs found.")

    def test_a_running_workflow_reports_its_status_not_a_conclusion(self):
        self.assertIn("In_Progress", workflow_status_text({"status": "in_progress", "name": "CI"}))

    def test_a_finished_workflow_reports_its_conclusion(self):
        text = workflow_status_text({"status": "completed", "conclusion": "failure", "name": "CI"})

        self.assertIn("Failure", text)

    def test_an_underscored_conclusion_is_made_readable(self):
        text = workflow_status_text(
            {"status": "completed", "conclusion": "startup_failure", "name": "CI"}
        )

        self.assertIn("Startup Failure", text)

    def test_a_repository_with_no_release_says_so(self):
        self.assertEqual(release_status_text(None), "No public release yet.")

    def test_a_release_without_a_tag_does_not_render_a_blank(self):
        self.assertIn("untagged", release_status_text({"published_at": None}))


class ChangedFilesTests(unittest.TestCase):
    def test_no_file_details_says_so(self):
        self.assertEqual(summarize_changed_files([]), "No file details available.")

    def test_up_to_three_files_are_named(self):
        text = summarize_changed_files([{"filename": f"f{n}.py"} for n in range(3)])

        self.assertIn("f2.py", text)
        self.assertNotIn("more", text)

    def test_beyond_three_the_rest_are_counted(self):
        text = summarize_changed_files([{"filename": f"f{n}.py"} for n in range(10)])

        self.assertIn("+7 more", text)

    def test_a_file_without_a_name_does_not_render_as_nothing(self):
        self.assertIn("unknown", summarize_changed_files([{}]))


if __name__ == "__main__":
    unittest.main()
