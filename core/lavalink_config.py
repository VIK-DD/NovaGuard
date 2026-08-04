"""Configuration helpers for the Lavalink music backend."""

import os
import re

DEFAULT_LAVALINK_URI = "http://127.0.0.1:2333"
DEFAULT_LAVALINK_PASSWORD = "youshallnotpass"
DEFAULT_SEARCH_SOURCE = "ytmsearch"
URL_START = re.compile(r"^https?://", re.IGNORECASE)
SEARCH_PREFIX = re.compile(r"^[a-z][a-z0-9_]*search\d*:", re.IGNORECASE)


def lavalink_enabled():
    backend = os.getenv("MUSIC_BACKEND", "yt-dlp").strip().lower()
    return backend in {"lavalink", "lava", "ll"}


def lavalink_uri():
    return os.getenv("LAVALINK_URI", DEFAULT_LAVALINK_URI).strip() or DEFAULT_LAVALINK_URI


def lavalink_password():
    return (
        os.getenv("LAVALINK_PASSWORD", DEFAULT_LAVALINK_PASSWORD).strip()
        or DEFAULT_LAVALINK_PASSWORD
    )


def lavalink_search_source():
    source = os.getenv("MUSIC_LAVALINK_SEARCH_SOURCE", DEFAULT_SEARCH_SOURCE).strip().lower()
    source = source.rstrip(":")
    return source or DEFAULT_SEARCH_SOURCE


def lavalink_search_query(query):
    cleaned = (query or "").strip().strip("<>").strip()
    if URL_START.match(cleaned):
        return cleaned
    if SEARCH_PREFIX.match(cleaned):
        return cleaned
    return f"{lavalink_search_source()}:{cleaned}"


def lavalink_wavelink_search(query):
    """Return ``(query, source)`` for ``wavelink.Playable.search``.

    Wavelink adds the search prefix itself when ``source`` is provided. Passing
    a pre-prefixed query with the default source creates requests like
    ``ytmsearch:ytmsearch:song`` on Lavalink.
    """
    cleaned = (query or "").strip().strip("<>").strip()
    if URL_START.match(cleaned) or SEARCH_PREFIX.match(cleaned):
        return cleaned, None
    return cleaned, lavalink_search_source()
