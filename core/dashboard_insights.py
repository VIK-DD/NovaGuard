"""Pure summaries used by the per-guild web dashboard payload."""

from datetime import UTC, datetime

from .level_curve import level_from_xp


def dashboard_seconds_between(started_at, ended_at):
    if not started_at or not ended_at:
        return 0
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(ended_at).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return max(int((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()), 0)


def dashboard_setup_summary(settings, channel_keys, *, github_watch_configured=False):
    recommended_keys = ["update_channel", "error_log_channel", "log_channel", "welcome_channel"]
    if github_watch_configured:
        recommended_keys.append("github_event_channel")
    return {
        "configured_channels": sum(1 for key in channel_keys if settings.get(key)),
        "total_channels": len(channel_keys),
        "recommended_done": sum(1 for key in recommended_keys if settings.get(key)),
        "recommended_total": len(recommended_keys),
    }


def dashboard_levels_summary(guild, guild_levels, *, limit=5):
    total_xp = sum(max(int(record.get("xp", 0) or 0), 0) for record in guild_levels.values())
    leaderboard = []
    ordered = sorted(
        guild_levels.items(),
        key=lambda item: item[1].get("xp", 0),
        reverse=True,
    )[:limit]
    for position, (user_id, record) in enumerate(ordered, start=1):
        member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
        xp = int(record.get("xp", 0) or 0)
        leaderboard.append(
            {
                "position": position,
                "user_id": str(user_id),
                "display_name": member.display_name if member else f"User {user_id}",
                "xp": xp,
                "messages": int(record.get("messages", 0) or 0),
                "level": level_from_xp(xp)[0],
            }
        )
    return {
        "tracked_members": len(guild_levels),
        "total_xp": total_xp,
        "leaderboard": leaderboard,
    }


def dashboard_voice_summary(settings, history, pending, *, limit=5):
    reports = []
    for report in history[:limit]:
        session = report.get("session") or {}
        members = session.get("members") if isinstance(session, dict) else {}
        started_at = session.get("started_at") if isinstance(session, dict) else None
        ended_at = report.get("ended_at")
        reports.append(
            {
                "id": str(report.get("id") or ""),
                "channel_id": str(report.get("channel_id") or ""),
                "channel_name": report.get("channel_name") or "Voice session",
                "started_at": started_at,
                "ended_at": ended_at,
                "sent_at": report.get("sent_at"),
                "duration_seconds": dashboard_seconds_between(started_at, ended_at),
                "unique_members": len(members) if isinstance(members, dict) else 0,
                "peak_members": int(session.get("peak_members", 0) or 0) if isinstance(session, dict) else 0,
            }
        )
    return {
        "configured": bool(settings.get("voice_report_channel")),
        "report_channel_id": (
            str(settings.get("voice_report_channel"))
            if settings.get("voice_report_channel")
            else None
        ),
        "pending_count": len(pending) if isinstance(pending, dict) else 0,
        "recent_reports": reports,
    }


def dashboard_module_summary(settings, automod, levels_settings, ai_settings, economy_settings):
    return [
        {
            "key": "welcome",
            "label": "Welcome",
            "enabled": bool(
                settings.get("welcome_channel")
                or settings.get("goodbye_channel")
                or settings.get("autorole")
            ),
        },
        {
            "key": "moderation",
            "label": "Moderation",
            "enabled": bool(
                settings.get("log_channel")
                or settings.get("error_log_channel")
                or automod.get("invites")
                or automod.get("spam")
                or automod.get("badwords")
            ),
        },
        {"key": "levels", "label": "Levels", "enabled": bool(levels_settings.get("enabled"))},
        {"key": "voice", "label": "Voice reports", "enabled": bool(settings.get("voice_report_channel"))},
        {"key": "tickets", "label": "Tickets", "enabled": bool(settings.get("ticket_staff_role"))},
        {"key": "roles", "label": "Role panels", "enabled": bool(settings.get("role_panel_channel"))},
        {"key": "giveaways", "label": "Giveaways", "enabled": bool(settings.get("giveaway_channel"))},
        {"key": "ai", "label": "AI assistant", "enabled": bool(ai_settings.get("enabled"))},
        {"key": "economy", "label": "Economy", "enabled": bool(economy_settings.get("enabled"))},
        {
            "key": "updates",
            "label": "Updates",
            "enabled": bool(settings.get("update_channel") or settings.get("github_event_channel")),
        },
    ]
