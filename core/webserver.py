"""Embedded web API for the NovaGuard dashboard.

Runs an aiohttp server inside the bot process so the website can read and
write the same per-guild settings the slash commands use. Authentication is
Discord OAuth2 (identify + guilds); only members with Manage Server on a
guild the bot is in may touch that guild's config.

Enable by setting WEB_ENABLED=true plus DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET
(the bot application's OAuth2 credentials) in .env.
"""

import asyncio
import os
import secrets
import time
from datetime import UTC, datetime
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from .config import BOT_CODENAME, BOT_VERSION
from .storage import get_guild_settings, update_guild_settings

WEB_ENABLED = os.getenv("WEB_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8300") or 8300)
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
OAUTH_REDIRECT = os.getenv("WEB_OAUTH_REDIRECT", f"http://localhost:{WEB_PORT}/api/auth/callback")
CORS_ORIGIN = os.getenv("WEB_CORS_ORIGIN", "").strip().rstrip("/")
AFTER_LOGIN = os.getenv("WEB_AFTER_LOGIN", "/api/me")
COOKIE_SECURE = os.getenv("WEB_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}

DISCORD_API = "https://discord.com/api/v10"
SESSION_COOKIE = "ng_session"
STATE_COOKIE = "ng_state"
SESSION_TTL = 7 * 24 * 3600
GUILDS_CACHE_SECONDS = 120
MANAGE_GUILD = 0x20

CHANNEL_KEYS = (
    "welcome_channel",
    "goodbye_channel",
    "log_channel",
    "update_channel",
    "github_event_channel",
    "error_log_channel",
)
ROLE_KEYS = ("autorole", "ticket_staff_role")
AUTOMOD_DEFAULTS = {"invites": True, "spam": True, "badwords": []}
MAX_BADWORDS = 100
MAX_BADWORD_LENGTH = 40


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class WebServer:
    """The dashboard API. One instance per bot, started from setup_hook."""

    def __init__(self, bot):
        self.bot = bot
        self.runner = None
        self.http: aiohttp.ClientSession | None = None
        self.sessions: dict[str, dict] = {}
        self.pending_states: dict[str, float] = {}

    # ── lifecycle ────────────────────────────────────────────────────

    @property
    def oauth_ready(self):
        return bool(CLIENT_ID and CLIENT_SECRET)

    async def start(self):
        if not WEB_ENABLED:
            print("Web API disabled (set WEB_ENABLED=true to serve the dashboard API).")
            return
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))

        app = web.Application()
        app.router.add_get("/api/health", self.handle_health)
        app.router.add_get("/api/stats", self.handle_stats)
        app.router.add_get("/api/auth/login", self.handle_login)
        app.router.add_get("/api/auth/callback", self.handle_callback)
        app.router.add_post("/api/auth/logout", self.handle_logout)
        app.router.add_get("/api/me", self.handle_me)
        app.router.add_get("/api/guilds", self.handle_guilds)
        app.router.add_get("/api/guilds/{guild_id}/config", self.handle_config_get)
        app.router.add_put("/api/guilds/{guild_id}/config", self.handle_config_put)
        app.router.add_options("/{tail:.*}", self.handle_preflight)

        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, WEB_HOST, WEB_PORT)
        await site.start()
        oauth_note = "OAuth ready" if self.oauth_ready else "OAuth NOT configured (login disabled)"
        print(f"Web API listening on {WEB_HOST}:{WEB_PORT} • {oauth_note}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        if self.http:
            await self.http.close()
            self.http = None

    # ── plumbing ─────────────────────────────────────────────────────

    def _cors_headers(self, request):
        origin = request.headers.get("Origin", "")
        if not origin:
            return {}
        if CORS_ORIGIN and origin.rstrip("/") != CORS_ORIGIN:
            return {}
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET, PUT, POST, OPTIONS",
            "Vary": "Origin",
        }

    def _json(self, request, payload, status=200):
        return web.json_response(payload, status=status, headers=self._cors_headers(request))

    async def handle_preflight(self, request):
        return web.Response(status=204, headers=self._cors_headers(request))

    def _prune(self):
        now = time.time()
        for sid in [s for s, entry in self.sessions.items() if entry["expires_at"] < now]:
            self.sessions.pop(sid, None)
        for state in [s for s, exp in self.pending_states.items() if exp < now]:
            self.pending_states.pop(state, None)

    def _session(self, request):
        self._prune()
        sid = request.cookies.get(SESSION_COOKIE)
        return self.sessions.get(sid) if sid else None

    def _require_session(self, request):
        entry = self._session(request)
        if entry is None:
            raise ApiError(401, "Not logged in. Start at /api/auth/login.")
        return entry

    async def _discord_get(self, path, token):
        assert self.http is not None
        async with self.http.get(
            f"{DISCORD_API}{path}", headers={"Authorization": f"Bearer {token}"}
        ) as response:
            if response.status == 401:
                raise ApiError(401, "Discord session expired — log in again.")
            if response.status >= 400:
                raise ApiError(502, f"Discord API error {response.status}.")
            return await response.json()

    async def _refresh_guilds(self, entry):
        if time.time() - entry.get("guilds_fetched_at", 0) < GUILDS_CACHE_SECONDS:
            return
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

    def _can_manage(self, entry, guild_id):
        info = entry.get("guilds", {}).get(str(guild_id))
        if not info:
            return False
        return info["owner"] or bool(info["permissions"] & MANAGE_GUILD)

    async def _authorized_guild(self, request):
        entry = self._require_session(request)
        guild_id = request.match_info["guild_id"]
        if not guild_id.isdigit():
            raise ApiError(400, "Invalid guild id.")
        await self._refresh_guilds(entry)
        if not self._can_manage(entry, guild_id):
            raise ApiError(403, "You need Manage Server on that guild.")
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            raise ApiError(404, "NovaGuard is not in that guild.")
        return entry, guild

    # ── auth ─────────────────────────────────────────────────────────

    async def handle_login(self, request):
        if not self.oauth_ready:
            return self._json(request, {"error": "OAuth not configured on the bot."}, status=503)
        self._prune()
        state = secrets.token_urlsafe(24)
        self.pending_states[state] = time.time() + 600
        params = urlencode(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": OAUTH_REDIRECT,
                "response_type": "code",
                "scope": "identify guilds",
                "state": state,
                "prompt": "none",
            }
        )
        response = web.HTTPFound(f"https://discord.com/oauth2/authorize?{params}")
        response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True,
                            samesite="Lax", secure=COOKIE_SECURE)
        return response

    async def handle_callback(self, request):
        code = request.query.get("code")
        state = request.query.get("state", "")
        cookie_state = request.cookies.get(STATE_COOKIE, "")
        if not code or not state or state != cookie_state or self.pending_states.pop(state, 0) < time.time():
            return self._json(request, {"error": "Invalid OAuth state — try logging in again."}, status=400)

        assert self.http is not None
        async with self.http.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_REDIRECT,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as token_response:
            if token_response.status >= 400:
                return self._json(request, {"error": "Discord rejected the OAuth code."}, status=502)
            token_data = await token_response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            return self._json(request, {"error": "No access token from Discord."}, status=502)

        try:
            user = await self._discord_get("/users/@me", access_token)
        except ApiError as error:
            return self._json(request, {"error": error.message}, status=error.status)

        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = {
            "user": {
                "id": str(user["id"]),
                "username": user.get("global_name") or user.get("username", "?"),
                "avatar": user.get("avatar"),
            },
            "access_token": access_token,
            "guilds": {},
            "guilds_fetched_at": 0,
            "expires_at": time.time() + SESSION_TTL,
        }

        response = web.HTTPFound(AFTER_LOGIN)
        response.set_cookie(SESSION_COOKIE, sid, max_age=SESSION_TTL, httponly=True,
                            samesite="Lax", secure=COOKIE_SECURE)
        response.del_cookie(STATE_COOKIE)
        return response

    async def handle_logout(self, request):
        sid = request.cookies.get(SESSION_COOKIE)
        if sid:
            self.sessions.pop(sid, None)
        response = self._json(request, {"ok": True})
        response.del_cookie(SESSION_COOKIE)
        return response

    # ── public endpoints ─────────────────────────────────────────────

    async def handle_health(self, request):
        return self._json(request, {"ok": True, "bot_ready": self.bot.is_ready()})

    async def handle_stats(self, request):
        guilds = list(self.bot.guilds)
        launched_at = getattr(self.bot, "launched_at", None)
        uptime = int((datetime.now(UTC) - launched_at).total_seconds()) if launched_at else 0
        return self._json(
            request,
            {
                "version": BOT_VERSION,
                "codename": BOT_CODENAME,
                "guilds": len(guilds),
                "members": sum(g.member_count or 0 for g in guilds),
                "commands": len(list(self.bot.tree.walk_commands())),
                "uptime_seconds": uptime,
                "ready": self.bot.is_ready(),
            },
        )

    # ── session endpoints ────────────────────────────────────────────

    async def handle_me(self, request):
        try:
            entry = self._require_session(request)
        except ApiError as error:
            return self._json(request, {"error": error.message}, status=error.status)
        return self._json(request, {"user": entry["user"]})

    async def handle_guilds(self, request):
        try:
            entry = self._require_session(request)
            await self._refresh_guilds(entry)
        except ApiError as error:
            return self._json(request, {"error": error.message}, status=error.status)

        bot_guild_ids = {str(g.id) for g in self.bot.guilds}
        manageable = [
            {**info, "bot_present": info["id"] in bot_guild_ids}
            for info in entry["guilds"].values()
            if info["owner"] or info["permissions"] & MANAGE_GUILD
        ]
        manageable.sort(key=lambda g: (not g["bot_present"], g["name"].lower()))
        return self._json(request, {"guilds": manageable})

    # ── guild config ─────────────────────────────────────────────────

    def _config_payload(self, guild):
        settings = get_guild_settings(guild.id)
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
        try:
            _, guild = await self._authorized_guild(request)
        except ApiError as error:
            return self._json(request, {"error": error.message}, status=error.status)
        return self._json(request, self._config_payload(guild))

    async def handle_config_put(self, request):
        try:
            entry, guild = await self._authorized_guild(request)
            body = await request.json()
        except ApiError as error:
            return self._json(request, {"error": error.message}, status=error.status)
        except Exception:
            return self._json(request, {"error": "Body must be JSON."}, status=400)

        if not isinstance(body, dict):
            return self._json(request, {"error": "Body must be a JSON object."}, status=400)

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
                automod = dict(AUTOMOD_DEFAULTS)
                automod.update(get_guild_settings(guild.id).get("automod") or {})
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
            return self._json(request, {"error": "Validation failed.", "details": errors}, status=400)
        if not changes:
            return self._json(request, {"error": "Nothing to update."}, status=400)

        await asyncio.to_thread(update_guild_settings, guild.id, **changes)

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

        return self._json(request, self._config_payload(guild))
