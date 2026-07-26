"""Build the frozen updates archive from the Discord #updates channel.

Run once. Reads every "Bot Update Deployed" embed, parses it into the feed entry
shape, and writes core/updates_archive.json oldest-first. Restart notices and
timeline recaps are ignored. Read-only against Discord; never prints the token.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
# `data/` is gitignored — it holds the live SQLite database — so the archive lives
# beside the module that reads it and ships with an ordinary pull.
ARCHIVE_PATH = BASE_DIR / "core" / "updates_archive.json"
DISCORD_API = "https://discord.com/api/v10"
# Discord's edge answers 403 to the default urllib agent before the API sees the
# token, so identify the client the way its docs require.
USER_AGENT = "DiscordBot (https://novaguard.fun, 3.0.0)"

DEPLOY_TITLE = re.compile(r"bot update deployed", re.I)
FIELD_ALIASES = {
    "release highlights": "highlights",
    "what changed": "highlights",
    "command & project changes": "changes",
    "code stats": "stats",
    "build": "build",
}
STAT_PATTERNS = {
    "added_lines": re.compile(r"\+\s*(\d+)\s*lines?\s+added", re.I),
    "removed_lines": re.compile(r"-\s*(\d+)\s*lines?\s+removed", re.I),
    "changed_files": re.compile(r"~\s*(\d+)\s*tracked\s+files?\s+changed", re.I),
}
# Highlight bullets are written as "• 🚀 Setup wizard upgraded …" — the marker,
# then a category emoji. The page carries no emoji, so both are stripped and the
# sentence stands on its own.
LEADING_EMOJI = re.compile(
    r"^(?:[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]+\s*)+"
)
BUILD_PATTERN = re.compile(r"#(\d+)")
VERSION_PATTERN = re.compile(r"v(\d+\.\d+\.\d+)")
CODENAME_PATTERN = re.compile(r'"([^"]+)"')


def normalize_field_name(name):
    """Fold a field name to a comparable key, dropping the decorative emoji."""
    lowered = (name or "").lower()
    stripped = re.sub(r"[^a-z0-9&\s]", "", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def parse_bullets(value):
    """Split a field value into bullet lines, without markers or code fences."""
    bullets = []
    for raw in (value or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        line = line.lstrip("•-* \t").strip()
        line = LEADING_EMOJI.sub("", line).strip()
        if line:
            bullets.append(line)
    return bullets


def parse_deploy_embed(embed, created_at, fallback_build):
    """Turn one deploy embed into a feed entry, or None if it is not one."""
    if not DEPLOY_TITLE.search(embed.get("title") or ""):
        return None

    entry = {"build": fallback_build, "created_at": created_at}
    highlights = []
    changes = []

    for field in embed.get("fields") or []:
        key = FIELD_ALIASES.get(normalize_field_name(field.get("name")))
        value = field.get("value") or ""
        if key == "highlights":
            highlights.extend(parse_bullets(value))
        elif key == "changes":
            changes.extend(parse_bullets(value))
        elif key == "stats":
            for stat_key, pattern in STAT_PATTERNS.items():
                match = pattern.search(value)
                if match:
                    entry[stat_key] = int(match.group(1))
        elif key == "build":
            build_match = BUILD_PATTERN.search(value)
            if build_match:
                entry["build"] = int(build_match.group(1))
            version_match = VERSION_PATTERN.search(value)
            if version_match:
                entry["version"] = version_match.group(1)
            codename_match = CODENAME_PATTERN.search(value)
            if codename_match:
                entry["codename"] = codename_match.group(1)

    if highlights:
        entry["highlights"] = highlights
    if changes:
        entry["changes"] = changes

    has_stats = any(stat_key in entry for stat_key in STAT_PATTERNS)
    if not highlights and not changes and not has_stats:
        return None
    return entry


def load_env(path):
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def discord_get(url, token):
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_channel_messages(channel_id, token):
    messages = []
    before = None
    while True:
        url = f"{DISCORD_API}/channels/{channel_id}/messages?limit=100"
        if before:
            url += f"&before={before}"
        batch = discord_get(url, token)
        if not batch:
            break
        messages.extend(batch)
        before = batch[-1]["id"]
        if len(batch) < 100:
            break
    return messages


def build_archive(messages):
    """Parse newest-first Discord messages into an oldest-first archive."""
    entries = []
    for message in reversed(messages):
        for embed in message.get("embeds") or []:
            entry = parse_deploy_embed(embed, message.get("timestamp"), len(entries) + 1)
            if entry:
                entries.append(entry)
    return entries


def main():
    env = load_env(BASE_DIR / ".env")
    token = os.environ.get("TOKEN") or env.get("TOKEN")
    channel_id = os.environ.get("UPDATE_CHANNEL_ID") or env.get("UPDATE_CHANNEL_ID")
    if not token or not channel_id:
        print("TOKEN and UPDATE_CHANNEL_ID must be set in the environment or .env")
        return 1

    try:
        messages = fetch_channel_messages(channel_id, token)
    except urllib.error.HTTPError as error:
        print(f"Discord request failed: HTTP {error.code} - {error.reason}")
        return 1

    entries = build_archive(messages)
    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(entries)} releases to {ARCHIVE_PATH.relative_to(BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
