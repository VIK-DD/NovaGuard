"""Which commits get announced, and — mostly — which do not.

Every poll hands back the same newest commits again, so the only thing
standing between a working feed and a channel full of duplicates is this
arithmetic. The tests are weighted accordingly: one says the right commits
appear, the rest say the wrong ones never do.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.github_commits as remember_module  # noqa: E402
from core.github_commits import (  # noqa: E402
    branches_needing_a_read,
    hidden_count,
    merge_new_commits,
    remember_across_branches,
    remembered_shas,
    select_new_commits,
)


def commit(sha, message="a change"):
    return {"sha": sha, "commit": {"message": message}}


# GitHub answers newest first; these read the same way.
def page(*shas):
    return [commit(sha) for sha in shas]


class SelectNewCommitsTests(unittest.TestCase):
    def test_everything_is_new_when_nothing_is_remembered(self):
        picked = select_new_commits(page("c", "b", "a"), [])

        self.assertEqual([c["sha"] for c in picked], ["a", "b", "c"])

    def test_they_come_back_oldest_first(self):
        # They are posted in order, and a channel reading newest-at-the-top is
        # confusing to scroll back through.
        picked = select_new_commits(page("newest", "middle", "oldest"), [])

        self.assertEqual(picked[0]["sha"], "oldest")
        self.assertEqual(picked[-1]["sha"], "newest")

    def test_only_the_ones_above_the_last_seen_commit_are_taken(self):
        picked = select_new_commits(page("d", "c", "b", "a"), ["b", "a"])

        self.assertEqual([c["sha"] for c in picked], ["c", "d"])

    def test_a_poll_with_nothing_new_announces_nothing(self):
        self.assertEqual(select_new_commits(page("b", "a"), ["b", "a"]), [])

    def test_an_empty_answer_announces_nothing(self):
        self.assertEqual(select_new_commits([], []), [])
        self.assertEqual(select_new_commits(None, ["a"]), [])

    def test_the_walk_stops_at_the_first_familiar_commit(self):
        # GitHub returns newest first, so anything below a known SHA is known
        # too. Judging each commit on its own would re-announce one whose SHA
        # had aged out of the remembered window — which is how a channel fills
        # with duplicates after a restart.
        picked = select_new_commits(page("d", "c", "b", "a"), ["c"])

        self.assertEqual([c["sha"] for c in picked], ["d"])

    def test_a_commit_without_a_sha_is_not_announced(self):
        # A malformed entry is not evidence of a new commit.
        self.assertEqual(select_new_commits([{"commit": {"message": "x"}}], []), [])

    def test_a_burst_is_capped_so_one_push_cannot_flood_a_channel(self):
        picked = select_new_commits(page(*[f"c{n}" for n in range(20)]), [], limit=5)

        self.assertEqual(len(picked), 5)

    def test_the_cap_keeps_the_newest_not_the_oldest(self):
        picked = select_new_commits(page("c3", "c2", "c1", "c0"), [], limit=2)

        self.assertEqual([c["sha"] for c in picked], ["c2", "c3"])

    def test_the_ones_left_out_can_be_counted(self):
        self.assertEqual(hidden_count(page("d", "c", "b", "a"), [], limit=2), 2)
        self.assertEqual(hidden_count(page("b", "a"), [], limit=5), 0)


class RememberedShaTests(unittest.TestCase):
    def test_it_remembers_more_than_one_poll_of_history(self):
        # With only the newest kept, commits landing underneath it between two
        # polls would look new again on the following pass.
        remembered = remembered_shas(page(*[f"c{n}" for n in range(30)]))

        self.assertGreater(len(remembered), 1)

    def test_the_window_does_not_grow_without_end(self):
        remembered = remembered_shas(page(*[f"c{n}" for n in range(200)]), keep=40)

        self.assertEqual(len(remembered), 40)

    def test_entries_without_a_sha_are_not_stored(self):
        remembered = remembered_shas([commit("a"), {"commit": {}}, commit("b")])

        self.assertEqual(remembered, ["a", "b"])

    def test_what_is_remembered_silences_the_next_poll(self):
        # The round trip that matters: store what was announced, and the same
        # answer must produce nothing at all next time.
        commits = page("c", "b", "a")

        self.assertEqual(select_new_commits(commits, remembered_shas(commits)), [])


def branch(name, head):
    return {"name": name, "commit": {"sha": head}}


class BranchSelectionTests(unittest.TestCase):
    """Each branch costs its own request, so most of them must be skipped."""

    def test_a_branch_whose_head_is_known_is_not_read_again(self):
        # The listing already carries every head SHA, so a branch that has not
        # moved cannot be hiding anything and needs no request at all.
        branches = [branch("main", "a"), branch("feature", "b")]

        self.assertEqual(branches_needing_a_read(branches, ["a", "b"]), [])

    def test_only_the_branch_that_moved_is_read(self):
        branches = [branch("main", "a"), branch("feature", "new"), branch("old", "c")]

        self.assertEqual(branches_needing_a_read(branches, ["a", "c"]), ["feature"])

    def test_a_first_run_reads_everything(self):
        branches = [branch("main", "a"), branch("feature", "b")]

        self.assertEqual(branches_needing_a_read(branches, []), ["main", "feature"])

    def test_a_malformed_branch_is_skipped_rather_than_crashing(self):
        # One odd entry must not stop the watcher for the whole repository.
        branches = [{"name": "main"}, {"commit": {"sha": "x"}}, None, branch("ok", "y")]

        self.assertEqual(branches_needing_a_read(branches, []), ["ok"])

    def test_nothing_to_read_when_there_are_no_branches(self):
        self.assertEqual(branches_needing_a_read([], ["a"]), [])
        self.assertEqual(branches_needing_a_read(None, []), [])


class MergeAcrossBranchesTests(unittest.TestCase):
    def test_commits_from_several_branches_are_gathered(self):
        merged = merge_new_commits(
            [("main", page("a")), ("feature", page("b"))],
            [],
        )

        self.assertEqual([(name, c["sha"]) for name, c in merged], [("main", "a"), ("feature", "b")])

    def test_the_same_commit_on_two_branches_is_announced_once(self):
        # Pushing a working branch and then main is one commit on two
        # branches. Reporting it twice would make every change look doubled.
        merged = merge_new_commits(
            [("main", page("shared")), ("feature", page("shared"))],
            [],
        )

        self.assertEqual(len(merged), 1)

    def test_the_branch_walked_first_is_the_one_credited(self):
        merged = merge_new_commits(
            [("main", page("shared")), ("feature", page("shared"))],
            [],
        )

        self.assertEqual(merged[0][0], "main")

    def test_commits_already_announced_are_not_repeated(self):
        merged = merge_new_commits([("main", page("b", "a"))], ["a"])

        self.assertEqual([c["sha"] for _, c in merged], ["b"])

    def test_a_burst_across_branches_is_still_capped(self):
        merged = merge_new_commits(
            [("main", page(*[f"m{n}" for n in range(10)])), ("feature", page("f1"))],
            [],
            limit=4,
        )

        self.assertEqual(len(merged), 4)

    def test_nothing_new_anywhere_announces_nothing(self):
        self.assertEqual(merge_new_commits([("main", page("a"))], ["a"]), [])
        self.assertEqual(merge_new_commits([], []), [])


class StoredStateTests(unittest.TestCase):
    """Telling a pre-branch state file from a branch-aware one."""

    def test_a_state_file_written_before_branches_primes_instead_of_announcing(self):
        # It only ever covered the default branch. Trusting it as complete
        # would make every other branch look new on the first poll after the
        # upgrade, and announce months-old commits from stale branches as if
        # they had just landed.
        seen, prime = remember_module.stored_shas(["a", "b"])

        self.assertTrue(prime)
        self.assertEqual(seen, [])

    def test_a_branch_aware_state_file_is_trusted(self):
        seen, prime = remember_module.stored_shas({"seen": ["a", "b"]})

        self.assertFalse(prime)
        self.assertEqual(seen, ["a", "b"])

    def test_no_state_at_all_primes(self):
        for empty in (None, [], {}):
            with self.subTest(state=empty):
                seen, prime = remember_module.stored_shas(empty)
                self.assertEqual(seen, [])
                self.assertEqual(prime, not isinstance(empty, dict))

    def test_what_is_stored_reads_back_as_trusted(self):
        seen, prime = remember_module.stored_shas(remember_module.store_shas(["a"]))

        self.assertFalse(prime)
        self.assertEqual(seen, ["a"])


class RememberAcrossBranchesTests(unittest.TestCase):
    def test_new_shas_come_before_the_old_ones(self):
        # Newest first, so what falls off the end is the oldest history.
        self.assertEqual(remember_across_branches(["old"], ["new"]), ["new", "old"])

    def test_a_sha_is_stored_only_once_however_many_branches_carry_it(self):
        remembered = remember_across_branches(["a"], ["b", "a"], ["b"])

        self.assertEqual(remembered, ["b", "a"])

    def test_the_window_is_bounded(self):
        remembered = remember_across_branches([], [f"c{n}" for n in range(500)], keep=300)

        self.assertEqual(len(remembered), 300)

    def test_empty_entries_are_not_stored(self):
        self.assertEqual(remember_across_branches(None, ["a", "", None]), ["a"])

    def test_what_is_remembered_silences_the_next_poll(self):
        # The round trip that matters across branches too.
        per_branch = [("main", page("b", "a")), ("feature", page("c"))]
        remembered = remember_across_branches(
            [], [commit["sha"] for _, commits in per_branch for commit in commits]
        )

        self.assertEqual(merge_new_commits(per_branch, remembered), [])


if __name__ == "__main__":
    unittest.main()
