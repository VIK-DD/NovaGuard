"""Public update feed: the frozen Discord archive plus the live engine history.

Read-only with respect to the changelog engine. This module never writes
.update_state.json and never calls into the announcement path, so serving the
feed cannot disturb what the bot posts to Discord.
"""

import re
from datetime import datetime

from .config import BASE_DIR
from .storage import load_json_file

# `data/` is gitignored (it holds the live SQLite database), so the archive ships
# beside this module and reaches the Pi with an ordinary pull.
ARCHIVE_FILE = BASE_DIR / "core" / "updates_archive.json"
STAT_KEYS = ("added_lines", "removed_lines", "changed_files")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
LEADING_EMOJI = re.compile(r"^(?:[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\ufe0f\u200d]+\s*)+")


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
    bullets = []
    for item in value:
        text = LEADING_EMOJI.sub("", str(item)).strip()
        if text:
            bullets.append(text)
    return bullets


def _clean_feed_entry(entry):
    cleaned = dict(entry)
    # Preserve the classification before presentation cleanup removes the
    # leading release emoji used by the update engine.
    from .release_versions import is_significant

    cleaned["significant"] = is_significant(entry)
    changes = _bullets(cleaned.get("changes"))
    highlights = _bullets(cleaned.get("highlights"))
    if changes:
        cleaned["changes"] = changes
    else:
        cleaned.pop("changes", None)
    if highlights:
        cleaned["highlights"] = highlights
    else:
        cleaned.pop("highlights", None)
    return cleaned


def normalize_engine_entry(entry):
    """Reshape one engine history entry into a feed entry, or None if unusable.

    The engine records a single `summary` list; the feed exposes `changes`, so the
    page only ever handles the archive's shape.
    """
    if not isinstance(entry, dict):
        return None
    if _timestamp(entry.get("created_at")) is None:
        return None

    from .release_versions import is_significant

    normalized = {
        "created_at": entry["created_at"],
        # The public text is cleaned below, so carry this decision as data.
        "significant": is_significant(entry),
    }
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
    archive_cutoff = None
    for entry in archive_entries:
        if not isinstance(entry, dict):
            continue
        created_at = entry.get("created_at")
        stamp = _timestamp(created_at)
        if stamp is None or created_at in seen:
            continue
        seen.add(created_at)
        feed.append(_clean_feed_entry(entry))
        archive_cutoff = stamp if archive_cutoff is None else max(archive_cutoff, stamp)

    # The archive is the published record up to its newest entry, so the engine
    # only contributes the tail beyond it. Deduplicating by `created_at` alone is
    # not enough: the archive stamps a release with its Discord message time while
    # the engine stamps when it recorded it, seconds apart, so the same release
    # would otherwise appear twice under two timestamps.
    for raw in engine_entries:
        normalized = normalize_engine_entry(raw)
        if not normalized or normalized["created_at"] in seen:
            continue
        stamp = _timestamp(normalized["created_at"])
        if archive_cutoff is not None and stamp is not None and stamp <= archive_cutoff:
            continue
        seen.add(normalized["created_at"])
        feed.append(normalized)

    feed.sort(key=lambda entry: _timestamp(entry.get("created_at")) or 0, reverse=True)

    # Number every release by its chronological position, oldest = 1. The engine's
    # own counter restarted whenever its state file was reset, so its numbers
    # repeat and would run backwards against the archive. Renumbering here keeps a
    # single monotonic sequence across both sources, matching the positions the
    # archive file already carries, so the statically rendered page and the live
    # tail agree. It happens before the limit is applied, so `?limit=` never
    # changes the number a release is known by.
    total = len(feed)
    feed = [dict(entry, build=total - index) for index, entry in enumerate(feed)]
    return feed[:limit]
