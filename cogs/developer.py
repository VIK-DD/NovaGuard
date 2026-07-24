"""🐙 Developer category — GitHub profile cards, repo dashboards, health and the live watcher."""

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.config import GITHUB_STATE_FILE, github_config
from core.github_api import github_api
from core.guild_config import resolve_configured_channels
from core.storage import get_guild_settings, load_json_file, save_json_file
from core.theme import Palette, brand_footer, make_embed, pick_embed_color
from core.updates import safe_send_embed
from core.utils import (
    build_link_view,
    defer_interaction,
    first_line,
    format_github_time,
    humanize_number,
    parse_github_datetime,
    respond,
    truncate,
)

WATCHED_EVENT_TYPES = {"PushEvent", "PullRequestEvent", "IssuesEvent", "ReleaseEvent"}


def load_github_state():
    return load_json_file(GITHUB_STATE_FILE, {"events": {}})


def save_github_state(state):
    save_json_file(GITHUB_STATE_FILE, state)


def choose_primary_repo(repo_name=None):
    target_repo = (repo_name or github_config.primary_repo or "").strip().strip("/")
    if target_repo:
        return target_repo
    if github_config.watch_repos:
        return github_config.watch_repos[0]
    return None


def repo_to_urls(full_name):
    base_url = f"https://github.com/{full_name}"
    return {
        "repo": base_url,
        "commits": f"{base_url}/commits",
        "pulls": f"{base_url}/pulls",
        "issues": f"{base_url}/issues",
        "releases": f"{base_url}/releases",
        "actions": f"{base_url}/actions",
    }


def push_commit_message(commit):
    message = (
        commit.get("message")
        or commit.get("commit", {}).get("message", "")
    )
    return truncate(first_line(message), 70)


def push_commit_sha(commit):
    return (commit.get("sha") or "")[:7] or "unknown"


def summarize_changed_files(files):
    if not files:
        return "No file details available."
    top_files = [f"`{item.get('filename', 'unknown')}`" for item in files[:3]]
    remaining = len(files) - len(top_files)
    summary = ", ".join(top_files)
    if remaining > 0:
        summary += f" +{remaining} more"
    return summary


def build_languages_text(languages):
    if not languages:
        return "No language data yet."

    total = sum(languages.values()) or 1
    top_languages = sorted(languages.items(), key=lambda item: item[1], reverse=True)[:4]
    lines = []
    for name, size in top_languages:
        percent = round((size / total) * 100)
        filled = max(round(percent / 10), 1)
        bar = "▰" * filled + "▱" * (10 - filled)
        lines.append(f"{bar} `{percent:>3}%` {name}")
    return "\n".join(lines)


def detect_top_language(repos):
    counter = Counter(repo["language"] for repo in repos if repo.get("language"))
    return counter.most_common(1)[0][0] if counter else None


def workflow_status_text(workflow_run):
    if not workflow_run:
        return "No workflow runs found."

    status = workflow_run.get("status", "unknown")
    conclusion = workflow_run.get("conclusion")
    workflow_name = workflow_run.get("name", "Latest workflow")

    if status != "completed":
        return f"{workflow_name}: {status.title()}"
    if not conclusion:
        return f"{workflow_name}: Completed"
    return f"{workflow_name}: {conclusion.replace('_', ' ').title()}"


def release_status_text(release):
    if not release:
        return "No public release yet."
    tag_name = release.get("tag_name", "untagged")
    published_at = format_github_time(release.get("published_at"))
    return f"{tag_name} published {published_at}"


def summarize_recent_work(commits):
    if not commits:
        return "No recent commits found."

    messages = [first_line(commit["commit"]["message"], "internal work").lower() for commit in commits]
    categories = Counter()
    for message in messages:
        if any(word in message for word in ("fix", "bug", "patch", "hotfix")):
            categories["Fixes"] += 1
        elif any(word in message for word in ("feat", "feature", "add", "implement")):
            categories["Features"] += 1
        elif any(word in message for word in ("doc", "readme")):
            categories["Docs"] += 1
        else:
            categories["Chores"] += 1

    if not categories:
        return "Mixed internal work."
    return " | ".join(f"{label}: {count}" for label, count in categories.items())


