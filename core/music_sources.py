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


def parse_position(text):
    """Read a seek position like ``90``, ``1:30`` or ``1:02:03`` into seconds.

    The inverse of :func:`format_duration`, so whatever the player prints can
    be typed straight back. Returns None for anything unparseable rather than
    guessing, because seeking to the wrong spot is worse than refusing.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    parts = [part.strip() for part in cleaned.split(":")]
    if len(parts) > 3:
        return None

    total = 0
    for index, part in enumerate(parts):
        # Reject signs and decimals: only plain digits make sense per field.
        if not part.isdigit():
            return None
        value = int(part)
        # Past the leading field, anything above 59 is a typo rather than a
        # position - "1:75" means nothing, while a bare "75" is fine.
        if index > 0 and value > 59:
            return None
        total = total * 60 + value
    return total


def normalise_query(text):
    """Fold a query so trivially different spellings share a cache entry."""
    return " ".join((text or "").lower().split())


def search_cache_key(text):
    return f"search:{SEARCH_CACHE_VERSION}:{normalise_query(text)}"


def search_cache_prefix(text):
    return f"search:{SEARCH_CACHE_VERSION}:{normalise_query(text)}"


def stream_cache_key(url):
    return f"stream:{(url or '').strip()}"


def _fold_search_text(text):
    """Normalize search text across case, punctuation and Romanian diacritics."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.lower()
    folded = re.sub(r"[^a-z0-9]+", " ", folded)
    return " ".join(folded.split())


def _search_tokens(text):
    return [token for token in _fold_search_text(text).split() if len(token) > 1]


def _contains_phrase(haystack, phrase):
    return phrase in _fold_search_text(haystack)


def _entry_haystack(entry):
    return " ".join(
        str(part or "")
        for part in (
            entry.get("title"),
            entry.get("uploader"),
            entry.get("channel"),
            entry.get("artist"),
        )
    )


def search_entry_score(query, entry, source):
    """Score one search result. Higher is better; negative means unusable."""
    entry = entry or {}
    title = entry.get("title") or ""
    page_url = _entry_page_url(entry, source)
    if not title or not page_url:
        return -100.0

    query_folded = _fold_search_text(query)
    title_folded = _fold_search_text(title)
    haystack_folded = _fold_search_text(_entry_haystack(entry))
    query_tokens = _search_tokens(query)
    if not query_tokens:
        return -100.0

    matched = sum(1 for token in query_tokens if token in haystack_folded)
    coverage = matched / len(query_tokens)
    title_ratio = SequenceMatcher(None, query_folded, title_folded).ratio()
    score = (coverage * 58) + (title_ratio * 32)

    if source == "youtube":
        score += 8

    duration = int(entry.get("duration") or 0)
    if duration and duration > 900 and not any(term in query_folded for term in ("mix", "live", "concert")):
        score -= 12
    if duration and duration < 45:
        score -= 8

    for term in NEGATIVE_RESULT_TERMS:
        if term not in query_folded and _contains_phrase(title, term):
            score -= 8
    for term in POSITIVE_RESULT_TERMS:
        if term in query_folded and _contains_phrase(_entry_haystack(entry), term):
            score += 4

    view_count = int(entry.get("view_count") or 0)
    if view_count >= 1_000_000:
        score += 5
    elif view_count >= 100_000:
        score += 2

    return round(score, 3)


def best_search_entry(query, entries, source):
    """Pick the best candidate from a provider result page."""
    candidates = [
        (search_entry_score(query, entry, source), entry)
        for entry in (entries or [])
        if entry
    ]
    if not candidates:
        return None, -100.0
    score, entry = max(candidates, key=lambda item: item[0])
    return entry, score


# ── extraction ───────────────────────────────────────────────────────

import asyncio
import base64
from difflib import SequenceMatcher
import json
import logging
import urllib.parse
import urllib.request
import shutil
import time
import unicodedata
from pathlib import Path

from .database import cache_get, cache_put
from .music_queue import Track

log = logging.getLogger("novaguard.music")

