"""The two doors into the dashboard: the OAuth callback and the token refresh.

Both fail in ways nobody sees. A weakened state check does not break login —
it keeps working perfectly, for the attacker too. A refresh that spends a
single-use token twice logs someone out for no reason they could describe.

The existing smoke test walks the happy path end to end; these are the
branches it never reaches, chosen because each one is a defence that could be
removed without any visible symptom.
"""

import asyncio
import hashlib
import hmac
import os
import sys
import time
import unittest
from unittest import mock

# core.webserver reads these once, at import, into module constants. Whichever
# test file imports it first therefore decides them for the whole run — so
# these must match tests/test_webserver.py exactly, and are set with
# setdefault so that file wins when it gets there first. Setting a different
# port here made that file start its server on one port and connect to
# another, which surfaced as a connection error with no obvious cause.
os.environ.setdefault("WEB_ENABLED", "true")
os.environ.setdefault("WEB_PORT", "8399")
os.environ.setdefault("WEB_HOST", "127.0.0.1")
# Credentials present => OAuth enabled, token encryption active, state keyed.
os.environ.setdefault("DISCORD_CLIENT_ID", "123456789012345678")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "test-client-secret-abcdef")
os.environ.setdefault("WEB_CORS_ORIGIN", "http://localhost:5173")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import webserver as web  # noqa: E402


class FakeTree:
    def walk_commands(self):
        return iter(())


class FakeBot:
    def __init__(self):
        self.guilds = []
        self.user = None
        self.tree = FakeTree()
        self.latency = 0.05

    def is_closed(self):
        return False


class FakeRequest:
    def __init__(self, query=None, cookies=None):
        self.query = query or {}
        self.cookies = cookies or {}
        self.headers = {}
        self.remote = "203.0.113.7"


def signed_state(*, age_seconds=0, nonce="abc123", tamper=False):
    """Mint a state token the way the server does, or one that is subtly wrong."""
    issued = int(time.time()) - age_seconds
    body = f"{nonce}.{issued}"
    signature = hmac.new(web._STATE_SECRET, body.encode("utf-8"), hashlib.sha256).hexdigest()
    if tamper:
        signature = ("0" * len(signature)) if signature[0] != "0" else ("1" * len(signature))
    return f"{body}.{signature}"


class AuthTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = web.WebServer(FakeBot())
        # Rate limiting is a separate concern with its own tests. A bucket
        # shared across these would start refusing part-way through, and the
        # failures would read as auth bugs.
        self.server.rate_buckets.clear()


class ClientAddressTests(AuthTestCase):
    def test_direct_bind_ignores_spoofed_cloudflare_headers(self):
        request = FakeRequest()
        request.headers["CF-Connecting-IP"] = "198.51.100.99"

        with mock.patch.object(web, "TRUST_PROXY", False):
            self.assertEqual(self.server._client_ip(request), "203.0.113.7")

    def test_trusted_loopback_proxy_uses_a_valid_cloudflare_address(self):
        request = FakeRequest()
        request.headers["CF-Connecting-IP"] = "2001:0db8::1"

        with mock.patch.object(web, "TRUST_PROXY", True):
            self.assertEqual(self.server._client_ip(request), "2001:db8::1")

    def test_malformed_forwarded_addresses_are_never_bucket_keys(self):
        request = FakeRequest()
        request.headers["CF-Connecting-IP"] = "attacker-controlled-value"
        request.headers["X-Forwarded-For"] = "also-invalid, 203.0.113.8"

        with mock.patch.object(web, "TRUST_PROXY", True):
            self.assertEqual(self.server._client_ip(request), "203.0.113.7")


