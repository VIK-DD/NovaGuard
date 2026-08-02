"""Automatic update changelog engine.

Fingerprints every tracked project file and generates a human-friendly
changelog embed whenever the deployed code changes. Now understands the
modular layout (core/ + cogs/) and slash command decorators.
"""

import ast
import asyncio
import difflib
import hashlib
from datetime import UTC, datetime

import aiohttp
import discord

from .config import BASE_DIR, BOT_CODENAME, BOT_VERSION, UPDATE_STATE_FILE, github_config
from .guild_config import resolve_configured_channels
from .storage import load_json_file, save_json_file
from .theme import Palette
from .update_feed import MAX_LIMIT as UPDATE_FEED_MAX_LIMIT
from .update_feed import merged_update_feed
from .utils import build_link_view, parse_github_datetime

COMMAND_DECORATORS = {"command", "hybrid_command", "context_menu"}
STATUS_VARIABLE_NAMES = {"stream_statuses", "DEFAULT_STREAM_STATUSES"}

# Human names for the tracked source files, so release notes can say
# "improvements to voice session reports" instead of "`cogs/voice.py`".
# Wording only — nothing here feeds the fingerprint or announce logic.
FRIENDLY_AREAS = {
    "bot.py": "the bot's core",
    ".env.example": "the setup guides",
    "SETUP.md": "the setup guides",
    "cogs/ai.py": "the /ask AI assistant",
    "cogs/automod.py": "the AutoMod filters",
    "cogs/developer.py": "the GitHub cards & watcher",
    "cogs/economy.py": "coins & economy games",
    "cogs/fun.py": "fun & games",
    "cogs/giveaways.py": "giveaways",
    "cogs/levels.py": "levels & XP",
    "cogs/logs.py": "server logs",
    "cogs/moderation.py": "the moderation tools",
    "cogs/roles.py": "role panels",
    "cogs/setup.py": "the setup wizard",
    "cogs/system.py": "the health & status tools",
    "cogs/tickets.py": "support tickets",
    "cogs/utility.py": "the utility tools",
    "cogs/voice.py": "voice session reports",
    "cogs/welcome.py": "welcome messages",
    "core/automod_settings.py": "the AutoMod filters",
    "core/backups.py": "the backup system",
    "core/config.py": "the bot's configuration",
    "core/database.py": "data storage",
    "core/error_digest.py": "error alerts",
    "core/github_api.py": "the GitHub connection",
    "core/guild_config.py": "server configuration",
    "core/levels_settings.py": "levels & XP",
    "core/maintenance.py": "maintenance mode",
    "core/storage.py": "data storage",
    "core/theme.py": "the visual style",
    "core/update_feed.py": "the public update feed",
    "core/updates.py": "update announcements",
    "core/utils.py": "the bot's core",
    "core/webserver.py": "the web dashboard",
}


def humanize_areas(file_names, limit=4):
    """Turn tracked file paths into a readable list of feature areas."""
    areas = []
    for file_name in sorted(file_names):
        label = FRIENDLY_AREAS.get(file_name)
        if label is None:
            stem = file_name.rsplit("/", 1)[-1]
            label = stem.removesuffix(".py").replace("_", " ")
        if label not in areas:
            areas.append(label)

    shown = areas[:limit]
    if not shown:
        return "the bot"
    if len(shown) == 1:
        text = shown[0]
    else:
        text = ", ".join(shown[:-1]) + f" and {shown[-1]}"
    hidden = len(areas) - len(shown)
    if hidden > 0:
        text += f" (+{hidden} more)"
    return text


def tracked_files():
    files = [BASE_DIR / "bot.py", BASE_DIR / ".env.example", BASE_DIR / "SETUP.md"]
    for folder_name in ("core", "cogs"):
        folder = BASE_DIR / folder_name
        if folder.is_dir():
            files.extend(sorted(folder.glob("*.py")))
    return [path for path in files if path.exists()]


def read_tracked_files():
    contents = {}
    for file_path in tracked_files():
        key = str(file_path.relative_to(BASE_DIR))
        contents[key] = file_path.read_text(encoding="utf-8")
    return contents


