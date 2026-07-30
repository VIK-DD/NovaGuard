#!/usr/bin/env python3
"""Recover a voice session report from a NovaGuard backup zip.

The bot now keeps failed voice reports in data/voice_pending_reports.json, but
older versions could lose a completed report when Discord timed out during send.
This script reconstructs one report from data/voice_sessions.json inside a
backup and queues it for /voice retry or automatic retry on restart.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def as_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def backup_voice_sessions(backup_path: Path):
    with zipfile.ZipFile(backup_path) as archive:
        try:
            raw = archive.read("data/voice_sessions.json")
        except KeyError as error:
            raise SystemExit(f"{backup_path} does not contain data/voice_sessions.json") from error
    return json.loads(raw.decode("utf-8"))


def finalize_session(session: dict, ended_at: datetime):
    for record in session.get("members", {}).values():
        joined_at = parse_time(record.get("joined_at"))
        if joined_at is None:
            continue
        record["total_seconds"] = float(record.get("total_seconds", 0)) + max(
            0,
            (ended_at - joined_at).total_seconds(),
        )
        record["joined_at"] = None
    session["updated_at"] = as_iso(ended_at)


def main():
    parser = argparse.ArgumentParser(description="Queue a lost voice report from a backup.")
    parser.add_argument("backup", type=Path, help="Path to novaguard-backup-*.zip")
    parser.add_argument("--guild-id", required=True, help="Discord guild id")
    parser.add_argument("--channel-id", required=True, help="Voice/stage channel id from the log")
    parser.add_argument(
        "--ended-at",
        default=None,
        help="ISO timestamp for session end. Defaults to now in UTC.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="NovaGuard data directory. Defaults to ./data",
    )
    args = parser.parse_args()

    ended_at = parse_time(args.ended_at) if args.ended_at else datetime.now(UTC)
    if ended_at is None:
        raise SystemExit("--ended-at must be an ISO timestamp, e.g. 2026-07-30T00:35:00+00:00")

    sessions = backup_voice_sessions(args.backup)
    guild_sessions = sessions.get(str(args.guild_id), {})
    session = guild_sessions.get(str(args.channel_id))
    if not session:
        available = ", ".join(sorted(guild_sessions)) or "none"
        raise SystemExit(f"No backup session for channel {args.channel_id}. Available channels: {available}")

    session = json.loads(json.dumps(session))
    finalize_session(session, ended_at)
    report_id = f"{args.channel_id}-{int(ended_at.timestamp())}"

    pending_path = args.data_dir / "voice_pending_reports.json"
    pending = load_json(pending_path, {})
    guild_pending = pending.setdefault(str(args.guild_id), {})
    guild_pending[report_id] = {
        "id": report_id,
        "guild_id": str(args.guild_id),
        "channel_id": str(args.channel_id),
        "channel_name": session.get("channel_name", f"Voice #{args.channel_id}"),
        "ended_at": as_iso(ended_at),
        "session": session,
        "attempts": 0,
        "last_error": None,
    }
    save_json(pending_path, pending)

    print(f"Queued voice report {report_id} in {pending_path}")
    print("Restart the bot, or run /voice retry after the new code is deployed.")


if __name__ == "__main__":
    main()