EXTRACT_TIMEOUT_SECONDS = 20
SEARCH_TTL_SECONDS = 7 * 86400
STREAM_TTL_SECONDS = 6 * 3600
MAX_PLAYLIST_TRACKS = 100
HTTP_TIMEOUT_SECONDS = 10
SEARCH_CACHE_VERSION = "v3"
YOUTUBE_SEARCH_RESULTS = 8
SOUNDCLOUD_SEARCH_RESULTS = 5
SEARCH_PROVIDERS = (
    (f"ytsearch{YOUTUBE_SEARCH_RESULTS}:", "youtube"),
    (f"scsearch{SOUNDCLOUD_SEARCH_RESULTS}:", "soundcloud"),
)
MIN_SEARCH_SCORE = 28
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_RESULT_TYPES = {"url", "url_transparent"}
NEGATIVE_RESULT_TERMS = {
    "8d",
    "bass boosted",
    "cover",
    "instrumental",
    "karaoke",
    "live",
    "nightcore",
    "reaction",
    "reverb",
    "slowed",
    "speed up",
    "sped up",
    "tutorial",
}
POSITIVE_RESULT_TERMS = {
    "audio",
    "lyrics",
    "lyric",
    "official",
    "oficial",
    "videoclip",
    "video",
}
FFMPEG_HEADER_BLOCKLIST = {
    "accept-encoding",
    "connection",
    "content-length",
    "host",
    "range",
    "transfer-encoding",
}
YOUTUBE_EJS_FAILURE_MARKERS = (
    "signature solving failed",
    "n challenge solving failed",
    "only images are available",
    "requested format is not available",
)
# "Sign in to confirm you're not a bot" — matched on the prefix so both the
# straight and the curly apostrophe variants are caught.
YOUTUBE_BOT_CHECK_MARKERS = (
    "sign in to confirm",
)
BOT_CHECK_RECENT_WINDOW_SECONDS = 900
_last_ejs_hint_at = 0.0
_last_bot_check_hint_at = 0.0
_bot_check_seen_at = 0.0


def _is_youtube_ejs_failure(message):
    text = (message or "").lower()
    return "[youtube]" in text and any(marker in text for marker in YOUTUBE_EJS_FAILURE_MARKERS)


def _is_youtube_bot_check(message):
    text = (message or "").lower()
    return "[youtube]" in text and any(marker in text for marker in YOUTUBE_BOT_CHECK_MARKERS)


def youtube_bot_check_recent(window_seconds=BOT_CHECK_RECENT_WINDOW_SECONDS):
    """True when YouTube challenged this host within the recent window."""
    if _bot_check_seen_at <= 0:
        return False
    return (time.monotonic() - _bot_check_seen_at) < window_seconds


def _maybe_log_youtube_bot_check_hint(message):
    """Remember and explain YouTube's IP challenge, throttled for the logs."""
    global _last_bot_check_hint_at, _bot_check_seen_at
    if not _is_youtube_bot_check(message):
        return
    _bot_check_seen_at = time.monotonic()
    now = time.monotonic()
    if _last_bot_check_hint_at > 0 and now - _last_bot_check_hint_at < 300:
        return
    _last_bot_check_hint_at = now
    if configured_proxy():
        log.warning(
            "YouTube is challenging this host even through MUSIC_YTDLP_PROXY. "
            "Rotate the proxy exit IP or refresh MUSIC_YTDLP_COOKIES_FILE from a "
            "fresh browser session, then restart PM2."
        )
    else:
        log.warning(
            "YouTube is challenging this host IP ('Sign in to confirm you're not a bot'). "
            "Cookies and PO tokens rarely clear an IP-level flag; route music through a "
            "clean egress instead: set MUSIC_YTDLP_PROXY=http://user:pass@host:port in "
            ".env and restart PM2. See SETUP.md > Music."
        )


def _maybe_log_youtube_ejs_hint(message):
    """Throttle a clear operator hint when yt-dlp cannot solve YouTube formats."""
    global _last_ejs_hint_at
    if not _is_youtube_ejs_failure(message):
        return
    now = time.monotonic()
    if _last_ejs_hint_at > 0 and now - _last_ejs_hint_at < 300:
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
        _maybe_log_youtube_bot_check_hint(message)
        log.warning("yt-dlp warning: %s", message)

    def error(self, message):
        _maybe_log_youtube_ejs_hint(message)
        _maybe_log_youtube_bot_check_hint(message)
        log.warning("yt-dlp error: %s", message)


def _parse_cookies_from_browser(value):
    """Parse yt-dlp's Python API tuple from browser[:profile[:keyring[:container]]]."""
    parts = [part.strip() for part in (value or "").split(":")]
    return tuple(part for part in parts if part)


def _split_env_list(value):
    """Split comma/pipe separated env values without keeping empty fragments."""
    return [part.strip() for part in re.split(r"[,|]", value or "") if part.strip()]


def _split_extractor_specs(value):
    """Split extractor-arg specs on pipes/newlines; values may contain commas."""
    return [part.strip() for part in re.split(r"[|\n]", value or "") if part.strip()]


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