class StateGateTests(AuthTestCase):
    """Every one of these is a door that has to stay shut."""

    async def assert_refused(self, request):
        with self.assertRaises(web.ApiError) as caught:
            await self.server.handle_callback(request)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.code, "invalid_state")

    async def test_a_state_that_does_not_match_the_cookie_is_refused(self):
        # The cross-site request forgery case: an attacker can put anything in
        # the query string, but cannot write a cookie on this domain.
        await self.assert_refused(
            FakeRequest(
                query={"code": "abc", "state": signed_state(nonce="attacker")},
                cookies={web.STATE_COOKIE: signed_state(nonce="victim")},
            )
        )

    async def test_a_callback_with_no_cookie_at_all_is_refused(self):
        await self.assert_refused(FakeRequest(query={"code": "abc", "state": signed_state()}))

    async def test_a_state_with_the_right_shape_but_a_forged_signature_is_refused(self):
        # Matching the cookie is not enough. An attacker able to set both still
        # cannot sign, which is what the server secret is for.
        forged = signed_state(tamper=True)
        await self.assert_refused(
            FakeRequest(query={"code": "abc", "state": forged}, cookies={web.STATE_COOKIE: forged})
        )

    async def test_an_expired_state_is_refused(self):
        old = signed_state(age_seconds=web.STATE_TTL + 60)
        await self.assert_refused(
            FakeRequest(query={"code": "abc", "state": old}, cookies={web.STATE_COOKIE: old})
        )

    async def test_a_state_issued_in_the_future_is_refused(self):
        # A clock that jumped, or a token minted somewhere else. Either way it
        # is not something this server handed out a moment ago.
        ahead = signed_state(age_seconds=-3600)
        await self.assert_refused(
            FakeRequest(query={"code": "abc", "state": ahead}, cookies={web.STATE_COOKIE: ahead})
        )

    async def test_a_callback_without_a_code_is_refused(self):
        state = signed_state()
        await self.assert_refused(
            FakeRequest(query={"state": state}, cookies={web.STATE_COOKIE: state})
        )

    async def test_an_empty_state_does_not_match_a_missing_cookie(self):
        # Both sides absent compare equal as strings; the emptiness checks are
        # what stop that becoming a way in.
        await self.assert_refused(FakeRequest(query={"code": "abc", "state": ""}))

    async def test_a_genuine_callback_gets_past_the_gate(self):
        # Proves the refusals above are the checks working, rather than the
        # whole path being broken.
        state = signed_state()
        request = FakeRequest(
            query={"code": "abc", "state": state}, cookies={web.STATE_COOKIE: state}
        )

        with mock.patch.object(self.server, "_token_request", return_value={}) as exchange:
            with self.assertRaises(web.ApiError) as caught:
                await self.server.handle_callback(request)

        exchange.assert_awaited()
        self.assertNotEqual(caught.exception.code, "invalid_state")