def compute_health_score(commits_last_week, open_prs, branch_data, workflow_run, release):
    score = 100
    if commits_last_week == 0:
        score -= 20
    if open_prs > 15:
        score -= 10
    if branch_data and not branch_data.get("protected"):
        score -= 10
    if workflow_run and workflow_run.get("status") == "completed" and workflow_run.get("conclusion") not in {
        None,
        "success",
    }:
        score -= 25
    if not release:
        score -= 5

    score = max(score, 10)
    if score >= 90:
        label = "🌟 Excellent"
    elif score >= 75:
        label = "💪 Strong"
    elif score >= 60:
        label = "🛡️ Stable"
    else:
        label = "🚨 Needs Attention"
    return score, label


def extract_hot_files(commit_details):
    counter = Counter()
    for commit in commit_details:
        if not commit:
            continue
        for file_info in commit.get("files", []):
            counter[file_info.get("filename", "unknown")] += 1

    if not counter:
        return "No file change data yet."

    top_files = counter.most_common(3)
    return "\n".join(f"`{file_name}` touched {count}x" for file_name, count in top_files)


def build_profile_embed(user, repos):
    total_stars = sum(repo.get("stargazers_count", 0) for repo in repos)
    top_repo = max(repos, key=lambda repo: repo.get("stargazers_count", 0), default=None)
    latest_repo = max(repos, key=lambda repo: repo.get("pushed_at") or "", default=None)
    top_language = detect_top_language(repos)
    primary_repo = choose_primary_repo()

    embed = discord.Embed(
        title=f"👤 {user['login']} — GitHub Profile",
        description=truncate(user.get("bio") or "Building cool things, one repo at a time.", 180),
        color=pick_embed_color(top_language),
        url=user.get("html_url"),
    )
    embed.set_thumbnail(url=user.get("avatar_url"))
    embed.add_field(
        name="📊 Profile Stats",
        value=(
            f"Repos: `{humanize_number(user.get('public_repos', 0))}`\n"
            f"Followers: `{humanize_number(user.get('followers', 0))}`\n"
            f"Following: `{humanize_number(user.get('following', 0))}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="✨ Highlights",
        value=(
            f"Total stars: `{humanize_number(total_stars)}`\n"
            f"Top repo: `{top_repo['name'] if top_repo else 'N/A'}`\n"
            f"Top language: `{top_language or 'Unknown'}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="🕒 Recent Activity",
        value=(
            f"Latest push: {format_github_time(latest_repo.get('pushed_at') if latest_repo else None)}\n"
            f"Focus repo: `{primary_repo or 'Set GITHUB_PRIMARY_REPO'}`\n"
            f"Location: `{user.get('location') or 'Not set'}`"
        ),
        inline=False,
    )
    embed.set_footer(text=f"{github_config.brand_name} • GitHub profile card")

    buttons = [
        ("Profile", user.get("html_url")),
        ("Followers", f"{user.get('html_url')}?tab=followers"),
        ("Following", f"{user.get('html_url')}?tab=following"),
    ]
    if primary_repo:
        buttons.insert(1, ("Primary Repo", f"https://github.com/{primary_repo}"))
    return embed, build_link_view(buttons)


def build_repo_embed(repo, languages, open_prs, open_issues, workflow_run, release):
    language_name = repo.get("language")
    urls = repo_to_urls(repo["full_name"])
    description_parts = [truncate(repo.get("description") or "No repository description set.", 180)]
    if repo.get("topics"):
        description_parts.append("Topics: " + ", ".join(f"`{topic}`" for topic in repo["topics"][:4]))

    embed = discord.Embed(
        title=f"📦 {repo['full_name']} — Live Status",
        description="\n".join(description_parts),
        color=pick_embed_color(language_name),
        url=repo.get("html_url"),
    )
    embed.add_field(
        name="⭐ Repository Stats",
        value=(
            f"Stars: `{humanize_number(repo.get('stargazers_count', 0))}`\n"
            f"Forks: `{humanize_number(repo.get('forks_count', 0))}`\n"
            f"Watchers: `{humanize_number(repo.get('subscribers_count', 0))}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="🚦 Current Status",
        value=(
            f"Branch: `{repo.get('default_branch', 'main')}`\n"
            f"Open PRs: `{humanize_number(open_prs)}`\n"
            f"Open Issues: `{humanize_number(open_issues)}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="📸 Code Snapshot",
        value=(
            f"Primary language: `{language_name or 'Unknown'}`\n"
            f"Pushed: {format_github_time(repo.get('pushed_at'))}\n"
            f"Created: {format_github_time(repo.get('created_at'))}"
        ),
        inline=False,
    )
    embed.add_field(name="🧬 Languages", value=build_languages_text(languages), inline=True)
    embed.add_field(
        name="⚙️ Automation",
        value=(
            f"CI: `{workflow_status_text(workflow_run)}`\n"
            f"Release: `{release.get('tag_name', 'None') if release else 'None'}`\n"
            f"Visibility: `{('Private' if repo.get('private') else 'Public')}`"
        ),
        inline=True,
    )
    embed.set_footer(text=f"{github_config.brand_name} • Repo control center")

    return embed, build_link_view(
        [
            ("Repository", urls["repo"]),
            ("Commits", urls["commits"]),
            ("Pulls", urls["pulls"]),
            ("Issues", urls["issues"]),
            ("Releases", urls["releases"]),
        ]
    )


def build_dashboard_embed(user, repos, repo, commits, workflow_run, release, open_prs, open_issues):
    total_stars = sum(item.get("stargazers_count", 0) for item in repos)
    top_language = detect_top_language(repos)
    latest_commit = commits[0] if commits else None
    latest_message = truncate(first_line(latest_commit["commit"]["message"]), 90) if latest_commit else "No commit data."
    recent_commit_count = sum(
        1
        for item in commits
        if parse_github_datetime(item["commit"]["author"]["date"]) >= datetime.now(UTC) - timedelta(days=7)
    )

    embed = discord.Embed(
        title="🚀 Developer Dashboard",
        description=f"A live GitHub snapshot for `{user['login']}` and `{repo['full_name']}`.",
        color=pick_embed_color(top_language),
    )
    embed.set_thumbnail(url=user.get("avatar_url"))
    embed.add_field(
        name="💓 Profile Pulse",
        value=(
            f"Followers: `{humanize_number(user.get('followers', 0))}`\n"
            f"Public repos: `{humanize_number(user.get('public_repos', 0))}`\n"
            f"Total stars: `{humanize_number(total_stars)}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="📈 Repo Heartbeat",
        value=(
            f"Open PRs: `{humanize_number(open_prs)}`\n"
            f"Open Issues: `{humanize_number(open_issues)}`\n"
            f"7-day commits: `{humanize_number(recent_commit_count)}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="🏗️ Release + CI",
        value=(
            f"{workflow_status_text(workflow_run)}\n"
            f"{release_status_text(release)}"
        ),
        inline=False,
    )
    embed.add_field(
        name="📝 Latest Commit",
        value=(
            f"`{latest_commit['sha'][:7]}` {latest_message}\n"
            f"Committed {format_github_time(latest_commit['commit']['author']['date'])}"
            if latest_commit
            else "No commit data found."
        ),
        inline=False,
    )
    if github_config.uptime_url:
        embed.add_field(name="🛰️ Ops Link", value=f"[Uptime Dashboard]({github_config.uptime_url})", inline=False)
    embed.set_footer(text=f"{github_config.brand_name} • Developer dashboard")

    repo_urls = repo_to_urls(repo["full_name"])
    return embed, build_link_view(
        [
            ("Profile", user.get("html_url")),
            ("Repository", repo_urls["repo"]),
            ("Actions", repo_urls["actions"]),
            ("Releases", repo_urls["releases"]),
            ("Commits", repo_urls["commits"]),
        ]
    )


def build_health_embed(repo, commits, workflow_run, release, branch_data, open_prs, open_issues, hot_files_text):
    week_ago = datetime.now(UTC) - timedelta(days=7)
    commits_last_week = sum(
        1
        for commit in commits
        if parse_github_datetime(commit["commit"]["author"]["date"]) >= week_ago
    )
    score, label = compute_health_score(commits_last_week, open_prs, branch_data, workflow_run, release)

    score_blocks = round(score / 10)
    score_bar = "🟩" * score_blocks + "⬛" * (10 - score_blocks)
    embed = discord.Embed(
        title=f"🩺 {repo['full_name']} — Project Health",
        description=f"{score_bar}\n# {score}/100 • {label}",
        color=pick_embed_color(repo.get("language"), Palette.SUCCESS if score >= 75 else Palette.ORANGE),
    )
    embed.add_field(
        name="🚚 Delivery Pulse",
        value=(
            f"7-day commits: `{humanize_number(commits_last_week)}`\n"
            f"Open PRs: `{humanize_number(open_prs)}`\n"
            f"Open Issues: `{humanize_number(open_issues)}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="🧩 Work Mix",
        value=summarize_recent_work(commits[:8]),
        inline=True,
    )
    embed.add_field(
        name="🛠️ Pipeline",
        value=(
            f"CI: `{workflow_status_text(workflow_run)}`\n"
            f"Branch protection: `{('On' if branch_data and branch_data.get('protected') else 'Off')}`\n"
            f"Release: `{release.get('tag_name', 'None') if release else 'None'}`"
        ),
        inline=False,
    )
    embed.add_field(name="🔥 Hot Files", value=hot_files_text, inline=False)
    embed.set_footer(text=f"{github_config.brand_name} • Project health report")

    repo_urls = repo_to_urls(repo["full_name"])
    return embed, build_link_view(
        [
            ("Repository", repo_urls["repo"]),
            ("Issues", repo_urls["issues"]),
            ("Pulls", repo_urls["pulls"]),
            ("Actions", repo_urls["actions"]),
        ]
    )


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
            comparison = await github_api.fetch_compare(repo_name, base_sha, head_sha)
            if comparison:
                commits = comparison.get("commits", [])
                changed_files = comparison.get("files", [])

        if not commits and payload_commits:
            commits = payload_commits

        if not commits:
            fallback_count = min(max(payload.get("size", 1), 1), 5)
            commits = await github_api.fetch_repo_commits(
                repo_name,
                per_page=fallback_count,
                sha=payload.get("ref", "refs/heads/main").split("/")[-1],
            ) or []

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
        pull_request = payload.get("pull_request", {})
        action = payload.get("action", "updated").replace("_", " ")
        merged = pull_request.get("merged")
        color = Palette.SUCCESS if merged else Palette.INFO
        state = "Merged" if merged else pull_request.get("state", "open").title()

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

    async def cog_load(self):
        # light per-user cooldown on every command here — they all hit the
        # GitHub API, so this caps abuse against our shared token quota
        for command in self.walk_app_commands():
            app_commands.checks.cooldown(1, 6.0)(command)
        if github_config.watch_repos:
            self.watch_github_activity.start()

    async def cog_unload(self):
        self.watch_github_activity.cancel()

    @tasks.loop(seconds=github_config.poll_seconds)
    async def watch_github_activity(self):
        if not github_config.watch_repos:
            return

        state = await asyncio.to_thread(load_github_state)
        event_state = state.setdefault("events", {})
        channels = await resolve_configured_channels(self.bot, "github_event_channel", github_config.event_channel_id)

        for repo_name in github_config.watch_repos:
            try:
                events = await github_api.fetch_repo_events(repo_name, per_page=10)
            except RuntimeError as error:
                print(f"GitHub watcher error for {repo_name}: {error}")
                continue
            except (asyncio.TimeoutError, aiohttp.ClientError) as error:
                print(f"GitHub watcher skipped {repo_name}: temporary network issue ({error})")
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