def _parse_extractor_args(value):
    """Parse `ie:key=value;other=value` into yt-dlp's Python API shape."""
    parsed = {}
    for spec in _split_extractor_specs(value):
        ie_key, separator, settings = spec.partition(":")
        ie_key = ie_key.strip()
        if not separator or not ie_key:
            continue
        bucket = parsed.setdefault(ie_key, {})
        for item in (part.strip() for part in settings.split(";")):
            if not item:
                continue
            key, has_value, raw_value = item.partition("=")
            key = key.strip().replace("-", "_")
            if not has_value or not key:
                continue
            bucket.setdefault(key, []).append(os.path.expanduser(raw_value.strip()))
    return parsed


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


def configured_proxy():
    """The music proxy URL from the environment, or empty when unset."""
    return os.getenv("MUSIC_YTDLP_PROXY", "").strip()


_non_http_proxy_warned = False


def ffmpeg_proxy_url():
    """Proxy FFmpeg must stream through, or None.

    YouTube CDN URLs are bound to the IP that resolved them, so when yt-dlp
    goes through a proxy the audio stream has to ride the same proxy. FFmpeg
    only tunnels through http(s) proxies; a socks:// value works for yt-dlp
    but would leave FFmpeg on the flagged IP, so it is refused loudly here.
    """
    global _non_http_proxy_warned
    proxy = configured_proxy()
    if not proxy:
        return None
    if proxy.lower().startswith(("http://", "https://")):
        return proxy
    if not _non_http_proxy_warned:
        _non_http_proxy_warned = True
        log.warning(
            "MUSIC_YTDLP_PROXY is not an http(s) URL; FFmpeg cannot stream YouTube "
            "through it and playback will 403. Use http://user:pass@host:port."
        )
    return None


def ydl_runtime_options(*, include_cookies=True):
    """Environment-driven yt-dlp options that should be read at call time."""
    options = {}
    proxy = configured_proxy()
    if proxy:
        options["proxy"] = proxy
    cookies_file = os.getenv("MUSIC_YTDLP_COOKIES_FILE", "").strip()
    cookies_from_browser = os.getenv("MUSIC_YTDLP_COOKIES_FROM_BROWSER", "").strip()
    js_runtimes = (
        os.getenv("MUSIC_YTDLP_JS_RUNTIMES", "").strip()
        or os.getenv("MUSIC_YTDLP_JS_RUNTIME", "").strip()
    )
    remote_components = os.getenv("MUSIC_YTDLP_REMOTE_COMPONENTS", "").strip()
    extractor_args = os.getenv("MUSIC_YTDLP_EXTRACTOR_ARGS", "").strip()
    if include_cookies and cookies_file:
        options["cookiefile"] = os.path.expanduser(cookies_file)
    if include_cookies and cookies_from_browser:
        options["cookiesfrombrowser"] = _parse_cookies_from_browser(cookies_from_browser)
    if js_runtimes:
        options["js_runtimes"] = _parse_js_runtimes(js_runtimes)
    else:
        deno_path = detected_deno_path()
        if deno_path:
            options["js_runtimes"] = {"deno": {"path": deno_path}}
    if remote_components:
        options["remote_components"] = _split_env_list(remote_components)
    if extractor_args:
        parsed_args = _parse_extractor_args(extractor_args)
        if parsed_args:
            options["extractor_args"] = parsed_args
    return options


def _env_enabled(name, default=False):
    value = os.getenv(name, "").strip().lower()
    if not value:
        return bool(default)
    return value not in {"0", "false", "no", "off"}


def configured_min_audio_bitrate():
    """Preferred minimum audio bitrate in kbps, or None when unset.

    This is a preference unless MUSIC_STRICT_MIN_AUDIO_BITRATE is enabled. A
    strict 320 kbps requirement would reject many healthy YouTube Opus streams,
    so the default keeps playback reliable and only prefers higher bitrate.
    """
    value = os.getenv("MUSIC_MIN_AUDIO_BITRATE_KBPS", "").strip()
    if not value:
        return None
    try:
        bitrate = int(value)
    except ValueError:
        return None
    return max(1, min(bitrate, 512))


def strict_min_audio_bitrate_enabled():
    return _env_enabled("MUSIC_STRICT_MIN_AUDIO_BITRATE", default=False)


def ydl_format_selector():
    """Prefer stable direct audio URLs before fragile HLS/DASH segment streams."""
    stable_audio = (
        "bestaudio"
        "[protocol!=m3u8]"
        "[protocol!=m3u8_native]"
        "[protocol!=http_dash_segments]"
    )
    any_audio = "bestaudio"
    minimum = configured_min_audio_bitrate()
    if not minimum:
        return f"{stable_audio}/{any_audio}/best"

    preferred_stable = f"{stable_audio}[abr>={minimum}]"
    preferred_any = f"{any_audio}[abr>={minimum}]"
    if strict_min_audio_bitrate_enabled():
        return f"{preferred_stable}/{preferred_any}"
    return f"{preferred_stable}/{preferred_any}/{stable_audio}/{any_audio}/best"


