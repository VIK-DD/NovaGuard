"""Smoke test for the hardened dashboard API — fake bot, real server, real SQLite.

Covers the full v3 contract: uniform error envelope + codes, /api/v1 + legacy
aliases, CORS allow-list, HMAC-signed OAuth state, token encryption at rest,
health DB probe, bot-starting 503, and the CSRF Origin guard.

Run standalone:  python tests/test_webserver.py
"""

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

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
from core.invite_permissions import DEFAULT_INVITE_PERMISSIONS  # noqa: E402
from core.levels_settings import resolve_levels  # noqa: E402
from core.maintenance import (  # noqa: E402
    MAINTENANCE_STATE_FILE,
    load_maintenance_state,
    save_maintenance_state,
    verify_preview_code,
)
from core.storage import get_guild_settings, reset_guild_settings  # noqa: E402
from core.webserver import (  # noqa: E402
    _CIPHER,
    _hash_sid,
    ApiError,
    WebServer,
    after_login_strands_user,
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
        self.dispatched = []

    def is_ready(self):
        return self.ready

    def get_guild(self, gid):
        return self._guild if gid == TEST_GUILD_ID else None

    def dispatch(self, *args, **kwargs):
        # Recorded, not simulated: no listener runs, but a test can assert a
        # config save actually reached the same "modlog" event moderation
        # actions use (cogs/logs.py on_modlog -> send_log -> log_channel).
        self.dispatched.append((args, kwargs))


class TimeoutRequest:
    async def __aenter__(self):
        raise asyncio.TimeoutError

    async def __aexit__(self, *args):
        return False


class TimeoutHttp:
    def get(self, *args, **kwargs):
        return TimeoutRequest()

    def post(self, *args, **kwargs):
        return TimeoutRequest()


async def main():
    server = WebServer(FakeBot())
    await server.start()
    results = []

    async with aiohttp.ClientSession() as http:
        async def check(name, ok):
            results.append((name, ok))
            print(("PASS" if ok else "FAIL"), name)

        # ── Discord upstream timeout stays a retryable API response ─────
        original_http = server.http
        server.http = TimeoutHttp()
        try:
            await server._discord_get("/users/@me/guilds", "test-token")
            timeout_result = None
        except ApiError as error:
            timeout_result = error
        finally:
            server.http = original_http
        await check(
            "Discord timeout becomes retryable 503",
            timeout_result is not None
            and timeout_result.status == 503
            and timeout_result.code == "upstream_unavailable"
            and timeout_result.retry_after == 3,
        )

        # ── post-login redirect target ────────────────────────────────
        # A bare path resolves against the API's own origin, so it can never
        # reach a dashboard declared on a separate origin. Only the first login
        # is affected — later visits already carry the session cookie — so this
        # has to be caught at startup rather than waited for as a bug report.
        split_origin = {"https://novaguard.fun"}
        await check(
            "path WEB_AFTER_LOGIN flagged when the dashboard is cross-origin",
            after_login_strands_user("/dashboard", split_origin)
            and after_login_strands_user("/api/me", split_origin),
        )
        await check(
            "absolute WEB_AFTER_LOGIN accepted",
            not after_login_strands_user("https://novaguard.fun/dashboard/", split_origin),
        )
        await check(
            "path WEB_AFTER_LOGIN fine when no cross-origin dashboard is declared",
            not after_login_strands_user("/api/me", set()),
        )

        # ── OAuth token exchange survives a flaky upstream ────────────
        # Observed in production: aiohttp.SocketTimeoutError escaped
        # _token_request, which had no handler, and the login died as an
        # unhandled 500 with a stack trace. It must become the same retryable
        # error every other Discord call produces.
        original_http = server.http
        server.http = TimeoutHttp()
        try:
            await server._token_request({"grant_type": "authorization_code", "code": "x"})
            token_timeout = None
        except ApiError as error:
            token_timeout = error
        finally:
            server.http = original_http
        await check(
            "a token-exchange timeout is a clean 503, not an unhandled error",
            token_timeout is not None
            and token_timeout.status == 503
            and token_timeout.code == "upstream_unavailable",
        )
        await check(
            "a timeout never reads as Discord refusing the token",
            # None means "Discord answered and said no", which makes
            # _ensure_fresh_token delete the session. A blip must not do that.
            token_timeout is not None,
        )

        # ── health + DB probe (fix #5) ────────────────────────────────
        async with http.get(f"{V1}/health") as r:
            data = await r.json()
            await check("health 200 + db_ok", r.status == 200 and data["ok"] and data["db_ok"] is True)
            await check("security headers present", r.headers.get("X-Content-Type-Options") == "nosniff")
        await check("db_ping direct", db_ping() is True)

        # ── maintenance state rides along on /health ──────────────────
        # Saved and restored around the checks: this writes the real
        # data/maintenance.json, and a test must not leave the bot shut down.
        original_maintenance = load_maintenance_state()
        try:
            save_maintenance_state(True, "Testing the sync", updated_by="test-suite")
            async with http.get(f"{V1}/health") as r:
                data = await r.json()
                await check(
                    "health reports maintenance on, with the message",
                    r.status == 200
                    and data["maintenance"]["enabled"] is True
                    and data["maintenance"]["message"] == "Testing the sync",
                )

            save_maintenance_state(False, updated_by="test-suite")
            async with http.get(f"{V1}/health") as r:
                data = await r.json()
                await check(
                    "health reports maintenance off, and leaks no stale message",
                    data["maintenance"]["enabled"] is False
                    and "message" not in data["maintenance"],
                )
            # ── preview code lifecycle ────────────────────────────────
            first = save_maintenance_state(True, "Preview test", updated_by="test-suite")
            code = first.get("preview_code")
            await check(
                "enabling from off mints a code", bool(code) and code.startswith("ng_preview_")
            )

            raw_file = json.loads(MAINTENANCE_STATE_FILE.read_text(encoding="utf-8"))
            await check(
                "the code itself is never written to disk",
                "preview_code" not in raw_file
                and code not in raw_file.values()
                and bool(raw_file.get("preview_hash")),
            )

            again = save_maintenance_state(True, "Corrected wording", updated_by="test-suite")
            await check(
                "re-enabling while on keeps the code and the activation time",
                again.get("preview_code") is None
                and again["preview_hash"] == first["preview_hash"]
                and again["updated_at"] == first["updated_at"],
            )

            await check("the right code verifies", verify_preview_code(code) == first["updated_at"])
            await check("a wrong code does not", verify_preview_code("ng_preview_nope") is None)

            save_maintenance_state(False, updated_by="test-suite")
            await check(
                "disabling clears the code",
                verify_preview_code(code) is None
                and load_maintenance_state().get("preview_hash") is None,
            )

            # ── the verify route ──────────────────────────────────────
            live = save_maintenance_state(True, "Preview route", updated_by="test-suite")
            live_code = live["preview_code"]

            async with http.get(f"{V1}/health") as r:
                data = await r.json()
                await check(
                    "health publishes when maintenance began, and no secrets",
                    data["maintenance"]["since"] == live["updated_at"]
                    and "preview_hash" not in data["maintenance"]
                    and "preview_salt" not in data["maintenance"]
                    and "preview_code" not in data["maintenance"],
                )

            async with http.post(f"{V1}/maintenance/preview", json={"code": live_code}) as r:
                data = await r.json()
                await check(
                    "the right code is accepted",
                    r.status == 200 and data["ok"] is True and data["since"] == live["updated_at"],
                )

            async with http.post(f"{V1}/maintenance/preview", json={"code": "ng_preview_wrong"}) as r:
                wrong_status, wrong_body = r.status, await r.text()
            await check("a wrong code is refused", wrong_status == 401)

            save_maintenance_state(False, updated_by="test-suite")
            async with http.post(f"{V1}/maintenance/preview", json={"code": live_code}) as r:
                off_status, off_body = r.status, await r.text()
            await check(
                "a code sent while maintenance is off is indistinguishable from a wrong one",
                off_status == wrong_status and off_body == wrong_body,
            )
        finally:
            save_maintenance_state(
                original_maintenance["enabled"],
                original_maintenance["message"],
                updated_by=original_maintenance.get("updated_by"),
            )

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
            await check(
                "stats expose canonical public release",
                r.status == 200
                and data.get("version") == "2.0"
                and data.get("phase_label") == "Open Beta"
                and {"release_label", "runtime_version", "guilds", "commands"} <= set(data),
            )

        async with http.get(f"{V1}/invite", allow_redirects=False) as r:
            query = parse_qs(urlparse(r.headers.get("Location", "")).query)
            await check(
                "invite uses the least-privilege permission set",
                r.status == 302
                and query.get("permissions") == [DEFAULT_INVITE_PERMISSIONS]
                and query.get("permissions") != ["8"],
            )

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
                and len(data["channels"]) == 2
                and "automod" in data["settings"]
                and "voice_report_channel" in data["settings"],
            )
        async with http.get(f"{V1}/guilds/{TEST_GUILD_ID}/config", cookies=cookies) as r:
            data = await r.json()
            await check(
                "config payload exposes github_watch_configured",
                r.status == 200 and isinstance(data.get("github_watch_configured"), bool),
            )
        async with http.get(f"{LEGACY}/guilds/{TEST_GUILD_ID}/config", cookies=cookies) as r:
            await check("config GET legacy alias", r.status == 200)

        async with http.get(f"{V1}/guilds/{TEST_GUILD_ID}/dashboard", cookies=cookies) as r:
            data = await r.json()
            offsite = data.get("backup", {}).get("offsite", {})
            await check(
                "dashboard exposes sanitized off-site backup health",
                r.status == 200
                and {
                    "configured",
                    "matches_backup",
                    "latest_ok",
                    "uploaded_at",
                    "check_ok",
                    "checked_at",
                }
                == set(offsite)
                and "destination" not in offsite
                and "remote_path" not in offsite,
            )

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

        # ── config save reaches the Discord log channel ─────────────────
        # cogs/logs.py's on_modlog -> send_log already ships and is proven by
        # moderation.py's kick/ban/mute embeds; this confirms the dashboard's
        # PUT actually reaches that same dispatch, not just that the code path
        # reads correctly.
        last_event, last_args = server.bot.dispatched[-1]
        await check(
            "a saved config change dispatches modlog for the guild",
            last_event[0] == "modlog" and last_event[1] is server.bot._guild,
        )
        await check(
            "the modlog embed names who changed what",
            "Vik" in last_event[2].description and "welcome_channel" in last_event[2].description,
        )
        await check(
            "the settings cache serves the write straight back",
            get_guild_settings(TEST_GUILD_ID).get("welcome_channel") == 111,
        )

        # ── levels block ──────────────────────────────────────────────
        async with http.get(f"{V1}/guilds/{TEST_GUILD_ID}/config", cookies=cookies) as r:
            levels = (await r.json()).get("settings", {}).get("levels", {})
            await check(
                "levels defaults appear in the config payload",
                levels.get("announce") == "dm"
                and levels.get("xp_min") == 5
                and levels.get("ignored_roles") == [],
            )

        patch = {"levels": {"xp_min": 3, "xp_max": 30, "cooldown": 45,
                            "announce": "channel", "announce_channel": "112",
                            "ignored_channels": ["111"]}}
        async with http.put(f"{V1}/guilds/{TEST_GUILD_ID}/config", json=patch, cookies=cookies) as r:
            saved = (await r.json()).get("settings", {}).get("levels", {})
            await check(
                "a valid levels patch saves",
                r.status == 200 and saved.get("xp_max") == 30 and saved.get("cooldown") == 45
                and saved.get("announce_channel") == "112"
                and saved.get("ignored_channels") == ["111"],
            )
        await check(
            "levels survived the round trip to storage",
            resolve_levels(get_guild_settings(TEST_GUILD_ID))["xp_max"] == 30,
        )

        # Only xp_min moves, and it has to be judged against the saved xp_max.
        async with http.put(f"{V1}/guilds/{TEST_GUILD_ID}/config",
                            json={"levels": {"xp_min": 90}}, cookies=cookies) as r:
            data = await r.json()
            await check(
                "a one-sided xp patch is checked against what is saved",
                r.status == 400 and data.get("code") == "validation_failed"
                and any("xp_max" in d for d in data.get("details", [])),
            )

        async with http.put(f"{V1}/guilds/{TEST_GUILD_ID}/config",
                            json={"levels": {"announce_channel": "999"}}, cookies=cookies) as r:
            data = await r.json()
            await check(
                "an announce channel from another guild is refused",
                r.status == 400 and data.get("code") == "validation_failed",
            )

        async with http.put(f"{V1}/guilds/{TEST_GUILD_ID}/config",
                            json={"levels": "nope"}, cookies=cookies) as r:
            await check("a non-object levels patch is refused", r.status == 400)

        async with http.get(f"{V1}/guilds/{TEST_GUILD_ID}/audit", cookies=cookies) as r:
            data = await r.json()
            first = (data.get("audit") or [{}])[0]
            await check(
                "audit trail recorded",
                r.status == 200 and first.get("action") == "config_update"
                and first.get("username") == "Vik"
                and isinstance(first.get("id"), int)
                and "next_cursor" in data,
            )

        async with http.get(
            f"{V1}/guilds/{TEST_GUILD_ID}/audit?limit=1", cookies=cookies
        ) as r:
            page_one = await r.json()
            cursor = page_one.get("next_cursor")
            first_id = (page_one.get("audit") or [{}])[0].get("id")
            await check(
                "audit page advertises an older cursor",
                r.status == 200 and isinstance(cursor, int) and first_id == cursor,
            )
        async with http.get(
            f"{V1}/guilds/{TEST_GUILD_ID}/audit?limit=1&cursor={cursor}", cookies=cookies
        ) as r:
            page_two = await r.json()
            second_id = (page_two.get("audit") or [{}])[0].get("id")
            await check(
                "audit cursor returns the next stable page",
                r.status == 200 and isinstance(second_id, int) and second_id < first_id,
            )

        async with http.get(
            f"{V1}/guilds/{TEST_GUILD_ID}/audit?kind=settings&actor=Vik", cookies=cookies
        ) as r:
            filtered = await r.json()
            await check(
                "audit filters combine safely",
                r.status == 200
                and filtered.get("audit")
                and all(
                    row.get("username") == "Vik"
                    and (
                        row.get("action") == "config_update"
                        or str(row.get("action", "")).startswith("update_")
                    )
                    for row in filtered["audit"]
                ),
            )

        for query in ("limit=banana", "limit=-1", "cursor=nope", "kind=nope", "after=not-a-date"):
            async with http.get(
                f"{V1}/guilds/{TEST_GUILD_ID}/audit?{query}", cookies=cookies
            ) as r:
                payload = await r.json()
                await check(
                    f"invalid audit query is rejected: {query}",
                    r.status == 400 and payload.get("code") == "bad_request",
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
