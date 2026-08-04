"""Turning user input into playable tracks.

This module holds two very different halves. Everything above the extraction
section is pure string work with no I/O, so it is cheap to test exhaustively.
That matters because misreading a link is the most common way a music command
surprises someone. The extraction half wraps yt-dlp in later tasks.
"""

import os
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


def spotify_credentials_configured():
    return bool(
        os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        and os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    )


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


# ── extraction ───────────────────────────────────────────────────────

import asyncio
import base64
import json
import logging
import urllib.parse
import urllib.request

from .database import cache_get, cache_put
from .music_queue import Track

log = logging.getLogger("novaguard.music")

EXTRACT_TIMEOUT_SECONDS = 20
SEARCH_TTL_SECONDS = 7 * 86400
STREAM_TTL_SECONDS = 6 * 3600
MAX_PLAYLIST_TRACKS = 100
HTTP_TIMEOUT_SECONDS = 10
SEARCH_PROVIDERS = (
    ("ytsearch1:", "youtube"),
    ("scsearch1:", "soundcloud"),
)


class _YtDlpLogger:
    """Route yt-dlp's own output into the bot logger instead of raw stderr."""

    def debug(self, message):
        log.debug("yt-dlp: %s", message)

    def warning(self, message):
        log.warning("yt-dlp warning: %s", message)

    def error(self, message):
        log.warning("yt-dlp error: %s", message)


def _parse_cookies_from_browser(value):
    """Parse yt-dlp's Python API tuple from browser[:profile[:keyring[:container]]]."""
    parts = [part.strip() for part in (value or "").split(":")]
    return tuple(part for part in parts if part)


def ydl_runtime_options():
    """Environment-driven yt-dlp options that should be read at call time."""
    options = {}
    cookies_file = os.getenv("MUSIC_YTDLP_COOKIES_FILE", "").strip()
    cookies_from_browser = os.getenv("MUSIC_YTDLP_COOKIES_FROM_BROWSER", "").strip()
    if cookies_file:
        options["cookiefile"] = os.path.expanduser(cookies_file)
    if cookies_from_browser:
        options["cookiesfrombrowser"] = _parse_cookies_from_browser(cookies_from_browser)
    return options


# `default_search` is deliberately unset: the search prefix is chosen in code
# so a query that happens to look like a URL cannot send yt-dlp somewhere
# unexpected.
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "extract_flat": False,
    "socket_timeout": 15,
    "retries": 1,
    "ignoreerrors": True,
    "logger": _YtDlpLogger(),
    # IPv6-first resolution often stalls on small VPS hosts.
    "source_address": "0.0.0.0",
}


def track_from_entry(entry, requester_id, source):
    """Build a Track from one yt-dlp result.

    Defensive throughout: yt-dlp entries are loosely typed, and a field that
    is present for one extractor is absent or null for another. ``url`` holds an
    expiring CDN link, so ``webpage_url`` is preferred as the stable identity.
    """
    entry = entry or {}
    return Track(
        title=entry.get("title") or "Unknown track",
        url=entry.get("webpage_url") or entry.get("original_url") or entry.get("url") or "",
        duration=int(entry.get("duration") or 0),
        source=source,
        requester_id=str(requester_id),
        thumbnail=entry.get("thumbnail"),
        uploader=entry.get("uploader") or entry.get("channel"),
        stream_url=entry.get("url"),
    )


def _blocking_extract(target, flat=False):
    """Run yt-dlp. Called only through asyncio.to_thread."""
    import yt_dlp

    options = dict(YDL_OPTIONS)
    options.update(ydl_runtime_options())
    if flat:
        options["extract_flat"] = "in_playlist"
        options["noplaylist"] = False
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(target, download=False)


