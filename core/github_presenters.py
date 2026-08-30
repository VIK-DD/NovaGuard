"""Discord embeds for GitHub profile, repository, dashboard and health views."""

from datetime import UTC, datetime, timedelta

import discord

from .config import github_config
from .github_insights import (
    build_languages_text,
    compute_health_score,
    detect_top_language,
    release_status_text,
    summarize_recent_work,
    workflow_status_text,
)
from .theme import Palette, pick_embed_color
from .utils import (
    clamp,
    build_link_view,
    first_line,
    format_github_time,
    humanize_number,
    parse_github_datetime,
    truncate,
)


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
            f"Release: `{clamp(release.get('tag_name', 'None'), 100) if release else 'None'}`\n"
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
        value=f"{workflow_status_text(workflow_run)}\n{release_status_text(release)}",
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
    embed.add_field(name="🧩 Work Mix", value=summarize_recent_work(commits[:8]), inline=True)
    embed.add_field(
        name="🛠️ Pipeline",
        value=(
            f"CI: `{workflow_status_text(workflow_run)}`\n"
            f"Branch protection: `{('On' if branch_data and branch_data.get('protected') else 'Off')}`\n"
            f"Release: `{clamp(release.get('tag_name', 'None'), 100) if release else 'None'}`"
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
