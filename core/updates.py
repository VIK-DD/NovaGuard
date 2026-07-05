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
from .guild_config import resolve_channel, resolve_configured_channels
from .storage import load_json_file, save_json_file
from .theme import Palette
from .utils import build_link_view, parse_github_datetime

COMMAND_DECORATORS = {"command", "hybrid_command", "context_menu"}
STATUS_VARIABLE_NAMES = {"stream_statuses", "DEFAULT_STREAM_STATUSES"}


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


def summarize_feature_highlights(old_files, new_files):
    changed_files = changed_file_names(old_files, new_files)
    highlights = []

    if any_changed(changed_files, "cogs/setup.py", "core/guild_config.py"):
        setup_source = new_files.get("cogs/setup.py", "")
        if "ChannelSelect" in setup_source and "config = app_commands.Group" in setup_source:
            highlights.append("🚀 Setup wizard upgraded with select menus, channel picker and `/config` admin tools")

    if any_changed(changed_files, "core/database.py", "core/storage.py"):
        database_source = new_files.get("core/database.py", "")
        if "novaguard.sqlite3" in database_source and "level_records" in database_source:
            highlights.append("🗄️ SQLite now powers server config, XP levels and economy wallets")

    if any_changed(changed_files, "core/backups.py", "cogs/system.py"):
        if "create_backup" in new_files.get("core/backups.py", ""):
            highlights.append("🧳 Automatic backups added with manual `/config backup` support")

    if any_changed(changed_files, "cogs/system.py", "core/error_digest.py"):
        system_source = new_files.get("cogs/system.py", "")
        if "HIGH_LAG_ALERT_MS" in system_source and "loop_lag_snapshot" in system_source:
            highlights.append("🩺 Health monitoring now tracks event-loop lag and sends admin alerts")

    if any_changed(changed_files, "cogs/levels.py", "cogs/economy.py", "core/database.py"):
        if "load_levels_data" in new_files.get("core/database.py", "") and "load_economy_data" in new_files.get("core/database.py", ""):
            highlights.append("🏆 Levels and economy migrate safely from JSON into SQLite")

    if any_changed(changed_files, "core/updates.py"):
        highlights.append("📜 Update embeds now produce cleaner professional release notes")

    if any_changed(changed_files, "cogs/developer.py", "core/updates.py", "core/guild_config.py"):
        developer_source = new_files.get("cogs/developer.py", "")
        if "resolve_configured_channels" in developer_source:
            highlights.append("🐙 GitHub/update feeds now respect per-server setup channels")

    return highlights[:6]


def summarize_changes(old_files, new_files):
    if not old_files:
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

    added_commands = sorted(set(new_commands) - set(old_commands))
    removed_commands = sorted(set(old_commands) - set(new_commands))
    changed_commands = sorted(
        name for name in (set(old_commands) & set(new_commands)) if old_commands[name] != new_commands[name]
    )

    if added_commands:
        summary.append("Added commands: " + format_command_list(added_commands, limit=12))
    if removed_commands:
        summary.append("Removed commands: " + format_command_list(removed_commands))
    if changed_commands:
        summary.append("Updated command behavior: " + format_command_list(changed_commands, limit=12))

    if extract_all_stream_texts(old_files) != extract_all_stream_texts(new_files):
        summary.append("Refreshed rotating streaming statuses")

    other_changed_files = []
    internal_changed_files = []
    for file_name in sorted(changed_file_names(old_files, new_files)):
        if file_name.endswith(".py"):
            internal_changed_files.append(f"`{file_name}`")
        else:
            other_changed_files.append(f"`{file_name}`")

    if other_changed_files:
        summary.append("Updated project files: " + ", ".join(other_changed_files[:6]))
    if internal_changed_files and (not summary or not (added_commands or removed_commands or changed_commands)):
        summary.append("Internal engine improvements: " + ", ".join(internal_changed_files[:6]))

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
        summary.append("General internal improvements and cleanup")

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
    if state["history"]:
        state["latest"] = state["history"][-1]
    return state


def save_update_state(state):
    save_json_file(UPDATE_STATE_FILE, state)


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


def clamp(text, limit=1024):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def is_release_highlight(item):
    return item.startswith(("🚀", "🗄️", "🧳", "🩺", "🏆", "📜", "🐙"))


def bullet_list(items):
    return "\n".join(f"• {item}" for item in items)


def build_code_update_embed(update_entry):
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
            value=f"`#{update_entry['build']}` • v{BOT_VERSION} \"{BOT_CODENAME}\"",
            inline=True,
        )
    embed.set_footer(text=f"{github_config.brand_name} • Automatic update summary")
    return embed


def build_restart_update_embed(update_entry):
    embed = build_code_update_embed(update_entry)
    embed.title = "🔄 Bot Restarted • Current Live Build"
    embed.description = "The bot is back online. Here is the latest deployed update."
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
                name=f"Update #{len(update_history) - offset + 1} • {time_label}",
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
    summary, added_lines, removed_lines = summarize_changes(old_files, files_data)
    history = normalize_update_history(saved_state.get("history", []))
    changed_count = len(changed_file_names(old_files, files_data))
    update_entry = {
        "summary": summary,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "changed_files": changed_count,
        "created_at": datetime.now(UTC).isoformat(),
        "fingerprint": current_fingerprint,
        "build": len(history) + 1,
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
    summary, added_lines, removed_lines = summarize_changes(old_files, files_data)
    return {
        "summary": summary,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "changed_files": len(changed_file_names(old_files, files_data)),
        "created_at": datetime.now(UTC).isoformat(),
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
    if payload is None:
        return False

    channels = await resolve_configured_channels(bot, "update_channel", github_config.update_channel_id)
    if not channels:
        return False

    update_entry = payload["update_entry"]
    sent_any = False
    for channel in channels:
        sent_any = await safe_send_embed(channel, build_code_update_embed(update_entry), build_update_buttons()) or sent_any

    if not sent_any:
        return False

    history = payload["history"]
    if not history or history[-1].get("fingerprint") != payload["fingerprint"]:
        history.append(update_entry)
    history = normalize_update_history(history)

    await asyncio.to_thread(
        save_update_state,
        {
            "fingerprint": payload["fingerprint"],
            "files": payload["files_data"],
            "latest": update_entry,
            "history": history,
        },
    )
    return True


async def send_latest_saved_update_embed(bot):
    saved_state = await asyncio.to_thread(load_update_state)
    latest_update = saved_state.get("latest")
    if not latest_update:
        return False

    channels = await resolve_configured_channels(bot, "update_channel", github_config.update_channel_id)
    if not channels:
        return False

    sent_any = False
    for channel in channels:
        sent_any = await safe_send_embed(channel, build_restart_update_embed(latest_update), build_update_buttons()) or sent_any
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
        await send_latest_saved_update_embed(bot)
