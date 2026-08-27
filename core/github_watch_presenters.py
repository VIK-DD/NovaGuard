"""Discord embeds for GitHub commit digests and watcher events."""

from datetime import UTC, datetime

import discord

from .github_insights import summarize_changed_files
from .github_presenters import repo_to_urls
from .theme import Palette, brand_footer
from .utils import build_link_view, first_line, parse_github_datetime, truncate


_ACTION_STATES = {"opened": "Open", "reopened": "Open", "closed": "Closed"}


def pull_request_state(pull_request, action):
    """Return only a pull-request state supported by the available data."""
    if pull_request.get("merged"):
        return "Merged"
    state = pull_request.get("state")
    if state:
        return str(state).title()
    return _ACTION_STATES.get(action, "Unknown")


def push_commit_message(commit):
    message = commit.get("message") or commit.get("commit", {}).get("message", "")
    return truncate(first_line(message), 70)


def push_commit_sha(commit):
    return (commit.get("sha") or "")[:7] or "unknown"


def commit_author_name(commit):
    account = commit.get("author") or {}
    if account.get("login"):
        return account["login"]
    return (commit.get("commit", {}).get("author") or {}).get("name") or "someone"


def build_commit_digest_embed(repo_name, branch_name, commits):
    """Build one card for a batch of commits on one branch."""
    urls = repo_to_urls(repo_name)
    lines = []
    for entry in reversed(commits):
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
    """Build a card per branch, preserving the branch traversal order."""
    grouped = {}
    for branch_name, commit in branch_commits:
        grouped.setdefault(branch_name, []).append(commit)
    return [
        build_commit_digest_embed(repo_name, branch_name, commits)
        for branch_name, commits in grouped.items()
    ]


def _event_context(repo_name, event):
    actor = event.get("actor", {})
    actor_name = actor.get("login", "GitHub user")
    actor_url = f"https://github.com/{actor_name}" if actor_name else None
    timestamp = parse_github_datetime(event.get("created_at")) or datetime.now(UTC)
    return event.get("payload", {}), actor_name, actor_url, repo_to_urls(repo_name), timestamp


def build_push_watcher_embed(repo_name, event, commits, changed_files):
    payload, actor_name, actor_url, repo_urls, timestamp = _event_context(repo_name, event)
    base_sha = payload.get("before")
    head_sha = payload.get("head")
    branch_name = payload.get("ref", "refs/heads/main").split("/")[-1]

    commit_lines = [
        f"`{push_commit_sha(commit)}` {push_commit_message(commit)}"
        for commit in commits[-3:]
    ]
    commit_lines.reverse()
    if len(commits) > 3:
        commit_lines.append(f"...and {len(commits) - 3} more commit(s)")

    compare_url = (
        f"{repo_urls['repo']}/compare/{base_sha}...{head_sha}"
        if base_sha and head_sha
        else None
    )
    embed = discord.Embed(
        title=f"📤 Push update in {repo_name}",
        description=f"{actor_name} pushed to `{branch_name}`.",
        color=discord.Color.green(),
        timestamp=timestamp,
    )
    embed.add_field(name="Commits", value="\n".join(commit_lines) or "No commit details.", inline=False)
    embed.add_field(name="Files Changed", value=summarize_changed_files(changed_files), inline=False)
    embed.add_field(name="Branch", value=f"`{branch_name}`", inline=True)
    embed.add_field(
        name="Pushed By",
        value=f"[{actor_name}]({actor_url})" if actor_url else actor_name,
        inline=True,
    )
    embed.set_footer(text="GitHub watcher • Push event")
    return embed, build_link_view(
        [
            ("Repository", repo_urls["repo"]),
            ("Compare", compare_url),
            ("Latest Commit", f"{repo_urls['repo']}/commit/{head_sha}" if head_sha else None),
        ]
    )


def build_pull_request_watcher_embed(repo_name, event, pull_request):
    payload, _actor_name, _actor_url, repo_urls, timestamp = _event_context(repo_name, event)
    raw_action = payload.get("action", "updated")
    action = raw_action.replace("_", " ")
    color = Palette.SUCCESS if pull_request.get("merged") else Palette.INFO
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
    embed.add_field(name="Summary", value=truncate(pull_request.get("body"), 240), inline=False)
    embed.set_footer(text="GitHub watcher • Pull request event")
    return embed, build_link_view(
        [
            ("Repository", repo_urls["repo"]),
            ("Pull Request", pull_request.get("html_url")),
            (
                "Files",
                f"{pull_request.get('html_url')}/files" if pull_request.get("html_url") else None,
            ),
        ]
    )


def build_issue_watcher_embed(repo_name, event):
    payload, actor_name, actor_url, repo_urls, timestamp = _event_context(repo_name, event)
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


def build_release_watcher_embed(repo_name, event):
    payload, _actor_name, _actor_url, repo_urls, timestamp = _event_context(repo_name, event)
    release = payload.get("release", {})
    action = payload.get("action", "published").replace("_", " ")
    embed = discord.Embed(
        title=f"🏷️ Release {action} in {repo_name}",
        description=truncate(
            release.get("body") or release.get("name") or "A new release is now live.",
            220,
        ),
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
