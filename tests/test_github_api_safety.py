"""What a member may point the host's GitHub credentials at.

The bot's HTTP session carries the operator's GITHUB_TOKEN on every request,
and `GitHubAPI.get_json` builds its URL by formatting a string:

    url = f"{self.base_url}{path}"

aiohttp hands that to yarl, which resolves dot segments exactly as a browser
would. So `/github username:../user` turned `/users/<name>` into `/user` - the
authenticated-user endpoint - and `/users/<name>/repos` into `/user/repos`,
which lists the token owner's PRIVATE repositories. An ordinary member with no
permissions could run it, and the profile card was rendered publicly.

Two layers now stand in the way, and the tests cover both:

* every interpolated path segment is percent-encoded, so `/` and `.` cannot
  travel out of the segment they were placed in - this holds even for a caller
  that forgets to validate;
* the repository-scoped commands accept only repositories this instance is
  configured to watch, so the token cannot be aimed at a private repo that
  merely happens to be readable.
"""

import os
import sys
import unittest

import yarl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.github_api import (  # noqa: E402
    GitHubAPI,
    _repo_path,
    _segment,
    valid_full_name,
    valid_login,
)


def resolved(path):
    """The URL aiohttp would actually request for this path."""
    return str(yarl.URL(f"{GitHubAPI.base_url}{path}"))


class PathSegmentEncodingTests(unittest.TestCase):
    """The layer that holds even when a caller forgets to validate."""

    def test_a_traversal_segment_cannot_change_the_endpoint(self):
        # The regression, stated as the URL that actually goes out.
        self.assertEqual(
            resolved(f"/users/{_segment('../user')}"),
            "https://api.github.com/users/..%2Fuser",
        )

    def test_the_private_repo_listing_stays_out_of_reach(self):
        self.assertEqual(
            resolved(f"/users/{_segment('../user')}/repos"),
            "https://api.github.com/users/..%2Fuser/repos",
        )

    def test_an_ordinary_username_is_left_alone(self):
        self.assertEqual(
            resolved(f"/users/{_segment('VIK-DD')}"),
            "https://api.github.com/users/VIK-DD",
        )

    def test_a_repo_keeps_its_one_structural_slash(self):
        self.assertEqual(_repo_path("VIK-DD/NovaGuard"), "VIK-DD/NovaGuard")

    def test_extra_slashes_in_a_repo_name_cannot_add_path(self):
        # partition() keeps the first slash and quotes everything after it.
        self.assertEqual(
            resolved(f"/repos/{_repo_path('a/../../user')}"),
            "https://api.github.com/repos/a/..%2F..%2Fuser",
        )

    def test_every_traversal_shape_stays_on_its_endpoint(self):
        for probe in ("../user", "..%2Fuser", "a/../..", "./../user", "%2e%2e/user", "a/b/c"):
            with self.subTest(probe=probe):
                url = resolved(f"/users/{_segment(probe)}")
                self.assertTrue(
                    url.startswith("https://api.github.com/users/"),
                    f"{probe!r} escaped its segment: {url}",
                )

    def test_a_query_string_cannot_be_smuggled_in(self):
        url = resolved(f"/users/{_segment('x?foo=bar')}")
        self.assertNotIn("?", url.split("/users/", 1)[1])


class EveryEndpointEncodesTests(unittest.IsolatedAsyncioTestCase):
    """The encoding layer has to hold for *every* method, not most of them.

    docs/SECURITY.md states flatly that "every GitHub path segment is
    percent-encoded now". Two methods were left out - `count_open_pull_requests`
    and `count_open_issues` interpolated `full_name` raw - and no test noticed,
    which is how a documented control quietly stops being true. Neither is
    reachable with unvalidated input today; the point of the encoding layer is
    that it holds anyway, for the caller who forgets.
    """

    async def _requested_paths(self, method_name, *args):
        api = GitHubAPI(token="unused")
        seen = []

        async def capture(path, params=None):
            seen.append(path)
            return []  # empty batch ends the paging loops immediately

        api.get_json = capture
        await getattr(api, method_name)(*args)
        return seen

    async def test_the_counting_endpoints_encode_their_repository(self):
        for method in ("count_open_pull_requests", "count_open_issues"):
            with self.subTest(method=method):
                paths = await self._requested_paths(method, "a/../../user")

                self.assertTrue(paths, f"{method} made no request")
                for path in paths:
                    url = resolved(path)
                    self.assertTrue(
                        url.startswith("https://api.github.com/repos/a/"),
                        f"{method} escaped /repos/: {url}",
                    )

    async def test_an_ordinary_repository_still_reaches_its_endpoint(self):
        paths = await self._requested_paths("count_open_issues", "VIK-DD/NovaGuard")

        self.assertEqual(paths[0], "/repos/VIK-DD/NovaGuard/issues")


