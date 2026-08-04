"""Turning user input into playable tracks.

This module holds two very different halves. Everything above the extraction
section is pure string work with no I/O, so it is cheap to test exhaustively.
That matters because misreading a link is the most common way a music command
surprises someone. The extraction half wraps yt-dlp in later tasks.
"""

import re
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
SOUNDCLOUD_HOSTS = {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}
SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com"}

SPOTIFY_PATH = re.compile(r"^/(?:intl-[a-z]{2}/)?(track|playlist|album)/([A-Za-z0-9]+)")
URL_START = re.compile(r"^https?://", re.IGNORECASE)


def classify_input(text):
    """Decide what the user gave us.

    Returns ``(kind, platform, identifier)``. ``kind`` is "search", "track" or
    "playlist"; ``platform`` is "youtube", "soundcloud", "spotify" or None.
    Anything unrecognised degrades to a plain search rather than erroring.
    """
    cleaned = (text or "").strip().strip("<>").strip()
    if not URL_START.match(cleaned):
        return "search", None, cleaned

    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return "search", None, cleaned

    host = (parsed.netloc or "").lower()
    query = parse_qs(parsed.query or "")

    if host in YOUTUBE_HOSTS:
        # A watch URL that also carries `list` is someone playing one video
        # from a playlist; honour the video, not the whole list.
        if "list" in query and "v" not in query:
            return "playlist", "youtube", query["list"][0]
        return "track", "youtube", cleaned

    if host in SOUNDCLOUD_HOSTS:
        kind = "playlist" if "/sets/" in (parsed.path or "") else "track"
        return kind, "soundcloud", cleaned

    if host in SPOTIFY_HOSTS:
        match = SPOTIFY_PATH.match(parsed.path or "")
        if match:
            resource, identifier = match.group(1), match.group(2)
            return ("track" if resource == "track" else "playlist"), "spotify", identifier

    return "search", None, cleaned


def spotify_to_query(metadata):
    """Build the search terms that stand in for a Spotify track.

    Spotify permits no audio streaming to third-party apps, so a Spotify link
    can only ever name a song we then find elsewhere.
    """
    title = (metadata or {}).get("title") or ""
    artist = (metadata or {}).get("artist") or ""
    if artist and title:
        return f"{artist} - {title}"
    return title or artist or ""


def format_duration(seconds, live_label=None):
    """Render a track length.

    Zero renders as ``live_label`` when one is given, because a zero-length
    track from yt-dlp means a livestream.
    """
    total = int(seconds or 0)
    if total <= 0:
        return live_label if live_label else "0:00"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def normalise_query(text):
    """Fold a query so trivially different spellings share a cache entry."""
    return " ".join((text or "").lower().split())


def search_cache_key(text):
    return f"search:{normalise_query(text)}"


def stream_cache_key(url):
    return f"stream:{(url or '').strip()}"
