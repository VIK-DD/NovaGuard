"""🐙 Developer category — GitHub profile cards, repo dashboards, health and the live watcher."""

import asyncio
import logging
from datetime import UTC, datetime

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.loop_guard import keep_running
from core.config import GITHUB_STATE_FILE, github_config
from core.github_api import github_api
from core.github_commits import (
    branches_needing_a_read,
    merge_new_commits,
    remember_across_branches,
    store_shas,
    stored_shas,
)
from core.github_insights import (
    extract_hot_files,
    summarize_changed_files,
)
from core.github_presenters import (
    build_dashboard_embed,
    build_health_embed,
    build_profile_embed,
    build_repo_embed,
    choose_primary_repo,
    repo_to_urls,
)
from core.guild_config import resolve_configured_channels
from core.storage import get_guild_settings, load_json_file, save_json_file
from core.theme import Palette, brand_footer, make_embed
from core.updates import safe_send_embed
from core.utils import (
    build_link_view,
    defer_interaction,
    first_line,
    format_github_time,
    parse_github_datetime,
    respond,
    truncate,
)

log = logging.getLogger(__name__)

# PushEvent is deliberately absent: pushes are read from /commits instead.
# The Events API is a cached timeline GitHub documents as unsuitable for
# real-time use, and on 2026-08-19 it was a full day behind — commits sat on
# main at 20:42 while the newest event returned dated from 21:30 the evening
# before. The other three have no current alternative, so they stay here and
# arrive late rather than not at all.
WATCHED_EVENT_TYPES = {"PullRequestEvent", "IssuesEvent", "ReleaseEvent"}

# Only branches that actually moved are read, so this is reached solely when
# a great many change at once — a force-push cleanup, or a first sight after
# the state file is lost. Reading them all in one pass would spend the rate
# limit on history nobody is waiting for; the rest are picked up next poll.
MAX_BRANCHES_PER_POLL = 10

# What each pull request action implies about the state, for when the payload
# does not carry one. "synchronize" and friends say nothing about it.
_ACTION_STATES = {"opened": "Open", "reopened": "Open", "closed": "Closed"}


def pull_request_state(pull_request, action):
    """The State to display, using only what is actually known.

    The events feed trims the pull request down to url, id, number, head and
    base. Reading `state` off that and defaulting to "open" published a closed
    pull request as `State: Open`, contradicting the title of the same embed.
    """
    if pull_request.get("merged"):
        return "Merged"
    state = pull_request.get("state")
    if state:
        return str(state).title()
    return _ACTION_STATES.get(action, "Unknown")


async def hydrate_pull_request(repo_name, pull_request):
    """Fill in the fields the events feed leaves out.

    A payload that already has a title came from somewhere complete and is
    left alone, so this costs one API call per pull request event and none
    otherwise. A failed fetch returns what we had: a thinner embed is fine,
    an inconsistent one is not, and the caller no longer depends on `state`.
    """
    if pull_request.get("title") or not pull_request.get("number"):
        return pull_request
    try:
        full = await github_api.fetch_pull_request(repo_name, pull_request["number"])
    except Exception:
        log.warning("Could not fetch pull request %s#%s", repo_name, pull_request.get("number"))
        return pull_request
    return {**pull_request, **(full or {})}


def load_github_state():
    return load_json_file(GITHUB_STATE_FILE, {"events": {}})


def save_github_state(state):
    save_json_file(GITHUB_STATE_FILE, state)


def push_commit_message(commit):
    message = (
        commit.get("message")
        or commit.get("commit", {}).get("message", "")
    )
    return truncate(first_line(message), 70)


def push_commit_sha(commit):
    return (commit.get("sha") or "")[:7] or "unknown"


def commit_author_name(commit):
    account = commit.get("author") or {}
    if account.get("login"):
        return account["login"]
    return (commit.get("commit", {}).get("author") or {}).get("name") or "someone"


