"""🐙 Developer category — GitHub profile cards, repo dashboards, health and the live watcher."""

import asyncio
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.loop_guard import keep_running
from core.config import GITHUB_STATE_FILE, github_config
from core.github_api import github_api, valid_login
from core.github_commits import (
    branches_needing_a_read,
    merge_new_commits,
    remember_across_branches,
    store_shas,
    stored_shas,
)
from core.github_insights import extract_hot_files
from core.github_presenters import (
    build_dashboard_embed,
    build_health_embed,
    build_profile_embed,
    build_repo_embed,
    choose_primary_repo,
    repo_to_urls,
)
from core.github_watch_presenters import (
    build_commit_digest_embed,
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
from core.guild_config import resolve_configured_channels
from core.storage import get_guild_settings, load_json_file, save_json_file
from core.theme import Palette, brand_footer, make_embed
from core.updates import safe_send_embed
from core.utils import (
    build_link_view,
    defer_interaction,
    first_line,
    format_github_time,
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


async def build_watcher_embed(repo_name, event):
    event_type = event.get("type")
    payload = event.get("payload", {})
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

        return build_push_watcher_embed(repo_name, event, commits, changed_files)

    if event_type == "PullRequestEvent":
        # The feed hands over a five-key stub; everything readable comes from
        # the fetch below.
        pull_request = await hydrate_pull_request(repo_name, payload.get("pull_request", {}))
        return build_pull_request_watcher_embed(repo_name, event, pull_request)

    if event_type == "IssuesEvent":
        return build_issue_watcher_embed(repo_name, event)

    if event_type == "ReleaseEvent":
        return build_release_watcher_embed(repo_name, event)

    return None, None


def configured_repos():
    """Every repository this instance is set up to talk about, lowercased."""
    names = list(github_config.watch_repos or [])
    if github_config.primary_repo:
        names.append(github_config.primary_repo)
    return {name.strip().strip("/").lower() for name in names if name}


async def reject_repo(interaction, target_repo):
    """Refuse a repository this instance was not configured for. True when refused.

    The bot's GitHub session carries the host's token, and `/repos/{owner}/{name}`
    answers for a private repository whenever that token can see one. Without
    this, any member could name someone's private repo and have its commits,
    release notes and health card rendered into a public channel under the
    host's credentials. Public repositories are no safer to allow, because the
    same request is what spends the host's rate limit.

    The allow-list is the configured repos, which is what every one of these
    commands already defaults to - naming one explicitly is a convenience, not
    a separate feature.
    """
    allowed = configured_repos()
    if target_repo and str(target_repo).strip().strip("/").lower() in allowed:
        return False
    listed = ", ".join(f"`{name}`" for name in sorted(allowed)) or "`none configured`"
    embed = make_embed(
        "🔒 Not a tracked repository",
        "NovaGuard only reports on the repositories it is configured to watch, "
        "because these lookups use the host's GitHub credentials.\n\n"
        f"Tracked here: {listed}",
        color=Palette.WARNING,
    )
    brand_footer(embed)
    await respond(interaction, embed, ephemeral=True)
    return True


async def reject_login(interaction, username):
    """Refuse anything that cannot be a real GitHub login. True when refused."""
    if valid_login(username):
        return False
    embed = make_embed(
        "🔍 Not a GitHub username",
        "GitHub usernames are up to 39 letters, digits and hyphens.",
        color=Palette.WARNING,
    )
    brand_footer(embed)
    await respond(interaction, embed, ephemeral=True)
    return True


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
        if await reject_login(interaction, target_username):
            return
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
        if await reject_repo(interaction, target_repo):
            return
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
        if await reject_repo(interaction, target_repo):
            return
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
        if await reject_repo(interaction, target_repo):
            return
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
        if await reject_repo(interaction, target_repo):
            return
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
    # Answers with the host's own configuration - which repositories are
    # watched (private names included), which channels the owner routes
    # events to, the poll interval, whether a token is set. That is the
    # operator's setup, not this guild's, so it takes Manage Server and is
    # answered privately rather than posted for everyone to read.
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
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
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Developer(bot))
