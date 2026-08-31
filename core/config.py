"""Environment configuration and shared constants for the bot."""

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPDATE_STATE_FILE = BASE_DIR / ".update_state.json"
GITHUB_STATE_FILE = BASE_DIR / ".github_state.json"

# Internal runtime/API generation. This is deliberately not the public product
# version: the public release is derived from the update history in
# core.release_versions and advances automatically with decimal rollover
# (2.8, 2.9, 3.0, 3.1, ...).
BOT_RUNTIME_VERSION = "3.0.0"
# Backwards-compatible alias for older integrations. New user-facing code must
# use current_project_release() instead of displaying this value.
BOT_VERSION = BOT_RUNTIME_VERSION
BOT_CODENAME = "Nova"
STREAM_URL = "https://www.twitch.tv/the8bitdrummer"

DEFAULT_STREAM_STATUSES = [
    "Watching late-night commits",
    "I'll never forget that July",
    "/help • the slash era",
    "Shipping updates automatically",
]
DEFAULT_STREAM_STATUS_INTERVAL_SECONDS = 15


# Names where .env disagreed with an inherited environment variable and won.
# Empty in every ordinary start; non-empty means somebody edited .env and the
# process was carrying a different value, which config_check reports.
DOTENV_OVERRIDES: list[str] = []


def load_dotenv_if_present():
    """Load .env, and let it win over whatever the process inherited.

    This used to be `os.environ.setdefault`, so an inherited variable beat the
    file. That is the usual convention and it was the wrong one here, because
    of how this bot is actually run: pm2 captures the environment at
    `pm2 start` and re-injects that same copy on every `pm2 restart` unless it
    is given `--update-env`. SETUP.md said to rotate a secret in .env and then
    `pm2 restart`, which meant the rotation appeared to succeed and the process
    kept using the old TOKEN, client secret or WEB_TOKEN_KEY - with no error,
    no warning, and a compromised credential still live. A rotation that looks
    like it worked is the worst possible failure for one.

    So .env is the source of truth when it exists. It is the file SETUP.md
    tells operators to edit and the one production_check checks the permissions
    of; nothing else should quietly outrank it.
    """
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return

    DOTENV_OVERRIDES.clear()
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        existing = os.environ.get(key)
        if existing is not None and existing != value:
            # Recorded, never logged with the value attached: these are secrets.
            DOTENV_OVERRIDES.append(key)
        os.environ[key] = value


load_dotenv_if_present()


def env_int(name, default=None):
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def parse_csv_env(name):
    raw_value = os.getenv(name, "")
    return [item.strip().strip("/") for item in raw_value.split(",") if item.strip()]


def parse_stream_statuses():
    raw_value = os.getenv("STREAM_STATUSES")
    if raw_value:
        statuses = [item.strip() for item in raw_value.split("|") if item.strip()]
        if statuses:
            return statuses
    return list(DEFAULT_STREAM_STATUSES)


def parse_stream_status_interval():
    value = env_int("STREAM_STATUS_INTERVAL_SECONDS", DEFAULT_STREAM_STATUS_INTERVAL_SECONDS)
    if value is None:
        return DEFAULT_STREAM_STATUS_INTERVAL_SECONDS
    return max(10, value)


@dataclass
class GitHubConfig:
    username: str | None
    primary_repo: str | None
    watch_repos: list[str]
    token: str | None
    event_channel_id: int | None
    update_channel_id: int | None
    poll_seconds: int
    brand_name: str
    uptime_url: str | None


github_config = GitHubConfig(
    username=os.getenv("GITHUB_USERNAME"),
    primary_repo=os.getenv("GITHUB_PRIMARY_REPO"),
    watch_repos=parse_csv_env("GITHUB_WATCH_REPOS"),
    token=os.getenv("GITHUB_TOKEN"),
    event_channel_id=env_int("GITHUB_EVENT_CHANNEL_ID"),
    update_channel_id=env_int("UPDATE_CHANNEL_ID"),
    poll_seconds=env_int("GITHUB_POLL_SECONDS", 300),
    brand_name=os.getenv("BOT_BRAND", "Developed by VIK & CloudMedia"),
    uptime_url=os.getenv("UPTIME_URL"),
)

if not github_config.watch_repos and github_config.primary_repo:
    github_config.watch_repos = [github_config.primary_repo]
if not github_config.event_channel_id and github_config.update_channel_id:
    github_config.event_channel_id = github_config.update_channel_id

# Optional main server ID for defaults; use /resync scope:server for an immediate command update.
GUILD_ID = env_int("GUILD_ID")
ERROR_LOG_CHANNEL_ID = env_int("ERROR_LOG_CHANNEL_ID")

stream_statuses = parse_stream_statuses()
stream_status_interval_seconds = parse_stream_status_interval()