async def _extract(target, *, flat=False):
    """Extraction with the shared timeout, off the event loop.

    Returns None on any failure. This layer never raises: a dead link must not
    be able to take down a player loop.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_blocking_extract, target, flat),
            timeout=EXTRACT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning("Music extraction timed out for %s", target)
        return None
    except Exception as error:
        log.warning("Music extraction failed for %s: %r", target, error)
        return None


async def refresh_stream_url(track):
    """Re-resolve a track whose CDN link expired. Returns True on success."""
    if not track.url:
        return False
    info = await _extract(track.url)
    if not info:
        return False
    fresh = track_from_entry(info, track.requester_id, track.source)
    if not fresh.stream_url:
        return False
    track.stream_url = fresh.stream_url
    return True


async def extract(text, requester_id):
    """Resolve user input into playable tracks.

    Returns a list, empty when nothing could be resolved. Search results are
    cached for a week; the expiring stream link inside a cached entry is never
    trusted, so the player refreshes it before playing.
    """
    kind, platform, identifier = classify_input(text)

    if kind == "search" or platform == "spotify":
        return await _extract_by_search(kind, platform, identifier, requester_id)

    if kind == "playlist":
        target = f"https://www.youtube.com/playlist?list={identifier}" if platform == "youtube" else text
        info = await _extract(target, flat=True)
        entries = [entry for entry in ((info or {}).get("entries") or []) if entry][:MAX_PLAYLIST_TRACKS]
        if not entries:
            log.warning("Music playlist extraction returned no entries for %s", target)
        return [track_from_entry(entry, requester_id, platform) for entry in entries]

    info = await _extract(text)
    if not info:
        log.warning("Music track extraction returned no info for %s", text)
        return []
    return [track_from_entry(info, requester_id, platform or "youtube")]


async def _extract_by_search(kind, platform, identifier, requester_id):
    """Search YouTube for a query, or for the song a Spotify link names."""
    if platform == "spotify":
        metadata = await resolve_spotify(kind, identifier)
        queries = [query for query in (spotify_to_query(item) for item in metadata) if query]
    else:
        queries = [identifier] if identifier else []

    tracks = []
    for query in queries[:MAX_PLAYLIST_TRACKS]:
        key = search_cache_key(query)
        cached = cache_get(key)
        if cached:
            tracks.append(track_from_entry(cached, requester_id, cached.get("_source") or "youtube"))
            continue
        entry = None
        source = "youtube"
        for prefix, source_name in SEARCH_PROVIDERS:
            info = await _extract(f"{prefix}{query}")
            entries = (info or {}).get("entries") or []
            if entries and entries[0]:
                entry = entries[0]
                source = source_name
                break
            log.warning(
                "Music search provider %s returned no entries for %r",
                source_name,
                query,
            )
        if not entry:
            log.warning("Music search exhausted all providers for %r", query)
            continue
        cache_put(key, {**entry, "_source": source}, SEARCH_TTL_SECONDS)
        tracks.append(track_from_entry(entry, requester_id, source))
    return tracks


def _fetch_json(url, headers=None, data=None):
    """Blocking HTTP GET/POST returning parsed JSON. Only via to_thread."""
    request = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.load(response)


async def resolve_spotify(kind, identifier):
    """Spotify metadata as ``[{"title", "artist"}]``.

    Spotify permits no audio streaming to third-party apps. Without
    credentials, a single track still resolves through public oEmbed; playlists
    return nothing until the Web API credentials are configured.
    """
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    has_credentials = spotify_credentials_configured()

    if kind == "track" and not has_credentials:
        link = f"https://open.spotify.com/track/{identifier}"
        url = "https://open.spotify.com/oembed?url=" + urllib.parse.quote(link, safe="")
        try:
            oembed = await asyncio.to_thread(_fetch_json, url)
        except Exception as error:
            log.warning("Spotify oEmbed lookup failed: %r", error)
            return []
        return [{"title": oembed.get("title") or "", "artist": ""}]

    if not has_credentials:
        return []

    try:
        auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        token_payload = await asyncio.to_thread(
            _fetch_json,
            "https://accounts.spotify.com/api/token",
            {
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            b"grant_type=client_credentials",
        )
        token = token_payload.get("access_token")
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token}"}

        if kind == "track":
            data = await asyncio.to_thread(
                _fetch_json, f"https://api.spotify.com/v1/tracks/{identifier}", headers
            )
            items = [data]
        else:
            data = await asyncio.to_thread(
                _fetch_json,
                f"https://api.spotify.com/v1/playlists/{identifier}/tracks"
                f"?limit={MAX_PLAYLIST_TRACKS}",
                headers,
            )
            items = [row.get("track") for row in (data.get("items") or []) if row.get("track")]
    except Exception as error:
        log.warning("Spotify API lookup failed: %r", error)
        return []

    return [
        {
            "title": item.get("name") or "",
            "artist": ", ".join(artist.get("name", "") for artist in (item.get("artists") or [])),
        }
        for item in items
        if item
    ]