class NameValidationTests(unittest.TestCase):
    def test_real_logins_are_accepted(self):
        for name in ("VIK-DD", "a", "octocat", "a-b-c", "A1"):
            self.assertTrue(valid_login(name), name)

    def test_anything_that_cannot_be_a_login_is_refused(self):
        for name in ("../user", "a/b", "", None, "-lead", "trail-", "a" * 40, "a b", "a.b"):
            self.assertFalse(valid_login(name), repr(name))

    def test_full_names_need_exactly_one_slash_and_two_valid_halves(self):
        self.assertTrue(valid_full_name("VIK-DD/NovaGuard"))
        self.assertTrue(valid_full_name("owner/repo.name_1"))
        for name in ("VIK-DD", "a/b/c", "../user", "/repo", "owner/", "", None):
            self.assertFalse(valid_full_name(name), repr(name))


class ConfiguredRepositoryGateTests(unittest.TestCase):
    """The second layer: which repositories the commands will talk about."""

    def test_only_configured_repositories_are_allowed(self):
        from cogs import developer
        from core.config import github_config

        original_watch = github_config.watch_repos
        original_primary = github_config.primary_repo
        try:
            github_config.watch_repos = ["VIK-DD/NovaGuard"]
            github_config.primary_repo = "VIK-DD/NovaGuard"
            allowed = developer.configured_repos()
            self.assertIn("vik-dd/novaguard", allowed)
            # Case and stray slashes must not be a way around the list.
            self.assertEqual(developer.configured_repos(), {"vik-dd/novaguard"})
            self.assertNotIn("someone/private-repo", allowed)
        finally:
            github_config.watch_repos = original_watch
            github_config.primary_repo = original_primary

    def test_no_configuration_means_no_repository_is_allowed(self):
        from cogs import developer
        from core.config import github_config

        original_watch = github_config.watch_repos
        original_primary = github_config.primary_repo
        try:
            github_config.watch_repos = []
            github_config.primary_repo = None
            self.assertEqual(developer.configured_repos(), set())
        finally:
            github_config.watch_repos = original_watch
            github_config.primary_repo = original_primary

    def test_every_repository_command_consults_the_gate(self):
        # Source inspection, because the alternative is a full interaction
        # harness for five commands. A new repo command that forgets the gate
        # is exactly the regression worth catching.
        import inspect

        from cogs import developer

        for name in ("repo", "health", "commits", "release"):
            with self.subTest(command=name):
                source = inspect.getsource(getattr(developer.Developer, name).callback)
                self.assertIn("reject_repo", source, f"/{name} does not gate its repository")

    def test_the_profile_command_validates_its_username(self):
        import inspect

        from cogs import developer

        source = inspect.getsource(developer.Developer.github.callback)
        self.assertIn("reject_login", source)

    def test_the_watcher_diagnostics_are_not_public(self):
        # /ghwatch answers with the host's own configuration - watched repos,
        # the owner's channels, whether a token is set.
        import inspect

        from cogs import developer

        source = inspect.getsource(developer.Developer.ghwatch.callback)
        self.assertIn("ephemeral=True", source)
        self.assertIsNotNone(
            getattr(developer.Developer.ghwatch, "default_permissions", None),
            "/ghwatch is still visible to every member",
        )


if __name__ == "__main__":
    unittest.main()
