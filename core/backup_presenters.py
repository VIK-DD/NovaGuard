"""Discord presentation helpers for backup status and restore guidance."""

from datetime import datetime

import discord

from .backups import (
    backup_max_expected_age_seconds,
    backup_schedule_label,
    human_size,
    remote_backup_config,
    remote_backup_status,
    remote_join,
)
from .config import BASE_DIR
from .privacy_ledger import LEDGER_PATH, REMOTE_LEDGER_PATH
from .theme import Palette, brand_footer, make_embed


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
            check_line = (
                f"\nRemote check: ✅ exists • "
                f"`{human_size(remote_check.get('bytes', 0))}`"
            )
        else:
            message = remote_check.get("message") or "not verified"
            check_line = f"\nRemote check: ⚠️ `{message[:120]}`"
    if not latest:
        return (
            f"Configured for `{destination}`, but no full upload has been "
            f"recorded yet.{guild_line}"
        )

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
        stale = (
            ""
            if status.get("matches_backup")
            else "\n⚠️ Latest local backup has not been confirmed off-site yet."
        )
        return (
            f"✅ `{backup_name}` uploaded to `{destination}`."
            f"{uploaded}{stale}{check_line}{guild_line}"
        )

    message = latest.get("message") or "Upload failed."
    return (
        f"⚠️ Last upload failed for `{backup_name}` to `{destination}`.\n"
        f"`{message[:180]}`{check_line}{guild_line}"
    )


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

        remote_check = (
            remote_status.get("latest_remote_check")
            or latest_remote.get("check")
            or {}
        )
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
    remote_check = (
        (status or {}).get("latest_remote_check") or latest.get("check") or {}
    )
    retention = (status or {}).get("latest_retention") or {}
    embed = make_embed(
        "☁️ Backup remote",
        (
            f"Destination: `{status.get('destination')}`\n"
            f"Full prefix: `{status.get('full_prefix')}`\n"
            f"Guild prefix: `{status.get('guild_prefix')}`\n"
            f"Retention: full `{status.get('full_keep_days')}` days • "
            f"guild `{status.get('guild_keep_days')}` days"
            if configured
            else "Remote backup is not configured. Set `BACKUP_REMOTE_DEST` "
            "after configuring `rclone`."
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
        failed = [
            target
            for target in targets
            if isinstance(target, dict) and not target.get("ok")
        ]
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
            export
            for export in guild_exports.get("exports", [])
            if isinstance(export, dict) and not export.get("ok")
        ][:5]
        failed_text = "\n".join(
            f"• `{item.get('guild_name')}` - `{item.get('message') or 'failed'}`"
            for item in failed
        )
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
            "No backup archives exist yet. Run `/backup create` or wait for the "
            "scheduled 07:00/19:00 backup.",
            color=Palette.WARNING,
        )
        brand_footer(embed, "Backup status")
        return embed

    checked_report = report or {}
    remote_status = remote_backup_status(latest["name"])
    health_score, health_label, health_lines = backup_health_summary(
        latest,
        checked_report,
        remote_status,
    )
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
        f"Showing newest `{len(backups)}` archive(s). Automatic pruning keeps the "
        "newest backups on disk.",
        color=Palette.INFO,
    )
    if not backups:
        embed.description = "No backup archives exist yet."
    else:
        lines = []
        for index, backup in enumerate(backups, start=1):
            lines.append(
                f"`#{index}` `{backup['name']}`\n"
                f"Size `{backup['size_text']}` • "
                f"{discord.utils.format_dt(backup['mtime'], 'R')}"
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
    extracted = report.get("extracted_files") or 0
    embed.add_field(
        name="Result",
        value=(
            f"{backup_integrity_line(report)}\n"
            f"SQLite: `{report.get('sqlite') or 'not included'}`\n"
            + (
                f"Unpacked `{extracted}` file(s), then removed them — "
                "nothing decrypted is left on disk."
                if extracted
                else "Not extracted."
            )
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


def deletion_ledger_text():
    """Explain why the restore requires a deletion ledger and where it lives."""
    lines = [
        f"The restore stops unless it can read `{LEDGER_PATH.name}`, which records who "
        "asked to be erased. Applying it is what stops an old archive putting their "
        "data back.",
        "",
        "**It is not inside the archive.** On this machine it is already in place.",
    ]

    config = remote_backup_config()
    if config["configured"]:
        remote_path = remote_join(config["destination"], REMOTE_LEDGER_PATH)
        lines += [
            "On a replacement host it will not exist yet — fetch the off-site copy "
            "first, then point the restore at it:",
            f"```bash\n{config['rclone_bin']} copyto \\\n"
            f"  {remote_path} \\\n"
            "  /tmp/deletion-ledger.ngbackup\n```",
            "and add `--encrypted-ledger /tmp/deletion-ledger.ngbackup` to the "
            "restore command below.",
        ]
    else:
        lines += [
            f"⚠️ No off-site destination is configured, so `{LEDGER_PATH}` is the "
            "**only** copy that exists. Losing this host loses it, and a restore "
            "afterwards cannot honour past erasure requests.",
        ]

    return "\n".join(lines)


def backup_restore_plan_embed(backup, report):
    scratch_block = (
        f"cd {BASE_DIR}\n"
        "pm2 stop 0\n"
        "mkdir -p data-before-restore\n"
        "cp -a data/. data-before-restore/\n"
        "rm -rf backups/restore-check\n"
        "venv/bin/python tools/restore_backup.py \\\n"
        f"  backups/{backup['name']} \\\n"
        "  --output backups/restore-check --replace"
    )
    golive_block = (
        "cp backups/restore-check/data/novaguard.sqlite3 data/novaguard.sqlite3\n"
        "cp backups/restore-check/data/*.json data/ 2>/dev/null || true\n"
        "cp backups/restore-check/.update_state.json . 2>/dev/null || true\n"
        "cp backups/restore-check/.github_state.json . 2>/dev/null || true\n"
        "pm2 restart 0 --update-env\n"
        "pm2 logs 0 --lines 100"
    )

    embed = make_embed(
        "🧭 Backup restore plan",
        "Nothing is restored automatically. Read the ledger note and both steps "
        "before running any of them — step 1 stops the bot.",
        color=Palette.INFO if report.get("ok") else Palette.WARNING,
    )
    embed.add_field(
        name="Selected archive",
        value=f"`{backup['name']}`\nIntegrity: `{backup_integrity_line(report)}`",
        inline=False,
    )
    embed.add_field(
        name="Before you start — the deletion ledger",
        value=deletion_ledger_text(),
        inline=False,
    )
    embed.add_field(
        name="1 · Stop, set the current data aside, unpack",
        value=f"```bash\n{scratch_block}\n```",
        inline=False,
    )
    embed.add_field(
        name="2 · Put the unpacked copy live",
        value=f"```bash\n{golive_block}\n```",
        inline=False,
    )
    embed.add_field(name="Notes", value=backup_errors_text(report), inline=False)
    brand_footer(embed, "Manual restore plan")
    return embed