def build_fingerprint(files_data):
    joined = "".join(f"{name}\n{content}" for name, content in sorted(files_data.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def is_command_decorator(decorator):
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in COMMAND_DECORATORS
    )


def keyword_string(call, key, fallback=None):
    for keyword in call.keywords:
        if (
            keyword.arg == key
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ):
            return keyword.value.value
    return fallback


def keyword_name(call, key):
    for keyword in call.keywords:
        if keyword.arg == key and isinstance(keyword.value, ast.Name):
            return keyword.value.id
    return None


def extract_group_names(tree):
    raw_groups = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "Group"
            and isinstance(func.value, ast.Name)
            and func.value.id == "app_commands"
        ):
            continue

        for target in node.targets:
            if isinstance(target, ast.Name):
                raw_groups[target.id] = {
                    "name": keyword_string(node.value, "name", target.id),
                    "parent": keyword_name(node.value, "parent"),
                }

    resolved = {}

    def resolve(group_var):
        if group_var in resolved:
            return resolved[group_var]
        group = raw_groups.get(group_var)
        if not group:
            return group_var
        parent = group.get("parent")
        if parent and parent in raw_groups:
            resolved[group_var] = f"{resolve(parent)} {group['name']}"
        else:
            resolved[group_var] = group["name"]
        return resolved[group_var]

    for group_var in raw_groups:
        resolve(group_var)
    return resolved


def command_name_for(node, decorator, group_names):
    name = node.name
    name = keyword_string(decorator, "name", node.name)

    # Prefix group subcommands (e.g. @warn.command -> "warn add")
    func = decorator.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        parent = func.value.id
        if parent not in {"app_commands", "commands", "client", "bot", "tree", "self"}:
            return f"{group_names.get(parent, parent)} {name}"
    return name


def extract_command_sources(source):
    if not source.strip():
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    group_names = extract_group_names(tree)
    commands_found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if is_command_decorator(decorator):
                name = command_name_for(node, decorator, group_names)
                commands_found[name] = ast.get_source_segment(source, node) or name
                break
    return commands_found


def extract_all_commands(files_data):
    merged = {}
    for file_name in sorted(files_data):
        if file_name.endswith(".py"):
            merged.update(extract_command_sources(files_data[file_name]))
    return merged


def extract_stream_texts(source):
    if not source.strip():
        return set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    values = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in STATUS_VARIABLE_NAMES:
                if isinstance(node.value, ast.List):
                    for item in node.value.elts:
                        if isinstance(item, ast.Constant) and isinstance(item.value, str):
                            values.add(item.value)
    return values


def extract_all_stream_texts(files_data):
    texts = set()
    for file_name, content in files_data.items():
        if file_name.endswith(".py"):
            texts |= extract_stream_texts(content)
    return texts


def format_command_list(names, limit=18):
    shown = ", ".join(f"`/{name}`" for name in names[:limit])
    extra = len(names) - limit
    if extra > 0:
        shown += f" +{extra} more"
    return shown


def changed_file_names(old_files, new_files):
    return {
        file_name
        for file_name in set(old_files) | set(new_files)
        if old_files.get(file_name) != new_files.get(file_name)
    }


def any_changed(changed_files, *file_names):
    return any(file_name in changed_files for file_name in file_names)


def _markers_present(files_data, file_name, markers):
    source = files_data.get(file_name, "")
    return all(marker in source for marker in markers)


def feature_just_arrived(old_files, new_files, file_name, *markers):
    """True only when ``markers`` appear in ``file_name`` for the first time.

    A highlight has to describe what *this* release added. Testing the markers
    against the new snapshot alone re-announced a feature every time its file
    was touched again: build #39 told everyone that automatic backups and the
    SQLite migration had just landed, months after they actually shipped.
    """
    return _markers_present(new_files, file_name, markers) and not _markers_present(
        old_files, file_name, markers
    )


