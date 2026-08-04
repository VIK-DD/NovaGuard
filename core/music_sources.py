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
import shutil
import time
from pathlib import Path

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
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_RESULT_TYPES = {"url", "url_transparent"}
YOUTUBE_EJS_FAILURE_MARKERS = (
    "signature solving failed",
    "n challenge solving failed",
    "only images are available",
    "requested format is not available",
)
_last_ejs_hint_at = 0.0


def _is_youtube_ejs_failure(message):
    text = (message or "").lower()
    return "[youtube]" in text and any(marker in text for marker in YOUTUBE_EJS_FAILURE_MARKERS)


def _maybe_log_youtube_ejs_hint(message):
    """Throttle a clear operator hint when yt-dlp cannot solve YouTube formats."""
    global _last_ejs_hint_at
    if not _is_youtube_ejs_failure(message):
        return
    now = time.monotonic()
    if now - _last_ejs_hint_at < 300:
        return
    _last_ejs_hint_at = now
    options = ydl_runtime_options()
    log.warning(
        "YouTube EJS challenge failed. Deno detected at %s; yt-dlp js_runtimes=%s; "
        "remote_components=%s. Install/update Deno and `yt-dlp[default]`, then restart PM2.",
        detected_deno_path() or "not found",
        options.get("js_runtimes") or "yt-dlp default",
        options.get("remote_components") or "disabled",
    )


class _YtDlpLogger:
    """Route yt-dlp's own output into the bot logger instead of raw stderr."""

    def debug(self, message):
        log.debug("yt-dlp: %s", message)

    def warning(self, message):
        _maybe_log_youtube_ejs_hint(message)
        log.warning("yt-dlp warning: %s", message)

    def error(self, message):
        _maybe_log_youtube_ejs_hint(message)
        log.warning("yt-dlp error: %s", message)


def _parse_cookies_from_browser(value):
    """Parse yt-dlp's Python API tuple from browser[:profile[:keyring[:container]]]."""
    parts = [part.strip() for part in (value or "").split(":")]
    return tuple(part for part in parts if part)


def _split_env_list(value):
    """Split comma/pipe separated env values without keeping empty fragments."""
    return [part.strip() for part in re.split(r"[,|]", value or "") if part.strip()]


def _parse_js_runtimes(value):
    """Parse runtime[:path] env values into yt-dlp's Python API shape."""
    runtimes = {}
    items = _split_env_list(value)
    for item in items:
        if len(items) == 1 and (item.startswith("/") or item.startswith("~")):
            runtimes["deno"] = {"path": os.path.expanduser(item)}
            continue
        name, _, path = item.partition(":")
        name = name.strip().lower()
        if not name:
            continue
        runtimes[name] = {"path": os.path.expanduser(path.strip()) if path.strip() else None}
    return runtimes


def detected_deno_path():
    """Find Deno even when PM2 does not inherit the user's shell PATH."""
    found = shutil.which("deno")
    if found:
        return found
    for candidate in (
        Path.home() / ".deno" / "bin" / "deno",
        Path("/home/ubuntu/.deno/bin/deno"),
        Path("/usr/local/bin/deno"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


def ydl_runtime_options():
    """Environment-driven yt-dlp options that should be read at call time."""
    options = {}
    cookies_file = os.getenv("MUSIC_YTDLP_COOKIES_FILE", "").strip()
    cookies_from_browser = os.getenv("MUSIC_YTDLP_COOKIES_FROM_BROWSER", "").strip()
    js_runtimes = (
        os.getenv("MUSIC_YTDLP_JS_RUNTIMES", "").strip()
        or os.getenv("MUSIC_YTDLP_JS_RUNTIME", "").strip()
    )
    remote_components = os.getenv("MUSIC_YTDLP_REMOTE_COMPONENTS", "").strip()
    if cookies_file:
        options["cookiefile"] = os.path.expanduser(cookies_file)
    if cookies_from_browser:
        options["cookiesfrombrowser"] = _parse_cookies_from_browser(cookies_from_browser)
    if js_runtimes:
        options["js_runtimes"] = _parse_js_runtimes(js_runtimes)
    else:
        deno_path = detected_deno_path()
        if deno_path:
            options["js_runtimes"] = {"deno": {"path": deno_path}}
    if remote_components:
        options["remote_components"] = _split_env_list(remote_components)
    return options


def soundcloud_fallback_enabled():
    value = os.getenv("MUSIC_ENABLE_SOUNDCLOUD_FALLBACK", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def search_providers():
    if soundcloud_fallback_enabled():
        return SEARCH_PROVIDERS
    return (SEARCH_PROVIDERS[0],)


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


def _youtube_watch_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def _entry_page_url(entry, source):
    for key in ("webpage_url", "original_url"):
        value = entry.get(key)
        if value:
            return value
    value = entry.get("url") or ""
    if source == "youtube":
        video_id = entry.get("id") or value
        if YOUTUBE_ID.match(video_id or ""):
            return _youtube_watch_url(video_id)
    return value if URL_START.match(value) else ""


def _entry_stream_url(entry):
    value = entry.get("url") or ""
    if entry.get("_type") in URL_RESULT_TYPES:
        return None
    return value if URL_START.match(value) else None


def track_from_entry(entry, requester_id, source):
    """Build a Track from one yt-dlp result.

    Defensive throughout: yt-dlp entries are loosely typed, and a field that
    is present for one extractor is absent or null for another. ``url`` holds an
    expiring CDN link, so ``webpage_url`` is preferred as the stable identity.
    """
    entry = entry or {}
    return Track(
        title=entry.get("title") or "Unknown track",
        url=_entry_page_url(entry, source),
        duration=int(entry.get("duration") or 0),
        source=source,
        requester_id=str(requester_id),
        thumbnail=entry.get("thumbnail"),
        uploader=entry.get("uploader") or entry.get("channel"),
        stream_url=_entry_stream_url(entry),
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
        for prefix, source_name in search_providers():
            info = await _extract(f"{prefix}{query}", flat=True)
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


async def soundcloud_fallback_for(track):
    """Find a SoundCloud candidate when a YouTube stream cannot be resolved."""
    if not soundcloud_fallback_enabled() or not track or track.source == "soundcloud":
        return None
    query = " ".join(part for part in (track.title, track.uploader or "") if part).strip()
    if not query:
        return None
    info = await _extract(f"scsearch1:{query}", flat=True)
    entries = (info or {}).get("entries") or []
    if not entries or not entries[0]:
        log.warning("Music SoundCloud rescue returned no entries for %r", query)
        return None
    return track_from_entry(entries[0], track.requester_id, "soundcloud")


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