def build_commit_digest_embed(repo_name, branch_name, commits):
    """One card for a batch of commits on one branch, not one card each.

    A push of nine commits posted nine times buries the channel and tells the
    reader nothing the list would not.
    """
    urls = repo_to_urls(repo_name)
    lines = []
    for entry in reversed(commits):  # newest first for reading
        sha = push_commit_sha(entry)
        link = entry.get("html_url") or f"{urls['commits']}/{entry.get('sha', '')}"
        lines.append(f"[`{sha}`]({link}) {push_commit_message(entry)}")

    authors = []
    for entry in commits:
        name = commit_author_name(entry)
        if name not in authors:
            authors.append(name)

    count = len(commits)
    embed = discord.Embed(
        title=f"📤 {count} new commit{'' if count == 1 else 's'} in {repo_name}",
        description="\n".join(lines),
        color=discord.Color.green(),
        timestamp=(
            parse_github_datetime((commits[-1].get("commit", {}).get("author") or {}).get("date"))
            or datetime.now(UTC)
        ),
    )
    embed.add_field(name="Branch", value=f"`{branch_name}`", inline=True)
    embed.add_field(name="By", value=", ".join(f"`{name}`" for name in authors[:4]), inline=True)
    embed.add_field(name="Repository", value=f"[{repo_name}]({urls['repo']})", inline=True)
    brand_footer(embed, "GitHub activity")
    return embed


def build_commit_digest_embeds(repo_name, branch_commits):
    """A card per branch, in the order the branches were walked.

    Grouping matters now that several branches are watched: a card headed
    "main" listing a commit that landed on a working branch would be wrong
    about the one thing the card exists to say.
    """
    grouped = {}
    for branch_name, commit in branch_commits:
        grouped.setdefault(branch_name, []).append(commit)
    return [
        build_commit_digest_embed(repo_name, branch_name, commits)
        for branch_name, commits in grouped.items()
    ]


