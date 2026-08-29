"""Pure health summaries and Discord cards for read-only system commands."""

from __future__ import annotations

from datetime import UTC, datetime

from .health_report import clamp_field, fail_line, info_line, ok_line, warn_line
from .release_versions import public_release_label
from .theme import Palette, brand_footer, make_embed
from .utils import format_timedelta


def summarize_loop_lag(samples):
    values = list(samples)
    if not values:
        return {
            "label": "Warming up",
            "line": info_line("Event loop", "collecting lag samples"),
            "details": "Collecting samples",
            "color": Palette.INFO,
            "latest": 0,
            "average": 0,
            "peak": 0,
        }

    latest = values[-1]
    average = sum(values) / len(values)
    peak = max(values)
    details = f"latest `{latest:.0f}ms` • avg `{average:.0f}ms` • peak `{peak:.0f}ms`"

    if peak >= 3000 or average >= 1000:
        label = "High lag"
        line = fail_line("Event loop", details)
        color = Palette.DANGER
    elif peak >= 800 or average >= 250:
        label = "Small lag"
        line = warn_line("Event loop", details)
        color = Palette.WARNING
    else:
        label = "Healthy"
        line = ok_line("Event loop", details)
        color = Palette.SUCCESS

    return {
        "label": label,
        "line": line,
        "details": details.replace("`", ""),
        "color": color,
        "latest": latest,
        "average": average,
        "peak": peak,
    }


def ping_profile(gateway_ms):
    if gateway_ms < 150:
        return Palette.SUCCESS, "Feeling fast today ⚡"
    if gateway_ms < 300:
        return Palette.WARNING, "A little sleepy 😴"
    return Palette.DANGER, "Running through molasses 🐌"


def build_ping_embed(gateway_ms, rest_ms, uptime):
    color, mood = ping_profile(gateway_ms)
    embed = make_embed("🏓 Pong!", mood, color=color)
    embed.add_field(name="🛰️ Gateway", value=f"`{gateway_ms}ms`", inline=True)
    embed.add_field(name="⚡ REST", value=f"`{rest_ms}ms`", inline=True)
    embed.add_field(
        name="⏱️ Uptime",
        value=f"`{format_timedelta(uptime)}`",
        inline=True,
    )
    brand_footer(embed, "Pulse check")
    return embed


def build_uptime_embed(launched_at, checked_at=None):
    checked_at = checked_at or datetime.now(UTC)
    delta = checked_at - launched_at
    embed = make_embed(
        "⏱️ Uptime",
        f"Online for **{format_timedelta(delta)}**\nBooted <t:{int(launched_at.timestamp())}:R>",
        color=Palette.TEAL,
    )
    brand_footer(embed, "Still going strong")
    return embed


