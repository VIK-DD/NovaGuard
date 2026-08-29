"""Tests for the admin key, unlock sessions, guess throttling and owner ids."""

import asyncio
import os
import sys
import unittest
from unittest import mock

import discord

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.admin_auth import (  # noqa: E402
    KEY_PREFIX,
    LOCKOUT_SECONDS,
    MAX_FAILED_ATTEMPTS,
    AdminSessions,
    env_owner_ids,
    generate_key,
    hash_key,
    looks_like_key,
    verify_key,
)
from core.maintenance import user_can_bypass_maintenance  # noqa: E402


class FakeClock:
    """Hand-cranked clock so expiry is tested without waiting."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class KeyGenerationTests(unittest.TestCase):
    def test_keys_carry_the_prefix(self):
        self.assertTrue(generate_key().startswith(KEY_PREFIX))

    def test_keys_are_unique(self):
        self.assertEqual(len({generate_key() for _ in range(50)}), 50)

    def test_keys_are_long_enough_to_resist_guessing(self):
        # 24 random bytes, url-safe encoded: at least 32 characters of
        # entropy after the prefix.
        self.assertGreaterEqual(len(generate_key()) - len(KEY_PREFIX), 32)

    def test_shape_check_rejects_obvious_junk(self):
        self.assertTrue(looks_like_key(generate_key()))
        for junk in ("", None, "hunter2", "ng_admin", "  "):
            with self.subTest(value=junk):
                self.assertFalse(looks_like_key(junk))


class HashingTests(unittest.TestCase):
    def test_the_same_key_and_salt_always_hash_alike(self):
        digest, salt = hash_key("ng_admin_example")

        self.assertEqual(hash_key("ng_admin_example", salt=salt)[0], digest)

    def test_the_same_key_hashes_differently_under_different_salts(self):
        # Without per-key salts, two operators sharing a key would share a
        # hash, and one leak would expose both.
        first, first_salt = hash_key("ng_admin_example")
        second, second_salt = hash_key("ng_admin_example")

        self.assertNotEqual(first_salt, second_salt)
        self.assertNotEqual(first, second)

    def test_the_plaintext_never_appears_in_the_hash(self):
        secret = "ng_admin_verysecretvalue"
        digest, salt = hash_key(secret)

        self.assertNotIn("verysecretvalue", digest)
        self.assertNotIn("verysecretvalue", salt)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.secret = "ng_admin_correct-key"
        self.digest, self.salt = hash_key(self.secret)

    def test_the_right_key_verifies(self):
        self.assertTrue(verify_key(self.secret, self.digest, self.salt))

    def test_a_wrong_key_is_refused(self):
        self.assertFalse(verify_key("ng_admin_wrong-key", self.digest, self.salt))

    def test_a_near_miss_is_refused(self):
        self.assertFalse(verify_key(self.secret + "x", self.digest, self.salt))

    def test_the_wrong_salt_is_refused(self):
        other_salt = hash_key(self.secret)[1]

        self.assertFalse(verify_key(self.secret, self.digest, other_salt))

    def test_missing_or_malformed_inputs_never_pass(self):
        for plaintext, digest, salt in (
            ("", self.digest, self.salt),
            (None, self.digest, self.salt),
            (self.secret, "", self.salt),
            (self.secret, self.digest, ""),
            (self.secret, self.digest, "not-hex"),
        ):
            with self.subTest(plaintext=plaintext, salt=salt):
                self.assertFalse(verify_key(plaintext, digest, salt))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.sessions = AdminSessions(ttl_seconds=900, clock=self.clock)

    def test_a_user_starts_locked(self):
        self.assertFalse(self.sessions.is_unlocked("42"))
        self.assertEqual(self.sessions.seconds_left("42"), 0)

    def test_unlocking_opens_a_session(self):
        self.sessions.unlock("42")

        self.assertTrue(self.sessions.is_unlocked("42"))
        self.assertEqual(self.sessions.seconds_left("42"), 900)

    def test_ids_are_compared_as_strings(self):
        self.sessions.unlock(42)

        self.assertTrue(self.sessions.is_unlocked("42"))

    def test_a_session_expires_on_its_own(self):
        self.sessions.unlock("42")
        self.clock.advance(899)
        self.assertTrue(self.sessions.is_unlocked("42"))

        self.clock.advance(2)

        self.assertFalse(self.sessions.is_unlocked("42"))

    def test_unlocking_one_user_does_not_unlock_another(self):
        self.sessions.unlock("42")

        self.assertFalse(self.sessions.is_unlocked("99"))

    def test_locking_ends_the_session_immediately(self):
        self.sessions.unlock("42")

        self.assertTrue(self.sessions.lock("42"))
        self.assertFalse(self.sessions.is_unlocked("42"))
        self.assertFalse(self.sessions.lock("42"))

    def test_lock_all_clears_everyone(self):
        self.sessions.unlock("1")
        self.sessions.unlock("2")

        self.assertEqual(self.sessions.lock_all(), 2)
        self.assertFalse(self.sessions.is_unlocked("1"))
        self.assertFalse(self.sessions.is_unlocked("2"))


class ThrottlingTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.sessions = AdminSessions(clock=self.clock)

    def test_failures_count_down_the_remaining_attempts(self):
        remaining = [self.sessions.record_failure("42") for _ in range(3)]

        self.assertEqual(
            remaining,
            [MAX_FAILED_ATTEMPTS - 1, MAX_FAILED_ATTEMPTS - 2, MAX_FAILED_ATTEMPTS - 3],
        )

    def test_too_many_failures_lock_the_user_out(self):
        for _ in range(MAX_FAILED_ATTEMPTS):
            self.sessions.record_failure("42")

        self.assertTrue(self.sessions.is_locked_out("42"))
        self.assertGreater(self.sessions.lockout_seconds_left("42"), 0)

    def test_a_lockout_lifts_once_it_expires(self):
        for _ in range(MAX_FAILED_ATTEMPTS):
            self.sessions.record_failure("42")

        self.clock.advance(LOCKOUT_SECONDS + 1)

        self.assertFalse(self.sessions.is_locked_out("42"))

    def test_one_user_being_locked_out_does_not_affect_another(self):
        for _ in range(MAX_FAILED_ATTEMPTS):
            self.sessions.record_failure("42")

        self.assertFalse(self.sessions.is_locked_out("99"))

    def test_a_successful_unlock_clears_earlier_failures(self):
        for _ in range(MAX_FAILED_ATTEMPTS - 1):
            self.sessions.record_failure("42")

        self.sessions.unlock("42")

        self.assertEqual(self.sessions.record_failure("42"), MAX_FAILED_ATTEMPTS - 1)


class OwnerIdTests(unittest.TestCase):
    def test_no_extra_owners_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOT_OWNER_IDS", None)
            self.assertEqual(env_owner_ids(), set())

    def test_ids_are_parsed_from_a_list(self):
        with mock.patch.dict(os.environ, {"BOT_OWNER_IDS": "111, 222;333"}):
            self.assertEqual(env_owner_ids(), {"111", "222", "333"})

    def test_junk_entries_add_nobody(self):
        with mock.patch.dict(os.environ, {"BOT_OWNER_IDS": "abc, , 444, <@555>"}):
            self.assertEqual(env_owner_ids(), {"444"})


class OwnerIdsAreActuallyConsultedTests(unittest.TestCase):
    """BOT_OWNER_IDS was parsed, documented and tested - and never read.

    env_owner_ids() existed with these tests above it while no authorization
    decision anywhere called it, so an operator who set BOT_OWNER_IDS for a
    co-owner or a break-glass account got a control that silently did nothing.
    These tests are about the wiring, not the parsing.
    """

    class FakeUser:
        def __init__(self, ident):
            self.id = ident

    class UnreachableBot:
        """application_info() failing is exactly when break-glass matters."""

        async def application_info(self):
            raise discord.HTTPException(mock.Mock(status=503), "unavailable")

    def test_a_listed_id_is_an_owner_even_when_discord_is_unreachable(self):
        with mock.patch.dict(os.environ, {"BOT_OWNER_IDS": "777"}):
            allowed = asyncio.run(
                user_can_bypass_maintenance(self.UnreachableBot(), self.FakeUser(777))
            )
        self.assertTrue(allowed)

    def test_an_unlisted_id_is_still_refused(self):
        with mock.patch.dict(os.environ, {"BOT_OWNER_IDS": "777"}):
            allowed = asyncio.run(
                user_can_bypass_maintenance(self.UnreachableBot(), self.FakeUser(778))
            )
        self.assertFalse(allowed)

    def test_an_empty_list_grants_nobody(self):
        with mock.patch.dict(os.environ, {"BOT_OWNER_IDS": ""}):
            allowed = asyncio.run(
                user_can_bypass_maintenance(self.UnreachableBot(), self.FakeUser(777))
            )
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
