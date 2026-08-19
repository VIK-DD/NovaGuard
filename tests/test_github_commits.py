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

from core.github_commits import (  # noqa: E402
    hidden_count,
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


if __name__ == "__main__":
    unittest.main()
