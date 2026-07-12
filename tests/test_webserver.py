"""Smoke test for the hardened dashboard API — fake bot, real server, real SQLite.

Covers the full v3 contract: uniform error envelope + codes, /api/v1 + legacy
aliases, CORS allow-list, HMAC-signed OAuth state, token encryption at rest,
health DB probe, bot-starting 503, and the CSRF Origin guard.

Run standalone:  python tests/test_webserver.py
"""

import asyncio
import os
import sys
import time
from datetime import UTC, datetime

os.environ["WEB_ENABLED"] = "true"
os.environ["WEB_PORT"] = "8399"
os.environ["WEB_HOST"] = "127.0.0.1"
# creds present ⇒ OAuth enabled + token encryption active + state HMAC keyed
os.environ["DISCORD_CLIENT_ID"] = "123456789012345678"
os.environ["DISCORD_CLIENT_SECRET"] = "test-client-secret-abcdef"
os.environ["WEB_CORS_ORIGIN"] = "http://localhost:5173"

# repo root = parent of this tests/ directory (path-agnostic for CI)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp  # noqa: E402

from core.database import connect  # noqa: E402
from core.storage import get_guild_settings, reset_guild_settings  # noqa: E402
from core.webserver import (  # noqa: E402
    _CIPHER,
    _hash_sid,
    WebServer,
    db_load_session,
    db_ping,
    db_save_session,
)

TEST_GUILD_ID = 987654321987654321
BASE = "http://127.0.0.1:8399"
V1 = f"{BASE}/api/v1"
LEGACY = f"{BASE}/api"
SID = "test-sid-" + "x" * 20


class FakeChannel:
    def __init__(self, cid, name):
        self.id = cid
        self.name = name
        self.category = None


class FakeGuild:
    def __init__(self):
        self.id = TEST_GUILD_ID
        self.name = "Test Guild"
        self.icon = None
        self.member_count = 42
        self.text_channels = [FakeChannel(111, "general"), FakeChannel(112, "logs")]
        self.roles = []


class FakeTree:
    def walk_commands(self):
        return iter(())


class FakeBot:
    def __init__(self):
        self.guilds = []
        self.tree = FakeTree()
        self.launched_at = None
        self.ready = True
        self._guild = FakeGuild()

    def is_ready(self):
        return self.ready

    def get_guild(self, gid):
        return self._guild if gid == TEST_GUILD_ID else None

    def dispatch(self, *args, **kwargs):
        pass


