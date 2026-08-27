"""Read-only setup scores and Discord configuration cards."""

from .config import github_config
from .storage import get_guild_settings
from .theme import Palette, brand_footer, make_embed, progress_bar


CHANNEL_KEYS = {
    "update_channel": ("🚀 Bot Updates", "Automatic code changelog and restart summaries"),
    "github_event_channel": ("🐙 GitHub Feed", "Push, PR, issue and release activity"),
    "error_log_channel": ("🚨 Admin Errors", "Serious bot error digest embeds"),
    "log_channel": ("📋 Server Logs", "Deleted/edited messages, joins/leaves, bans"),
    "voice_report_channel": (
        "🎙️ Voice Reports",
        "Completed voice session attendance and duration reports",
    ),
    "status_channel": ("📡 Service Status", "Public status card, refreshed twice a day"),
    "welcome_channel": ("👋 Welcome", "New member welcome cards"),
    "goodbye_channel": ("📤 Goodbye", "Leave messages"),
}

RECOMMENDED_KEYS = (
    "update_channel",
    "error_log_channel",
    "log_channel",
    "welcome_channel",
)

SETUP_PRIVACY_NOTICE = (
    "Review `/privacy policy` and tell members which optional features you enable. "
    "Server Logs can repost deleted/edited message excerpts inside Discord; `/ask` sends only "
    "the submitted question to Anthropic when AI is available. Every member can use "
    "`/privacy export` or `/privacy delete`."
)


def mention_channel(guild, channel_id):
    if not channel_id:
        return "`Not set`"
    try:
        channel = guild.get_channel(int(channel_id))
    except (TypeError, ValueError):
        return "`Invalid channel`"
    return channel.mention if channel else f"`{channel_id}`"


def setup_score(settings):
    total = len(RECOMMENDED_KEYS)
    done = sum(1 for key in RECOMMENDED_KEYS if settings.get(key))
    if github_config.watch_repos or github_config.primary_repo:
        total += 1
        done += 1 if settings.get("github_event_channel") else 0
    return done, total


def build_setup_embed(guild, notice=None):
    settings = get_guild_settings(guild.id)
    done, total = setup_score(settings)
    ratio_text = f"{done}/{total}"
    completed = bool(settings.get("setup_completed"))

    if completed:
        color = Palette.SUCCESS
        title = "✅ NovaGuard Setup — Complete"
        status = (
            "**Setup is marked complete.** Every channel below is optional — NovaGuard "
            "runs fine with none, some, or all of them set. Re-open `/setup` anytime to change things."
        )
    else:
        color = Palette.PRIMARY if not done else Palette.INFO
        title = "🚀 NovaGuard Setup"
        status = (
            "Every channel here is **optional** — set the ones you want, leave the rest empty. "
            "Choose a setting in the first menu, then pick its channel in the second. "
            "**Clear** removes the chosen setting, and **Mark complete** finishes "
            "(even with nothing set)."
        )

    if notice:
        status = f"> {notice}\n\n{status}"

    embed = make_embed(title, status, color=color)
    embed.add_field(
        name="Optional channels set",
        value=f"{progress_bar(done, total, slots=12)} `{ratio_text}` configured — all optional",
        inline=False,
    )

    core_lines = []
    for key in ("update_channel", "github_event_channel", "error_log_channel", "log_channel"):
        label, description = CHANNEL_KEYS[key]
        core_lines.append(
            f"{label}: {mention_channel(guild, settings.get(key))}\n`{description}`"
        )
    embed.add_field(name="Core Channels", value="\n\n".join(core_lines), inline=False)

    community_lines = []
    for key in ("welcome_channel", "goodbye_channel", "voice_report_channel"):
        label, description = CHANNEL_KEYS[key]
        community_lines.append(
            f"{label}: {mention_channel(guild, settings.get(key))}\n`{description}`"
        )
    autorole = settings.get("autorole")
    try:
        role = guild.get_role(int(autorole)) if autorole else None
    except (TypeError, ValueError):
        role = None
    community_lines.append(
        f"🎭 Auto-role: {role.mention if role else '`Not set`'}\n"
        "`Use /welcome set when you want an auto-role too`"
    )
    embed.add_field(name="Community", value="\n\n".join(community_lines), inline=False)

    embed.add_field(
        name="Optional Next Steps",
        value=(
            "`/ticketpanel channel:#support staff_role:@Staff` for tickets\n"
            "`/rolepanel` for self-role buttons\n"
            "`/automod status` to review moderation filters"
        ),
        inline=False,
    )
    embed.add_field(
        name="Privacy before enabling features",
        value=SETUP_PRIVACY_NOTICE,
        inline=False,
    )
    brand_footer(embed, "Server setup")
    return embed


def build_config_embed(guild):
    settings = get_guild_settings(guild.id)
    done, total = setup_score(settings)
    embed = make_embed(
        "🧭 NovaGuard Config",
        "Advanced server configuration overview. Use `/setup` for the friendly wizard.",
        color=Palette.INFO,
    )
    embed.add_field(
        name="Setup Health",
        value=f"{progress_bar(done, total, slots=12)} `{done}/{total}` recommended items",
        inline=False,
    )

    lines = []
    for key, (label, description) in CHANNEL_KEYS.items():
        lines.append(
            f"{label}: {mention_channel(guild, settings.get(key))}\n`{key}` • {description}"
        )
    embed.add_field(name="Channels", value="\n\n".join(lines), inline=False)

    extra = []
    for key in ("autorole", "ticket_staff_role", "setup_completed"):
        value = settings.get(key)
        if key.endswith("_role") or key == "autorole":
            try:
                role = guild.get_role(int(value)) if value else None
            except (TypeError, ValueError):
                role = None
            display = role.mention if role else "`Not set`"
        else:
            display = f"`{value}`" if value is not None else "`Not set`"
        extra.append(f"`{key}`: {display}")
    embed.add_field(name="Other Settings", value="\n".join(extra), inline=False)
    brand_footer(embed, "Config view")
    return embed


def plain_label(key):
    """Return a menu label without its leading emoji."""
    label, _ = CHANNEL_KEYS[key]
    head, _, rest = label.partition(" ")
    return rest if rest and not head.isalnum() else label
