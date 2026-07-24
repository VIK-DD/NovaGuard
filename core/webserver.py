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
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from .config import BOT_CODENAME, BOT_VERSION
from .database import connect
from .storage import get_guild_settings, update_guild_settings

try:  # at-rest token encryption is optional — degrade gracefully if unavailable
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - exercised only on minimal installs
    Fernet = None
    InvalidToken = Exception

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
COOKIE_SECURE = os.getenv("WEB_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}
# Cookie SameSite policy. "Lax" works when the dashboard is same-site as the API
# (including subdomains of one registrable domain). Use "None" for a dashboard on
# a different domain — browsers require Secure for SameSite=None, so we force it.
COOKIE_SAMESITE = (os.getenv("WEB_COOKIE_SAMESITE", "Lax").strip().capitalize() or "Lax")
if COOKIE_SAMESITE not in {"Lax", "Strict", "None"}:
    COOKIE_SAMESITE = "Lax"
if COOKIE_SAMESITE == "None":
    COOKIE_SECURE = True
TRUST_PROXY = os.getenv("WEB_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}
INVITE_PERMISSIONS = os.getenv("WEB_INVITE_PERMISSIONS", "8").strip() or "8"

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
MAX_SESSIONS_PER_USER = 5
AUDIT_KEEP_DAYS = 90
MAX_BODY_BYTES = 64 * 1024
MANAGE_GUILD = 0x20
TOKEN_PREFIX = "enc:"  # marks an encrypted token column so legacy rows still load
SCHEMA_VERSION = 1  # bump + add a migration branch in init_web_tables when tables change

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
ROLE_KEYS = ("autorole", "ticket_staff_role")
AUTOMOD_DEFAULTS = {"invites": True, "spam": True, "badwords": []}
MAX_BADWORDS = 100
MAX_BADWORD_LENGTH = 40

_DB_LOCK = threading.Lock()

# HMAC key for signing OAuth state tokens. Reuses the client secret so it needs
# no extra configuration; a per-process random fallback keeps things sane when
# OAuth is not configured (login is disabled in that case anyway).
_STATE_SECRET = (CLIENT_SECRET or secrets.token_urlsafe(32)).encode("utf-8")


def _build_cipher():
    """Derive a Fernet cipher from the client secret, or None if we can't."""
    if Fernet is None:
        return None
    secret = CLIENT_SECRET or os.getenv("WEB_TOKEN_KEY", "").strip()
    if not secret:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(("novaguard-token::" + secret).encode()).digest())
    return Fernet(key)


_CIPHER = _build_cipher()


def _encrypt_token(value):
    if value is None or _CIPHER is None:
        return value
    return TOKEN_PREFIX + _CIPHER.encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_token(value):
    if not isinstance(value, str) or not value.startswith(TOKEN_PREFIX):
        return value  # legacy plaintext (or None) — return unchanged
    if _CIPHER is None:
        return None  # encrypted but we lost the key ⇒ treat as unusable
    try:
        return _CIPHER.decrypt(value[len(TOKEN_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


# ── SQL layer (runs in threads via asyncio.to_thread) ────────────────

def init_web_tables():
    with _DB_LOCK, connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS web_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS web_sessions (
                sid_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_json TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_expires_at REAL NOT NULL DEFAULT 0,
                guilds_json TEXT NOT NULL DEFAULT '{}',
                guilds_fetched_at REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                expires_at REAL NOT NULL,
                last_seen_at REAL NOT NULL DEFAULT 0
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS web_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                ip TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_web_audit_guild ON web_audit (guild_id, id DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions (user_id)")

        # ── schema migrations (dedicated web_meta, never touches the bot's DB) ──
        row = db.execute("SELECT value FROM web_meta WHERE key = 'schema_version'").fetchone()
        version = int(row["value"]) if row else 0
        # future migrations go here, e.g.:
        #   if version < 2:
        #       db.execute("ALTER TABLE web_sessions ADD COLUMN ...")
        if version != SCHEMA_VERSION:
            db.execute(
                "INSERT INTO web_meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )


def db_ping():
    """Cheap connectivity probe for the health endpoint."""
    try:
        with _DB_LOCK, connect() as db:
            db.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def _hash_sid(sid):
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def db_save_session(sid, entry):
    with _DB_LOCK, connect() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO web_sessions
            (sid_hash, user_id, user_json, access_token, refresh_token, token_expires_at,
             guilds_json, guilds_fetched_at, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _hash_sid(sid),
                entry["user"]["id"],
                json.dumps(entry["user"]),
                _encrypt_token(entry["access_token"]),
                _encrypt_token(entry.get("refresh_token")),
                entry.get("token_expires_at", 0),
                json.dumps(entry.get("guilds", {})),
                entry.get("guilds_fetched_at", 0),
                entry.get("created_at") or datetime.now(UTC).isoformat(),
                entry["expires_at"],
                time.time(),
            ),
        )
        # keep only the newest sessions per user
        db.execute(
            """
            DELETE FROM web_sessions WHERE user_id = ? AND sid_hash NOT IN (
                SELECT sid_hash FROM web_sessions WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
            )
            """,
            (entry["user"]["id"], entry["user"]["id"], MAX_SESSIONS_PER_USER),
        )


def db_load_session(sid):
    with _DB_LOCK, connect() as db:
        row = db.execute(
            "SELECT * FROM web_sessions WHERE sid_hash = ?", (_hash_sid(sid),)
        ).fetchone()
    if row is None:
        return None
    entry = {
        "user": json.loads(row["user_json"]),
        "access_token": _decrypt_token(row["access_token"]),
        "refresh_token": _decrypt_token(row["refresh_token"]),
        "token_expires_at": row["token_expires_at"],
        "guilds": json.loads(row["guilds_json"]),
        "guilds_fetched_at": row["guilds_fetched_at"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_seen_at": row["last_seen_at"],
    }
    if entry["expires_at"] < time.time():
        db_delete_session(sid)
        return None
    return entry


def db_delete_session(sid):
    with _DB_LOCK, connect() as db:
        db.execute("DELETE FROM web_sessions WHERE sid_hash = ?", (_hash_sid(sid),))


def db_touch_session(sid, entry):
    with _DB_LOCK, connect() as db:
        db.execute(
            """
            UPDATE web_sessions SET access_token = ?, refresh_token = ?, token_expires_at = ?,
                   guilds_json = ?, guilds_fetched_at = ?, last_seen_at = ?
            WHERE sid_hash = ?
            """,
            (
                _encrypt_token(entry["access_token"]),
                _encrypt_token(entry.get("refresh_token")),
                entry.get("token_expires_at", 0),
                json.dumps(entry.get("guilds", {})),
                entry.get("guilds_fetched_at", 0),
                time.time(),
                _hash_sid(sid),
            ),
        )


def db_gc():
    cutoff = datetime.now(UTC).timestamp() - AUDIT_KEEP_DAYS * 86400
    with _DB_LOCK, connect() as db:
        db.execute("DELETE FROM web_sessions WHERE expires_at < ?", (time.time(),))
        db.execute(
            "DELETE FROM web_audit WHERE created_at < ?",
            (datetime.fromtimestamp(cutoff, UTC).isoformat(),),
        )


def db_add_audit(guild_id, user, action, changes, ip):
    with _DB_LOCK, connect() as db:
        db.execute(
            """
            INSERT INTO web_audit (guild_id, user_id, username, action, changes_json, ip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(guild_id),
                user["id"],
                user["username"],
                action,
                json.dumps(changes, ensure_ascii=False),
                ip,
                datetime.now(UTC).isoformat(),
            ),
        )


def db_get_audit(guild_id, limit):
    with _DB_LOCK, connect() as db:
        rows = db.execute(
            """
            SELECT username, user_id, action, changes_json, created_at
            FROM web_audit WHERE guild_id = ? ORDER BY id DESC LIMIT ?
            """,
            (str(guild_id), limit),
        ).fetchall()
    return [
        {
            "username": row["username"],
            "user_id": row["user_id"],
            "action": row["action"],
            "changes": json.loads(row["changes_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


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
            ("GET", "/invite", self.handle_invite),
            ("GET", "/auth/login", self.handle_login),
            ("GET", "/auth/callback", self.handle_callback),
            ("POST", "/auth/logout", self.handle_logout),
            ("GET", "/me", self.handle_me),
            ("GET", "/guilds", self.handle_guilds),
            ("GET", "/guilds/{guild_id}/config", self.handle_config_get),
            ("PUT", "/guilds/{guild_id}/config", self.handle_config_put),
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
            print("Web API disabled (set WEB_ENABLED=true to serve the dashboard API).")
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
        print(
            f"Web API listening on {WEB_HOST}:{WEB_PORT}{API_PREFIX} • {oauth_note} • "
            f"sessions in SQLite • {crypto_note}"
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

    def _client_ip(self, request):
        if TRUST_PROXY:
            # CF-Connecting-IP is set by Cloudflare and cannot be spoofed by the
            # client through the tunnel; fall back to the first X-Forwarded-For hop.
            cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
            if cf_ip:
                return cf_ip
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.remote or "?"

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
            # This is a pure JSON API: forbid loading/executing any resource.
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
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
        assert self.http is not None
        async with self.http.post(
            f"{DISCORD_API}/oauth2/token",
            data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, **data},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            if response.status >= 400:
                return None
            return await response.json()

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
        return response

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

        token_data = await self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": OAUTH_REDIRECT}
        )
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
        return response

    async def handle_logout(self, request):
        self._check_origin(request)
        sid, entry = await self._session(request)
        if sid and entry:
            # revoke the token at Discord, then forget the session
            assert self.http is not None
            if entry.get("access_token"):
                try:
                    await self.http.post(
                        f"{DISCORD_API}/oauth2/token/revoke",
                        data={
                            "client_id": CLIENT_ID,
                            "client_secret": CLIENT_SECRET,
                            "token": entry["access_token"],
                            "token_type_hint": "access_token",
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                except aiohttp.ClientError:
                    pass
            await asyncio.to_thread(db_delete_session, sid)
            self._session_locks.pop(sid, None)
        response = web.json_response({"ok": True})
        response.del_cookie(SESSION_COOKIE)
        return response

    # ── public endpoints ─────────────────────────────────────────────

    async def handle_health(self, request):
        db_ok = await asyncio.to_thread(db_ping)
        payload = {
            "ok": bool(db_ok and self.bot.is_ready()),
            "bot_ready": self.bot.is_ready(),
            "db_ok": db_ok,
        }
        return web.json_response(payload, status=200 if db_ok else 503)

    async def handle_invite(self, request):
        if not CLIENT_ID:
            raise ApiError(503, "Client id not configured.", code="oauth_unavailable")
        params = urlencode(
            {"client_id": CLIENT_ID, "permissions": INVITE_PERMISSIONS, "scope": "bot applications.commands"}
        )
        return web.HTTPFound(f"https://discord.com/oauth2/authorize?{params}")

    async def handle_stats(self, request):
        self._rate_limit(request, "read")
        guilds = list(self.bot.guilds)
        launched_at = getattr(self.bot, "launched_at", None)
        uptime = int((datetime.now(UTC) - launched_at).total_seconds()) if launched_at else 0
        return web.json_response(
            {
                "version": BOT_VERSION,
                "codename": BOT_CODENAME,
                "guilds": len(guilds),
                "members": sum(g.member_count or 0 for g in guilds),
                "commands": len(list(self.bot.tree.walk_commands())),
                "uptime_seconds": uptime,
                "ready": self.bot.is_ready(),
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
        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        automod = dict(AUTOMOD_DEFAULTS)
        automod.update(settings.get("automod") or {})

        return {
            "guild": {
                "id": str(guild.id),
                "name": guild.name,
                "icon": str(guild.icon) if guild.icon else None,
                "member_count": guild.member_count,
            },
            "settings": {
                **{key: (str(settings[key]) if settings.get(key) else None) for key in CHANNEL_KEYS},
                **{key: (str(settings[key]) if settings.get(key) else None) for key in ROLE_KEYS},
                "automod": automod,
            },
            "channels": [
                {"id": str(channel.id), "name": channel.name,
                 "category": channel.category.name if channel.category else None}
                for channel in guild.text_channels
            ],
            "roles": [
                {"id": str(role.id), "name": role.name, "color": f"#{role.color.value:06X}",
                 "assignable": role < guild.me.top_role and not role.managed}
                for role in sorted(guild.roles, key=lambda r: -r.position)
                if not role.is_default()
            ],
        }

    async def handle_config_get(self, request):
        self._rate_limit(request, "read")
        _, _, guild = await self._authorized_guild(request)
        return web.json_response(await self._config_payload(guild))

    async def handle_audit(self, request):
        self._rate_limit(request, "read")
        _, _, guild = await self._authorized_guild(request)
        limit = min(int(request.query.get("limit", "50") or 50), 200)
        entries = await asyncio.to_thread(db_get_audit, guild.id, limit)
        return web.json_response({"audit": entries})

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

        for key in CHANNEL_KEYS:
            if key not in body:
                continue
            value = body[key]
            if value in (None, "", 0):
                changes[key] = None
            elif str(value) in text_channel_ids:
                changes[key] = int(value)
            else:
                errors.append(f"{key}: not a text channel in this guild")

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

        if "automod" in body:
            raw = body["automod"]
            if not isinstance(raw, dict):
                errors.append("automod: must be an object")
            else:
                current = await asyncio.to_thread(get_guild_settings, guild.id)
                automod = dict(AUTOMOD_DEFAULTS)
                automod.update(current.get("automod") or {})
                for flag in ("invites", "spam"):
                    if flag in raw:
                        automod[flag] = bool(raw[flag])
                if "badwords" in raw:
                    if not isinstance(raw["badwords"], list):
                        errors.append("automod.badwords: must be a list of words")
                    else:
                        words = []
                        for word in raw["badwords"][:MAX_BADWORDS]:
                            word = str(word).strip().lower()[:MAX_BADWORD_LENGTH]
                            if word and word not in words:
                                words.append(word)
                        automod["badwords"] = words
                changes["automod"] = automod

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
            pass

        return web.json_response(await self._config_payload(guild))
