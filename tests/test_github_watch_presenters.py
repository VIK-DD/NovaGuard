"""Presentation-only coverage for the GitHub activity watcher."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.github_watch_presenters import (  # noqa: E402
    build_commit_digest_embeds,
    build_issue_watcher_embed,
    build_pull_request_watcher_embed,
    build_push_watcher_embed,
    build_release_watcher_embed,
    commit_author_name,
    pull_request_state,
    push_commit_message,
    push_commit_sha,
)


REPO = "VIK-DD/NovaGuard"
CREATED_AT = "2026-08-27T18:00:00Z"


def field(embed, name):
    for item in embed.fields:
        if item.name == name:
            return item.value
    raise AssertionError(f"no field named {name!r}")


def commit(sha, message, author="VIK", when="2026-08-27T17:59:00Z"):
    return {
        "sha": sha,
        "html_url": f"https://github.com/{REPO}/commit/{sha}",
        "author": {"login": author} if author else None,
        "commit": {
            "message": message,
            "author": {"name": author or "Local Author", "date": when},
        },
    }


class CommitPresentationTests(unittest.TestCase):
    def test_commit_helpers_accept_compare_and_commits_api_shapes(self):
        direct = {"sha": "abcdef012345", "message": "First line\nMore detail", "author": {"login": "vik"}}
        nested = commit("123456789", "Nested message", author=None)

        self.assertEqual(push_commit_sha(direct), "abcdef0")
        self.assertEqual(push_commit_message(direct), "First line")
        self.assertEqual(commit_author_name(direct), "vik")
        self.assertEqual(commit_author_name(nested), "Local Author")

    def test_digest_groups_commits_by_branch_in_first_seen_order(self):
        embeds = build_commit_digest_embeds(
            REPO,
            [
                ("main", commit("a" * 40, "First")),
                ("feature", commit("b" * 40, "Feature")),
                ("main", commit("c" * 40, "Newest")),
            ],
        )

        self.assertEqual(len(embeds), 2)
        self.assertEqual(field(embeds[0], "Branch"), "`main`")
        self.assertEqual(field(embeds[1], "Branch"), "`feature`")
        self.assertIn("Newest", embeds[0].description)
        self.assertLess(embeds[0].description.index("Newest"), embeds[0].description.index("First"))


class WatcherEventPresentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_push_card_preserves_branch_actor_commit_and_file_summary(self):
        event = {
            "created_at": CREATED_AT,
            "actor": {"login": "VIK-DD"},
            "payload": {
                "before": "a" * 40,
                "head": "b" * 40,
                "ref": "refs/heads/feature/cards",
            },
        }
        commits = [commit(str(index) * 40, f"Commit {index}") for index in range(4)]

        embed, view = build_push_watcher_embed(
            REPO,
            event,
            commits,
            [{"filename": "core/example.py", "status": "modified", "additions": 5, "deletions": 2}],
        )

        self.assertIn("VIK-DD pushed", embed.description)
        self.assertEqual(field(embed, "Branch"), "`cards`")
        self.assertIn("1 more commit", field(embed, "Commits"))
        self.assertIn("core/example.py", field(embed, "Files Changed"))
        self.assertEqual([button.label for button in view.children], ["Repository", "Compare", "Latest Commit"])

    async def test_pull_request_card_reports_merged_state_and_branch_flow(self):
        event = {"created_at": CREATED_AT, "payload": {"action": "closed"}}
        pull_request = {
            "number": 42,
            "title": "Extract presenter",
            "body": "Keeps network access in the cog.",
            "state": "closed",
            "merged": True,
            "draft": False,
            "html_url": f"https://github.com/{REPO}/pull/42",
            "head": {"ref": "feature/presenter"},
            "base": {"ref": "main"},
        }

        embed, view = build_pull_request_watcher_embed(REPO, event, pull_request)

        self.assertIn("closed", embed.title)
        self.assertIn("Merged", field(embed, "PR Details"))
        self.assertIn("feature/presenter", field(embed, "Branch Flow"))
        self.assertEqual(view.children[1].label, "Pull Request")

    async def test_pull_request_state_does_not_guess_for_unrelated_actions(self):
        self.assertEqual(pull_request_state({}, "synchronize"), "Unknown")

    async def test_issue_card_keeps_issue_metadata_and_actor(self):
        issue_url = f"https://github.com/{REPO}/issues/7"
        event = {
            "created_at": CREATED_AT,
            "actor": {"login": "reporter"},
            "payload": {
                "action": "reopened",
                "issue": {
                    "number": 7,
                    "title": "A real issue",
                    "body": "Steps to reproduce.",
                    "state": "open",
                    "comments": 3,
                    "html_url": issue_url,
                },
            },
        }

        embed, view = build_issue_watcher_embed(REPO, event)

        self.assertIn("reopened", embed.title)
        self.assertIn("Comments: `3`", field(embed, "Issue Details"))
        self.assertIn("reporter", field(embed, "Opened By"))
        self.assertEqual(view.children[1].url, issue_url)

    async def test_release_card_keeps_tag_name_and_prerelease_state(self):
        release_url = f"https://github.com/{REPO}/releases/tag/v3.0.0-rc1"
        event = {
            "created_at": CREATED_AT,
            "payload": {
                "action": "published",
                "release": {
                    "tag_name": "v3.0.0-rc1",
                    "name": "Version 3 RC",
                    "body": "Release candidate notes.",
                    "prerelease": True,
                    "html_url": release_url,
                },
            },
        }

        embed, view = build_release_watcher_embed(REPO, event)

        details = field(embed, "Release Details")
        self.assertIn("v3.0.0-rc1", details)
        self.assertIn("Pre-release: `Yes`", details)
        self.assertEqual(view.children[1].url, release_url)


if __name__ == "__main__":
    unittest.main()
