"""Async GitHub REST client shared by the developer cog and the watcher."""

import asyncio

import aiohttp

from .config import github_config


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

        timeout = aiohttp.ClientTimeout(total=20)
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
        except (asyncio.TimeoutError, aiohttp.ClientError) as error:
            raise RuntimeError(f"GitHub API temporary network issue: {error}") from error

    async def fetch_user(self, username):
        return await self.get_json(f"/users/{username}")

    async def fetch_user_repos(self, username):
        repos = []
        page = 1

        while True:
            batch = await self.get_json(
                f"/users/{username}/repos",
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
        return await self.get_json(f"/repos/{full_name}")

    async def fetch_repo_languages(self, full_name):
        return await self.get_json(f"/repos/{full_name}/languages")

    async def fetch_repo_events(self, full_name, per_page=10):
        return await self.get_json(f"/repos/{full_name}/events", params={"per_page": per_page})

    async def fetch_repo_commits(self, full_name, per_page=8):
        return await self.get_json(f"/repos/{full_name}/commits", params={"per_page": per_page})

    async def fetch_commit_detail(self, full_name, sha):
        return await self.get_json(f"/repos/{full_name}/commits/{sha}")

    async def fetch_compare(self, full_name, base_sha, head_sha):
        """GitHub's public Events API push payloads no longer include a
        `commits` array (just `before`/`head` SHAs) — use compare to recover them."""
        return await self.get_json(f"/repos/{full_name}/compare/{base_sha}...{head_sha}")

    async def fetch_latest_workflow_run(self, full_name):
        data = await self.get_json(f"/repos/{full_name}/actions/runs", params={"per_page": 1})
        if not data:
            return None
        runs = data.get("workflow_runs", [])
        return runs[0] if runs else None

    async def fetch_branch(self, full_name, branch_name):
        return await self.get_json(f"/repos/{full_name}/branches/{branch_name}")

    async def fetch_latest_release(self, full_name):
        return await self.get_json(f"/repos/{full_name}/releases/latest")

    async def search_open_pull_requests(self, full_name):
        data = await self.get_json(
            "/search/issues",
            params={"q": f"repo:{full_name} is:pr is:open"},
        )
        return 0 if not data else data.get("total_count", 0)

    async def search_open_issues(self, full_name):
        data = await self.get_json(
            "/search/issues",
            params={"q": f"repo:{full_name} is:issue is:open"},
        )
        return 0 if not data else data.get("total_count", 0)


github_api = GitHubAPI(github_config.token)
