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
        request.headers["X-Forwarded-For"] = "203.0.113.8, also-invalid"

        with mock.patch.object(web, "TRUST_PROXY", True):
            self.assertEqual(self.server._client_ip(request), "203.0.113.7")

    def test_a_forged_forwarded_prefix_cannot_choose_the_bucket(self):
        # nginx's standard proxy_add_x_forwarded_for *appends* the address it
        # saw, copying whatever the client sent through in front of it. Reading
        # the first hop let a client pick its own rate-limit bucket - a fresh
        # one per request - and write any address it liked into the audit log.
        # Only the last hop was put there by the proxy.
        request = FakeRequest()
        request.headers["X-Forwarded-For"] = "9.9.9.9, 198.51.100.23"

        with mock.patch.object(web, "TRUST_PROXY", True):
            self.assertEqual(self.server._client_ip(request), "198.51.100.23")

    def test_a_single_hop_proxy_is_still_read_correctly(self):
        # A proxy configured to replace rather than append leaves one entry,
        # and it is the client.
        request = FakeRequest()
        request.headers["X-Forwarded-For"] = "198.51.100.24"

        with mock.patch.object(web, "TRUST_PROXY", True):
            self.assertEqual(self.server._client_ip(request), "198.51.100.24")

    def test_cloudflare_still_wins_over_a_forwarded_chain(self):
        # With Cloudflare in front of another proxy the last XFF hop is
        # Cloudflare's own edge address, so the header it sets itself - which a
        # client cannot reach past the tunnel to forge - is both safer and more
        # accurate.
        request = FakeRequest()
        request.headers["CF-Connecting-IP"] = "198.51.100.25"
        request.headers["X-Forwarded-For"] = "9.9.9.9, 172.71.0.1"

        with mock.patch.object(web, "TRUST_PROXY", True):
            self.assertEqual(self.server._client_ip(request), "198.51.100.25")

    def test_forwarded_headers_are_ignored_entirely_on_a_direct_bind(self):
        request = FakeRequest()
        request.headers["X-Forwarded-For"] = "9.9.9.9, 198.51.100.26"

        with mock.patch.object(web, "TRUST_PROXY", False):
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


class StateKeySeparationTests(unittest.TestCase):
    """The state signer must not be the OAuth credential itself."""

    def test_the_state_key_is_derived_not_the_raw_client_secret(self):
        # It used to be `CLIENT_SECRET.encode()`, which made every state token
        # a (known message, MAC) pair under the credential that also talks to
        # Discord's token endpoint. One secret, two unrelated jobs.
        self.assertNotEqual(web._STATE_SECRET, web.CLIENT_SECRET.encode("utf-8"))
        self.assertEqual(len(web._STATE_SECRET), 32)

    def test_the_derivation_is_domain_separated(self):
        # Same input material as the token cipher, different label, so one
        # cannot be used to attack the other.
        plain = hashlib.sha256(web.CLIENT_SECRET.encode("utf-8")).digest()
        self.assertNotEqual(web._STATE_SECRET, plain)


class PermissionRevocationTests(AuthTestCase):
    """A revocation the bot watched happen beats the cache window.

    The TTL bounds the worst case; the gateway knows the actual case. Without
    this, someone whose Manage Server was taken away kept write access to the
    dashboard until their cached permission set aged out.
    """

    def entry(self, *, user_id="42", fetched_at=None):
        return {
            "user": {"id": user_id, "username": "someone"},
            "access_token": "a1",
            "token_expires_at": time.time() + 3600,
            "guilds": {},
            "guilds_fetched_at": time.time() if fetched_at is None else fetched_at,
        }

    async def test_a_fresh_cache_is_normally_left_alone(self):
        entry = self.entry()

        with mock.patch.object(self.server, "_discord_get") as fetch:
            await self.server._refresh_guilds("sid", entry)

        fetch.assert_not_called()

    async def test_a_witnessed_change_forces_a_refetch_inside_the_window(self):
        entry = self.entry()
        self.server.note_permission_change(42)

        with mock.patch.object(self.server, "_ensure_fresh_token"), \
             mock.patch.object(self.server, "_discord_get", return_value=[]) as fetch, \
             mock.patch.object(web, "db_touch_session"):
            await self.server._refresh_guilds("sid", entry)

        fetch.assert_awaited_once()

    async def test_a_change_older_than_the_cached_copy_changes_nothing(self):
        # The refetch already happened after the event; doing it again on
        # every request afterwards would put Discord in front of each one.
        self.server.note_permission_change(42)
        entry = self.entry(fetched_at=time.time() + 1)

        with mock.patch.object(self.server, "_discord_get") as fetch:
            await self.server._refresh_guilds("sid", entry)

        fetch.assert_not_called()

    async def test_someone_else_losing_a_permission_is_not_our_business(self):
        entry = self.entry(user_id="7")
        self.server.note_permission_change(42)

        with mock.patch.object(self.server, "_discord_get") as fetch:
            await self.server._refresh_guilds("sid", entry)

        fetch.assert_not_called()

    async def test_only_a_manage_guild_change_is_recorded(self):
        unchanged = mock.Mock(id=42, guild_permissions=mock.Mock(manage_guild=True))
        await self.server._on_member_update(unchanged, unchanged)
        self.assertEqual(self.server._permission_events, {})

        after = mock.Mock(id=42, guild_permissions=mock.Mock(manage_guild=False))
        await self.server._on_member_update(unchanged, after)
        self.assertIn("42", self.server._permission_events)

    def test_the_event_table_cannot_grow_without_bound(self):
        # Same reasoning as the rate-limit table: an unbounded dict fed by
        # gateway traffic is a slow memory leak on a small host.
        old = time.time() - web.GUILDS_CACHE_SECONDS - 60
        self.server._permission_events = {str(i): old for i in range(5000)}

        self.server.note_permission_change(99999)

        self.assertLess(len(self.server._permission_events), 5000)
        self.assertIn("99999", self.server._permission_events)


