"""Tests for which commands the admin gate protects, and what it reveals."""

import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cogs.admin as admin_cog  # noqa: E402
import cogs.setup as setup_cog  # noqa: E402
import cogs.system as system_cog  # noqa: E402
from core.admin_auth import (  # noqa: E402
    GATE_LOCKED,
    GATE_LOCKED_OUT,
    GATE_NO_KEY,
    GATE_NOT_OWNER,
    GATE_OK,
    AdminSessions,
    gate_state,
)

# Every backup subcommand reaches the whole database, not one guild's slice.
GUARDED_BACKUP_COMMANDS = (
    "config_backup",
    "backup_create",
    "backup_status",
    "backup_remote",
    "backup_list",
    "backup_inspect",
    "backup_test",
    "backup_restore",
)


class GateDecisionTests(unittest.TestCase):
    def setUp(self):
        self.sessions = AdminSessions()

    def _state(self, is_owner, *, key=True, user="42"):
        return gate_state(is_owner, user, sessions=self.sessions, key_configured=key)

    def test_a_non_owner_is_refused_even_with_a_key_and_a_session(self):
        self.sessions.unlock("42")

        self.assertEqual(self._state(False), GATE_NOT_OWNER)

    def test_the_owner_still_needs_to_unlock(self):
        self.assertEqual(self._state(True), GATE_LOCKED)

    def test_the_owner_passes_once_unlocked(self):
        self.sessions.unlock("42")

        self.assertEqual(self._state(True), GATE_OK)

    def test_no_key_configured_blocks_even_the_owner(self):
        self.sessions.unlock("42")

        self.assertEqual(self._state(True, key=False), GATE_NO_KEY)

    def test_lockout_beats_an_open_session(self):
        # Someone guessing must not slip through on a session opened earlier.
        self.sessions.unlock("42")
        for _ in range(10):
            self.sessions.record_failure("42")

        self.assertEqual(self._state(True), GATE_LOCKED_OUT)

    def test_owner_is_checked_before_anything_else(self):
        # A stranger must not learn whether a key exists or whether they are
        # rate limited - either would confirm the second factor exists.
        for key_configured in (True, False):
            with self.subTest(key=key_configured):
                self.assertEqual(self._state(False, key=key_configured), GATE_NOT_OWNER)


class RefusalMessageTests(unittest.TestCase):
    def test_a_stranger_is_not_told_a_key_exists(self):
        embed = admin_cog.refusal_embed(GATE_NOT_OWNER)
        blob = f"{embed.title} {embed.description}".lower()

        self.assertNotIn("key", blob)
        self.assertNotIn("unlock", blob)

    def test_the_owner_is_told_exactly_what_to_do(self):
        locked = admin_cog.refusal_embed(GATE_LOCKED)
        self.assertIn("/admin unlock", locked.description)

        missing = admin_cog.refusal_embed(GATE_NO_KEY)
        self.assertIn("tools.admin_key", missing.description)


class GuardedCommandTests(unittest.TestCase):
    """The security fix these tests exist to keep: backup commands used to be
    open to anyone holding Manage Server in any guild the bot had joined,
    which exposed every other guild's data."""

    def _source(self, name):
        command = getattr(setup_cog.Setup, name)
        callback = getattr(command, "callback", command)
        return inspect.getsource(callback)

    def test_every_backup_command_calls_the_admin_gate(self):
        for name in GUARDED_BACKUP_COMMANDS:
            with self.subTest(command=name):
                self.assertIn("require_admin", self._source(name))

    def test_the_gate_runs_before_any_backup_work(self):
        # A gate placed after the work would leak the result it guards.
        for name in GUARDED_BACKUP_COMMANDS:
            with self.subTest(command=name):
                source = self._source(name)
                gate = source.index("require_admin")
                for call in ("create_backup", "inspect_backup", "list_backups", "latest_backup"):
                    position = source.find(call)
                    if position != -1:
                        self.assertLess(gate, position)

    def test_guild_scoped_export_stays_available_to_server_admins(self):
        # Server admins keep a way to get their own guild's data out.
        source = self._source("config_export")

        self.assertNotIn("require_admin", source)


class BootstrapTests(unittest.TestCase):
    """The key must never guard the path that publishes the key's own command."""

    def test_publishing_commands_is_owner_only_and_never_needs_an_unlock(self):
        # /resync publishes the command list, /admin unlock included. Gating
        # the whole command behind an unlock deadlocks first-time setup: the
        # key cannot be used until the command that accepts it exists.
        source = inspect.getsource(system_cog.System.resync.callback)
        owner_check = source.index("user_can_bypass_maintenance")
        gate = source.index("require_admin")

        self.assertLess(owner_check, gate)
        # The unlock only guards the clearing branch, never the plain sync.
        self.assertIn('scope == "clear-server" and not await require_admin', source)

    def test_resync_still_records_who_ran_it(self):
        source = inspect.getsource(system_cog.System.resync.callback)

        self.assertIn("record_audit", source)

    def test_maintenance_stays_behind_the_key(self):
        # Unlike resync, maintenance changes global state and is reachable
        # once the commands exist, so it keeps the second factor.
        source = inspect.getsource(system_cog.System.maintenance.callback)

        self.assertIn("require_admin", source)


class AuditTrailTests(unittest.TestCase):
    def test_refusals_are_recorded(self):
        source = inspect.getsource(admin_cog.require_admin)

        self.assertIn("record_audit", source)
        self.assertIn("denied", source)

    def test_the_key_is_never_written_to_the_audit_trail(self):
        # The unlock handler sees the plaintext key; nothing it records may
        # contain it.
        source = inspect.getsource(admin_cog.Admin.unlock.callback)
        audited = re.findall(r"record_audit\((.*?)\)", source, re.DOTALL)

        self.assertTrue(audited)
        for call in audited:
            self.assertNotIn("key", call.replace("admin.unlock", ""))


if __name__ == "__main__":
    unittest.main()
