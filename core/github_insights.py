"""Pure summaries and health signals derived from GitHub API payloads."""

from collections import Counter

from .utils import first_line, format_github_time


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
