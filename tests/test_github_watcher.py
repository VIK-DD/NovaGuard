"""The GitHub watcher must not describe a pull request it never read.

The repo Events API does not hand back a whole pull_request object. Sampled
live from /repos/VIK-DD/NovaGuard/events, it carries exactly five keys:

    {"url": ..., "id": ..., "number": 16,
     "head": {"ref": ...}, "base": {"ref": ...}}

No title, no body, no state, no html_url. The watcher read those anyway, so a
closed Dependabot PR arrived in Discord titled "Pull request closed" while its
own detail field said `State: Open`, above "No pull request title." and "No
details available.". Number and branch flow looked right, which made the rest
look like a Discord glitch rather than missing data.

The push branch in the same file already re-fetches what the payload omits.
These tests hold the pull request branch to the same standard.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cogs.developer as developer  # noqa: E402
from cogs.developer import pull_request_state  # noqa: E402

REPO = "VIK-DD/NovaGuard"

# Exactly what the Events API returns, keys and all.
TRIMMED_PR = {
    "url": f"https://api.github.com/repos/{REPO}/pulls/16",
    "id": 4242629674,
    "number": 16,
    "head": {"ref": "dependabot/pip/pynacl-gte-1.6.2-and-lt-2", "sha": "1d18d27"},
    "base": {"ref": "main", "sha": "abc1234"},
}

FULL_PR = {
    "number": 16,
    "title": "Bump pynacl from 1.5.0 to 1.6.2",
    "body": "Bumps pynacl from 1.5.0 to 1.6.2.",
    "state": "closed",
    "merged": False,
    "draft": False,
    "html_url": f"https://github.com/{REPO}/pull/16",
    "head": {"ref": "dependabot/pip/pynacl-gte-1.6.2-and-lt-2"},
    "base": {"ref": "main"},
}


def event(action="closed", pull_request=None):
    return {
        "id": "1",
        "type": "PullRequestEvent",
        "created_at": "2026-08-18T13:01:00Z",
        "payload": {
            "action": action,
            "number": 16,
            "pull_request": dict(TRIMMED_PR if pull_request is None else pull_request),
        },
    }


def field(embed, name):
    for f in embed.fields:
        if f.name == name:
            return f.value
    raise AssertionError(f"no field named {name!r}; got {[f.name for f in embed.fields]}")


class PullRequestStateTests(unittest.TestCase):
    """What the State field may claim, given what is actually known."""

    def test_a_merged_pull_request_says_so(self):
        self.assertEqual(pull_request_state({"merged": True, "state": "closed"}, "closed"), "Merged")

    def test_a_real_state_is_used_when_the_payload_carries_one(self):
        self.assertEqual(pull_request_state({"state": "closed"}, "closed"), "Closed")
        self.assertEqual(pull_request_state({"state": "open"}, "opened"), "Open")

    def test_a_missing_state_follows_the_action_rather_than_guessing_open(self):
        # This is the reported bug: no state in the payload used to mean the
        # literal default "open", contradicting the action in the same embed.
        self.assertEqual(pull_request_state({}, "closed"), "Closed")

    def test_an_opened_or_reopened_action_reads_as_open(self):
        self.assertEqual(pull_request_state({}, "opened"), "Open")
        self.assertEqual(pull_request_state({}, "reopened"), "Open")

    def test_an_unrecognised_action_admits_it_does_not_know(self):
        # Better a plain "Unknown" than a confident wrong answer.
        self.assertEqual(pull_request_state({}, "synchronize"), "Unknown")


class FakeGitHubApi:
    def __init__(self, pull_request=None, error=None):
        self.pull_request = pull_request
        self.error = error
        self.calls = []

    async def fetch_pull_request(self, full_name, number):
        self.calls.append((full_name, number))
        if self.error:
            raise self.error
        return self.pull_request


class WatcherEmbedTests(unittest.IsolatedAsyncioTestCase):
    def _patch_api(self, api):
        patcher = mock.patch.object(developer, "github_api", api)
        patcher.start()
        self.addCleanup(patcher.stop)
        return api

    async def test_the_trimmed_payload_is_refetched_so_the_title_is_real(self):
        api = self._patch_api(FakeGitHubApi(FULL_PR))

        embed, _view = await developer.build_watcher_embed(REPO, event())

        self.assertEqual(api.calls, [(REPO, 16)])
        self.assertIn("Bump pynacl", embed.description)
        self.assertNotIn("No pull request title", embed.description)

    async def test_the_body_comes_through_instead_of_a_placeholder(self):
        self._patch_api(FakeGitHubApi(FULL_PR))

        embed, _view = await developer.build_watcher_embed(REPO, event())

        self.assertIn("Bumps pynacl", field(embed, "Summary"))

    async def test_a_closed_pull_request_never_reports_itself_as_open(self):
        self._patch_api(FakeGitHubApi(FULL_PR))

        embed, _view = await developer.build_watcher_embed(REPO, event(action="closed"))

        self.assertIn("closed", embed.title.lower())
        self.assertIn("Closed", field(embed, "PR Details"))
        self.assertNotIn("Open", field(embed, "PR Details"))

    async def test_the_embed_links_to_the_pull_request(self):
        self._patch_api(FakeGitHubApi(FULL_PR))

        embed, _view = await developer.build_watcher_embed(REPO, event())

        self.assertEqual(embed.url, FULL_PR["html_url"])

    async def test_a_failed_refetch_still_produces_a_consistent_embed(self):
        # GitHub being briefly unavailable must not put a contradiction in
        # front of the reader; the action alone is enough to be truthful.
        self._patch_api(FakeGitHubApi(error=RuntimeError("rate limited")))

        embed, _view = await developer.build_watcher_embed(REPO, event(action="closed"))

        self.assertIsNotNone(embed)
        self.assertIn("Closed", field(embed, "PR Details"))
        self.assertNotIn("Open", field(embed, "PR Details"))

    async def test_the_branch_flow_survives_either_way(self):
        self._patch_api(FakeGitHubApi(error=RuntimeError("rate limited")))

        embed, _view = await developer.build_watcher_embed(REPO, event())

        flow = field(embed, "Branch Flow")
        self.assertIn("dependabot/pip/pynacl-gte-1.6.2-and-lt-2", flow)
        self.assertIn("main", flow)

    async def test_a_payload_that_already_has_a_title_is_not_refetched(self):
        # Webhook-shaped payloads arrive complete; spending an API call on
        # them would burn rate limit for nothing.
        api = self._patch_api(FakeGitHubApi(FULL_PR))

        await developer.build_watcher_embed(REPO, event(pull_request=FULL_PR))

        self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
