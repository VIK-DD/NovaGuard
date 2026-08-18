"""🚀 Setup category — one-command onboarding and server configuration."""

import asyncio
import io
import json
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from core.backups import (
    backup_max_expected_age_seconds,
    backup_schedule_label,
    create_backup,
    human_size,
    inspect_backup,
    latest_backup,
    list_backups,
    refresh_latest_remote_check,
    remote_backup_status,
)
from cogs.admin import require_admin
from core.config import github_config
from core.privacy import export_guild_data
from core.storage import get_guild_settings, reset_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import defer_interaction, respond


CHANNEL_KEYS = {
    "update_channel": ("🚀 Bot Updates", "Automatic code changelog and restart summaries"),
    "github_event_channel": ("🐙 GitHub Feed", "Push, PR, issue and release activity"),
    "error_log_channel": ("🚨 Admin Errors", "Serious bot error digest embeds"),
    "log_channel": ("📋 Server Logs", "Deleted/edited messages, joins/leaves, bans"),
    "voice_report_channel": ("🎙️ Voice Reports", "Completed voice session attendance and duration reports"),
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

    # The panel is one message that rewrites itself, so the result of the last
    # action belongs at the top of it rather than in a separate reply.
    if notice:
        status = f"{notice}\n\n{status}"

    embed = make_embed(title, status, color=color)
    embed.add_field(
        name="Optional channels set",
        value=f"{progress_bar(done, total, slots=12)} `{ratio_text}` configured — all optional",
        inline=False,
    )

    core_lines = []
    for key in ("update_channel", "github_event_channel", "error_log_channel", "log_channel"):
        label, description = CHANNEL_KEYS[key]
        core_lines.append(f"{label}: {mention_channel(guild, settings.get(key))}\n`{description}`")
    embed.add_field(name="Core Channels", value="\n\n".join(core_lines), inline=False)

    community_lines = []
    for key in ("welcome_channel", "goodbye_channel", "voice_report_channel"):
        label, description = CHANNEL_KEYS[key]
        community_lines.append(f"{label}: {mention_channel(guild, settings.get(key))}\n`{description}`")
    autorole = settings.get("autorole")
    try:
        role = guild.get_role(int(autorole)) if autorole else None
    except (TypeError, ValueError):
        role = None
    community_lines.append(f"🎭 Auto-role: {role.mention if role else '`Not set`'}\n`Use /welcome set when you want an auto-role too`")
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
    embed.add_field(name="Privacy before enabling features", value=SETUP_PRIVACY_NOTICE, inline=False)
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
        lines.append(f"{label}: {mention_channel(guild, settings.get(key))}\n`{key}` • {description}")
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


def export_config_file(guild):
    """A server administrator's complete guild-scoped privacy export.

    The /backup group archives every guild at once and is the bot owner's,
    so this is how a single server takes its own data out - scoped by
    guild_id, with nothing from anyone else in it.
    """
    payload = export_guild_data(guild.id)
    payload["guild_name"] = guild.name
    data = json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")
    return discord.File(io.BytesIO(data), filename=f"novaguard-{guild.id}.json")


def backup_integrity_line(report):
    if not report:
        return "Not checked"
    if report["ok"]:
        return "✅ Ready to restore"
    return "⚠️ Needs attention"


def backup_errors_text(report):
    if not report:
        return "No integrity report available."
    if report["errors"]:
        return "\n".join(f"• {error}" for error in report["errors"][:5])
    if report["warnings"]:
        return "\n".join(f"• {warning}" for warning in report["warnings"][:5])
    return "No issues found."


def find_backup(name=None):
    backups = list_backups()
    if not name:
        return backups[0] if backups else None
    target = name.strip()
    for backup in backups:
        if backup["name"] == target:
            return backup
    return None


def backup_contents_text(report):
    included = report.get("included") or []
    if not included:
        return "No files found in archive."
    shown = included[:12]
    lines = [f"• `{item}`" for item in shown]
    if len(included) > len(shown):
        lines.append(f"• ...and `{len(included) - len(shown)}` more")
    return "\n".join(lines)


def backup_remote_text(status):
    if not status or not status.get("configured"):
        return "Not configured. Set `BACKUP_REMOTE_DEST` after configuring `rclone`."

    latest = status.get("latest") or {}
    guild_exports = status.get("latest_guild_exports") or {}
    remote_check = status.get("latest_remote_check") or latest.get("check") or {}
    destination = status.get("destination") or "remote storage"
    guild_line = ""
    if guild_exports:
        guild_line = (
            f"\nServer exports: `{guild_exports.get('uploaded', 0)}` uploaded • "
            f"`{guild_exports.get('failed', 0)}` failed"
        )
    check_line = ""
    if remote_check:
        if remote_check.get("ok"):
            check_line = f"\nRemote check: ✅ exists • `{human_size(remote_check.get('bytes', 0))}`"
        else:
            check_line = f"\nRemote check: ⚠️ `{(remote_check.get('message') or 'not verified')[:120]}`"
    if not latest:
        return f"Configured for `{destination}`, but no full upload has been recorded yet.{guild_line}"

    backup_name = latest.get("backup_name") or "unknown backup"
    if latest.get("ok"):
        uploaded_at = latest.get("uploaded_at")
        uploaded = ""
        if uploaded_at:
            try:
                uploaded_dt = datetime.fromisoformat(uploaded_at)
                uploaded = f"\nUploaded: {discord.utils.format_dt(uploaded_dt, 'R')}"
            except ValueError:
                uploaded = ""
        stale = "" if status.get("matches_backup") else "\n⚠️ Latest local backup has not been confirmed off-site yet."
        return f"✅ `{backup_name}` uploaded to `{destination}`.{uploaded}{stale}{check_line}{guild_line}"

    message = latest.get("message") or "Upload failed."
    return f"⚠️ Last upload failed for `{backup_name}` to `{destination}`.\n`{message[:180]}`{check_line}{guild_line}"


def backup_health_summary(latest, report=None, remote_status=None):
    report = report or {}
    remote_status = remote_status or {}
    score = 0
    lines = []

    if latest and report.get("encrypted"):
        score += 20
        lines.append("✅ Encrypted local archive exists")
    elif latest:
        score += 5
        lines.append("⚠️ Local archive is legacy plaintext")
    else:
        lines.append("⚠️ No local archive found")

    if report.get("ok") and report.get("sqlite") == "ok":
        score += 25
        lines.append("✅ Zip + SQLite integrity passed")
    elif report.get("ok"):
        score += 15
        lines.append("⚠️ Archive opens, SQLite not fully confirmed")
    elif report:
        lines.append("⚠️ Integrity check needs attention")
    else:
        lines.append("⚠️ Integrity check has not run yet")

    if latest:
        age_seconds = max((discord.utils.utcnow() - latest["mtime"]).total_seconds(), 0)
        if age_seconds <= backup_max_expected_age_seconds():
            score += 15
            lines.append(f"✅ Fresh for schedule `{backup_schedule_label()}`")
        else:
            lines.append(f"⚠️ Older than expected for `{backup_schedule_label()}`")

    if remote_status.get("configured"):
        latest_remote = remote_status.get("latest") or {}
        if latest_remote.get("ok") and remote_status.get("matches_backup"):
            score += 15
            lines.append("✅ Latest local backup matches Drive upload")
        elif latest_remote.get("ok"):
            lines.append("⚠️ Drive has an upload, but not the latest local archive")
        else:
            lines.append("⚠️ Latest Drive upload failed or is missing")

        remote_check = remote_status.get("latest_remote_check") or latest_remote.get("check") or {}
        if remote_check.get("ok"):
            score += 15
            lines.append("✅ Drive file existence check passed")
        else:
            lines.append("⚠️ Drive file existence check is not clean")

        guild_exports = remote_status.get("latest_guild_exports") or {}
        if guild_exports.get("uploaded", 0) and not guild_exports.get("failed", 0):
            score += 10
            lines.append("✅ Per-server exports uploaded")
        elif guild_exports:
            lines.append("⚠️ Per-server exports need attention")
        else:
            lines.append("⚠️ No per-server export batch recorded yet")
    else:
        lines.append("⚠️ Off-site Drive backup is not configured")

    if score >= 90:
        label = "Healthy"
    elif score >= 70:
        label = "Watch"
    else:
        label = "Risk"
    return min(score, 100), label, lines[:6]


def backup_remote_embed(status):
    configured = bool(status and status.get("configured"))
    latest = (status or {}).get("latest") or {}
    guild_exports = (status or {}).get("latest_guild_exports") or {}
    remote_check = (status or {}).get("latest_remote_check") or latest.get("check") or {}
    retention = (status or {}).get("latest_retention") or {}
    embed = make_embed(
        "☁️ Backup remote",
        (
            f"Destination: `{status.get('destination')}`\n"
            f"Full prefix: `{status.get('full_prefix')}`\n"
            f"Guild prefix: `{status.get('guild_prefix')}`\n"
            f"Retention: full `{status.get('full_keep_days')}` days • guild `{status.get('guild_keep_days')}` days"
            if configured
            else "Remote backup is not configured. Set `BACKUP_REMOTE_DEST` after configuring `rclone`."
        ),
        color=Palette.SUCCESS if configured and latest.get("ok") else Palette.WARNING,
    )
    if latest:
        embed.add_field(
            name="Latest full upload",
            value=(
                f"Backup: `{latest.get('backup_name')}`\n"
                f"Status: `{'ok' if latest.get('ok') else 'failed'}`\n"
                f"Remote path: `{latest.get('remote_path') or '-'}`\n"
                f"Message: `{(latest.get('message') or '-')[:180]}`"
            ),
            inline=False,
        )
    if remote_check:
        checked_at = remote_check.get("checked_at")
        checked_text = ""
        if checked_at:
            try:
                checked_dt = datetime.fromisoformat(checked_at)
                checked_text = f"\nChecked: {discord.utils.format_dt(checked_dt, 'R')}"
            except ValueError:
                checked_text = ""
        embed.add_field(
            name="Remote existence check",
            value=(
                f"Status: `{'ok' if remote_check.get('ok') else 'failed'}`\n"
                f"Exists: `{'yes' if remote_check.get('exists') else 'no'}`\n"
                f"Size: `{human_size(remote_check.get('bytes', 0))}`"
                f"{checked_text}\n"
                f"Message: `{(remote_check.get('message') or '-')[:180]}`"
            ),
            inline=False,
        )
    if retention:
        targets = retention.get("targets") or []
        failed = [target for target in targets if isinstance(target, dict) and not target.get("ok")]
        embed.add_field(
            name="Retention",
            value=(
                f"Enabled: `{'yes' if retention.get('enabled') else 'no'}`\n"
                f"Status: `{'ok' if retention.get('ok') else 'failed'}`\n"
                f"Targets: `{len(targets)}` checked • `{len(failed)}` failed\n"
                f"Message: `{(retention.get('message') or '-')[:180]}`"
            ),
            inline=False,
        )
    if guild_exports:
        failed = [
            export for export in guild_exports.get("exports", [])
            if isinstance(export, dict) and not export.get("ok")
        ][:5]
        failed_text = "\n".join(f"• `{item.get('guild_name')}` - `{item.get('message') or 'failed'}`" for item in failed)
        embed.add_field(
            name="Latest server exports",
            value=(
                f"Uploaded: `{guild_exports.get('uploaded', 0)}`\n"
                f"Failed: `{guild_exports.get('failed', 0)}`\n"
                f"Skipped: `{guild_exports.get('skipped', 0)}`"
                + (f"\n{failed_text}" if failed_text else "")
            ),
            inline=False,
        )
    brand_footer(embed, "Backup remote")
    return embed


def backup_status_embed(latest, report=None):
    if not latest:
        embed = make_embed(
            "🧳 Backup status",
            "No backup archives exist yet. Run `/backup create` or wait for the scheduled 07:00/19:00 backup.",
            color=Palette.WARNING,
        )
        brand_footer(embed, "Backup status")
        return embed

    checked_report = report or {}
    remote_status = remote_backup_status(latest["name"])
    health_score, health_label, health_lines = backup_health_summary(latest, checked_report, remote_status)
    embed = make_embed(
        "🧳 Backup status",
        f"Latest backup: `{latest['name']}`",
        color=Palette.SUCCESS if health_score >= 90 else Palette.WARNING,
    )
    embed.add_field(
        name="Archive",
        value=(
            f"Size: `{latest['size_text']}`\n"
            f"Created: {discord.utils.format_dt(latest['mtime'], 'F')} "
            f"({discord.utils.format_dt(latest['mtime'], 'R')})"
        ),
        inline=False,
    )
    embed.add_field(
        name="Integrity",
        value=(
            f"{backup_integrity_line(checked_report)}\n"
            f"Encrypted: `{'yes' if checked_report.get('encrypted') else 'no'}`\n"
            f"SQLite: `{checked_report.get('sqlite') or 'not included'}`\n"
            f"Files: `{len(checked_report.get('included', []))}` total • "
            f"`{len(checked_report.get('json_files', []))}` JSON checked"
        ),
        inline=False,
    )
    embed.add_field(
        name="Health score",
        value=f"`{health_score}/100` • **{health_label}**\n" + "\n".join(health_lines),
        inline=False,
    )
    embed.add_field(
        name="Off-site copy",
        value=backup_remote_text(remote_status),
        inline=False,
    )
    embed.add_field(name="Notes", value=backup_errors_text(checked_report), inline=False)
    brand_footer(embed, "Backup status")
    return embed


def backup_list_embed(backups):
    embed = make_embed(
        "🧳 Backup archives",
        f"Showing newest `{len(backups)}` archive(s). Automatic pruning keeps the newest backups on disk.",
        color=Palette.INFO,
    )
    if not backups:
        embed.description = "No backup archives exist yet."
    else:
        lines = []
        for index, backup in enumerate(backups, start=1):
            lines.append(
                f"`#{index}` `{backup['name']}`\n"
                f"Size `{backup['size_text']}` • {discord.utils.format_dt(backup['mtime'], 'R')}"
            )
        embed.add_field(name="Latest first", value="\n\n".join(lines), inline=False)
    brand_footer(embed, "Backup list")
    return embed


def backup_test_embed(latest, report):
    color = Palette.SUCCESS if report["ok"] else Palette.DANGER
    embed = make_embed(
        "🧪 Backup restore test",
        f"Checked `{latest['name']}` without touching live data.",
        color=color,
    )
    embed.add_field(
        name="Result",
        value=(
            f"{backup_integrity_line(report)}\n"
            f"SQLite: `{report.get('sqlite') or 'not included'}`\n"
            f"Extracted to: `{report.get('extract_path') or 'not extracted'}`"
        ),
        inline=False,
    )
    embed.add_field(name="Notes", value=backup_errors_text(report), inline=False)
    brand_footer(embed, "Backup restore test")
    return embed


def backup_inspect_embed(backup, report):
    embed = make_embed(
        "🔎 Backup inspect",
        f"Archive: `{backup['name']}`",
        color=Palette.SUCCESS if report.get("ok") else Palette.WARNING,
    )
    embed.add_field(
        name="Archive",
        value=(
            f"Size: `{backup['size_text']}`\n"
            f"Created: {discord.utils.format_dt(backup['mtime'], 'F')} "
            f"({discord.utils.format_dt(backup['mtime'], 'R')})\n"
            f"SQLite integrity: `{report.get('sqlite') or 'not included'}`"
        ),
        inline=False,
    )
    embed.add_field(name="Contents", value=backup_contents_text(report), inline=False)
    embed.add_field(name="Notes", value=backup_errors_text(report), inline=False)
    brand_footer(embed, "Backup inspect")
    return embed


def backup_restore_plan_embed(backup, report):
    command_block = (
        "cd ~/NovaGuard\n"
        "pm2 stop 0\n"
        "mkdir -p data-before-restore\n"
        "cp -a data/. data-before-restore/\n"
        "rm -rf backups/restore-check\n"
        f"venv/bin/python tools/restore_backup.py backups/{backup['name']} --output backups/restore-check --replace\n"
        "cp backups/restore-check/data/novaguard.sqlite3 data/novaguard.sqlite3\n"
        "cp backups/restore-check/data/*.json data/ 2>/dev/null || true\n"
        "cp backups/restore-check/.update_state.json . 2>/dev/null || true\n"
        "cp backups/restore-check/.github_state.json . 2>/dev/null || true\n"
        "pm2 restart 0 --update-env\n"
        "pm2 logs 0 --lines 100"
    )
    embed = make_embed(
        "🧭 Backup restore plan",
        "This does not restore anything automatically. Stop the bot first and run the commands only when you are sure.",
        color=Palette.INFO if report.get("ok") else Palette.WARNING,
    )
    embed.add_field(
        name="Selected archive",
        value=f"`{backup['name']}`\nIntegrity: `{backup_integrity_line(report)}`",
        inline=False,
    )
    embed.add_field(name="Commands", value=f"```bash\n{command_block[:920]}\n```", inline=False)
    embed.add_field(name="Notes", value=backup_errors_text(report), inline=False)
    brand_footer(embed, "Manual restore plan")
    return embed


def plain_label(key):
    """The menu label without its emoji, for reading inside a sentence."""
    label, _ = CHANNEL_KEYS[key]
    head, _, rest = label.partition(" ")
    return rest if rest and not head.isalnum() else label


class SetupTargetSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=plain_label(key), value=key, description=description[:100])
            for key, (_label, description) in CHANNEL_KEYS.items()
        ]
        super().__init__(
            placeholder="1. Choose what to configure…",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction):
        key = self.values[0]
        self.view.pending_key = key
        await self.view.refresh(
            interaction,
            f"Now pick a channel for **{plain_label(key)}** in the menu below.",
        )


class SetupChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="2. Choose a setting above first…",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            row=1,
            disabled=True,
        )

    async def callback(self, interaction):
        key = self.view.pending_key
        if not key:
            # The old panel defaulted to update_channel here and wrote there
            # without telling anyone. Refusing is the only honest answer.
            return await self.view.refresh(
                interaction, "Choose what to configure first, then pick its channel."
            )
        channel = self.values[0]
        await self.view.save(interaction, key, channel.id, channel.mention)


class SetupView(discord.ui.View):
    """One message that rewrites itself, holding all of its state in the open.

    Discord clears a select menu whenever the message is edited, so any state
    kept only in a variable goes invisible the moment the panel updates. That
    is what made the previous panel write a second channel over the first.
    Here the pending setting is always mirrored into the channel menu's label
    and into the embed, and it is cleared the instant a save lands.
    """

    def __init__(self):
        super().__init__(timeout=900)
        self.pending_key = None
        self.target_select = SetupTargetSelect()
        self.channel_select = SetupChannelSelect()
        self.add_item(self.target_select)
        self.add_item(self.channel_select)
        self._sync()

    def _sync(self):
        """Make the channel menu describe exactly what it is about to set."""
        if self.pending_key:
            self.channel_select.placeholder = f"2. Pick the channel for {plain_label(self.pending_key)}…"
            self.channel_select.disabled = False
        else:
            self.channel_select.placeholder = "2. Choose a setting above first…"
            self.channel_select.disabled = True

    async def refresh(self, interaction, notice=None):
        self._sync()
        await interaction.response.edit_message(
            embed=build_setup_embed(interaction.guild, notice=notice),
            view=self,
        )

    async def save(self, interaction, key, channel_id, mention):
        update_guild_settings(interaction.guild_id, **{key: channel_id})
        # Cleared before the redraw: a target that outlived its save is what
        # let the next channel picked silently replace the previous setting.
        self.pending_key = None
        await self.refresh(interaction, f"Saved **{plain_label(key)}** to {mention}.")

    async def interaction_check(self, interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Only members with **Manage Server** can use setup.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Use this channel", emoji="📍", style=discord.ButtonStyle.primary, row=2)
    async def use_this_channel(self, interaction, button):
        key = self.pending_key
        if not key:
            return await self.refresh(interaction, "Choose what to configure first.")
        # get_channel returns guild channels only, so a thread or a DM cannot
        # be saved as somewhere the bot will later post.
        channel = interaction.guild.get_channel(interaction.channel_id) if interaction.guild else None
        if channel is None:
            return await self.refresh(interaction, "Run `/setup` in a normal server text channel to use this.")
        await self.save(interaction, key, channel.id, channel.mention)

    @discord.ui.button(label="Clear", emoji="🗑️", style=discord.ButtonStyle.secondary, row=2)
    async def clear_selected(self, interaction, button):
        key = self.pending_key
        if not key:
            return await self.refresh(interaction, "Choose the setting you want to clear from the menu above.")
        update_guild_settings(interaction.guild_id, **{key: None})
        self.pending_key = None
        await self.refresh(interaction, f"Cleared **{plain_label(key)}**. It is now unset.")

    @discord.ui.button(label="Mark complete", emoji="✅", style=discord.ButtonStyle.success, row=2)
    async def mark_complete(self, interaction, button):
        update_guild_settings(interaction.guild_id, setup_completed=True)
        await self.refresh(
            interaction,
            "✅ Setup marked complete. Every channel stays optional — re-open `/setup` anytime.",
        )


class Setup(commands.Cog):
    """A friendly setup dashboard for new servers."""

    EMOJI = "🚀"
    COLOR = Palette.SUCCESS
    DESCRIPTION = "One-command onboarding and server configuration."

    config = app_commands.Group(
        name="config",
        description="Advanced NovaGuard configuration",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )
    backup = app_commands.Group(
        name="backup",
        description="NovaGuard backup safety tools",
        # These archive every guild at once, so they belong to the bot owner.
        # Discord cannot express "bot owner", and administrator is the
        # narrowest thing it offers: server admins still see them and are
        # refused by the owner check, ordinary members never see them.
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Open the NovaGuard setup dashboard")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup_command(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        await respond(interaction, build_setup_embed(interaction.guild), view=SetupView(), ephemeral=True)

    @config.command(name="view", description="View the saved NovaGuard configuration")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_view(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        await respond(interaction, build_config_embed(interaction.guild), ephemeral=True)

    @config.command(name="export", description="Export this server's NovaGuard config as JSON")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_export(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        embed = make_embed(
            "📦 Server export ready",
            "This file contains all live NovaGuard data scoped to this server. It never includes bot tokens or API keys.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Config export")
        await interaction.followup.send(embed=embed, file=export_config_file(interaction.guild), ephemeral=True)

    @config.command(name="backup", description="Create a manual backup archive now")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_backup(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        # Archives every guild's data, not just this one, so it is the bot
        # owner's to run. Server admins export their own guild with
        # /config export.
        if not await require_admin(interaction, self.bot, action="backup.create"):
            return
        backup = await self.bot.loop.run_in_executor(None, create_backup, "manual")
        embed = make_embed(
            "🧳 Backup created",
            f"`{backup['name']}`\nIncluded `{len(backup['included'])}` state file(s).",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Manual backup")
        await respond(interaction, embed, ephemeral=True)

    @backup.command(name="create", description="Create and verify a manual backup archive now")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_create(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.create"):
            return
        backup = await asyncio.to_thread(create_backup, "manual")
        latest = {
            "name": backup["name"],
            "size_text": backup["size_text"],
            "mtime": discord.utils.utcnow(),
        }
        embed = backup_status_embed(latest, backup["integrity"])
        embed.title = "🧳 Backup created"
        await respond(interaction, embed, ephemeral=True)

    @backup.command(name="status", description="Check the newest backup archive and restore readiness")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_status(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.status"):
            return
        latest = latest_backup()
        report = await asyncio.to_thread(inspect_backup, latest["path"]) if latest else None
        await respond(interaction, backup_status_embed(latest, report), ephemeral=True)

    @backup.command(name="remote", description="Show Google Drive/off-site backup upload status")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_remote(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        # Exposes the off-site destination path, which is worth protecting on
        # its own.
        if not await require_admin(interaction, self.bot, action="backup.remote"):
            return
        latest = latest_backup()
        current_status = remote_backup_status(latest["name"] if latest else None)
        if current_status.get("configured") and current_status.get("latest"):
            status = await asyncio.to_thread(refresh_latest_remote_check, latest["name"] if latest else None)
        else:
            status = current_status
        await respond(interaction, backup_remote_embed(status), ephemeral=True)

    @backup.command(name="list", description="List the newest backup archives")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_list(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.list"):
            return
        backups = await asyncio.to_thread(list_backups, 8)
        await respond(interaction, backup_list_embed(backups), ephemeral=True)

    @backup.command(name="inspect", description="Inspect a local backup archive without restoring it")
    @app_commands.describe(name="Backup archive name; leave empty for the latest backup")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_inspect(self, interaction: discord.Interaction, name: str | None = None):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.inspect"):
            return
        backup = await asyncio.to_thread(find_backup, name)
        if not backup:
            embed = make_embed(
                "Backup not found",
                "No matching local backup archive exists. Use `/backup list` to see available archives.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Backup inspect")
            return await respond(interaction, embed, ephemeral=True)
        report = await asyncio.to_thread(inspect_backup, backup["path"])
        await respond(interaction, backup_inspect_embed(backup, report), ephemeral=True)

    @backup.command(name="test", description="Extract and verify the newest backup without touching live data")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_test(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.test"):
            return
        latest = latest_backup()
        if not latest:
            return await respond(interaction, backup_status_embed(None), ephemeral=True)
        report = await asyncio.to_thread(inspect_backup, latest["path"], extract=True)
        await respond(interaction, backup_test_embed(latest, report), ephemeral=True)

    @backup.command(name="restore", description="Show a safe manual restore plan for a backup")
    @app_commands.describe(name="Backup archive name; leave empty for the latest backup")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_restore(self, interaction: discord.Interaction, name: str | None = None):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="backup.restore"):
            return
        backup = await asyncio.to_thread(find_backup, name)
        if not backup:
            embed = make_embed(
                "Backup not found",
                "No matching local backup archive exists. Use `/backup list` to see available archives.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Backup restore plan")
            return await respond(interaction, embed, ephemeral=True)
        report = await asyncio.to_thread(inspect_backup, backup["path"])
        await respond(interaction, backup_restore_plan_embed(backup, report), ephemeral=True)

    @config.command(name="reset", description="Reset NovaGuard setup/config for this server")
    @app_commands.describe(confirm="Set to true to confirm the reset")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_reset(self, interaction: discord.Interaction, confirm: bool = False):
        await defer_interaction(interaction, ephemeral=True)
        if not confirm:
            embed = make_embed(
                "⚠️ Reset confirmation needed",
                "Run `/config reset confirm:true` to clear saved setup channels/settings for this server.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Config reset")
            return await respond(interaction, embed, ephemeral=True)

        reset_guild_settings(interaction.guild_id)
        embed = make_embed(
            "🧹 Config reset",
            "Saved setup channels/settings were cleared. Run `/setup` to configure NovaGuard again.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Config reset")
        await respond(interaction, embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if not (perms.send_messages and perms.embed_links):
                continue

            try:
                await channel.send(embed=build_setup_embed(guild), view=SetupView())
            except discord.HTTPException:
                continue
            break


async def setup(bot):
    await bot.add_cog(Setup(bot))