async def build_watcher_embed(repo_name, event):
    event_type = event.get("type")
    payload = event.get("payload", {})
    actor = event.get("actor", {})
    actor_name = actor.get("login", "GitHub user")
    actor_url = f"https://github.com/{actor_name}" if actor_name else None
    repo_urls = repo_to_urls(repo_name)
    timestamp = parse_github_datetime(event.get("created_at")) or datetime.now(UTC)

    if event_type == "PushEvent":
        # The public Events API push payload only carries before/head SHAs —
        # fetch the actual commit list via compare instead of payload["commits"].
        base_sha = payload.get("before")
        head_sha = payload.get("head")
        commits = []
        changed_files = []
        payload_commits = payload.get("commits") or []
        if base_sha and head_sha and set(base_sha) != {"0"}:
            try:
                comparison = await github_api.fetch_compare(repo_name, base_sha, head_sha)
            except RuntimeError as error:
                log.warning(f"GitHub watcher compare skipped for {repo_name}: {error}")
                comparison = None
            if comparison:
                commits = comparison.get("commits", [])
                changed_files = comparison.get("files", [])

        if not commits and payload_commits:
            commits = payload_commits

        if not commits:
            fallback_count = min(max(payload.get("size", 1), 1), 5)
            try:
                commits = await github_api.fetch_repo_commits(
                    repo_name,
                    per_page=fallback_count,
                    sha=payload.get("ref", "refs/heads/main").split("/")[-1],
                ) or []
            except RuntimeError as error:
                log.warning(f"GitHub watcher commit fallback skipped for {repo_name}: {error}")
                commits = []

        branch_name = payload.get("ref", "refs/heads/main").split("/")[-1]
        commit_lines = []
        for commit in commits[-3:]:
            commit_lines.append(f"`{push_commit_sha(commit)}` {push_commit_message(commit)}")
        commit_lines.reverse()
        if len(commits) > 3:
            commit_lines.append(f"...and {len(commits) - 3} more commit(s)")

        compare_url = f"{repo_urls['repo']}/compare/{base_sha}...{head_sha}" if base_sha and head_sha else None
        embed = discord.Embed(
            title=f"📤 Push update in {repo_name}",
            description=f"{actor_name} pushed to `{branch_name}`.",
            color=discord.Color.green(),
            timestamp=timestamp,
        )
        embed.add_field(name="Commits", value="\n".join(commit_lines) or "No commit details.", inline=False)
        embed.add_field(name="Files Changed", value=summarize_changed_files(changed_files), inline=False)
        embed.add_field(name="Branch", value=f"`{branch_name}`", inline=True)
        embed.add_field(name="Pushed By", value=f"[{actor_name}]({actor_url})" if actor_url else actor_name, inline=True)
        embed.set_footer(text="GitHub watcher • Push event")
        return embed, build_link_view(
            [
                ("Repository", repo_urls["repo"]),
                ("Compare", compare_url),
                ("Latest Commit", f"{repo_urls['repo']}/commit/{head_sha}" if head_sha else None),
            ]
        )

    if event_type == "PullRequestEvent":
        raw_action = payload.get("action", "updated")
        # The feed hands over a five-key stub; everything readable comes from
        # the fetch below.
        pull_request = await hydrate_pull_request(repo_name, payload.get("pull_request", {}))
        action = raw_action.replace("_", " ")
        merged = pull_request.get("merged")
        color = Palette.SUCCESS if merged else Palette.INFO
        state = pull_request_state(pull_request, raw_action)

        embed = discord.Embed(
            title=f"🔀 Pull request {action} in {repo_name}",
            description=truncate(pull_request.get("title") or "No pull request title.", 140),
            color=discord.Color(color),
            timestamp=timestamp,
            url=pull_request.get("html_url"),
        )
        embed.add_field(
            name="PR Details",
            value=(
                f"Number: `#{pull_request.get('number', 0)}`\n"
                f"State: `{state}`\n"
                f"Draft: `{('Yes' if pull_request.get('draft') else 'No')}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Branch Flow",
            value=(
                f"`{pull_request.get('head', {}).get('ref', 'unknown')}` -> "
                f"`{pull_request.get('base', {}).get('ref', 'unknown')}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Summary",
            value=truncate(pull_request.get("body"), 240),
            inline=False,
        )
        embed.set_footer(text="GitHub watcher • Pull request event")
        return embed, build_link_view(
            [
                ("Repository", repo_urls["repo"]),
                ("Pull Request", pull_request.get("html_url")),
                ("Files", f"{pull_request.get('html_url')}/files" if pull_request.get("html_url") else None),
            ]
        )

    if event_type == "IssuesEvent":
        issue = payload.get("issue", {})
        action = payload.get("action", "updated").replace("_", " ")
        embed = discord.Embed(
            title=f"🐛 Issue {action} in {repo_name}",
            description=truncate(issue.get("title") or "No issue title.", 140),
            color=discord.Color.orange(),
            timestamp=timestamp,
            url=issue.get("html_url"),
        )
        embed.add_field(
            name="Issue Details",
            value=(
                f"Number: `#{issue.get('number', 0)}`\n"
                f"State: `{issue.get('state', 'open').title()}`\n"
                f"Comments: `{issue.get('comments', 0)}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Opened By",
            value=f"[{actor_name}]({actor_url})" if actor_url else actor_name,
            inline=True,
        )
        embed.add_field(name="Summary", value=truncate(issue.get("body"), 240), inline=False)
        embed.set_footer(text="GitHub watcher • Issue event")
        return embed, build_link_view(
            [
                ("Repository", repo_urls["repo"]),
                ("Issue", issue.get("html_url")),
                ("Issues Board", repo_urls["issues"]),
            ]
        )

    if event_type == "ReleaseEvent":
        release = payload.get("release", {})
        action = payload.get("action", "published").replace("_", " ")
        embed = discord.Embed(
            title=f"🏷️ Release {action} in {repo_name}",
            description=truncate(release.get("body") or release.get("name") or "A new release is now live.", 220),
            color=discord.Color.gold(),
            timestamp=timestamp,
            url=release.get("html_url"),
        )
        embed.add_field(
            name="Release Details",
            value=(
                f"Tag: `{release.get('tag_name', 'untagged')}`\n"
                f"Name: `{release.get('name') or release.get('tag_name', 'untagged')}`\n"
                f"Pre-release: `{('Yes' if release.get('prerelease') else 'No')}`"
            ),
            inline=False,
        )
        embed.set_footer(text="GitHub watcher • Release event")
        return embed, build_link_view(
            [
                ("Repository", repo_urls["repo"]),
                ("Release", release.get("html_url")),
                ("Releases", repo_urls["releases"]),
            ]
        )

    return None, None


async def send_config_error(interaction, variable_name):
    embed = make_embed(
        "⚙️ Missing configuration",
        f"Set `{variable_name}` in `.env` first, then restart the bot.",
        color=Palette.WARNING,
    )
    brand_footer(embed)
    await respond(interaction, embed, ephemeral=True)


class Developer(commands.Cog):
    """GitHub intelligence: profiles, repos, health reports and live events."""

    EMOJI = "🐙"
    COLOR = Palette.TEAL
    DESCRIPTION = "GitHub profile cards, repo dashboards, project health and the live watcher."

    def __init__(self, bot):
        self.bot = bot
        # repo -> default branch name, asked once per process. It only decides
        # which branch is credited for a commit that exists on several.
        self._default_branches: dict[str, str] = {}

    async def cog_load(self):
        # light per-user cooldown on every command here — they all hit the
        # GitHub API, so this caps abuse against our shared token quota
        for command in self.walk_app_commands():
            app_commands.checks.cooldown(1, 6.0)(command)
        if github_config.watch_repos:
            self.watch_github_activity.start()

    async def cog_unload(self):
        self.watch_github_activity.cancel()

    async def default_branch_of(self, repo_name):
        """Cached for the process: it decides credit, not correctness.

        When a commit exists on several branches the first one walked is the
        one named on the card, and the default branch is the honest answer.
        Asking GitHub once at first use costs one request ever, rather than
        one per poll for a cosmetic detail.
        """
        if repo_name not in self._default_branches:
            try:
                repo = await github_api.fetch_repo(repo_name) or {}
                self._default_branches[repo_name] = repo.get("default_branch") or ""
            except (RuntimeError, asyncio.TimeoutError, aiohttp.ClientError):
                # Unknown is fine: branches keep their listed order and a
                # shared commit is credited to whichever comes first.
                self._default_branches[repo_name] = ""
        return self._default_branches[repo_name]

    async def announce_new_commits(self, repo_name, commit_state, channels):
        """Post the commits that have landed on any branch since the last poll.

        Read from /commits rather than /events because that list is current;
        see WATCHED_EVENT_TYPES for what the timeline was doing instead.

        GitHub has no endpoint for "every commit on every branch", so each
        branch costs a request. The branch listing carries every head SHA
        though, so branches that have not moved are skipped entirely and a
        quiet repository costs exactly one request per poll.
        """
        try:
            branches = await github_api.fetch_repo_branches(repo_name) or []
        except RuntimeError as error:
            log.warning(f"GitHub commit poll skipped {repo_name}: {error}")
            return
        except (asyncio.TimeoutError, aiohttp.ClientError) as error:
            log.warning(f"GitHub commit poll skipped {repo_name}: temporary network issue ({error})")
            return

        if not branches:
            return

        # A state file written before branches were watched covered the
        # default branch only, so it is primed rather than trusted — see
        # stored_shas.
        seen, first_sight = stored_shas(commit_state.get(repo_name))

        moved = branches_needing_a_read(branches, seen)
        if not moved:
            return

        default = await self.default_branch_of(repo_name)
        # Default first, so a commit that exists on several branches is
        # credited to the one people recognise.
        moved.sort(key=lambda name: (name != default, name))
        if len(moved) > MAX_BRANCHES_PER_POLL:
            log.info(
                "GitHub commit poll for %s reading %d of %d changed branches this pass",
                repo_name,
                MAX_BRANCHES_PER_POLL,
                len(moved),
            )
            moved = moved[:MAX_BRANCHES_PER_POLL]

        per_branch = []
        for branch_name in moved:
            try:
                commits = await github_api.fetch_repo_commits(
                    repo_name, per_page=30, sha=branch_name
                ) or []
            except (RuntimeError, asyncio.TimeoutError, aiohttp.ClientError) as error:
                log.warning(
                    f"GitHub commit poll skipped {repo_name}@{branch_name}: {error}"
                )
                continue
            per_branch.append((branch_name, commits))

        if not per_branch:
            return

        every_sha = [
            commit.get("sha")
            for _branch, commits in per_branch
            for commit in commits
        ]
        heads = [(b.get("commit") or {}).get("sha") for b in branches if isinstance(b, dict)]

        # First sight of a repository: remember where every branch is and say
        # nothing. Announcing here would dump pages of history into the channel
        # the moment the watcher is switched on, or after the state file is lost.
        if first_sight:
            commit_state[repo_name] = store_shas(remember_across_branches([], every_sha, heads))
            return

        fresh = merge_new_commits(per_branch, seen)
        commit_state[repo_name] = store_shas(remember_across_branches(seen, every_sha, heads))
        if not fresh or not channels:
            return

        for embed in build_commit_digest_embeds(repo_name, fresh):
            for channel in channels:
                await safe_send_embed(channel, embed)

    @tasks.loop(seconds=github_config.poll_seconds)
    @keep_running(log, "GitHub activity poll")
    async def watch_github_activity(self):
        if not github_config.watch_repos:
            return

        state = await asyncio.to_thread(load_github_state)
        event_state = state.setdefault("events", {})
        commit_state = state.setdefault("commits", {})
        channels = await resolve_configured_channels(self.bot, "github_event_channel", github_config.event_channel_id)

        for repo_name in github_config.watch_repos:
            await self.announce_new_commits(repo_name, commit_state, channels)

        for repo_name in github_config.watch_repos:
            try:
                events = await github_api.fetch_repo_events(repo_name, per_page=10)
            except RuntimeError as error:
                log.warning(f"GitHub watcher skipped {repo_name}: {error}")
                continue
            except (asyncio.TimeoutError, aiohttp.ClientError) as error:
                log.warning(f"GitHub watcher skipped {repo_name}: temporary network issue ({error})")
                continue

            if not events:
                continue

            known_ids = set(event_state.get(repo_name, []))
            current_ids = [event["id"] for event in events[:50]]

            if not known_ids:
                event_state[repo_name] = current_ids
                continue

            new_events = [
                event
                for event in events
                if event["id"] not in known_ids and event.get("type") in WATCHED_EVENT_TYPES
            ]
            event_state[repo_name] = current_ids

            if not channels:
                continue

            for event in reversed(new_events):
                embed, view = await build_watcher_embed(repo_name, event)
                if embed is not None:
                    for channel in channels:
                        await safe_send_embed(channel, embed, view)

        await asyncio.to_thread(save_github_state, state)

    @watch_github_activity.before_loop
    async def before_watch_github_activity(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="github", description="Elegant GitHub profile card")
    @app_commands.describe(username="GitHub username (defaults to the configured one)")
    async def github(self, interaction: discord.Interaction, username: str | None = None):
        target_username = username or github_config.username
        if not target_username:
            return await send_config_error(interaction, "GITHUB_USERNAME")

        await defer_interaction(interaction)
        user, repos = await asyncio.gather(
            github_api.fetch_user(target_username),
            github_api.fetch_user_repos(target_username),
        )
        if not user:
            embed = make_embed("🔍 Not found", "I could not find that GitHub profile.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed)

        embed, view = build_profile_embed(user, repos)
        await respond(interaction, embed, view=view)

    @app_commands.command(name="repo", description="Live status card for a repository")
    @app_commands.describe(repo_name="owner/name (defaults to the primary repo)")
    async def repo(self, interaction: discord.Interaction, repo_name: str | None = None):
        target_repo = choose_primary_repo(repo_name)
        if not target_repo:
            return await send_config_error(interaction, "GITHUB_PRIMARY_REPO")

        await defer_interaction(interaction)
        repo_data, languages, open_prs, open_issues, workflow_run, release = await asyncio.gather(
            github_api.fetch_repo(target_repo),
            github_api.fetch_repo_languages(target_repo),
            github_api.search_open_pull_requests(target_repo),
            github_api.search_open_issues(target_repo),
            github_api.fetch_latest_workflow_run(target_repo),
            github_api.fetch_latest_release(target_repo),
        )
        if not repo_data:
            embed = make_embed("🔍 Not found", "I could not find that repository.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed)

        embed, view = build_repo_embed(repo_data, languages or {}, open_prs, open_issues, workflow_run, release)
        await respond(interaction, embed, view=view)

    @app_commands.command(name="dev", description="Developer dashboard: profile + repo, live")
    async def dev(self, interaction: discord.Interaction):
        if not github_config.username:
            return await send_config_error(interaction, "GITHUB_USERNAME")

        target_repo = choose_primary_repo()
        if not target_repo:
            return await send_config_error(interaction, "GITHUB_PRIMARY_REPO")

        await defer_interaction(interaction)
        user, repos, repo_data, commits, workflow_run, release, open_prs, open_issues = await asyncio.gather(
            github_api.fetch_user(github_config.username),
            github_api.fetch_user_repos(github_config.username),
            github_api.fetch_repo(target_repo),
            github_api.fetch_repo_commits(target_repo, per_page=8),
            github_api.fetch_latest_workflow_run(target_repo),
            github_api.fetch_latest_release(target_repo),
            github_api.search_open_pull_requests(target_repo),
            github_api.search_open_issues(target_repo),
        )
        if not user or not repo_data:
            embed = make_embed(
                "🧩 Dashboard unavailable",
                "I could not build the developer dashboard yet. Check your GitHub config.",
                color=Palette.WARNING,
            )
            brand_footer(embed)
            return await respond(interaction, embed)

        embed, view = build_dashboard_embed(
            user,
            repos,
            repo_data,
            commits or [],
            workflow_run,
            release,
            open_prs,
            open_issues,
        )
        await respond(interaction, embed, view=view)

    @app_commands.command(name="health", description="Project health report with score and hot files")
    @app_commands.describe(repo_name="owner/name (defaults to the primary repo)")
    async def health(self, interaction: discord.Interaction, repo_name: str | None = None):
        target_repo = choose_primary_repo(repo_name)
        if not target_repo:
            return await send_config_error(interaction, "GITHUB_PRIMARY_REPO")

        await defer_interaction(interaction)
        repo_data, commits, workflow_run, release, open_prs, open_issues = await asyncio.gather(
            github_api.fetch_repo(target_repo),
            github_api.fetch_repo_commits(target_repo, per_page=8),
            github_api.fetch_latest_workflow_run(target_repo),
            github_api.fetch_latest_release(target_repo),
            github_api.search_open_pull_requests(target_repo),
            github_api.search_open_issues(target_repo),
        )
        if not repo_data:
            embed = make_embed("🔍 Not found", "I could not find that repository.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed)

        branch_name = repo_data.get("default_branch", "main")
        branch_data = await github_api.fetch_branch(target_repo, branch_name)
        commit_details = await asyncio.gather(
            *(github_api.fetch_commit_detail(target_repo, commit["sha"]) for commit in (commits or [])[:5])
        )

        embed, view = build_health_embed(
            repo_data,
            commits or [],
            workflow_run,
            release,
            branch_data,
            open_prs,
            open_issues,
            extract_hot_files(commit_details),
        )
        await respond(interaction, embed, view=view)

    @app_commands.command(name="commits", description="The latest commits, beautifully listed")
    @app_commands.describe(repo_name="owner/name (defaults to the primary repo)", count="How many commits (1-10)")
    async def commits(
        self,
        interaction: discord.Interaction,
        repo_name: str | None = None,
        count: app_commands.Range[int, 1, 10] = 5,
    ):
        target_repo = choose_primary_repo(repo_name)
        if not target_repo:
            return await send_config_error(interaction, "GITHUB_PRIMARY_REPO")

        await defer_interaction(interaction)
        commits = await github_api.fetch_repo_commits(target_repo, per_page=count)
        if not commits:
            embed = make_embed("🔍 Not found", "No commits found for that repository.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed)

        urls = repo_to_urls(target_repo)
        lines = []
        for commit in commits:
            sha = commit.get("sha", "")[:7]
            commit_url = commit.get("html_url")
            message = truncate(first_line(commit["commit"]["message"]), 70)
            author = commit["commit"]["author"].get("name", "unknown")
            when = format_github_time(commit["commit"]["author"].get("date"))
            lines.append(f"[`{sha}`]({commit_url}) {message}\n└ by **{author}** {when}")

        embed = make_embed(f"📝 Latest commits • {target_repo}", "\n\n".join(lines), color=Palette.TEAL)
        brand_footer(embed, "Commit feed")
        await respond(
            interaction,
            embed,
            view=build_link_view([("All Commits", urls["commits"]), ("Repository", urls["repo"])]),
        )

    @app_commands.command(name="release", description="Details for the latest published release")
    @app_commands.describe(repo_name="owner/name (defaults to the primary repo)")
    async def release(self, interaction: discord.Interaction, repo_name: str | None = None):
        target_repo = choose_primary_repo(repo_name)
        if not target_repo:
            return await send_config_error(interaction, "GITHUB_PRIMARY_REPO")

        await defer_interaction(interaction)
        release_data = await github_api.fetch_latest_release(target_repo)
        if not release_data:
            embed = make_embed("📦 No release yet", f"`{target_repo}` has no published release.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed)

        embed = make_embed(
            f"🏷️ {release_data.get('name') or release_data.get('tag_name', 'Release')}",
            truncate(release_data.get("body") or "No release notes.", 300),
            color=Palette.GOLD,
            url=release_data.get("html_url"),
        )
        embed.add_field(
            name="Details",
            value=(
                f"Tag: `{release_data.get('tag_name', 'untagged')}`\n"
                f"Published: {format_github_time(release_data.get('published_at'))}\n"
                f"Pre-release: `{('Yes' if release_data.get('prerelease') else 'No')}`"
            ),
            inline=False,
        )
        brand_footer(embed, "Release radar")
        urls = repo_to_urls(target_repo)
        await respond(
            interaction,
            embed,
            view=build_link_view([("Release", release_data.get("html_url")), ("All Releases", urls["releases"])]),
        )

    @app_commands.command(name="ghwatch", description="GitHub watcher diagnostics")
    async def ghwatch(self, interaction: discord.Interaction):
        settings = get_guild_settings(interaction.guild_id)
        watch_channel_id = settings.get("github_event_channel") or github_config.event_channel_id
        update_channel_id = settings.get("update_channel") or github_config.update_channel_id
        watch_channel = f"<#{watch_channel_id}>" if watch_channel_id else "`Not set`"
        update_channel = f"<#{update_channel_id}>" if update_channel_id else "`Not set`"
        repos = ", ".join(f"`{repo}`" for repo in github_config.watch_repos) or "`No repos configured`"

        embed = make_embed(
            "📡 GitHub Watcher Status",
            "Current GitHub automation settings for this bot.",
            color=Palette.TEAL,
        )
        embed.add_field(name="Watch Repos", value=repos, inline=False)
        embed.add_field(
            name="Channels",
            value=f"Events: {watch_channel}\nCode updates: {update_channel}",
            inline=False,
        )
        embed.add_field(
            name="Runtime",
            value=(
                f"Polling every `{github_config.poll_seconds}` seconds\n"
                f"Watcher loop: `{('Running' if self.watch_github_activity.is_running() else 'Stopped')}`\n"
                f"GitHub token: `{('Configured' if github_config.token else 'Missing')}`\n"
                f"Primary repo: `{choose_primary_repo() or 'Not set'}`"
            ),
            inline=False,
        )
        brand_footer(embed, "Watcher diagnostics")
        await respond(interaction, embed)


async def setup(bot):
    await bot.add_cog(Developer(bot))
