"""Embedded web API for the NovaGuard dashboard — hardened edition.

Runs an aiohttp server inside the bot process so the website can read and
write the same per-guild settings the slash commands use.

Security & contract model
-------------------------
- Discord OAuth2 (identify + guilds); only members with Manage Server on a
  guild the bot is in may read or change that guild's config.
- Sessions live in SQLite (data/novaguard.sqlite3) and survive restarts.
  The cookie holds a random 256-bit id; the database stores only its SHA-256
  hash, so a leaked database cannot be replayed as a login.
- OAuth access/refresh tokens are encrypted at rest (Fernet, key derived from
  the client secret) when `cryptography` is available, and are refreshed
  automatically and revoked on logout.
- The OAuth `state` is a self-verifying HMAC token (double-submit cookie), so
  the login flow survives a bot restart without any server-side memory.
- Per-IP sliding-window rate limits (separate buckets for auth / read / write),
  keyed off the real client IP (CF-Connecting-IP behind a trusted proxy).
- Every dashboard change is written to a SQL audit trail (who, what, when, ip)
  and mirrored to the guild's log channel.
- Uniform response envelope: two middlewares stamp security + CORS headers on
  every response and turn any error (ApiError, 404, unexpected) into a JSON
  body `{"error": ..., "code": ...}` with a machine-readable code.
- Mutating requests (PUT/POST) are additionally guarded by an Origin check.
- Routes are served under /api/v1/... with legacy /api/... aliases.

Enable with WEB_ENABLED=true plus DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from . import shop
from .ai_settings import resolve_ai, validate_ai
from .api_security import API_CONTENT_SECURITY_POLICY
from .automod_settings import resolve_automod, validate_automod
from .config import BOT_CODENAME, BOT_RUNTIME_VERSION, github_config
from .database import (
    count_open_tickets,
    get_role_panel_record,
    list_ticket_records,
    list_role_panel_records,
    load_economy_data,
    load_levels_data,
    load_voice_store,
    save_role_panel_record,
)
from .economy_settings import resolve_economy, validate_economy
from .invite_permissions import DEFAULT_INVITE_PERMISSIONS
from .level_curve import level_from_xp
from .levels_settings import resolve_levels, validate_levels
from .maintenance import (
    DEFAULT_MAINTENANCE_MESSAGE,
    load_maintenance_state,
    verify_preview_code,
)
from .release_versions import current_project_release
from .storage import get_guild_settings, update_guild_settings
from .update_feed import merged_update_feed
from .updates import load_update_state
from .web_storage import (
    _CIPHER,
    db_add_audit,
    db_delete_session,
    db_gc,
    db_get_audit,
    db_load_session,
    db_ping,
    db_save_session,
    db_touch_session,
    init_web_tables,
)

log = logging.getLogger("novaguard.web")

# ── configuration ────────────────────────────────────────────────────

WEB_ENABLED = os.getenv("WEB_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8300") or 8300)
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
OAUTH_REDIRECT = os.getenv("WEB_OAUTH_REDIRECT", f"http://localhost:{WEB_PORT}/api/auth/callback")
# Comma-separated allow-list of browser origins. Empty ⇒ no cross-origin access
# is granted at all (same-origin only) — never a wildcard reflection.
CORS_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.getenv("WEB_CORS_ORIGIN", "").split(",")
    if origin.strip()
}
AFTER_LOGIN = os.getenv("WEB_AFTER_LOGIN", "/api/me")
# Where Discord sends someone once they finish adding the bot to a server.
#
# Opt-in, and deliberately so: Discord rejects the entire authorize URL with
# "Invalid OAuth2 redirect_uri" unless the exact value is registered in the
# application's OAuth2 → Redirects list. Defaulting this to a guess would
# break the invite link on every install that has not registered it, so an
# empty value keeps the old behaviour - Discord ends on its own "Authorized"
# screen, exactly as before.
INVITE_REDIRECT = os.getenv("WEB_INVITE_REDIRECT", "").strip()
# Once the bot is in, send them somewhere useful. The post-login destination
# is already configured and already points at the dashboard, so it is the
# sane default rather than a second thing to set up.
AFTER_INVITE = os.getenv("WEB_AFTER_INVITE", "").strip() or AFTER_LOGIN


def after_login_strands_user(after_login=None, cors_origins=None):
    """True when the post-login redirect cannot land on a cross-origin dashboard.

    `WEB_AFTER_LOGIN` is handed to the browser verbatim as a `Location`, so a
    bare path resolves against *this API's* origin. That is right for a
    single-origin setup, but a non-empty `WEB_CORS_ORIGIN` declares that the
    dashboard lives elsewhere — and then the path strands the user on an API
    URL: raw JSON for `/api/me`, a 404 body for anything else.

    Worth warning about loudly, because the symptom lies about its cause. It
    only bites the first login: afterwards the session cookie is already set,
    so the user reaches the dashboard on their own and everything works. That
    reads as a flaky login rather than a misconfigured one.
    """
    target = AFTER_LOGIN if after_login is None else after_login
    origins = CORS_ORIGINS if cors_origins is None else cors_origins
    return bool(origins) and not target.lower().startswith(("http://", "https://"))
COOKIE_SECURE = os.getenv("WEB_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}
# Cookie SameSite policy. "Lax" works when the dashboard is same-site as the API
# (including subdomains of one registrable domain). Use "None" for a dashboard on
# a different domain — browsers require Secure for SameSite=None, so we force it.
COOKIE_SAMESITE = (os.getenv("WEB_COOKIE_SAMESITE", "Lax").strip().capitalize() or "Lax")
if COOKIE_SAMESITE not in {"Lax", "Strict", "None"}:
    COOKIE_SAMESITE = "Lax"
if COOKIE_SAMESITE == "None":
    COOKIE_SECURE = True
_TRUST_PROXY_REQUESTED = os.getenv("WEB_TRUST_PROXY", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Forwarded client addresses are trustworthy only when the API cannot also be
# reached directly. Cloudflare Tunnel connects through loopback; a public bind
# would let any client forge CF-Connecting-IP and evade per-address controls.
TRUST_PROXY = _TRUST_PROXY_REQUESTED and WEB_HOST in {"127.0.0.1", "::1", "localhost"}
INVITE_PERMISSIONS = (
    os.getenv("WEB_INVITE_PERMISSIONS", DEFAULT_INVITE_PERMISSIONS).strip()
    or DEFAULT_INVITE_PERMISSIONS
)

API_PREFIX = "/api/v1"
LEGACY_PREFIX = "/api"
DISCORD_API = "https://discord.com/api/v10"
SESSION_COOKIE = "ng_session"
STATE_COOKIE = "ng_state"
SESSION_TTL = 7 * 24 * 3600
STATE_TTL = 600
GUILDS_CACHE_SECONDS = 120
DISCORD_DNS_CACHE_SECONDS = 300
DISCORD_REQUEST_TIMEOUT_SECONDS = 10
MAX_BODY_BYTES = 64 * 1024
MANAGE_GUILD = 0x20

RATE_LIMITS = {  # scope: (max requests, window seconds)
    "auth": (10, 60),
    "read": (120, 60),
    "write": (30, 60),
}

CHANNEL_KEYS = (
    "welcome_channel",
    "goodbye_channel",
    "log_channel",
    "voice_report_channel",
    "update_channel",
    "github_event_channel",
    "error_log_channel",
)
NATIVE_MANAGER_CHANNEL_KEYS = (
    "ticket_panel_channel",
    "role_panel_channel",
    "giveaway_channel",
)
CONFIG_CHANNEL_KEYS = CHANNEL_KEYS + NATIVE_MANAGER_CHANNEL_KEYS
ROLE_KEYS = ("autorole", "ticket_staff_role")
DASHBOARD_VOICE_HISTORY_LIMIT = 5
DASHBOARD_LEADERBOARD_LIMIT = 5

# HMAC key for signing OAuth state tokens. Reuses the client secret so it needs
# no extra configuration; a per-process random fallback keeps things sane when
# OAuth is not configured (login is disabled in that case anyway).
_STATE_SECRET = (CLIENT_SECRET or secrets.token_urlsafe(32)).encode("utf-8")


def count_visible_commands(tree):
    """How many commands Discord shows when someone types "/".

    walk_commands() counted every node — groups and the leaves inside them —
    giving 131. get_commands() returns the top-level entries, which is what
    Discord actually registers and what a person sees in the command picker:
    /backup appears once there, not as its eight subcommands. That number is
    81, and it matches what the bot logs as "synced N slash commands".
    """
    return sum(1 for _ in tree.get_commands())


# ── errors ───────────────────────────────────────────────────────────

class ApiError(Exception):
    """A client-facing error with an HTTP status and a machine-readable code."""

    _DEFAULT_CODES = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        429: "rate_limited",
        500: "internal_error",
        502: "upstream_error",
        503: "unavailable",
    }

    def __init__(self, status, message, code=None, retry_after=None, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code or self._DEFAULT_CODES.get(status, "error")
        self.retry_after = retry_after
        self.details = details


# ── the server ───────────────────────────────────────────────────────

class WebServer:
    """The dashboard API. One instance per bot, started from setup_hook."""

    def __init__(self, bot):
        self.bot = bot
        self.runner = None
        self.http: aiohttp.ClientSession | None = None
        self.rate_buckets: dict[tuple, deque] = {}
        # per-session locks serialise token refresh so parallel dashboard
        # requests can't race the single-use refresh token and log the user out
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._last_gc = 0.0

    @property
    def oauth_ready(self):
        return bool(CLIENT_ID and CLIENT_SECRET)

    def _build_app(self):
        app = web.Application(
            client_max_size=MAX_BODY_BYTES,
            middlewares=[self._headers_middleware, self._error_middleware],
        )
        # (method, path, handler) — registered under /api/v1 and legacy /api
        routes = [
            ("GET", "/health", self.handle_health),
            ("GET", "/stats", self.handle_stats),
            ("GET", "/updates", self.handle_updates),
            ("POST", "/maintenance/preview", self.handle_maintenance_preview),
            ("GET", "/invite", self.handle_invite),
            ("GET", "/invite/complete", self.handle_invite_complete),
            ("GET", "/auth/login", self.handle_login),
            ("GET", "/auth/callback", self.handle_callback),
            ("POST", "/auth/logout", self.handle_logout),
            ("GET", "/me", self.handle_me),
            ("GET", "/guilds", self.handle_guilds),
            ("GET", "/guilds/{guild_id}/config", self.handle_config_get),
            ("PUT", "/guilds/{guild_id}/config", self.handle_config_put),
            ("GET", "/guilds/{guild_id}/dashboard", self.handle_dashboard),
            ("POST", "/guilds/{guild_id}/actions/{action}", self.handle_guild_action),
            ("GET", "/guilds/{guild_id}/audit", self.handle_audit),
        ]
        for method, path, handler in routes:
            app.router.add_route(method, f"{API_PREFIX}{path}", handler)
            app.router.add_route(method, f"{LEGACY_PREFIX}{path}", handler)
        # CORS preflight (OPTIONS) is answered by the headers middleware, so no
        # catch-all route is needed — that keeps unknown paths returning 404.
        return app

    async def start(self):
        if not WEB_ENABLED:
            log.warning("Web API disabled (set WEB_ENABLED=true to serve the dashboard API).")
            return
        await asyncio.to_thread(init_web_tables)
        await asyncio.to_thread(db_gc)
        connector = aiohttp.TCPConnector(
            ttl_dns_cache=DISCORD_DNS_CACHE_SECONDS,
            limit=8,
            limit_per_host=4,
            keepalive_timeout=45,
        )
        timeout = aiohttp.ClientTimeout(
            total=DISCORD_REQUEST_TIMEOUT_SECONDS,
            connect=4,
            sock_connect=4,
            sock_read=8,
        )
        self.http = aiohttp.ClientSession(connector=connector, timeout=timeout)

        self.runner = web.AppRunner(self._build_app(), access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, WEB_HOST, WEB_PORT)
        await site.start()
        oauth_note = "OAuth ready" if self.oauth_ready else "OAuth NOT configured (login disabled)"
        crypto_note = "tokens encrypted" if _CIPHER else "tokens plaintext (install cryptography)"
        log.info(
            f"Web API listening on {WEB_HOST}:{WEB_PORT}{API_PREFIX} • {oauth_note} • "
            f"sessions in SQLite • {crypto_note} • after login → {AFTER_LOGIN}"
        )
        if after_login_strands_user():
            example = sorted(CORS_ORIGINS)[0]
            log.warning(
                f"  WARNING: WEB_AFTER_LOGIN={AFTER_LOGIN!r} is a path, so after logging in "
                f"the browser stays on this API instead of the dashboard. Only the first "
                f"login is affected, which makes it look intermittent. Set the full URL, "
                f"e.g. WEB_AFTER_LOGIN={example}/dashboard/"
            )

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        if self.http:
            await self.http.close()
            self.http = None

    # ── middlewares ──────────────────────────────────────────────────

    @web.middleware
    async def _error_middleware(self, request, handler):
        """Turn every failure into the uniform JSON envelope {error, code}."""
        try:
            return await handler(request)
        except ApiError as error:
            payload = {"error": error.message, "code": error.code}
            if error.details is not None:
                payload["details"] = error.details
            headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
            return web.json_response(payload, status=error.status, headers=headers)
        except web.HTTPException as http_error:
            # Redirect exceptions are control flow, not API failures. Returning
            # them from middleware is deprecated by aiohttp, while turning them
            # into JSON here would discard Location and Set-Cookie. Stamp the
            # headers that the outer middleware cannot add after a raised
            # redirect, then let aiohttp handle it natively.
            if 300 <= http_error.status < 400:
                for key, value in self._security_headers(request).items():
                    http_error.headers.setdefault(key, value)
                raise
            # aiohttp's own errors (unknown route → 404, wrong verb → 405, …)
            code = ApiError._DEFAULT_CODES.get(http_error.status, "http_error")
            return web.json_response(
                {"error": http_error.reason or "Error", "code": code},
                status=http_error.status,
            )
        except Exception:
            log.exception("Unhandled error in %s %s", request.method, request.path)
            return web.json_response(
                {"error": "Internal server error.", "code": "internal_error"}, status=500
            )

    @web.middleware
    async def _headers_middleware(self, request, handler):
        """Answer CORS preflight and stamp security + CORS headers on every
        response, errors included."""
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        for key, value in self._security_headers(request).items():
            response.headers.setdefault(key, value)
        return response

    # ── request plumbing ─────────────────────────────────────────────

    @staticmethod
    def _normalized_ip(value):
        try:
            return str(ipaddress.ip_address(str(value or "").strip()))
        except ValueError:
            return None

    def _client_ip(self, request):
        if TRUST_PROXY:
            # CF-Connecting-IP is set by Cloudflare and cannot be spoofed by the
            # client through the tunnel; fall back to the first X-Forwarded-For hop.
            cf_ip = self._normalized_ip(request.headers.get("CF-Connecting-IP"))
            if cf_ip:
                return cf_ip
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                forwarded_ip = self._normalized_ip(forwarded.split(",", 1)[0])
                if forwarded_ip:
                    return forwarded_ip
        return self._normalized_ip(request.remote) or "?"

    def _rate_limit(self, request, scope):
        limit, window = RATE_LIMITS[scope]
        key = (self._client_ip(request), scope)
        bucket = self.rate_buckets.setdefault(key, deque())
        now = time.monotonic()
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            retry = int(window - (now - bucket[0])) + 1
            raise ApiError(429, "Too many requests — slow down.", code="rate_limited", retry_after=retry)
        bucket.append(now)
        # opportunistic cleanup so the dict cannot grow forever
        if len(self.rate_buckets) > 2048:
            for k in [k for k, b in self.rate_buckets.items() if not b or now - b[-1] > 600]:
                self.rate_buckets.pop(k, None)

    def _allowed_origin(self, request):
        """Return the request Origin only if it is on the configured allow-list."""
        origin = request.headers.get("Origin", "")
        if origin and origin.rstrip("/") in CORS_ORIGINS:
            return origin
        return None

    def _check_origin(self, request):
        """Defense-in-depth CSRF guard for mutating requests.

        Allows same-origin (Origin host matches Host) and allow-listed cross
        origins; rejects everything else. Non-browser callers send no Origin
        and are covered by the session cookie + SameSite.
        """
        origin = request.headers.get("Origin")
        if not origin:
            return
        host = request.headers.get("Host", "")
        if origin.split("://", 1)[-1] == host:
            return
        if origin.rstrip("/") in CORS_ORIGINS:
            return
        raise ApiError(403, "Cross-origin request rejected.", code="bad_origin")

    def _security_headers(self, request):
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
            "Content-Security-Policy": API_CONTENT_SECURITY_POLICY,
        }
        if COOKIE_SECURE:
            # Served over HTTPS ⇒ tell browsers to never fall back to http
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        origin = self._allowed_origin(request)
        if origin:
            headers.update(
                {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "GET, PUT, POST, OPTIONS",
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                }
            )
        return headers

    def _require_ready(self):
        if not self.bot.is_ready():
            raise ApiError(
                503, "Bot is still starting — try again shortly.",
                code="bot_starting", retry_after=3,
            )

    async def _gc_maybe(self):
        if time.time() - self._last_gc > 3600:
            self._last_gc = time.time()
            # drop idle refresh locks (a held lock means a refresh is in flight)
            self._session_locks = {s: lock for s, lock in self._session_locks.items() if lock.locked()}
            await asyncio.to_thread(db_gc)

    # ── OAuth state (stateless, HMAC-signed) ─────────────────────────

    def _make_state(self):
        raw = f"{secrets.token_urlsafe(16)}.{int(time.time())}"
        sig = hmac.new(_STATE_SECRET, raw.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{raw}.{sig}"

    def _valid_state(self, token):
        parts = (token or "").split(".")
        if len(parts) != 3:
            return False
        nonce, ts, sig = parts
        expected = hmac.new(_STATE_SECRET, f"{nonce}.{ts}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        try:
            issued = int(ts)
        except ValueError:
            return False
        return 0 <= (time.time() - issued) < STATE_TTL

    # ── session handling ─────────────────────────────────────────────

    async def _session(self, request):
        await self._gc_maybe()
        sid = request.cookies.get(SESSION_COOKIE)
        if not sid:
            return None, None
        entry = await asyncio.to_thread(db_load_session, sid)
        return sid, entry

    async def _require_session(self, request):
        sid, entry = await self._session(request)
        if entry is None:
            raise ApiError(401, "Not logged in. Start at /api/v1/auth/login.", code="unauthorized")
        return sid, entry

    async def _discord_get(self, path, token):
        assert self.http is not None
        try:
            async with self.http.get(
                f"{DISCORD_API}{path}", headers={"Authorization": f"Bearer {token}"}
            ) as response:
                if response.status == 401:
                    raise ApiError(401, "Discord session expired — log in again.", code="session_expired")
                if response.status == 429:
                    raise ApiError(
                        429, "Discord is rate limiting us — try again shortly.",
                        code="upstream_rate_limited", retry_after=5,
                    )
                if response.status >= 400:
                    raise ApiError(502, f"Discord API error {response.status}.", code="upstream_error")
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            log.warning("Discord API request timed out for %s: %s", path, type(error).__name__)
            raise ApiError(
                503,
                "Discord is temporarily unavailable — retry in a few seconds.",
                code="upstream_unavailable",
                retry_after=3,
            ) from error

    async def _token_request(self, data):
        """Exchange or refresh an OAuth token.

        Returns None only when Discord *answered* and refused — that is a real
        rejection, and callers treat it as a dead session. A network failure
        raises instead, because the two must not be confused: returning None on
        a timeout would make _ensure_fresh_token delete a perfectly good session
        over a blip on the Pi's connection.

        Given a longer budget than the shared session timeout. This runs once
        per login and its failure costs the whole flow, while a slow answer
        still succeeds. Timing out on the read is also the worst case for the
        authorization code, which Discord may have already spent.
        """
        assert self.http is not None
        try:
            async with self.http.post(
                f"{DISCORD_API}/oauth2/token",
                data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, **data},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=20, connect=5, sock_connect=5, sock_read=15),
            ) as response:
                if response.status >= 400:
                    return None
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            log.warning("Discord token request failed: %s", type(error).__name__)
            raise ApiError(
                503,
                "Discord is temporarily unavailable — retry in a few seconds.",
                code="upstream_unavailable",
                retry_after=3,
            ) from error

    async def _ensure_fresh_token(self, sid, entry):
        """Refresh the OAuth token ~before it expires; kill the session if we can't.

        Serialised per session so parallel requests don't each spend the
        single-use refresh token (the second spend would fail and log the user
        out). The winner writes the new token to the DB; late waiters reload it.
        """
        if entry.get("token_expires_at", 0) - time.time() > 60:
            return
        lock = self._session_locks.setdefault(sid, asyncio.Lock())
        async with lock:
            # Someone may have refreshed while we waited — reload and re-check.
            fresh = await asyncio.to_thread(db_load_session, sid)
            if fresh is None:
                raise ApiError(401, "Discord session expired — log in again.", code="session_expired")
            if fresh.get("token_expires_at", 0) - time.time() > 60:
                entry.update(fresh)
                return

            refresh_token = fresh.get("refresh_token")
            token_data = None
            if refresh_token:
                token_data = await self._token_request(
                    {"grant_type": "refresh_token", "refresh_token": refresh_token}
                )
            if not token_data or "access_token" not in token_data:
                await asyncio.to_thread(db_delete_session, sid)
                raise ApiError(401, "Discord session expired — log in again.", code="session_expired")
            entry["access_token"] = token_data["access_token"]
            entry["refresh_token"] = token_data.get("refresh_token", refresh_token)
            entry["token_expires_at"] = time.time() + int(token_data.get("expires_in", 3600))
            await asyncio.to_thread(db_touch_session, sid, entry)

    async def _refresh_guilds(self, sid, entry):
        if time.time() - entry.get("guilds_fetched_at", 0) < GUILDS_CACHE_SECONDS:
            return
        await self._ensure_fresh_token(sid, entry)
        guilds = await self._discord_get("/users/@me/guilds", entry["access_token"])
        entry["guilds"] = {
            str(g["id"]): {
                "id": str(g["id"]),
                "name": g.get("name", "?"),
                "icon": g.get("icon"),
                "owner": bool(g.get("owner")),
                "permissions": int(g.get("permissions", 0)),
            }
            for g in guilds
        }
        entry["guilds_fetched_at"] = time.time()
        await asyncio.to_thread(db_touch_session, sid, entry)

    def _can_manage(self, entry, guild_id):
        info = entry.get("guilds", {}).get(str(guild_id))
        if not info:
            return False
        return info["owner"] or bool(info["permissions"] & MANAGE_GUILD)

    async def _authorized_guild(self, request):
        sid, entry = await self._require_session(request)
        guild_id = request.match_info["guild_id"]
        if not guild_id.isdigit():
            raise ApiError(400, "Invalid guild id.", code="bad_request")
        await self._refresh_guilds(sid, entry)
        if not self._can_manage(entry, guild_id):
            raise ApiError(403, "You need Manage Server on that guild.", code="forbidden")
        self._require_ready()
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            raise ApiError(404, "NovaGuard is not in that guild.", code="guild_not_found")
        return sid, entry, guild

    # ── auth endpoints ───────────────────────────────────────────────

    async def handle_login(self, request):
        self._rate_limit(request, "auth")
        if not self.oauth_ready:
            raise ApiError(503, "OAuth not configured on the bot.", code="oauth_unavailable")

        state = self._make_state()
        params = urlencode(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": OAUTH_REDIRECT,
                "response_type": "code",
                "scope": "identify guilds",
                "state": state,
            }
        )
        response = web.HTTPFound(f"https://discord.com/oauth2/authorize?{params}")
        response.set_cookie(STATE_COOKIE, state, max_age=STATE_TTL, httponly=True,
                            samesite=COOKIE_SAMESITE, secure=COOKIE_SECURE)
        raise response

    async def handle_callback(self, request):
        self._rate_limit(request, "auth")

        code = request.query.get("code")
        state = request.query.get("state", "")
        cookie_state = request.cookies.get(STATE_COOKIE, "")
        state_valid = (
            bool(code)
            and bool(state)
            and hmac.compare_digest(state, cookie_state)
            and self._valid_state(state)
        )
        if not state_valid:
            raise ApiError(400, "Invalid OAuth state — try logging in again.", code="invalid_state")

        try:
            token_data = await self._token_request(
                {"grant_type": "authorization_code", "code": code, "redirect_uri": OAUTH_REDIRECT}
            )
        except ApiError as error:
            if error.code != "upstream_unavailable":
                raise
            # This one is read by a person in a browser, so it has to say what
            # to do. Reloading this URL cannot work: Discord may already have
            # spent the authorization code, and a fresh login is the only way
            # to get a new one.
            raise ApiError(
                503,
                "Discord did not answer in time. Go back and log in again.",
                code="upstream_unavailable",
                retry_after=3,
            ) from error
        if not token_data or "access_token" not in token_data:
            raise ApiError(502, "Discord rejected the OAuth code.", code="upstream_error")

        user = await self._discord_get("/users/@me", token_data["access_token"])

        sid = secrets.token_urlsafe(32)
        entry = {
            "user": {
                "id": str(user["id"]),
                "username": user.get("global_name") or user.get("username", "?"),
                "avatar": user.get("avatar"),
            },
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "token_expires_at": time.time() + int(token_data.get("expires_in", 3600)),
            "guilds": {},
            "guilds_fetched_at": 0,
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": time.time() + SESSION_TTL,
        }
        await asyncio.to_thread(db_save_session, sid, entry)
        await asyncio.to_thread(
            db_add_audit, "-", entry["user"], "login", {}, self._client_ip(request)
        )

        response = web.HTTPFound(AFTER_LOGIN)
        response.set_cookie(SESSION_COOKIE, sid, max_age=SESSION_TTL, httponly=True,
                            samesite=COOKIE_SAMESITE, secure=COOKIE_SECURE)
        response.del_cookie(STATE_COOKIE)
        raise response

    async def handle_logout(self, request):
        self._check_origin(request)
        sid, entry = await self._session(request)
        if sid and entry:
            # revoke the token at Discord, then forget the session
            assert self.http is not None
            if entry.get("access_token"):
                try:
                    async with self.http.post(
                        f"{DISCORD_API}/oauth2/token/revoke",
                        data={
                            "client_id": CLIENT_ID,
                            "client_secret": CLIENT_SECRET,
                            "token": entry["access_token"],
                            "token_type_hint": "access_token",
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    ) as upstream:
                        # Discord returns no useful body here, but consuming it
                        # releases the connection back to aiohttp's pool.
                        await upstream.read()
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
            await asyncio.to_thread(db_delete_session, sid)
            self._session_locks.pop(sid, None)
        response = web.json_response({"ok": True})
        response.del_cookie(SESSION_COOKIE)
        return response

    # ── public endpoints ─────────────────────────────────────────────

    async def handle_health(self, request):
        db_ok = await asyncio.to_thread(db_ping)
        # The website reads this to decide whether to close the dashboard, so
        # it is a small file read — off the event loop, like db_ping above.
        state = await asyncio.to_thread(load_maintenance_state)
        maintenance = {"enabled": bool(state.get("enabled"))}
        if maintenance["enabled"]:
            maintenance["message"] = state.get("message") or DEFAULT_MAINTENANCE_MESSAGE
            # Which activation this is. Not a secret — it only says when the
            # window opened — and the website binds preview cookies to it, so a
            # code from a previous window stops working on its own.
            maintenance["since"] = state.get("updated_at")
        payload = {
            # Maintenance is deliberately absent from `ok`: this endpoint
            # answers "is the API alive", not "is the site open". Folding them
            # together would make the public status widget cry outage during a
            # routine update.
            "ok": bool(db_ok and self.bot.is_ready()),
            "bot_ready": self.bot.is_ready(),
            "db_ok": db_ok,
            "maintenance": maintenance,
        }
        return web.json_response(payload, status=200 if db_ok else 503)

    async def handle_maintenance_preview(self, request):
        # "auth" is 10 requests per 60 s, keyed on the visitor's real address —
        # _client_ip reads CF-Connecting-IP, so the proxy in front of the site
        # does not merge every visitor into one bucket.
        self._rate_limit(request, "auth")
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            body = {}
        code = body.get("code") if isinstance(body, dict) else None
        since = await asyncio.to_thread(
            verify_preview_code, code if isinstance(code, str) else ""
        )
        if not since:
            # One answer for a wrong code, a missing one, and a valid one sent
            # while maintenance is off. Nothing here tells a guesser whether a
            # code currently exists, let alone whether they are close to it.
            raise ApiError(401, "That preview code is not valid.", code="invalid_preview_code")
        return web.json_response({"ok": True, "since": since})

    async def handle_invite(self, request):
        if not CLIENT_ID:
            raise ApiError(503, "Client id not configured.", code="oauth_unavailable")
        params = {
            "client_id": CLIENT_ID,
            "permissions": INVITE_PERMISSIONS,
            "scope": "bot applications.commands",
        }
        if INVITE_REDIRECT:
            # Without both of these Discord has nowhere to send the person and
            # simply stops on its own "Authorized" screen - which is where the
            # invite used to dead-end.
            params["redirect_uri"] = INVITE_REDIRECT
            params["response_type"] = "code"
        raise web.HTTPFound(f"https://discord.com/oauth2/authorize?{urlencode(params)}")

    async def handle_invite_complete(self, request):
        """Land here after the bot is added, then bounce to the dashboard.

        Discord appends ?code=&guild_id=&permissions= on the way in. None of it
        is used: the bot learns about its new guild from the gateway, and the
        code is for exchanging a user token this flow never needs. This exists
        purely so the invite ends somewhere that belongs to us instead of on
        Discord's own confirmation screen.
        """
        raise web.HTTPFound(AFTER_INVITE)

    async def handle_stats(self, request):
        self._rate_limit(request, "read")
        guilds = list(self.bot.guilds)
        launched_at = getattr(self.bot, "launched_at", None)
        uptime = int((datetime.now(UTC) - launched_at).total_seconds()) if launched_at else 0
        release = await asyncio.to_thread(current_project_release)
        return web.json_response(
            {
                "version": release["version"],
                "phase": release["phase"],
                "phase_label": release["phase_label"],
                "release_label": f'{release["version"]} {release["phase_label"]}',
                "runtime_version": BOT_RUNTIME_VERSION,
                "codename": BOT_CODENAME,
                "guilds": len(guilds),
                "members": sum(g.member_count or 0 for g in guilds),
                "commands": count_visible_commands(self.bot.tree),
                "uptime_seconds": uptime,
                "ready": self.bot.is_ready(),
            }
        )

    async def handle_updates(self, request):
        """Public release feed for the website's /updates page.

        Reads the changelog engine's state but never writes it, so serving this
        cannot affect what the bot announces in Discord.
        """
        self._rate_limit(request, "read")
        state = load_update_state()
        updates = merged_update_feed(
            limit=request.query.get("limit", 50),
            history=state.get("history"),
            latest=state.get("latest"),
        )
        return web.json_response(
            {
                "updates": updates,
                "count": len(updates),
                "release": current_project_release(state),
            }
        )

    # ── session endpoints ────────────────────────────────────────────

    async def handle_me(self, request):
        self._rate_limit(request, "read")
        _, entry = await self._require_session(request)
        return web.json_response({"user": entry["user"]})

    async def handle_guilds(self, request):
        self._rate_limit(request, "read")
        sid, entry = await self._require_session(request)
        await self._refresh_guilds(sid, entry)

        bot_guild_ids = {str(g.id) for g in self.bot.guilds}
        manageable = [
            {**info, "bot_present": info["id"] in bot_guild_ids}
            for info in entry["guilds"].values()
            if info["owner"] or info["permissions"] & MANAGE_GUILD
        ]
        manageable.sort(key=lambda g: (not g["bot_present"], g["name"].lower()))
        return web.json_response({"guilds": manageable})

    # ── guild config ─────────────────────────────────────────────────

    async def _config_payload(self, guild):
        from cogs.giveaways import load_giveaways

        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        automod = resolve_automod(settings)
        ai_settings = resolve_ai(settings)
        economy_settings = resolve_economy(settings)
        open_tickets, open_ticket_count, role_panels, all_giveaways = await asyncio.gather(
            asyncio.to_thread(list_ticket_records, guild.id, open_only=True, limit=20),
            asyncio.to_thread(count_open_tickets, guild.id),
            asyncio.to_thread(list_role_panel_records, guild.id, limit=20),
            asyncio.to_thread(load_giveaways),
        )
        giveaways = [
            entry
            for entry in reversed(all_giveaways)
            if isinstance(entry, dict)
            if str(entry.get("guild_id")) == str(guild.id)
        ][:30]
        giveaway_payload = []
        for entry in giveaways:
            ends_at = entry.get("ends_at")
            if not entry.get("message_id") or not entry.get("channel_id") or not isinstance(ends_at, str):
                continue
            try:
                winner_count = min(max(int(entry.get("winners") or 1), 1), 10)
            except (TypeError, ValueError):
                winner_count = 1
            entrants = entry.get("entrants")
            winner_ids = entry.get("winner_ids")
            giveaway_payload.append(
                {
                    "message_id": str(entry["message_id"]),
                    "channel_id": str(entry["channel_id"]),
                    "prize": str(entry.get("prize") or "Untitled giveaway"),
                    "winners": winner_count,
                    "host_name": str(entry.get("host_name") or "staff"),
                    "ends_at": ends_at,
                    "entrant_count": len(entrants) if isinstance(entrants, list) else 0,
                    "ended": bool(entry.get("ended")),
                    "winner_ids": (
                        [str(value) for value in winner_ids]
                        if isinstance(winner_ids, list)
                        else []
                    ),
                }
            )
        ticket_channel = (
            guild.get_channel(int(settings["ticket_panel_channel"]))
            if settings.get("ticket_panel_channel")
            else None
        )
        ticket_role = (
            guild.get_role(int(settings["ticket_staff_role"]))
            if settings.get("ticket_staff_role")
            else None
        )
        if ticket_channel is not None and ticket_role is not None:
            from cogs.tickets import role_can_manage_tickets

            ticket_ready = role_can_manage_tickets(ticket_channel, ticket_role)
        else:
            ticket_ready = False
        get_cog = getattr(self.bot, "get_cog", None)
        ai_cog = get_cog("AI") if callable(get_cog) else None
        ai_status = (
            ai_cog.status_payload()
            if ai_cog is not None
            else {
                "available": False,
                "model": None,
                "minute_calls": 0,
                "minute_cap": 30,
                "daily_calls": 0,
                "daily_cap": 500,
            }
        )
        economy_cog = get_cog("Economy") if callable(get_cog) else None
        if economy_cog is not None:
            economy_status = economy_cog.status_payload(guild)
        else:
            economy_data = await asyncio.to_thread(load_economy_data)
            wallets = economy_data.get(str(guild.id), {})
            ordered_wallets = sorted(
                wallets.items(),
                key=lambda item: int(item[1].get("coins", 0) or 0),
                reverse=True,
            )
            economy_status = {
                "tracked_wallets": len(wallets),
                "total_coins": sum(
                    max(0, int(wallet.get("coins", 0) or 0))
                    for wallet in wallets.values()
                ),
                "leaderboard": [
                    {
                        "position": position,
                        "user_id": str(user_id),
                        "display_name": f"Member {user_id}",
                        "coins": max(0, int(wallet.get("coins", 0) or 0)),
                        "daily_streak": max(0, int(wallet.get("daily_streak", 0) or 0)),
                    }
                    for position, (user_id, wallet) in enumerate(ordered_wallets[:10], 1)
                ],
                "shop": [
                    {
                        "key": item["key"],
                        "label": item["label"],
                        "icon": item.get("icon") or "🪙",
                        "price": int(item["price"]),
                        "kind": item["kind"],
                        "description": item.get("description"),
                    }
                    for item in shop.catalog()
                ],
            }
        return {
            "guild": {
                "id": str(guild.id),
                "name": guild.name,
                "icon": str(guild.icon) if guild.icon else None,
                "member_count": guild.member_count,
            },
            # Instance-wide, not per-guild — same value for every guild this bot
            # serves. Exposed here (rather than a new endpoint) so the setup page
            # can read a guild's progress and this flag in one request. Lets the
            # website's recommended-channel count agree with cogs/setup.py's
            # setup_score, which adds a 5th recommended channel under the same
            # condition.
            "github_watch_configured": bool(
                github_config.watch_repos or github_config.primary_repo
            ),
            "settings": {
                **{
                    key: (str(settings[key]) if settings.get(key) else None)
                    for key in CONFIG_CHANNEL_KEYS
                },
                **{key: (str(settings[key]) if settings.get(key) else None) for key in ROLE_KEYS},
                "automod": automod,
                "levels": resolve_levels(settings),
                "ai": ai_settings,
                "economy": economy_settings,
            },
            "ai_status": ai_status,
            "economy_status": economy_status,
            "tickets": {
                "panel_channel_id": str(settings.get("ticket_panel_channel"))
                if settings.get("ticket_panel_channel")
                else None,
                "panel_message_id": str(settings.get("ticket_panel_message"))
                if settings.get("ticket_panel_message")
                else None,
                "ready": ticket_ready,
                "open_count": open_ticket_count,
                "open": [
                    {
                        "thread_id": row["thread_id"],
                        "opener_id": row["opener_id"],
                        "opener_name": row["opener_name"],
                        "created_at": row["created_at"],
                    }
                    for row in open_tickets
                ],
            },
            "role_panels": [
                {
                    "message_id": panel["message_id"],
                    "channel_id": panel["channel_id"],
                    "title": panel["title"],
                    "description": panel["description"],
                    "role_ids": panel["role_ids"],
                    "updated_at": panel["updated_at"],
                }
                for panel in role_panels
            ],
            "giveaways": giveaway_payload,
            "channels": [
                {"id": str(channel.id), "name": channel.name,
                 "category": channel.category.name if channel.category else None}
                for channel in guild.text_channels
            ],
            "roles": [
                {"id": str(role.id), "name": role.name, "color": f"#{role.color.value:06X}",
                 "assignable": role < guild.me.top_role and not role.managed,
                 "manages_threads": role.permissions.manage_threads}
                for role in sorted(guild.roles, key=lambda r: -r.position)
                if not role.is_default()
            ],
        }

    @staticmethod
    def _dashboard_level_from_xp(total_xp):
        return level_from_xp(total_xp)[0]

    @staticmethod
    def _dashboard_seconds_between(started_at, ended_at):
        if not started_at or not ended_at:
            return 0
        try:
            start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(ended_at).replace("Z", "+00:00"))
        except ValueError:
            return 0
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        return max(int((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()), 0)

    async def _dashboard_payload(self, guild):
        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        levels_settings = resolve_levels(settings)
        launched_at = getattr(self.bot, "launched_at", None)
        uptime = int((datetime.now(UTC) - launched_at).total_seconds()) if launched_at else 0

        configured_channels = sum(1 for key in CHANNEL_KEYS if settings.get(key))
        recommended_keys = ["update_channel", "error_log_channel", "log_channel", "welcome_channel"]
        if github_config.watch_repos or github_config.primary_repo:
            recommended_keys.append("github_event_channel")
        recommended_done = sum(1 for key in recommended_keys if settings.get(key))

        levels_data = await asyncio.to_thread(load_levels_data)
        guild_levels = levels_data.get(str(guild.id), {})
        total_xp = sum(max(int(record.get("xp", 0) or 0), 0) for record in guild_levels.values())
        leaderboard = []
        for position, (user_id, record) in enumerate(
            sorted(guild_levels.items(), key=lambda item: item[1].get("xp", 0), reverse=True)[
                :DASHBOARD_LEADERBOARD_LIMIT
            ],
            start=1,
        ):
            member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
            xp = int(record.get("xp", 0) or 0)
            leaderboard.append(
                {
                    "position": position,
                    "user_id": str(user_id),
                    "display_name": member.display_name if member else f"User {user_id}",
                    "xp": xp,
                    "messages": int(record.get("messages", 0) or 0),
                    "level": self._dashboard_level_from_xp(xp),
                }
            )

        voice_history = await asyncio.to_thread(load_voice_store, "voice_report_history", {})
        voice_pending = await asyncio.to_thread(load_voice_store, "voice_pending_reports", {})
        guild_voice_history = voice_history.get(str(guild.id), []) if isinstance(voice_history, dict) else []
        guild_voice_pending = voice_pending.get(str(guild.id), {}) if isinstance(voice_pending, dict) else {}
        voice_reports = []
        for report in guild_voice_history[:DASHBOARD_VOICE_HISTORY_LIMIT]:
            session = report.get("session") or {}
            members = session.get("members") if isinstance(session, dict) else {}
            started_at = session.get("started_at") if isinstance(session, dict) else None
            ended_at = report.get("ended_at")
            voice_reports.append(
                {
                    "id": str(report.get("id") or ""),
                    "channel_id": str(report.get("channel_id") or ""),
                    "channel_name": report.get("channel_name") or "Voice session",
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "sent_at": report.get("sent_at"),
                    "duration_seconds": self._dashboard_seconds_between(started_at, ended_at),
                    "unique_members": len(members) if isinstance(members, dict) else 0,
                    "peak_members": int(session.get("peak_members", 0) or 0) if isinstance(session, dict) else 0,
                }
            )

        update_state = load_update_state()
        update_feed = merged_update_feed(
            limit=5,
            history=update_state.get("history"),
            latest=update_state.get("latest"),
        )
        release = current_project_release(update_state)

        automod = resolve_automod(settings)
        modules = [
            {
                "key": "welcome",
                "label": "Welcome",
                "enabled": bool(
                    settings.get("welcome_channel")
                    or settings.get("goodbye_channel")
                    or settings.get("autorole")
                ),
            },
            {
                "key": "moderation",
                "label": "Moderation",
                "enabled": bool(
                    settings.get("log_channel")
                    or settings.get("error_log_channel")
                    or automod.get("invites")
                    or automod.get("spam")
                    or automod.get("badwords")
                ),
            },
            {"key": "levels", "label": "Levels", "enabled": bool(levels_settings.get("enabled"))},
            {"key": "voice", "label": "Voice reports", "enabled": bool(settings.get("voice_report_channel"))},
            {"key": "tickets", "label": "Tickets", "enabled": bool(settings.get("ticket_staff_role"))},
            {"key": "roles", "label": "Role panels", "enabled": bool(settings.get("role_panel_channel"))},
            {"key": "giveaways", "label": "Giveaways", "enabled": bool(settings.get("giveaway_channel"))},
            {"key": "ai", "label": "AI assistant", "enabled": bool(resolve_ai(settings)["enabled"])},
            {"key": "economy", "label": "Economy", "enabled": bool(resolve_economy(settings)["enabled"])},
            {
                "key": "updates",
                "label": "Updates",
                "enabled": bool(settings.get("update_channel") or settings.get("github_event_channel")),
            },
        ]

        return {
            "status": {
                "ready": self.bot.is_ready(),
                "version": release["version"],
                "phase": release["phase"],
                "phase_label": release["phase_label"],
                "release_label": f'{release["version"]} {release["phase_label"]}',
                "runtime_version": BOT_RUNTIME_VERSION,
                "codename": BOT_CODENAME,
                "uptime_seconds": uptime,
                "commands": count_visible_commands(self.bot.tree),
                "guilds": len(self.bot.guilds),
                "members": sum(g.member_count or 0 for g in self.bot.guilds),
            },
            "guild": {
                "id": str(guild.id),
                "name": guild.name,
                "icon": str(guild.icon) if guild.icon else None,
                "member_count": guild.member_count or 0,
            },
            "setup": {
                "configured_channels": configured_channels,
                "total_channels": len(CHANNEL_KEYS),
                "recommended_done": recommended_done,
                "recommended_total": len(recommended_keys),
            },
            "modules": modules,
            "automod": {
                "invites": bool(automod.get("invites")),
                "spam": bool(automod.get("spam")),
                "badwords_count": len(automod.get("badwords") or []),
            },
            "levels": {
                "enabled": bool(levels_settings.get("enabled")),
                "tracked_members": len(guild_levels),
                "total_xp": total_xp,
                "leaderboard": leaderboard,
            },
            "voice": {
                "configured": bool(settings.get("voice_report_channel")),
                "report_channel_id": str(settings.get("voice_report_channel")) if settings.get("voice_report_channel") else None,
                "pending_count": len(guild_voice_pending) if isinstance(guild_voice_pending, dict) else 0,
                "recent_reports": voice_reports,
            },
            "updates": update_feed[:5],
        }

    async def handle_config_get(self, request):
        self._rate_limit(request, "read")
        _, _, guild = await self._authorized_guild(request)
        return web.json_response(await self._config_payload(guild))

    async def handle_dashboard(self, request):
        self._rate_limit(request, "read")
        _, _, guild = await self._authorized_guild(request)
        return web.json_response(await self._dashboard_payload(guild))

    async def _audit_dashboard_action(self, request, guild, entry, action, changes=None):
        await asyncio.to_thread(
            db_add_audit,
            guild.id,
            entry["user"],
            action,
            changes or {},
            self._client_ip(request),
        )

    async def _handle_voice_test_action(self, guild, entry):
        import discord

        from cogs.voice import build_report_embed, new_session, now_utc, record_member_join, record_member_leave

        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        channel_id = settings.get("voice_report_channel")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if channel is None:
            raise ApiError(400, "Voice reports are not configured.", code="voice_not_configured")

        ended_at = now_utc()
        started_at = ended_at - timedelta(hours=1, minutes=27, seconds=18)
        session = new_session(0, "Voice report preview", started_at)
        user_id = int(entry["user"].get("id") or 0)
        username = entry["user"].get("username") or "Dashboard user"
        record_member_join(session, user_id, username, started_at)
        record_member_leave(session, user_id, ended_at)

        class PreviewVoiceChannel:
            id = 0
            name = "Voice report preview"
            mention = "Voice report preview"

        embed, _ = build_report_embed(session, PreviewVoiceChannel(), ended_at)
        embed.title = "Voice session preview"
        try:
            await asyncio.wait_for(
                channel.send(content=f"Test requested from the dashboard by **{username}**", embed=embed),
                timeout=8,
            )
        except (discord.HTTPException, asyncio.TimeoutError) as error:
            log.warning("Dashboard voice test failed for #%s", channel.id)
            raise ApiError(
                502,
                "Discord did not accept the voice test report in time.",
                code="voice_test_failed",
                details=[type(error).__name__],
            ) from error

        return {
            "ok": True,
            "action": "voice_test",
            "message": f"Voice report preview sent to #{channel.name}.",
            "channel_id": str(channel.id),
        }

    async def _handle_update_preview_action(self, guild):
        from .guild_config import resolve_channel
        from .updates import (
            build_code_update_embed,
            build_restart_update_embed,
            build_update_buttons,
            normalize_update_history,
            safe_send_embed,
        )

        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        channel = await resolve_channel(self.bot, settings.get("update_channel") or github_config.update_channel_id)
        if channel is None or getattr(channel, "guild", None) != guild:
            raise ApiError(
                400,
                "No update channel is configured for this server.",
                code="update_channel_not_configured",
            )

        saved_state = await asyncio.to_thread(load_update_state)
        latest_update = saved_state.get("latest")
        if not latest_update:
            raise ApiError(400, "No saved update is available.", code="update_preview_unavailable")

        history = normalize_update_history(saved_state.get("history", []))
        pending_fingerprint = saved_state.get("pending_announcement")
        latest_fingerprint = latest_update.get("fingerprint")
        embed = (
            build_code_update_embed(latest_update, history)
            if pending_fingerprint and pending_fingerprint == latest_fingerprint
            else build_restart_update_embed(latest_update, history)
        )
        sent = await safe_send_embed(channel, embed, build_update_buttons())
        if not sent:
            raise ApiError(
                502,
                "Discord did not accept the update preview in time.",
                code="update_preview_failed",
            )
        return {
            "ok": True,
            "action": "update_preview",
            "message": f"Latest update was sent to #{channel.name}.",
            "channel_id": str(channel.id),
        }

    async def _handle_ticket_panel_publish_action(self, guild):
        import discord

        from cogs.tickets import publish_ticket_panel, role_can_manage_tickets

        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        channel_id = settings.get("ticket_panel_channel")
        staff_role_id = settings.get("ticket_staff_role")
        if not channel_id or not staff_role_id:
            raise ApiError(
                400,
                "Choose a ticket channel and staff role, then save before publishing.",
                code="ticket_setup_incomplete",
            )
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        role = guild.get_role(int(staff_role_id)) if staff_role_id else None
        if channel is None or role is None:
            raise ApiError(
                400,
                "Choose a ticket channel and staff role, then save before publishing.",
                code="ticket_setup_incomplete",
            )
        if not role_can_manage_tickets(channel, role):
            raise ApiError(
                400,
                "The ticket staff role needs View Channel and Manage Threads in the panel channel.",
                code="ticket_staff_no_access",
            )

        previous_message_id = settings.get("ticket_panel_message")
        try:
            message, created = await asyncio.wait_for(
                publish_ticket_panel(channel, previous_message_id), timeout=10
            )
        except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError) as error:
            log.warning("Dashboard ticket panel publish failed for #%s", channel.id)
            raise ApiError(
                502,
                "Discord did not accept the ticket panel.",
                code="ticket_panel_failed",
                details=[type(error).__name__],
            ) from error

        await asyncio.to_thread(
            update_guild_settings,
            guild.id,
            ticket_panel_channel=channel.id,
            ticket_panel_message=message.id,
        )
        return {
            "ok": True,
            "action": "ticket_panel_publish",
            "message": f"Ticket panel {'published' if created else 'updated'} in #{channel.name}.",
            "channel_id": str(channel.id),
        }

    async def _handle_role_panel_publish_action(self, request, guild, entry):
        import discord

        from cogs.roles import publish_role_panel, validate_role_panel_input

        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "Body must be valid JSON.", code="bad_request")
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object.", code="bad_request")

        title, description, role_ids, errors = validate_role_panel_input(
            body.get("title"), body.get("description"), body.get("role_ids")
        )
        roles = []
        for role_id in role_ids:
            if not role_id.isdigit():
                continue
            role = guild.get_role(int(role_id))
            if role is None:
                errors.append(f"role_ids: {role_id} is not a role in this guild")
            elif role.is_default() or role.managed or role >= guild.me.top_role:
                errors.append(f"role_ids: @{role.name} cannot be assigned by NovaGuard")
            else:
                roles.append(role)
        if errors:
            raise ApiError(400, "Validation failed.", code="validation_failed", details=errors)

        previous_message_id = body.get("panel_message_id")
        previous_panel = None
        if previous_message_id not in (None, ""):
            if not str(previous_message_id).isdigit():
                raise ApiError(400, "Invalid role panel id.", code="invalid_role_panel")
            previous_panel = await asyncio.to_thread(
                get_role_panel_record, guild.id, previous_message_id
            )
            if previous_panel is None:
                raise ApiError(404, "That role panel is no longer tracked.", code="role_panel_not_found")

        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        channel_id = (
            previous_panel["channel_id"]
            if previous_panel is not None
            else settings.get("role_panel_channel")
        )
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if channel is None:
            raise ApiError(
                400,
                "Choose and save a default role-panel channel first.",
                code="role_panel_channel_missing",
            )

        try:
            message, created = await asyncio.wait_for(
                publish_role_panel(
                    channel,
                    title,
                    description,
                    roles,
                    previous_panel["message_id"] if previous_panel else None,
                ),
                timeout=10,
            )
        except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError) as error:
            log.warning("Dashboard role panel publish failed for #%s", channel.id)
            raise ApiError(
                502,
                "Discord did not accept the role panel.",
                code="role_panel_failed",
                details=[type(error).__name__],
            ) from error

        panel = await asyncio.to_thread(
            save_role_panel_record,
            guild.id,
            message.id,
            channel.id,
            title,
            description,
            role_ids,
            created_by=entry["user"]["id"],
            previous_message_id=previous_panel["message_id"] if previous_panel else None,
        )
        return {
            "ok": True,
            "action": "role_panel_publish",
            "message": f"Role panel {'published' if created else 'updated'} in #{channel.name}.",
            "channel_id": str(channel.id),
            "panel": {
                "message_id": panel["message_id"],
                "channel_id": panel["channel_id"],
                "title": panel["title"],
                "description": panel["description"],
                "role_ids": panel["role_ids"],
                "updated_at": panel["updated_at"],
            },
        }

    @staticmethod
    async def _giveaway_action_body(request):
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "Body must be valid JSON.", code="bad_request")
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object.", code="bad_request")
        return body

    def _giveaway_cog(self):
        cog = self.bot.get_cog("Giveaways")
        if cog is None:
            raise ApiError(
                503,
                "The giveaway manager is still starting. Try again shortly.",
                code="giveaway_unavailable",
            )
        return cog

    @staticmethod
    async def _giveaway_for_guild(guild_id, message_id):
        from cogs.giveaways import load_giveaways

        entries = await asyncio.to_thread(load_giveaways)
        return next(
            (
                entry
                for entry in entries
                if isinstance(entry, dict)
                if str(entry.get("guild_id")) == str(guild_id)
                and str(entry.get("message_id")) == str(message_id)
            ),
            None,
        )

    async def _handle_giveaway_start_action(self, request, guild, entry):
        import discord

        from cogs.giveaways import validate_giveaway_input

        body = await self._giveaway_action_body(request)
        duration, prize, winners, errors = validate_giveaway_input(
            body.get("duration"), body.get("prize"), body.get("winners")
        )
        if errors:
            raise ApiError(400, "Validation failed.", code="validation_failed", details=errors)

        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        channel_id = settings.get("giveaway_channel")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if channel is None:
            raise ApiError(
                400,
                "Choose and save a giveaway channel first.",
                code="giveaway_channel_missing",
            )

        cog = self._giveaway_cog()
        try:
            giveaway = await asyncio.wait_for(
                cog.start_giveaway(
                    channel,
                    guild_id=guild.id,
                    host_id=entry["user"]["id"],
                    host_name=entry["user"]["username"],
                    duration=duration,
                    prize=prize,
                    winners=winners,
                ),
                timeout=15,
            )
        except (
            discord.Forbidden,
            discord.HTTPException,
            asyncio.TimeoutError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            log.warning("Dashboard giveaway publish failed for #%s", channel.id)
            raise ApiError(
                502,
                "Discord did not accept the giveaway.",
                code="giveaway_publish_failed",
                details=[type(error).__name__],
            ) from error
        return {
            "ok": True,
            "action": "giveaway_start",
            "message": f"Giveaway for {giveaway['prize']} started in #{channel.name}.",
            "channel_id": str(channel.id),
        }

    async def _handle_giveaway_end_action(self, request, guild):
        body = await self._giveaway_action_body(request)
        message_id = str(body.get("message_id") or "")
        if not message_id.isdigit():
            raise ApiError(400, "Invalid giveaway id.", code="invalid_giveaway")
        tracked = await self._giveaway_for_guild(guild.id, message_id)
        if tracked is None or tracked.get("ended"):
            raise ApiError(404, "No active giveaway with that id.", code="giveaway_not_found")
        try:
            result = await asyncio.wait_for(
                self._giveaway_cog().finish_giveaway(message_id), timeout=15
            )
        except (asyncio.TimeoutError, OSError, TypeError, ValueError) as error:
            raise ApiError(
                504,
                "The giveaway draw could not be completed. Refresh before trying again.",
                code="giveaway_timeout",
            ) from error
        if result is None:
            raise ApiError(409, "That giveaway already ended.", code="giveaway_already_ended")
        return {
            "ok": True,
            "action": "giveaway_end",
            "message": f"Giveaway for {result['prize']} ended and the draw was saved.",
        }

    async def _handle_giveaway_reroll_action(self, request, guild):
        body = await self._giveaway_action_body(request)
        message_id = str(body.get("message_id") or "")
        if not message_id.isdigit():
            raise ApiError(400, "Invalid giveaway id.", code="invalid_giveaway")
        tracked = await self._giveaway_for_guild(guild.id, message_id)
        if tracked is None or not tracked.get("ended"):
            raise ApiError(404, "No ended giveaway with that id.", code="giveaway_not_found")
        try:
            result, winner_ids, announced = await asyncio.wait_for(
                self._giveaway_cog().reroll_giveaway(message_id), timeout=15
            )
        except (asyncio.TimeoutError, OSError, TypeError, ValueError) as error:
            raise ApiError(
                504,
                "The giveaway reroll could not be completed. Refresh before trying again.",
                code="giveaway_timeout",
            ) from error
        if result is None:
            raise ApiError(409, "That giveaway is not ready to reroll.", code="giveaway_not_ended")
        if not winner_ids:
            raise ApiError(409, "That giveaway has no entries to reroll.", code="giveaway_no_entries")
        return {
            "ok": True,
            "action": "giveaway_reroll",
            "message": (
                f"New winner{'s' if len(winner_ids) > 1 else ''} announced in the original channel."
                if announced
                else "The new draw was saved, but Discord did not accept the announcement."
            ),
        }

    async def handle_guild_action(self, request):
        self._rate_limit(request, "write")
        self._check_origin(request)
        _, entry, guild = await self._authorized_guild(request)
        action = request.match_info["action"].replace("-", "_")

        if action == "voice_test":
            payload = await self._handle_voice_test_action(guild, entry)
        elif action == "update_preview":
            payload = await self._handle_update_preview_action(guild)
        elif action == "ticket_panel_publish":
            payload = await self._handle_ticket_panel_publish_action(guild)
        elif action == "role_panel_publish":
            payload = await self._handle_role_panel_publish_action(request, guild, entry)
        elif action == "giveaway_start":
            payload = await self._handle_giveaway_start_action(request, guild, entry)
        elif action == "giveaway_end":
            payload = await self._handle_giveaway_end_action(request, guild)
        elif action == "giveaway_reroll":
            payload = await self._handle_giveaway_reroll_action(request, guild)
        else:
            raise ApiError(404, "Unknown dashboard action.", code="unknown_action")

        audit_changes = {"ok": payload.get("ok")}
        await self._audit_dashboard_action(
            request, guild, entry, f"dashboard_{action}", audit_changes
        )
        return web.json_response(payload)

    async def handle_audit(self, request):
        self._rate_limit(request, "read")
        _, _, guild = await self._authorized_guild(request)
        raw_limit = request.query.get("limit", "50") or "50"
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(400, "Audit limit must be a number.", code="bad_request")
        if limit < 1:
            raise ApiError(400, "Audit limit must be at least 1.", code="bad_request")
        limit = min(limit, 200)

        raw_cursor = request.query.get("cursor")
        cursor = None
        if raw_cursor:
            try:
                cursor = int(raw_cursor)
            except (TypeError, ValueError):
                raise ApiError(400, "Audit cursor is invalid.", code="bad_request")
            if cursor < 1:
                raise ApiError(400, "Audit cursor is invalid.", code="bad_request")

        kind = (request.query.get("kind") or "").strip().lower() or None
        if kind not in {None, "settings", "actions", "login"}:
            raise ApiError(400, "Audit kind is invalid.", code="bad_request")

        action = (request.query.get("action") or "").strip() or None
        actor = (request.query.get("actor") or "").strip() or None
        if action and len(action) > 80:
            raise ApiError(400, "Audit action filter is too long.", code="bad_request")
        if actor and len(actor) > 100:
            raise ApiError(400, "Audit actor filter is too long.", code="bad_request")

        def audit_timestamp(name):
            value = (request.query.get(name) or "").strip()
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ApiError(400, f"Audit {name} date is invalid.", code="bad_request")
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC).isoformat()

        after = audit_timestamp("after")
        before = audit_timestamp("before")
        if after and before and after >= before:
            raise ApiError(400, "Audit date range is invalid.", code="bad_request")

        entries, next_cursor = await asyncio.to_thread(
            db_get_audit,
            guild.id,
            limit,
            cursor=cursor,
            kind=kind,
            action=action,
            actor=actor,
            after=after,
            before=before,
        )
        return web.json_response({"audit": entries, "next_cursor": next_cursor})

    async def handle_config_put(self, request):
        self._rate_limit(request, "write")
        self._check_origin(request)
        sid, entry, guild = await self._authorized_guild(request)
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "Body must be valid JSON.", code="bad_request")
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object.", code="bad_request")

        text_channel_ids = {str(channel.id) for channel in guild.text_channels}
        changes = {}
        errors = []

        for key in CONFIG_CHANNEL_KEYS:
            if key not in body:
                continue
            value = body[key]
            if value in (None, "", 0):
                changes[key] = None
            elif str(value) in text_channel_ids:
                changes[key] = int(value)
            else:
                errors.append(f"{key}: not a text channel in this guild")

        # The old message belongs to the old channel. Keeping its ID after a
        # channel change makes the dashboard falsely report a live panel.
        if "ticket_panel_channel" in changes:
            changes["ticket_panel_message"] = None

        for key in ROLE_KEYS:
            if key not in body:
                continue
            value = body[key]
            if value in (None, "", 0):
                changes[key] = None
                continue
            role = guild.get_role(int(value)) if str(value).isdigit() else None
            if role is None or role.is_default():
                errors.append(f"{key}: role not found")
            elif key == "autorole" and (role.managed or role >= guild.me.top_role):
                errors.append(f"{key}: role must be below my top role and not managed")
            else:
                changes[key] = role.id

        if "ticket_panel_channel" in body or "ticket_staff_role" in body:
            from cogs.tickets import role_can_manage_tickets

            current = await asyncio.to_thread(get_guild_settings, guild.id)
            ticket_channel_id = changes.get(
                "ticket_panel_channel", current.get("ticket_panel_channel")
            )
            ticket_role_id = changes.get("ticket_staff_role", current.get("ticket_staff_role"))
            ticket_channel = (
                guild.get_channel(int(ticket_channel_id)) if ticket_channel_id else None
            )
            ticket_role = guild.get_role(int(ticket_role_id)) if ticket_role_id else None
            if (
                ticket_channel is not None
                and ticket_role is not None
                and not role_can_manage_tickets(ticket_channel, ticket_role)
            ):
                errors.append(
                    "ticket_staff_role: role needs View Channel and Manage Threads "
                    "in the ticket panel channel"
                )

        if "automod" in body:
            current = await asyncio.to_thread(get_guild_settings, guild.id)
            role_ids = {str(role.id) for role in guild.roles}
            automod, automod_errors = validate_automod(
                body["automod"], resolve_automod(current), text_channel_ids, role_ids
            )
            if automod_errors:
                errors.extend(automod_errors)
            else:
                changes["automod"] = automod

        if "levels" in body:
            # Rules live in core.levels_settings so the cog and this endpoint
            # cannot disagree about them. Validated against the guild's saved
            # config, which is what makes a one-sided xp_min/xp_max patch right.
            current = await asyncio.to_thread(get_guild_settings, guild.id)
            role_ids = {str(role.id) for role in guild.roles}
            levels, levels_errors = validate_levels(
                body["levels"], resolve_levels(current), text_channel_ids, role_ids
            )
            if levels_errors:
                errors.extend(levels_errors)
            else:
                changes["levels"] = levels

        if "ai" in body:
            current = await asyncio.to_thread(get_guild_settings, guild.id)
            ai, ai_errors = validate_ai(body["ai"], resolve_ai(current), text_channel_ids)
            if ai_errors:
                errors.extend(ai_errors)
            else:
                changes["ai"] = ai

        if "economy" in body:
            current = await asyncio.to_thread(get_guild_settings, guild.id)
            economy, economy_errors = validate_economy(
                body["economy"], resolve_economy(current)
            )
            if economy_errors:
                errors.extend(economy_errors)
            else:
                changes["economy"] = economy

        if errors:
            raise ApiError(400, "Validation failed.", code="validation_failed", details=errors)
        if not changes:
            raise ApiError(400, "Nothing to update.", code="nothing_to_update")

        await asyncio.to_thread(update_guild_settings, guild.id, **changes)
        await asyncio.to_thread(
            db_add_audit, guild.id, entry["user"], "config_update", changes, self._client_ip(request)
        )

        try:
            from .theme import Palette, brand_footer, make_embed

            summary = ", ".join(f"`{key}`" for key in changes)
            embed = make_embed(
                "🌐 Settings updated from the dashboard",
                f"**{entry['user']['username']}** changed: {summary}",
                color=Palette.INFO,
            )
            brand_footer(embed, "Web dashboard")
            self.bot.dispatch("modlog", guild, embed)
        except Exception:
            # The save already succeeded above; this only announces it. Losing
            # the announcement silently would look identical to it never having
            # been sent, so it gets a log line instead of a bare pass.
            log.warning("Could not post the dashboard change to modlog", exc_info=True)

        return web.json_response(await self._config_payload(guild))