def summarize_feature_highlights(old_files, new_files):
    highlights = []

    if feature_just_arrived(
        old_files, new_files, "cogs/setup.py", "ChannelSelect", "config = app_commands.Group"
    ):
        highlights.append("🚀 Setup wizard upgraded with select menus, channel picker and `/config` admin tools")

    if feature_just_arrived(
        old_files, new_files, "core/database.py", "novaguard.sqlite3", "level_records"
    ):
        highlights.append("🗄️ SQLite now powers server config, XP levels and economy wallets")

    if feature_just_arrived(old_files, new_files, "core/backups.py", "create_backup"):
        highlights.append("🧳 Automatic backups added with manual `/config backup` support")

    if feature_just_arrived(
        old_files, new_files, "cogs/system.py", "HIGH_LAG_ALERT_MS", "loop_lag_snapshot"
    ):
        highlights.append("🩺 Health monitoring now tracks event-loop lag and sends admin alerts")

    if feature_just_arrived(
        old_files, new_files, "core/database.py", "load_levels_data", "load_economy_data"
    ):
        highlights.append("🏆 Levels and economy migrate safely from JSON into SQLite")

    if feature_just_arrived(old_files, new_files, "cogs/developer.py", "resolve_configured_channels"):
        highlights.append("🐙 GitHub/update feeds now respect per-server setup channels")

    # There is deliberately no highlight for core/updates.py itself: it had no
    # marker at all, so it fired on every single edit to this file and said the
    # release notes had just been improved no matter what actually changed.
    return highlights[:6]


def summarize_changes(old_files, new_files, has_history=False):
    if not old_files:
        if has_history:
            summary = [
                "Deployment tracker state was rebuilt for the current live codebase",
                "No previous tracked snapshot was available, so this refresh avoids guessing command-by-command changes",
            ]
        else:
            command_names = sorted(extract_all_commands(new_files))
            summary = [f"Initial tracked release for v{BOT_VERSION} \"{BOT_CODENAME}\""]
            if command_names:
                summary.append("Available slash commands: " + format_command_list(command_names))
            if extract_all_stream_texts(new_files):
                summary.append("Streaming status rotation is active")
            if github_config.primary_repo:
                summary.append(f"GitHub system is connected to `{github_config.primary_repo}`")

        total_lines = sum(len(content.splitlines()) for content in new_files.values())
        return summary, total_lines, 0

    summary = []
    old_commands = extract_all_commands(old_files)
    new_commands = extract_all_commands(new_files)
    summary.extend(summarize_feature_highlights(old_files, new_files))
    changed_files = changed_file_names(old_files, new_files)

    added_commands = sorted(set(new_commands) - set(old_commands))
    removed_commands = sorted(set(old_commands) - set(new_commands))
    changed_commands = sorted(
        name for name in (set(old_commands) & set(new_commands)) if old_commands[name] != new_commands[name]
    )

    if "maintenance" in added_commands or any_changed(changed_files, "core/maintenance.py"):
        summary.append("🛠️ Added global maintenance mode with DND presence and graceful command blocking")

    if added_commands:
        summary.append("New commands ready to try: " + format_command_list(added_commands, limit=12))
    if removed_commands:
        summary.append("Retired commands: " + format_command_list(removed_commands))
    if changed_commands:
        summary.append(
            "Improved commands — same names, smoother behavior: "
            + format_command_list(changed_commands, limit=12)
        )

    if extract_all_stream_texts(old_files) != extract_all_stream_texts(new_files):
        summary.append("Fresh rotating status messages under the bot's name")

    other_changed_files = []
    internal_changed_files = []
    for file_name in sorted(changed_files):
        if file_name.endswith(".py"):
            internal_changed_files.append(file_name)
        else:
            other_changed_files.append(file_name)

    if other_changed_files:
        summary.append(
            "Refreshed docs and examples: " + ", ".join(f"`{name}`" for name in other_changed_files[:6])
        )
    if internal_changed_files and (not summary or not (added_commands or removed_commands or changed_commands)):
        summary.append(
            "Behind-the-scenes improvements to " + humanize_areas(internal_changed_files)
        )

    added_lines = 0
    removed_lines = 0
    for file_name in set(old_files) | set(new_files):
        diff_lines = list(
            difflib.ndiff(
                old_files.get(file_name, "").splitlines(),
                new_files.get(file_name, "").splitlines(),
            )
        )
        added_lines += sum(1 for line in diff_lines if line.startswith("+ "))
        removed_lines += sum(1 for line in diff_lines if line.startswith("- "))

    if not summary:
        summary.append("Small polish behind the scenes — everything works the same, just a little better")

    return summary, added_lines, removed_lines


def load_update_state():
    state = load_json_file(UPDATE_STATE_FILE, {})
    history = state.get("history")
    if not isinstance(history, list):
        history = []

    latest_update = state.get("latest")
    if latest_update and not history:
        history.append(latest_update)

    state["history"] = normalize_update_history(history)
    for index, update_entry in enumerate(state["history"], start=1):
        update_entry.setdefault("build", index)
    if state["history"]:
        state["latest"] = state["history"][-1]
    state.setdefault("pending_announcement", None)
    state.setdefault("last_announced_fingerprint", None)
    return state


