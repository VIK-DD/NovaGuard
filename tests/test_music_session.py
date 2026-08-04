"""Tests for the session registry that enforces the concurrency cap."""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_session import MusicSession, SessionRegistry  # noqa: E402


class SessionRegistryTests(unittest.TestCase):
    def test_a_new_registry_has_capacity_and_no_sessions(self):
        registry = SessionRegistry(max_sessions=3)
        self.assertEqual(registry.active_count(), 0)
        self.assertTrue(registry.has_capacity())

    def test_create_returns_a_session_bound_to_its_guild(self):
        registry = SessionRegistry(max_sessions=3)
        session = registry.create("123")
        self.assertIsInstance(session, MusicSession)
        self.assertEqual(session.guild_id, "123")
        self.assertIs(registry.get("123"), session)

    def test_a_guild_id_given_as_an_int_finds_the_same_session(self):
        registry = SessionRegistry(max_sessions=3)
        session = registry.create(123)
        self.assertIs(registry.get("123"), session)

    def test_creating_twice_for_one_guild_reuses_the_session(self):
        registry = SessionRegistry(max_sessions=3)
        first = registry.create("123")
        self.assertIs(registry.create("123"), first)
        self.assertEqual(registry.active_count(), 1)

    def test_capacity_runs_out_at_the_limit(self):
        registry = SessionRegistry(max_sessions=2)
        registry.create("1")
        registry.create("2")
        self.assertFalse(registry.has_capacity())
        self.assertEqual(registry.active_count(), 2)

    def test_an_existing_guild_is_served_even_at_the_cap(self):
        registry = SessionRegistry(max_sessions=1)
        registry.create("1")
        self.assertFalse(registry.has_capacity())
        self.assertIsNotNone(registry.create("1"))

    def test_drop_frees_capacity(self):
        registry = SessionRegistry(max_sessions=1)
        registry.create("1")
        registry.drop("1")
        self.assertTrue(registry.has_capacity())
        self.assertIsNone(registry.get("1"))

    def test_dropping_an_unknown_guild_is_harmless(self):
        registry = SessionRegistry(max_sessions=1)
        registry.drop("nope")
        self.assertEqual(registry.active_count(), 0)


class MusicSessionTests(unittest.TestCase):
    def test_a_fresh_session_starts_at_full_volume_with_an_empty_queue(self):
        session = MusicSession("1")
        self.assertEqual(session.volume, 100)
        self.assertTrue(session.queue.is_empty)
        self.assertIsNone(session.voice_client)

    def test_touch_resets_the_idle_clock(self):
        session = MusicSession("1")
        session._idle_since = time.monotonic() - 1200
        self.assertGreater(session.idle_seconds(), 1000)
        session.touch()
        self.assertLess(session.idle_seconds(), 1)


if __name__ == "__main__":
    unittest.main()