class RateLimitTests(AuthTestCase):
    """Bounded per address, bounded in memory, and not shared between doors."""

    def request_from(self, address):
        request = FakeRequest()
        request.remote = address
        return request

    async def test_logout_is_bounded_like_every_other_door(self):
        # It was the one handler that limited nothing while being reachable
        # unauthenticated, and each call takes the storage lock that every
        # authenticated request also needs.
        request = self.request_from("203.0.113.30")
        request.method = "POST"
        limit, _ = web.RATE_LIMITS["logout"]
        for _ in range(limit):
            self.server._rate_limit(request, "logout")

        with self.assertRaises(web.ApiError) as caught:
            await self.server.handle_logout(request)

        self.assertEqual(caught.exception.code, "rate_limited")

    def test_signing_out_cannot_close_the_login_door(self):
        # Two doors sharing a budget means traffic at one closes the other -
        # the bug already fixed for preview vs auth. Logging out is not
        # credential guessing and must not spend the guessing budget.
        request = self.request_from("203.0.113.31")
        limit, _ = web.RATE_LIMITS["logout"]
        for _ in range(limit):
            self.server._rate_limit(request, "logout")

        self.server._rate_limit(request, "auth")

    def test_the_preview_door_no_longer_spends_the_login_budget(self):
        # Both endpoints are public and unauthenticated. While they shared the
        # "auth" bucket, anonymous traffic on the maintenance preview form was
        # enough to close dashboard login for everyone on that address.
        self.assertIn("preview", web.RATE_LIMITS)

        request = self.request_from("203.0.113.10")
        limit, _ = web.RATE_LIMITS["preview"]
        for _ in range(limit):
            self.server._rate_limit(request, "preview")
        with self.assertRaises(web.ApiError):
            self.server._rate_limit(request, "preview")

        # The login door is untouched by that flood.
        self.server._rate_limit(request, "auth")

    def test_health_is_bounded_where_it_used_to_be_unlimited(self):
        request = self.request_from("203.0.113.11")
        limit, _ = web.RATE_LIMITS["health"]
        for _ in range(limit):
            self.server._rate_limit(request, "health")
        with self.assertRaises(web.ApiError) as caught:
            self.server._rate_limit(request, "health")
        self.assertEqual(caught.exception.code, "rate_limited")

    def test_a_flood_of_fresh_addresses_sheds_instead_of_growing_forever(self):
        # The old cleanup only removed already-stale keys, so a burst from one
        # IPv6 /64 could grow the table without bound inside a single window.
        with mock.patch.object(web, "MAX_RATE_BUCKETS", 50):
            for index in range(50):
                self.server._rate_limit(self.request_from(f"2001:db8::{index:x}"), "read")
            with self.assertRaises(web.ApiError) as caught:
                self.server._rate_limit(self.request_from("2001:db8::ffff"), "read")
        self.assertEqual(caught.exception.code, "rate_limited")
        self.assertLessEqual(len(self.server.rate_buckets), 50)

    def test_an_address_already_known_is_still_served_when_the_table_is_full(self):
        # Shedding must fall on new arrivals, not on whoever is mid-session.
        known = self.request_from("203.0.113.12")
        self.server._rate_limit(known, "read")
        with mock.patch.object(web, "MAX_RATE_BUCKETS", 1):
            self.server._rate_limit(known, "read")

    def test_stale_buckets_are_swept_rather_than_counted(self):
        self.server._rate_limit(self.request_from("203.0.113.13"), "read")
        self.assertEqual(len(self.server.rate_buckets), 1)
        self.server._evict_stale_buckets(time.monotonic() + 601)
        self.assertEqual(self.server.rate_buckets, {})


if __name__ == "__main__":
    unittest.main()
