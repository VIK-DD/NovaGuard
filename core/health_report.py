"""Storage health lines for /doctor.

Lifted out of cogs/system.py unchanged. That cog runs past thirteen hundred
lines around four background loops, and this part of it needs neither Discord
nor a running bot — only the filesystem — so it is far cheaper to test from
here than through a slash command.
"""

import json
from datetime import UTC, datetime

from core.backups import (
    BACKUP_DIR,
    backup_max_expected_age_seconds,
    backup_schedule_label,
    inspect_backup,
    latest_backup,
    list_backups,
)
from core.config import GITHUB_STATE_FILE, UPDATE_STATE_FILE
from core.database import DB_PATH
from core.storage import DATA_DIR
from core.utils import format_timedelta, truncate


def ok_line(label, details=""):
    return f"✅ **{label}**" + (f" — {details}" if details else "")


def warn_line(label, details=""):
    return f"⚠️ **{label}**" + (f" — {details}" if details else "")


def info_line(label, details=""):
    return f"ℹ️ **{label}**" + (f" — {details}" if details else "")


def fail_line(label, details=""):
    return f"❌ **{label}**" + (f" — {details}" if details else "")


def clamp_field(lines, limit=1010):
    """Join report lines into something an embed field will accept.

    Discord rejects an empty field value, hence the stand-in text.
    """
    value = "\n".join(lines) if lines else "No checks were run."
    return value if len(value) <= limit else value[: limit - 3] + "..."


def json_file_status(path, label):
    if not path.exists():
        return warn_line(label, "not created yet")
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fail_line(label, "invalid JSON")
    except OSError as error:
        return fail_line(label, truncate(str(error), 80))
    return ok_line(label, "valid JSON")


def storage_health_lines():
    lines = [
        ok_line("SQLite database", "ready") if DB_PATH.exists() else info_line("SQLite database", "will be created on first setup"),
        json_file_status(UPDATE_STATE_FILE, ".update_state.json"),
        json_file_status(GITHUB_STATE_FILE, ".github_state.json"),
    ]

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe_file = DATA_DIR / ".doctor_write_test.tmp"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
        lines.append(ok_line("data/", "writable"))
    except OSError as error:
        lines.append(fail_line("data/", truncate(str(error), 80)))

    data_files = sorted(DATA_DIR.glob("*.json")) if DATA_DIR.exists() else []
    if not data_files:
        lines.append(warn_line("feature data", "no JSON files yet"))
        return lines

    broken = []
    for path in data_files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            broken.append(path.name)

    if broken:
        lines.append(fail_line("feature data", "broken: " + ", ".join(broken[:5])))
    else:
        lines.append(ok_line("feature data", f"{len(data_files)} JSON file(s) valid"))

    backup_count = len(list_backups()) if BACKUP_DIR.exists() else 0
    newest_backup = latest_backup()
    if newest_backup:
        age = datetime.now(UTC) - newest_backup["mtime"]
        integrity = inspect_backup(newest_backup["path"])
        details = (
            f"{backup_count} archive(s), latest {format_timedelta(age)} ago, "
            f"{newest_backup['size_text']}, scheduled {backup_schedule_label()}"
        )
        if not integrity["ok"]:
            lines.append(fail_line("backups", details + " — integrity check failed"))
        elif age.total_seconds() > backup_max_expected_age_seconds():
            lines.append(warn_line("backups", details + " — latest backup is older than expected"))
        else:
            lines.append(ok_line("backups", details))
    else:
        lines.append(warn_line("backups", f"none yet, scheduled {backup_schedule_label()}"))
    return lines