class TokenRefreshTests(AuthTestCase):
    """Refresh tokens are single use, so spending one twice logs someone out."""

    SID = "session-1"

    def entry(self, *, expires_in=3600, refresh_token="r1"):
        return {
            "user": {"id": "1", "username": "vik", "avatar": None},
            "access_token": "a1",
            "refresh_token": refresh_token,
            "token_expires_at": time.time() + expires_in,
        }

    async def test_a_token_with_life_left_is_not_refreshed(self):
        entry = self.entry(expires_in=3600)

        with mock.patch.object(self.server, "_token_request") as exchange:
            await self.server._ensure_fresh_token(self.SID, entry)

        exchange.assert_not_called()

    async def test_a_token_about_to_expire_is_refreshed_and_stored(self):
        entry = self.entry(expires_in=10)
        stored = {}

        with mock.patch.object(web, "db_load_session", return_value=dict(entry)), \
             mock.patch.object(web, "db_touch_session", side_effect=lambda sid, e: stored.update(e)), \
             mock.patch.object(
                 self.server,
                 "_token_request",
                 return_value={"access_token": "a2", "refresh_token": "r2", "expires_in": 3600},
             ):
            await self.server._ensure_fresh_token(self.SID, entry)

        self.assertEqual(entry["access_token"], "a2")
        self.assertEqual(entry["refresh_token"], "r2")
        self.assertGreater(entry["token_expires_at"], time.time() + 3000)
        self.assertEqual(stored.get("access_token"), "a2")

    async def test_a_refresh_that_returns_no_new_refresh_token_keeps_the_old_one(self):
        # Discord may answer without one. Overwriting with None would end the
        # session at the following refresh instead.
        entry = self.entry(expires_in=10)

        with mock.patch.object(web, "db_load_session", return_value=dict(entry)), \
             mock.patch.object(web, "db_touch_session"), \
             mock.patch.object(
                 self.server,
                 "_token_request",
                 return_value={"access_token": "a2", "expires_in": 3600},
             ):
            await self.server._ensure_fresh_token(self.SID, entry)

        self.assertEqual(entry["refresh_token"], "r1")

    async def test_parallel_requests_spend_the_refresh_token_once(self):
        # Why the per-session lock exists. Refresh tokens are single use: a
        # second spend fails, and the member is logged out for no reason they
        # could describe.
        entry = self.entry(expires_in=10)
        calls = []
        state = {"row": dict(entry)}

        async def exchange(payload):
            calls.append(payload)
            await asyncio.sleep(0)
            return {"access_token": "a2", "refresh_token": "r2", "expires_in": 3600}

        with mock.patch.object(web, "db_load_session", side_effect=lambda sid: dict(state["row"])), \
             mock.patch.object(
                 web, "db_touch_session", side_effect=lambda sid, e: state.update(row=dict(e))
             ), \
             mock.patch.object(self.server, "_token_request", side_effect=exchange):
            await asyncio.gather(
                self.server._ensure_fresh_token(self.SID, entry),
                self.server._ensure_fresh_token(self.SID, dict(entry)),
            )

        self.assertEqual(len(calls), 1)

    async def test_a_session_deleted_while_waiting_is_reported_as_expired(self):
        entry = self.entry(expires_in=10)

        with mock.patch.object(web, "db_load_session", return_value=None):
            with self.assertRaises(web.ApiError) as caught:
                await self.server._ensure_fresh_token(self.SID, entry)

        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(caught.exception.code, "session_expired")

    async def test_a_session_with_no_refresh_token_is_deleted_not_left_half_alive(self):
        # Leaving it in the database would mean every later request repeats
        # this failure, instead of the member simply logging in again.
        entry = self.entry(expires_in=10, refresh_token=None)
        deleted = []

        with mock.patch.object(web, "db_load_session", return_value=dict(entry)), \
             mock.patch.object(web, "db_delete_session", side_effect=deleted.append), \
             mock.patch.object(self.server, "_token_request") as exchange:
            with self.assertRaises(web.ApiError) as caught:
                await self.server._ensure_fresh_token(self.SID, entry)

        exchange.assert_not_called()
        self.assertEqual(deleted, [self.SID])
        self.assertEqual(caught.exception.status, 401)

    async def test_a_rejected_refresh_deletes_the_session(self):
        entry = self.entry(expires_in=10)
        deleted = []

        with mock.patch.object(web, "db_load_session", return_value=dict(entry)), \
             mock.patch.object(web, "db_delete_session", side_effect=deleted.append), \
             mock.patch.object(
                 self.server, "_token_request", return_value={"error": "invalid_grant"}
             ):
            with self.assertRaises(web.ApiError) as caught:
                await self.server._ensure_fresh_token(self.SID, entry)

        self.assertEqual(deleted, [self.SID])
        self.assertEqual(caught.exception.code, "session_expired")

    async def test_a_refresh_by_another_request_is_picked_up_without_spending_again(self):
        # The re-check after taking the lock: whoever waited reloads and finds
        # the work already done.
        entry = self.entry(expires_in=10)
        already_fresh = self.entry(expires_in=3600)
        already_fresh["access_token"] = "a2"

        with mock.patch.object(web, "db_load_session", return_value=already_fresh), \
             mock.patch.object(self.server, "_token_request") as exchange:
            await self.server._ensure_fresh_token(self.SID, entry)

        exchange.assert_not_called()
        self.assertEqual(entry["access_token"], "a2")


if __name__ == "__main__":
    unittest.main()
