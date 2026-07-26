"""Public update feed: the frozen Discord archive plus the live engine history.

Read-only with respect to the changelog engine. This module never writes
.update_state.json and never calls into the announcement path, so serving the
feed cannot disturb what the bot posts to Discord.
"""

from datetime import datetime

from .config import BASE_DIR
from .storage import load_json_file

# `data/` is gitignored (it holds the live SQLite database), so the archive ships
# beside this module and reaches the Pi with an ordinary pull.
ARCHIVE_FILE = BASE_DIR / "core" / "updates_archive.json"
STAT_KEYS = ("added_lines", "removed_lines", "changed_files")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def load_archive():
    entries = load_json_file(ARCHIVE_FILE, [])
    return entries if isinstance(entries, list) else []


def _timestamp(value):
    """Sortable epoch seconds, or None when the value is not a usable date."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _bullets(value):
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def normalize_engine_entry(entry):
    """Reshape one engine history entry into a feed entry, or None if unusable.

    The engine records a single `summary` list; the feed exposes `changes`, so the
    page only ever handles the archive's shape.
    """
    if not isinstance(entry, dict):
        return None
    if _timestamp(entry.get("created_at")) is None:
        return None

    normalized = {"created_at": entry["created_at"]}
    if isinstance(entry.get("build"), int):
        normalized["build"] = entry["build"]
    for key in STAT_KEYS:
        if isinstance(entry.get(key), int):
            normalized[key] = entry[key]

    changes = _bullets(entry.get("summary")) or _bullets(entry.get("changes"))
    highlights = _bullets(entry.get("highlights"))
    if changes:
        normalized["changes"] = changes
    if highlights:
        normalized["highlights"] = highlights

    if not changes and not highlights and not any(key in normalized for key in STAT_KEYS):
        return None
    return normalized


def merged_update_feed(limit=DEFAULT_LIMIT, archive=None, history=None, latest=None):
    """Newest-first feed, deduplicated by `created_at`, capped at `limit`.

    The archive wins a collision: it is verified history, while the engine may
    re-record the same release after a state reset.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    archive_entries = load_archive() if archive is None else archive
    engine_entries = list(history or [])
    if latest:
        engine_entries.append(latest)

    feed = []
    seen = set()
    for entry in archive_entries:
        if not isinstance(entry, dict):
            continue
        created_at = entry.get("created_at")
        if _timestamp(created_at) is None or created_at in seen:
            continue
        seen.add(created_at)
        feed.append(entry)

    for raw in engine_entries:
        normalized = normalize_engine_entry(raw)
        if not normalized or normalized["created_at"] in seen:
            continue
        seen.add(normalized["created_at"])
        feed.append(normalized)

    feed.sort(key=lambda entry: _timestamp(entry.get("created_at")) or 0, reverse=True)
    return feed[:limit]