def save_update_state(state):
    save_json_file(UPDATE_STATE_FILE, state)


def persist_pending_update(payload):
    state = load_update_state()
    history = payload["history"]
    update_entry = payload["update_entry"]

    if not history or history[-1].get("fingerprint") != payload["fingerprint"]:
        history.append(update_entry)
    history = normalize_update_history(history)
    for index, history_entry in enumerate(history, start=1):
        history_entry.setdefault("build", index)

    state.update(
        {
            "fingerprint": payload["fingerprint"],
            "files": payload["files_data"],
            "latest": history[-1],
            "history": history,
            "pending_announcement": payload["fingerprint"],
        }
    )
    save_update_state(state)
    return state


def mark_announcement_delivered(fingerprint):
    state = load_update_state()
    if state.get("pending_announcement") == fingerprint:
        state["pending_announcement"] = None
    state["last_announced_fingerprint"] = fingerprint
    save_update_state(state)


def has_pending_announcement():
    state = load_update_state()
    latest_update = state.get("latest") or {}
    pending_fingerprint = state.get("pending_announcement")
    return bool(pending_fingerprint and latest_update.get("fingerprint") == pending_fingerprint)


def normalize_update_history(update_history):
    normalized = []
    seen_keys = set()

    for update_entry in update_history:
        if not isinstance(update_entry, dict):
            continue

        fingerprint = update_entry.get("fingerprint")
        created_at = update_entry.get("created_at")
        summary = tuple(update_entry.get("summary", []))
        unique_key = fingerprint or (created_at, summary)

        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        normalized.append(update_entry)

    normalized.sort(key=lambda item: item.get("created_at", ""))
    return normalized


def next_build_number(update_history):
    highest = 0
    for update_entry in update_history:
        try:
            highest = max(highest, int(update_entry.get("build", 0) or 0))
        except (TypeError, ValueError):
            continue
    return highest + 1


def public_build_numbers(update_history):
    """Map engine entries to the public timeline number used by /updates."""
    feed = merged_update_feed(limit=UPDATE_FEED_MAX_LIMIT, history=update_history, latest=None)
    return {
        entry.get("created_at"): entry.get("build")
        for entry in feed
        if entry.get("created_at") and isinstance(entry.get("build"), int)
    }


def public_build_number(update_entry, update_history=None):
    if update_history:
        number = public_build_numbers(update_history).get(update_entry.get("created_at"))
        if number:
            return number
    return update_entry.get("build", "?")


def clamp(text, limit=1024):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def is_release_highlight(item):
    return item.startswith(("🚀", "🗄️", "🧳", "🩺", "🏆", "📜", "🐙"))


def bullet_list(items):
    return "\n".join(f"• {item}" for item in items)


def build_code_update_embed(update_entry, update_history=None):
    build_number = public_build_number(update_entry, update_history)
    summary_items = update_entry.get("summary", []) or ["General improvements"]
    highlight_items = [item for item in summary_items if is_release_highlight(item)]
    change_items = [item for item in summary_items if not is_release_highlight(item)]

    embed = discord.Embed(
        title="🚀 Bot Update Deployed",
        description=(
            "A fresh NovaGuard build is live. "
            "This release note was generated automatically from the deployed code."
        ),
        color=discord.Color(Palette.PRIMARY),
        timestamp=parse_github_datetime(update_entry.get("created_at")) or datetime.now(UTC),
    )
    if highlight_items:
        embed.add_field(
            name="✨ Release Highlights",
            value=clamp(bullet_list(highlight_items)),
            inline=False,
        )
    if change_items:
        embed.add_field(
            name="🧭 Command & Project Changes",
            value=clamp(bullet_list(change_items)),
            inline=False,
        )
    if not highlight_items and not change_items:
        embed.add_field(name="✨ What Changed", value="• General improvements", inline=False)
    embed.add_field(
        name="📊 Code Stats",
        value=(
            f"```diff\n+ {update_entry.get('added_lines', 0)} lines added\n"
            f"- {update_entry.get('removed_lines', 0)} lines removed\n"
            f"~ {update_entry.get('changed_files', 'unknown')} tracked files changed\n```"
        ),
        inline=True,
    )
    if update_entry.get("build"):
        embed.add_field(
            name="🏗️ Build",
            value=f"`#{build_number}` • v{BOT_VERSION} \"{BOT_CODENAME}\"",
            inline=True,
        )
    embed.set_footer(text=f"{github_config.brand_name} • Automatic update summary")
    return embed