async def main():
    server = WebServer(FakeBot())
    await server.start()
    results = []

    async with aiohttp.ClientSession() as http:
        async def check(name, ok):
            results.append((name, ok))
            print(("PASS" if ok else "FAIL"), name)

        # ── health + DB probe (fix #5) ────────────────────────────────
        async with http.get(f"{V1}/health") as r:
            data = await r.json()
            await check("health 200 + db_ok", r.status == 200 and data["ok"] and data["db_ok"] is True)
            await check("security headers present", r.headers.get("X-Content-Type-Options") == "nosniff")
        await check("db_ping direct", db_ping() is True)

        # ── legacy alias still works (fix #3) ─────────────────────────
        async with http.get(f"{LEGACY}/health") as r:
            await check("legacy /api/health alias works", r.status == 200)

        # ── unknown route → uniform JSON 404 (fix #1) ─────────────────
        async with http.get(f"{V1}/does-not-exist") as r:
            data = await r.json()
            await check(
                "unknown route → JSON 404 with code",
                r.status == 404 and data.get("code") == "not_found",
            )

        # ── CORS allow-list ───────────────────────────────────────────
        async with http.get(f"{V1}/health", headers={"Origin": "http://localhost:5173"}) as r:
            await check(
                "CORS reflects allowed origin",
                r.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173",
            )
        async with http.get(f"{V1}/health", headers={"Origin": "http://evil.example"}) as r:
            await check(
                "CORS blocks unlisted origin",
                r.headers.get("Access-Control-Allow-Origin") is None,
            )
        async with http.options(
            f"{V1}/guilds/123/config",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT"},
        ) as r:
            await check(
                "OPTIONS preflight → 204 + CORS",
                r.status == 204 and r.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173",
            )

        async with http.get(f"{V1}/stats") as r:
            data = await r.json()
            await check("stats fields", r.status == 200 and {"version", "guilds", "commands"} <= set(data))

        # ── error envelope carries a machine-readable code (fix #2) ───
        async with http.get(f"{V1}/me") as r:
            data = await r.json()
            await check(
                "401 has code=unauthorized",
                r.status == 401 and data.get("code") == "unauthorized",
            )

        # ── login redirect: no prompt=none, signed state ─────────────
        async with http.get(f"{V1}/auth/login", allow_redirects=False) as r:
            loc = r.headers.get("Location", "")
            set_cookie = r.headers.get("Set-Cookie", "")
            await check(
                "login redirects to Discord authorize",
                r.status == 302 and "discord.com/oauth2/authorize" in loc,
            )
            await check("login drops prompt=none", "prompt=none" not in loc and "prompt%3Dnone" not in loc)
            await check("login sets signed state cookie", "ng_state=" in set_cookie)

        async with http.get(f"{V1}/auth/callback?code=x&state=wrong", allow_redirects=False) as r:
            data = await r.json()
            await check(
                "callback rejects bad state (400 invalid_state)",
                r.status == 400 and data.get("code") == "invalid_state",
            )

        # ── state token self-verifies without server memory ──────────
        token = server._make_state()
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        await check("state token self-verifies", server._valid_state(token) is True)
        await check("state token rejects tampering", server._valid_state(tampered) is False)
        await check("state token rejects garbage", server._valid_state("a.b.c") is False)

        # ── auth rate limit (fires enough to exhaust the 10/min bucket) ─
        statuses = []
        for _ in range(15):
            async with http.get(f"{V1}/auth/login", allow_redirects=False) as r:
                statuses.append(r.status)
        await check("auth rate limit kicks in (429)", 429 in statuses)

        # inject a logged-in session straight into SQLite
        entry = {
            "user": {"id": "1", "username": "Vik", "avatar": None},
            "access_token": "super-secret-access-token",
            "refresh_token": "super-secret-refresh-token",
            "token_expires_at": time.time() + 3600,
            "guilds": {str(TEST_GUILD_ID): {
                "id": str(TEST_GUILD_ID), "name": "Test Guild", "icon": None,
                "owner": True, "permissions": 0x20,
            }},
            "guilds_fetched_at": time.time(),
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": time.time() + 3600,
        }
        db_save_session(SID, entry)

        # ── tokens encrypted at rest ──────────────────────────────────
        with connect() as db:
            raw = db.execute(
                "SELECT access_token FROM web_sessions WHERE sid_hash = ?", (_hash_sid(SID),)
            ).fetchone()
        await check(
            "token encrypted at rest",
            _CIPHER is not None
            and raw["access_token"].startswith("enc:")
            and "super-secret-access-token" not in raw["access_token"],
        )
        loaded = db_load_session(SID)
        await check(
            "token round-trips on load",
            loaded is not None and loaded["access_token"] == "super-secret-access-token",
        )

        cookies = {"ng_session": SID}

        async with http.get(f"{V1}/guilds/{TEST_GUILD_ID}/config", cookies=cookies) as r:
            data = await r.json()
            await check(
                "config GET with session (v1)",
                r.status == 200 and data["guild"]["id"] == str(TEST_GUILD_ID)
                and len(data["channels"]) == 2 and "automod" in data["settings"],
            )
        async with http.get(f"{LEGACY}/guilds/{TEST_GUILD_ID}/config", cookies=cookies) as r:
            await check("config GET legacy alias", r.status == 200)

        # ── CSRF Origin guard on mutations (fix #8) ───────────────────
        async with http.put(
            f"{V1}/guilds/{TEST_GUILD_ID}/config",
            json={"welcome_channel": "111"},
            cookies=cookies,
            headers={"Origin": "http://evil.example"},
        ) as r:
            data = await r.json()
            await check(
                "PUT rejects foreign Origin (403 bad_origin)",
                r.status == 403 and data.get("code") == "bad_origin",
            )

        bad = {"welcome_channel": "999"}
        async with http.put(f"{V1}/guilds/{TEST_GUILD_ID}/config", json=bad, cookies=cookies) as r:
            data = await r.json()
            await check(
                "PUT rejects foreign channel (400 validation_failed)",
                r.status == 400 and data.get("code") == "validation_failed" and data.get("details"),
            )

        good = {"welcome_channel": "111", "log_channel": "112",
                "automod": {"invites": False, "badwords": ["Spoiler", "spoiler", "  x  "]}}
        async with http.put(f"{V1}/guilds/{TEST_GUILD_ID}/config", json=good, cookies=cookies) as r:
            data = await r.json()
            saved = data.get("settings", {})
            await check(
                "PUT saves + normalizes",
                r.status == 200
                and saved.get("welcome_channel") == "111"
                and saved.get("automod", {}).get("invites") is False
                and saved.get("automod", {}).get("badwords") == ["spoiler", "x"],
            )

        stored = get_guild_settings(TEST_GUILD_ID)
        await check("storage really persisted", stored.get("welcome_channel") == 111)

        async with http.get(f"{V1}/guilds/{TEST_GUILD_ID}/audit", cookies=cookies) as r:
            data = await r.json()
            first = (data.get("audit") or [{}])[0]
            await check(
                "audit trail recorded",
                r.status == 200 and first.get("action") == "config_update"
                and first.get("username") == "Vik",
            )

        # ── bot-starting → 503 (fix #6) ───────────────────────────────
        server.bot.ready = False
        async with http.get(f"{V1}/guilds/{TEST_GUILD_ID}/config", cookies=cookies) as r:
            data = await r.json()
            await check(
                "config GET while bot starting → 503 bot_starting",
                r.status == 503 and data.get("code") == "bot_starting",
            )
        server.bot.ready = True

        async with http.post(f"{V1}/auth/logout", cookies=cookies) as r:
            await check("logout ok", r.status == 200)
        await check("session gone after logout", db_load_session(SID) is None)

    reset_guild_settings(TEST_GUILD_ID)
    await server.stop()

    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        raise SystemExit(1)


asyncio.run(main())