def soundcloud_fallback_enabled():
    return _env_enabled("MUSIC_ENABLE_SOUNDCLOUD_FALLBACK", default=False)


def search_providers():
    if youtube_bot_check_recent():
        # While YouTube is challenging this host its streams will not resolve,
        # so searching it only delays the answer. Go straight to SoundCloud,
        # whether or not the fallback flag is set: a degraded stream beats none.
        return (SEARCH_PROVIDERS[1],)
    if soundcloud_fallback_enabled():
        return SEARCH_PROVIDERS
    return (SEARCH_PROVIDERS[0],)


# `default_search` is deliberately unset: the search prefix is chosen in code
# so a query that happens to look like a URL cannot send yt-dlp somewhere
# unexpected.
YDL_OPTIONS = {
    "format": None,
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


def _entry_http_headers(entry):
    headers = entry.get("http_headers") or {}
    if not isinstance(headers, dict):
        return {}
    safe_headers = {}
    for name, value in headers.items():
        name = str(name or "").strip()
        value = str(value or "").strip()
        if (
            not name
            or name.lower() in FFMPEG_HEADER_BLOCKLIST
            or not value
            or "\n" in name
            or "\r" in name
            or "\n" in value
            or "\r" in value
        ):
            continue
        safe_headers[name] = value
    return safe_headers


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
        http_headers=_entry_http_headers(entry),
    )


def _blocking_extract(target, flat=False, include_cookies=True):
    """Run yt-dlp. Called only through asyncio.to_thread."""
    import yt_dlp

    options = dict(YDL_OPTIONS)
    options["format"] = ydl_format_selector()
    options.update(ydl_runtime_options(include_cookies=include_cookies))
    if flat:
        options["extract_flat"] = "in_playlist"
        options["noplaylist"] = False
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(target, download=False)


async def _extract(target, *, flat=False, include_cookies=True):
    """Extraction with the shared timeout, off the event loop.

    Returns None on any failure. This layer never raises: a dead link must not
    be able to take down a player loop.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_blocking_extract, target, flat, include_cookies),
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
    if not info and track.source == "youtube":
        log.warning("YouTube stream resolve failed with cookies; retrying without cookies for %s", track.url)
        info = await _extract(track.url, include_cookies=False)
    if not info:
        return False
    fresh = track_from_entry(info, track.requester_id, track.source)
    if not fresh.stream_url:
        return False
    track.stream_url = fresh.stream_url
    track.http_headers = fresh.http_headers
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
    if not info and platform == "youtube":
        log.warning("YouTube direct extraction failed with cookies; retrying without cookies for %s", text)
        info = await _extract(text, include_cookies=False)
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
        best_entry = None
        best_source = "youtube"
        best_score = -100.0
        for prefix, source_name in search_providers():
            info = await _extract(f"{prefix}{query}", flat=True, include_cookies=False)
            entries = (info or {}).get("entries") or []
            entry, score = best_search_entry(query, entries, source_name)
            if entry and score > best_score:
                best_entry = entry
                best_source = source_name
                best_score = score
            if entry:
                log.info(
                    "Music search provider %s best score %.1f for %r -> %s",
                    source_name,
                    score,
                    query,
                    entry.get("title") or entry.get("webpage_url") or entry.get("url"),
                )
            else:
                log.warning(
                    "Music search provider %s returned no usable entries for %r",
                    source_name,
                    query,
                )
        if not best_entry or best_score < MIN_SEARCH_SCORE:
            log.warning("Music search exhausted all providers for %r", query)
            continue
        cache_put(key, {**best_entry, "_source": best_source}, SEARCH_TTL_SECONDS)
        tracks.append(track_from_entry(best_entry, requester_id, best_source))
    return tracks


async def soundcloud_fallback_for(track):
    """Find a SoundCloud candidate when a YouTube stream cannot be resolved.

    Runs when the operator enabled the fallback, and also whenever YouTube is
    actively challenging this host — in that state the alternative to a
    SoundCloud stream is silence.
    """
    if not (soundcloud_fallback_enabled() or youtube_bot_check_recent()):
        return None
    if not track or track.source == "soundcloud":
        return None
    query = " ".join(part for part in (track.title, track.uploader or "") if part).strip()
    if not query:
        return None
    info = await _extract(f"scsearch{SOUNDCLOUD_SEARCH_RESULTS}:{query}", flat=True)
    entries = (info or {}).get("entries") or []
    entry, score = best_search_entry(query, entries, "soundcloud")
    if not entry or score < MIN_SEARCH_SCORE:
        log.warning("Music SoundCloud rescue returned no entries for %r", query)
        return None
    return track_from_entry(entry, track.requester_id, "soundcloud")


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