def build_restart_update_embed(update_entry, update_history=None):
    build_number = public_build_number(update_entry, update_history)
    summary_items = update_entry.get("summary", []) or ["General improvements"]
    highlight_items = [item for item in summary_items if is_release_highlight(item)]
    change_items = [item for item in summary_items if not is_release_highlight(item)]

    embed = discord.Embed(
        title="🔄 Bot Restarted • Current Live Build",
        description="NovaGuard is back online. No new deployment was detected during this restart.",
        color=discord.Color(Palette.PRIMARY),
        timestamp=parse_github_datetime(update_entry.get("created_at")) or datetime.now(UTC),
    )
    embed.add_field(
        name="🏗️ Live Build",
        value=f"`#{build_number}` • v{BOT_VERSION} \"{BOT_CODENAME}\"",
        inline=True,
    )
    embed.add_field(
        name="📊 Code Stats",
        value=(
            f"`+{update_entry.get('added_lines', 0)}` / "
            f"`-{update_entry.get('removed_lines', 0)}` lines\n"
            f"`~{update_entry.get('changed_files', 'unknown')}` tracked files"
        ),
        inline=True,
    )
    preview_items = (highlight_items or change_items or summary_items)[:3]
    embed.add_field(
        name="📝 Latest Deployment Summary",
        value=clamp(bullet_list(preview_items)),
        inline=False,
    )
    return embed


