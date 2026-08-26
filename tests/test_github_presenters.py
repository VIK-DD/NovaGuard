"""Presentation-level coverage for the GitHub Discord cards."""

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.github_presenters import (  # noqa: E402
    build_dashboard_embed,
    build_health_embed,
    build_profile_embed,
    build_repo_embed,
    repo_to_urls,
)

REPO_NAME = "VIK-DD/NovaGuard"
REPO_URL = f"https://github.com/{REPO_NAME}"


def github_time(value):
    return value.isoformat().replace("+00:00", "Z")


def embed_field(embed, name):
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(f"no field named {name!r}; got {[field.name for field in embed.fields]}")


def view_links(view):
    return {item.label: item.url for item in view.children}


def repo(**overrides):
    data = {
        "name": "NovaGuard",
        "full_name": REPO_NAME,
        "html_url": REPO_URL,
        "description": "A Discord security bot.",
        "language": "Python",
        "topics": ["discord", "security"],
        "stargazers_count": 12,
        "forks_count": 3,
        "subscribers_count": 4,
        "default_branch": "main",
        "pushed_at": "2026-08-26T18:00:00Z",
        "created_at": "2025-01-01T00:00:00Z",
        "private": False,
    }
    data.update(overrides)
    return data


def user():
    return {
        "login": "VIK-DD",
        "html_url": "https://github.com/VIK-DD",
        "avatar_url": "https://avatars.example/vik.png",
        "bio": "Building NovaGuard.",
        "public_repos": 4,
        "followers": 20,
        "following": 5,
        "location": "Moldova",
    }


def commit(sha, message, when):
    return {
        "sha": sha,
        "commit": {
            "message": message,
            "author": {"date": github_time(when)},
        },
    }


class RepositoryUrlTests(unittest.TestCase):
    def test_every_repository_destination_has_the_expected_base(self):
        self.assertEqual(
            repo_to_urls(REPO_NAME),
            {
                "repo": REPO_URL,
                "commits": f"{REPO_URL}/commits",
                "pulls": f"{REPO_URL}/pulls",
                "issues": f"{REPO_URL}/issues",
                "releases": f"{REPO_URL}/releases",
                "actions": f"{REPO_URL}/actions",
            },
        )


class GitHubPresenterTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_card_contains_totals_and_primary_repo_link(self):
        repos = [repo(), repo(name="SideProject", stargazers_count=2)]

        with mock.patch(
            "core.github_presenters.choose_primary_repo",
            return_value=REPO_NAME,
        ):
            embed, view = build_profile_embed(user(), repos)

        self.assertEqual(embed.title, "👤 VIK-DD — GitHub Profile")
        self.assertIn("Total stars: `14`", embed_field(embed, "✨ Highlights"))
        self.assertIn("Top repo: `NovaGuard`", embed_field(embed, "✨ Highlights"))
        self.assertEqual(view_links(view)["Primary Repo"], REPO_URL)

    async def test_repository_card_contains_status_and_five_unique_links(self):
        embed, view = build_repo_embed(
            repo(),
            {"Python": 750, "JavaScript": 250},
            open_prs=2,
            open_issues=7,
            workflow_run={"name": "CI", "status": "completed", "conclusion": "success"},
            release={"tag_name": "v2.6"},
        )

        self.assertEqual(embed.title, f"📦 {REPO_NAME} — Live Status")
        self.assertIn("Open PRs: `2`", embed_field(embed, "🚦 Current Status"))
        self.assertIn("CI: `CI: Success`", embed_field(embed, "⚙️ Automation"))
        self.assertIn("75%", embed_field(embed, "🧬 Languages"))
        self.assertEqual(len(view.children), 5)
        self.assertEqual(view_links(view)["Releases"], f"{REPO_URL}/releases")

    async def test_dashboard_counts_only_commits_from_the_last_seven_days(self):
        now = datetime.now(UTC)
        commits = [
            commit("abcdef123", "fix: recent work", now - timedelta(days=1)),
            commit("123456789", "docs: old work", now - timedelta(days=8)),
        ]

        embed, view = build_dashboard_embed(
            user(),
            [repo()],
            repo(),
            commits,
            workflow_run={"name": "CI", "status": "completed", "conclusion": "success"},
            release={"tag_name": "v2.6", "published_at": github_time(now)},
            open_prs=2,
            open_issues=7,
        )

        self.assertIn("7-day commits: `1`", embed_field(embed, "📈 Repo Heartbeat"))
        self.assertIn("`abcdef1` fix: recent work", embed_field(embed, "📝 Latest Commit"))
        self.assertEqual(view_links(view)["Actions"], f"{REPO_URL}/actions")

    async def test_health_card_renders_score_pipeline_and_hot_files(self):
        now = datetime.now(UTC)

        embed, view = build_health_embed(
            repo(),
            [commit("abcdef123", "fix: healthy", now - timedelta(hours=1))],
            workflow_run={"name": "CI", "status": "completed", "conclusion": "success"},
            release={"tag_name": "v2.6"},
            branch_data={"protected": True},
            open_prs=2,
            open_issues=7,
            hot_files_text="`core/app.py` touched 3x",
        )

        self.assertIn("100/100", embed.description)
        self.assertIn("Branch protection: `On`", embed_field(embed, "🛠️ Pipeline"))
        self.assertEqual(embed_field(embed, "🔥 Hot Files"), "`core/app.py` touched 3x")
        self.assertEqual(view_links(view)["Pulls"], f"{REPO_URL}/pulls")


if __name__ == "__main__":
    unittest.main()