def build_botinfo_embed(
    *,
    bot_name,
    avatar_url,
    release,
    build_count,
    server_count,
    total_members,
    command_count,
    category_count,
    python_version,
    discord_version,
    gateway_ms,
    uptime,
):
    embed = make_embed(
        f"🤖 {bot_name}",
        f"`{public_release_label(release, prefix='v')}` — the slash-command era.",
        color=Palette.PRIMARY,
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    embed.add_field(
        name="🏗️ Build",
        value=f"Builds shipped: `{build_count}`\nAuto-changelog: `Active`",
        inline=True,
    )
    embed.add_field(
        name="🌍 Reach",
        value=f"Servers: `{server_count}`\nMembers: `{total_members:,}`",
        inline=True,
    )
    embed.add_field(
        name="🧩 Commands",
        value=f"Slash commands: `{command_count}`\nCategories: `{category_count}`",
        inline=True,
    )
    embed.add_field(
        name="🐍 Runtime",
        value=(
            f"Python `{python_version}`\n"
            f"discord.py `{discord_version}`\n"
            f"Gateway `{gateway_ms}ms`"
        ),
        inline=True,
    )
    embed.add_field(
        name="⏱️ Uptime",
        value=f"`{format_timedelta(uptime)}`",
        inline=True,
    )
    brand_footer(embed, "Bot info")
    return embed


def public_status_profile(gateway_ms, lag_label, maintenance_active):
    if maintenance_active:
        return (
            Palette.WARNING,
            "Maintenance mode is active. Core systems are online, but commands are limited.",
        )
    if gateway_ms >= 500 or lag_label == "High lag":
        return Palette.DANGER, "Online, but the Raspberry Pi is feeling pressure."
    if gateway_ms >= 250 or lag_label == "Small lag":
        return Palette.WARNING, "Online with a little latency wobble."
    return Palette.SUCCESS, "Online, responsive and ready."


def public_status_links(primary_repo=None, username=None, uptime_url=None):
    buttons = []
    if primary_repo:
        buttons.append(("Repository", f"https://github.com/{primary_repo}"))
    if username:
        buttons.append(("GitHub Profile", f"https://github.com/{username}"))
    if uptime_url:
        buttons.append(("Uptime", uptime_url))
    return buttons


def build_public_status_embed(
    *,
    bot_name,
    avatar_url,
    gateway_ms,
    uptime,
    lag,
    maintenance_active,
    release,
    command_count,
    project_label,
):
    color, mood = public_status_profile(gateway_ms, lag["label"], maintenance_active)
    embed = make_embed(f"🟢 {bot_name} Status", mood, color=color)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    embed.add_field(name="Gateway", value=f"`{gateway_ms}ms`", inline=True)
    embed.add_field(
        name="Event Loop",
        value=f"`{lag['label']}`\n{lag['details']}",
        inline=True,
    )
    embed.add_field(name="Uptime", value=f"`{format_timedelta(uptime)}`", inline=True)
    embed.add_field(
        name="Build",
        value=(
            f"`{public_release_label(release, prefix='v')}`\n"
            f"Slash commands: `{command_count}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="Project",
        value=(
            f"GitHub: `{project_label or 'Not configured'}`\n"
            f"Presence: `{'Maintenance' if maintenance_active else 'Streaming'}`"
        ),
        inline=True,
    )
    brand_footer(embed, "Public status")
    return embed


def build_doctor_runtime_lines(
    *,
    gateway_ms,
    ack_ms,
    lag_line,
    uptime,
    python_version,
    discord_version,
    cog_count,
    command_count,
):
    return [
        ok_line("Gateway", f"{gateway_ms}ms")
        if gateway_ms < 300
        else warn_line("Gateway", f"{gateway_ms}ms, a little slow"),
        ok_line("Discord ACK", f"{ack_ms}ms")
        if ack_ms < 1000
        else warn_line("Discord ACK", f"{ack_ms}ms, slow response"),
        lag_line,
        ok_line("Uptime", format_timedelta(uptime)),
        ok_line("Runtime", f"Python {python_version} • discord.py {discord_version}"),
        ok_line("Loaded", f"{cog_count} cogs • {command_count} slash commands"),
    ]


def build_doctor_config_lines(
    *,
    token_configured,
    env_found,
    guild_id,
    update_channel_id,
    github_channel_id,
    github_token_configured,
    anthropic_configured,
    error_channel_id,
):
    return [
        ok_line("TOKEN", "configured") if token_configured else fail_line("TOKEN", "missing"),
        ok_line(".env", "found")
        if env_found
        else warn_line(".env", "not found; using shell env only"),
        ok_line("GUILD_ID", f"{guild_id} (use /resync server for instant updates)")
        if guild_id
        else warn_line("GUILD_ID", "global sync can be slower"),
        ok_line("Update channel", f"<#{update_channel_id}>")
        if update_channel_id
        else warn_line("Update channel", "not configured; run /setup"),
        ok_line("GitHub feed", f"<#{github_channel_id}>")
        if github_channel_id
        else warn_line("GitHub feed", "not configured; run /setup"),
        ok_line("GITHUB_TOKEN", "configured")
        if github_token_configured
        else warn_line("GITHUB_TOKEN", "optional, but recommended for rate limits"),
        ok_line("ANTHROPIC_API_KEY", "configured")
        if anthropic_configured
        else warn_line("ANTHROPIC_API_KEY", "/ask disabled until configured"),
        ok_line("Error digest channel", f"<#{error_channel_id}>")
        if error_channel_id
        else info_line("Error digest channel", "optional; run /setup to enable"),
    ]


def build_doctor_permission_lines(permission_checks):
    return [
        ok_line(label, "available") if granted else warn_line(label, "missing or channel-limited")
        for label, granted in permission_checks
    ]


def build_doctor_github_lines(*, username, primary_repo, watch_repos, poll_seconds):
    return [
        ok_line("Username", username) if username else warn_line("Username", "not configured"),
        ok_line("Primary Repo", primary_repo)
        if primary_repo
        else warn_line("Primary Repo", "not configured"),
        ok_line("Watcher Repos", ", ".join(watch_repos))
        if watch_repos
        else warn_line("Watcher Repos", "none configured"),
        ok_line("Polling", f"every {poll_seconds}s"),
    ]


def build_doctor_feature_lines(
    *,
    maintenance_state,
    stream_running,
    stream_interval_seconds,
    update_channel_id,
    github_watcher_running,
    error_digest_line,
):
    maintenance_enabled = bool(maintenance_state.get("enabled"))
    if stream_running and not maintenance_enabled:
        stream_line = ok_line("Streaming status", f"rotating every {stream_interval_seconds}s")
    elif maintenance_enabled:
        stream_line = info_line("Streaming status", "paused while maintenance is active")
    else:
        stream_line = warn_line("Streaming status", "loop stopped")

    return [
        warn_line("Maintenance mode", maintenance_state.get("message"))
        if maintenance_enabled
        else ok_line("Maintenance mode", "inactive"),
        stream_line,
        ok_line("Startup updates", "background-safe")
        if update_channel_id
        else warn_line("Startup updates", "no channel set"),
        ok_line("GitHub watcher", "running")
        if github_watcher_running
        else warn_line("GitHub watcher", "stopped or not configured"),
        ok_line("Giveaways/Roles/Tickets", "persistent buttons"),
        error_digest_line,
        info_line("Polls", "temporary by design; buttons expire after restart/24h"),
    ]


def doctor_profile(*sections):
    lines = [line for section in sections for line in section]
    error_count = sum(line.startswith("❌") for line in lines)
    warning_count = sum(line.startswith("⚠️") for line in lines)

    if error_count:
        return (
            "🩺 Doctor Check • Needs attention",
            f"Found **{error_count} issue(s)** and **{warning_count} note(s)**.",
            Palette.DANGER,
        )
    if warning_count:
        return (
            "🩺 Doctor Check • Healthy with notes",
            f"No critical issues. **{warning_count} note(s)** are worth knowing.",
            Palette.WARNING,
        )
    return (
        "🩺 Doctor Check • All systems healthy",
        "Everything looks clean. The little Raspberry Pi is vibing.",
        Palette.SUCCESS,
    )


def build_doctor_embed(
    *,
    runtime_lines,
    config_lines,
    storage_lines,
    permission_lines,
    github_lines,
    feature_lines,
):
    sections = (
        runtime_lines,
        config_lines,
        storage_lines,
        permission_lines,
        github_lines,
        feature_lines,
    )
    title, description, color = doctor_profile(*sections)
    embed = make_embed(title, description, color=color)
    for name, lines in zip(
        ("Pulse", "Configuration", "Storage", "Permissions", "GitHub", "Feature Notes"),
        sections,
        strict=True,
    ):
        embed.add_field(name=name, value=clamp_field(lines), inline=False)
    brand_footer(embed, "Doctor diagnostics")
    return embed
