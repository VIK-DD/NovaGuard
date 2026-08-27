"""Pure health summaries and Discord cards for read-only system commands."""

from __future__ import annotations

from datetime import UTC, datetime

from .health_report import fail_line, info_line, ok_line, warn_line
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
        f"v`{release['version']}` **{release['phase_label']}** — the slash-command era.",
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
