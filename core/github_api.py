"""Async GitHub REST client shared by the developer cog and the watcher."""

import asyncio
import re
from urllib.parse import quote

import aiohttp

from .config import github_config

# GitHub's own rules. A login is 1-39 characters of alphanumerics and single
# hyphens; a repository name also allows dots and underscores. Anything else
# cannot name something real, so refusing it costs nothing.
GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
GITHUB_REPO_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def valid_login(value):
    """Whether this could be a real GitHub user or organisation name."""
    return bool(value) and bool(GITHUB_LOGIN.match(str(value)))


def valid_full_name(value):
    """`owner/repo`, both halves valid, and nothing else."""
    parts = str(value or "").split("/")
    if len(parts) != 2:
        return False
    owner, repo = parts
    return valid_login(owner) and bool(GITHUB_REPO_NAME.match(repo))


def _segment(value):
    """One path segment, percent-encoded so it cannot become several.

    This is the load-bearing one. `get_json` builds its URL by formatting a
    string and hands it to aiohttp, which resolves dot segments through yarl
    exactly as a browser would. So an unencoded `../user` where a username
    belongs turned `/users/<name>` into `/user` - the authenticated-user
    endpoint - and `/users/<name>/repos` into `/user/repos`, which lists
    private repositories under the host's own token. Quoting with `safe=""`
    means `/` and `.` cannot travel out of the segment they were put in.
    """
    return quote(str(value), safe="")


def _repo_path(full_name):
    """`owner/repo` with each half quoted; the slash between them is structural."""
    owner, _, repo = str(full_name or "").partition("/")
    return f"{_segment(owner)}/{_segment(repo)}"


class GitHubAPI:
    base_url = "https://api.github.com"

    def __init__(self, token=None):
        self.token = token
        self.session = None

    async def ensure_session(self):
        if self.session and not self.session.closed:
            return

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "vik-dd-discord-bot",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        timeout = aiohttp.ClientTimeout(total=10, connect=4, sock_connect=4, sock_read=8)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_json(self, path, params=None):
        await self.ensure_session()
        url = f"{self.base_url}{path}"

        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 404:
                    return None
                if response.status >= 400:
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    if response.status == 403 and remaining == "0":
                        raise RuntimeError(
                            "GitHub API rate limit reached. Add GITHUB_TOKEN or increase GITHUB_POLL_SECONDS."
                        )
                    raise RuntimeError(f"GitHub API error {response.status}: {await response.text()}")
                return await response.json()
        except asyncio.TimeoutError as error:
            raise RuntimeError("GitHub API timed out") from error
        except aiohttp.ClientError as error:
            raise RuntimeError(f"GitHub API temporary network issue: {error}") from error

    async def get_json_with_headers(self, path, params=None):
        await self.ensure_session()
        url = f"{self.base_url}{path}"

        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 404:
                    return None, response.headers
                if response.status >= 400:
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    if response.status == 403 and remaining == "0":
                        raise RuntimeError(
                            "GitHub API rate limit reached. Add GITHUB_TOKEN or increase GITHUB_POLL_SECONDS."
                        )
                    raise RuntimeError(f"GitHub API error {response.status}: {await response.text()}")
                return await response.json(), response.headers
        except asyncio.TimeoutError as error:
            raise RuntimeError("GitHub API timed out") from error
        except aiohttp.ClientError as error:
            raise RuntimeError(f"GitHub API temporary network issue: {error}") from error

    async def fetch_user(self, username):
        return await self.get_json(f"/users/{_segment(username)}")

    async def fetch_user_repos(self, username):
        repos = []
        page = 1

        while True:
            batch = await self.get_json(
                f"/users/{_segment(username)}/repos",
                params={"per_page": 100, "sort": "updated", "page": page},
            )
            if not batch:
                break
            repos.extend(batch)
            if len(batch) < 100 or page >= 2:
                break
            page += 1

        return repos

    async def fetch_repo(self, full_name):
        return await self.get_json(f"/repos/{_repo_path(full_name)}")

    async def fetch_repo_languages(self, full_name):
        return await self.get_json(f"/repos/{_repo_path(full_name)}/languages")

    async def fetch_repo_branches(self, full_name, per_page=100):
        """Every branch with its head SHA.

        The head is the useful part: a branch whose head is already known
        cannot be hiding new commits, so the watcher can skip reading it and
        a quiet repository costs one request rather than one per branch.
        """
        return await self.get_json(f"/repos/{_repo_path(full_name)}/branches", params={"per_page": per_page})

    async def fetch_repo_events(self, full_name, per_page=10):
        return await self.get_json(f"/repos/{_repo_path(full_name)}/events", params={"per_page": per_page})

    async def fetch_pull_request(self, full_name, number):
        """The whole pull request, which the events feed does not include.

        A PullRequestEvent carries only url, id, number, head and base — no
        title, body or state — so anything that wants to describe the pull
        request has to ask for it here.
        """
        return await self.get_json(f"/repos/{_repo_path(full_name)}/pulls/{_segment(number)}")

    async def fetch_repo_commits(self, full_name, per_page=8, sha=None):
        params = {"per_page": per_page}
        if sha:
            params["sha"] = sha
        return await self.get_json(f"/repos/{_repo_path(full_name)}/commits", params=params)

    async def fetch_commit_detail(self, full_name, sha):
        return await self.get_json(f"/repos/{_repo_path(full_name)}/commits/{_segment(sha)}")

    async def fetch_compare(self, full_name, base_sha, head_sha):
        """GitHub's public Events API push payloads no longer include a
        `commits` array (just `before`/`head` SHAs) — use compare to recover them."""
        return await self.get_json(f"/repos/{_repo_path(full_name)}/compare/{_segment(base_sha)}...{_segment(head_sha)}")

    async def fetch_latest_workflow_run(self, full_name):
        data = await self.get_json(f"/repos/{_repo_path(full_name)}/actions/runs", params={"per_page": 1})
        if not data:
            return None
        runs = data.get("workflow_runs", [])
        return runs[0] if runs else None

    async def fetch_branch(self, full_name, branch_name):
        return await self.get_json(f"/repos/{_repo_path(full_name)}/branches/{_segment(branch_name)}")

    async def fetch_latest_release(self, full_name):
        return await self.get_json(f"/repos/{_repo_path(full_name)}/releases/latest")

    async def count_open_pull_requests(self, full_name):
        total = 0
        page = 1

        while True:
            batch = await self.get_json(
                f"/repos/{full_name}/pulls",
                params={"state": "open", "per_page": 100, "page": page},
            )
            if not batch:
                break
            total += len(batch)
            if len(batch) < 100 or page >= 10:
                break
            page += 1

        return total

    async def count_open_issues(self, full_name):
        total = 0
        page = 1

        while True:
            batch = await self.get_json(
                f"/repos/{full_name}/issues",
                params={"state": "open", "per_page": 100, "page": page},
            )
            if not batch:
                break
            total += sum(1 for item in batch if "pull_request" not in item)
            if len(batch) < 100 or page >= 10:
                break
            page += 1

        return total

    async def search_open_pull_requests(self, full_name):
        return await self.count_open_pull_requests(full_name)

    async def search_open_issues(self, full_name):
        return await self.count_open_issues(full_name)


github_api = GitHubAPI(github_config.token)