def build_update_history_overview_embed(update_history):
    latest_update = update_history[-1]
    first_update = update_history[0]
    latest_time = parse_github_datetime(latest_update.get("created_at"))
    first_time = parse_github_datetime(first_update.get("created_at"))

    embed = discord.Embed(
        title="📜 Bot Release Timeline",
        description="A professional summary of every saved bot update, from the earliest build to the current live version.",
        color=discord.Color(Palette.PRIMARY),
        timestamp=latest_time or datetime.now(UTC),
    )
    embed.add_field(
        name="Overview",
        value=(
            f"Saved updates: `{len(update_history)}`\n"
            f"First tracked build: {discord.utils.format_dt(first_time, 'D') if first_time else 'Unknown'}\n"
            f"Latest deployment: {discord.utils.format_dt(latest_time, 'R') if latest_time else 'Unknown'}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Current Build",
        value=(
            f"Build: `#{public_build_number(latest_update, update_history)}`\n"
            f"Version: `v{BOT_VERSION} \"{BOT_CODENAME}\"`\n"
            f"Tracked files: `{len(tracked_files())}`\n"
            f"Primary repo: `{github_config.primary_repo or 'Not set'}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Latest Highlights",
        value=clamp(
            "\n".join(
                f"• {item}"
                for item in (latest_update.get("summary", []) or ["General internal improvements and cleanup"])[:5]
            )
        ),
        inline=False,
    )
    embed.set_footer(text=f"{github_config.brand_name} • Release overview")
    return embed


def build_update_history_embeds(update_history):
    if not update_history:
        return []

    embeds = [build_update_history_overview_embed(update_history)]
    newest_first = list(reversed(update_history))
    build_numbers = public_build_numbers(update_history)

    for index in range(0, len(newest_first), 4):
        chunk = newest_first[index:index + 4]
        embed = discord.Embed(
            title="🗂️ Bot Update Timeline",
            description="Latest and previous bot updates collected in one place.",
            color=discord.Color(Palette.PRIMARY),
        )

        for offset, update_entry in enumerate(chunk, start=index + 1):
            timestamp = parse_github_datetime(update_entry.get("created_at"))
            time_label = discord.utils.format_dt(timestamp, "f") if timestamp else "Unknown time"
            summary = update_entry.get("summary", []) or ["General internal improvements and cleanup"]
            summary_text = "\n".join(f"• {item}" for item in summary[:4])
            stats_text = (
                f"`+{update_entry.get('added_lines', 0)}` / "
                f"`-{update_entry.get('removed_lines', 0)}` lines"
            )
            embed.add_field(
                name=(
                    f"Build #{build_numbers.get(update_entry.get('created_at'), update_entry.get('build', '?'))}"
                    f" • {time_label}"
                ),
                value=clamp(f"{summary_text}\n{stats_text}"),
                inline=False,
            )

        embed.set_footer(text=f"{github_config.brand_name} • Update history")
        embeds.append(embed)

    return embeds


def build_update_buttons():
    buttons = []
    if github_config.primary_repo:
        buttons.append(("Repository", f"https://github.com/{github_config.primary_repo}"))
    if github_config.username:
        buttons.append(("Profile", f"https://github.com/{github_config.username}"))
    return build_link_view(buttons)


def prepare_update_payload():
    """Build the changelog payload off the event loop; AST/diff work is CPU-heavy on a Pi."""
    files_data = read_tracked_files()
    current_fingerprint = build_fingerprint(files_data)
    saved_state = load_update_state()

    if current_fingerprint == saved_state.get("fingerprint"):
        return None

    old_files = saved_state.get("files", {})
    history = normalize_update_history(saved_state.get("history", []))
    summary, added_lines, removed_lines = summarize_changes(old_files, files_data, has_history=bool(history))
    changed_count = len(changed_file_names(old_files, files_data))
    update_entry = {
        "summary": summary,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "changed_files": changed_count,
        "created_at": datetime.now(UTC).isoformat(),
        "fingerprint": current_fingerprint,
        "build": next_build_number(history),
    }
    return {
        "files_data": files_data,
        "history": history,
        "update_entry": update_entry,
        "fingerprint": current_fingerprint,
    }


def build_preview_update_entry():
    files_data = read_tracked_files()
    saved_state = load_update_state()
    old_files = saved_state.get("files", {})
    history = normalize_update_history(saved_state.get("history", []))
    summary, added_lines, removed_lines = summarize_changes(old_files, files_data, has_history=bool(history))
    return {
        "summary": summary,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "changed_files": len(changed_file_names(old_files, files_data)),
        "created_at": datetime.now(UTC).isoformat(),
        "build": next_build_number(history),
    }


async def safe_send_embed(channel, embed, view=None):
    kwargs = {"view": view} if view is not None else {}
    try:
        await asyncio.wait_for(channel.send(embed=embed, **kwargs), timeout=8)
        return True
    except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError) as error:
        print(f"Embed send skipped due to temporary network issue: {error}")
        return False


async def send_update_embed(bot):
    payload = await asyncio.to_thread(prepare_update_payload)
    if payload is not None:
        await asyncio.to_thread(persist_pending_update, payload)
    return await send_latest_saved_update_embed(bot)


async def send_latest_saved_update_embed(bot):
    saved_state = await asyncio.to_thread(load_update_state)
    latest_update = saved_state.get("latest")
    if not latest_update:
        return False

    channels = await resolve_configured_channels(bot, "update_channel", github_config.update_channel_id)
    if not channels:
        return False

    pending_fingerprint = saved_state.get("pending_announcement")
    latest_fingerprint = latest_update.get("fingerprint")
    is_pending_deploy = bool(pending_fingerprint and pending_fingerprint == latest_fingerprint)
    update_history = normalize_update_history(saved_state.get("history", []))
    embed = (
        build_code_update_embed(latest_update, update_history)
        if is_pending_deploy
        else build_restart_update_embed(latest_update, update_history)
    )

    sent_any = False
    for channel in channels:
        sent_any = await safe_send_embed(channel, embed, build_update_buttons()) or sent_any

    if sent_any and is_pending_deploy and latest_fingerprint:
        await asyncio.to_thread(mark_announcement_delivered, latest_fingerprint)
    return sent_any


async def send_update_history_embeds(bot, max_embeds=None):
    saved_state = await asyncio.to_thread(load_update_state)
    update_history = normalize_update_history(saved_state.get("history", []))
    if not update_history:
        return False

    channels = await resolve_configured_channels(bot, "update_channel", github_config.update_channel_id)
    if not channels:
        return False

    sent_any = False
    embeds = build_update_history_embeds(update_history)
    if max_embeds is not None:
        embeds = embeds[:max_embeds]

    for embed in embeds:
        for channel in channels:
            sent_any = await safe_send_embed(channel, embed, build_update_buttons()) or sent_any
    return sent_any


async def announce_startup_updates(bot):
    """Post a light startup update without blocking the gateway heartbeat."""
    sent_new_update = await send_update_embed(bot)
    if not sent_new_update:
        return await send_latest_saved_update_embed(bot)
    return sent_new_update
