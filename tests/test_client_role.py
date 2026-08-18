"""Deciding whether someone runs NovaGuard somewhere else.

The role means "this person administers a server NovaGuard is on", so the
reading is Manage Server — the same permission /setup, /automod and /welcome
require. Being a member somewhere is not enough.

The whole reason this is a three-state answer rather than a boolean is the
member cache. discord.py returns None from get_member both when someone is
not in a guild and when that guild's members have not been received yet, and
those two are indistinguishable. Treating the second as "not an admin" would
strip the role off a genuine customer after a reconnect. So a negative is
only trusted from a guild whose members are actually loaded; anything else is
UNKNOWN, and UNKNOWN never takes a role away.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.client_role import ADMIN, NOT_ADMIN, UNKNOWN, client_status  # noqa: E402

HOME = 1
OTHER = 2
THIRD = 3
USER = 100


class FakePermissions:
    def __init__(self, manage_guild):
        self.manage_guild = manage_guild


class FakeMember:
    def __init__(self, manage_guild):
        self.guild_permissions = FakePermissions(manage_guild)


class FakeGuild:
    def __init__(self, guild_id, *, members=None, chunked=True):
        self.id = guild_id
        self.chunked = chunked
        self._members = members or {}

    def get_member(self, user_id):
        return self._members.get(user_id)


def home():
    return FakeGuild(HOME, members={USER: FakeMember(False)})


class ClientStatusTests(unittest.TestCase):
    def test_an_admin_on_another_server_qualifies(self):
        guilds = [home(), FakeGuild(OTHER, members={USER: FakeMember(True)})]

        self.assertEqual(client_status(guilds, USER, home_guild_id=HOME), ADMIN)

    def test_a_plain_member_elsewhere_does_not_qualify(self):
        # The role says they run NovaGuard, not that they are on a server.
        guilds = [home(), FakeGuild(OTHER, members={USER: FakeMember(False)})]

        self.assertEqual(client_status(guilds, USER, home_guild_id=HOME), NOT_ADMIN)

    def test_being_an_admin_at_home_does_not_count(self):
        # Otherwise every admin of this server would award themselves the role.
        guilds = [FakeGuild(HOME, members={USER: FakeMember(True)})]

        self.assertEqual(client_status(guilds, USER, home_guild_id=HOME), UNKNOWN)

    def test_one_qualifying_server_is_enough(self):
        guilds = [
            home(),
            FakeGuild(OTHER, members={USER: FakeMember(False)}),
            FakeGuild(THIRD, members={USER: FakeMember(True)}),
        ]

        self.assertEqual(client_status(guilds, USER, home_guild_id=HOME), ADMIN)

    def test_absent_everywhere_else_is_a_clear_no(self):
        guilds = [home(), FakeGuild(OTHER, members={})]

        self.assertEqual(client_status(guilds, USER, home_guild_id=HOME), NOT_ADMIN)

    # --- the cache, and why a negative is not always a negative -------

    def test_an_unloaded_guild_cannot_produce_a_negative(self):
        # get_member would answer None here whether or not they are an admin,
        # so answering NOT_ADMIN would be inventing a fact.
        guilds = [home(), FakeGuild(OTHER, members={}, chunked=False)]

        self.assertEqual(client_status(guilds, USER, home_guild_id=HOME), UNKNOWN)

    def test_a_loaded_guild_still_settles_it_when_another_is_unloaded(self):
        guilds = [
            home(),
            FakeGuild(OTHER, members={}, chunked=False),
            FakeGuild(THIRD, members={USER: FakeMember(True)}),
        ]

        self.assertEqual(client_status(guilds, USER, home_guild_id=HOME), ADMIN)

    def test_an_unloaded_guild_does_not_spoil_a_confirmed_negative(self):
        # One trustworthy guild says no; the unloaded one says nothing. The
        # answer is still no, because no reachable guild made them an admin.
        guilds = [
            home(),
            FakeGuild(OTHER, members={USER: FakeMember(False)}),
            FakeGuild(THIRD, members={}, chunked=False),
        ]

        self.assertEqual(client_status(guilds, USER, home_guild_id=HOME), NOT_ADMIN)

    def test_nowhere_to_look_is_unknown_not_a_refusal(self):
        # The bot on one server alone knows nothing about anyone. Answering
        # NOT_ADMIN would revoke every client role the moment it was removed
        # from the last other server.
        self.assertEqual(client_status([home()], USER, home_guild_id=HOME), UNKNOWN)

    def test_no_guilds_at_all_is_unknown(self):
        # A failed gateway connect leaves this list empty; it is not evidence.
        self.assertEqual(client_status([], USER, home_guild_id=HOME), UNKNOWN)


if __name__ == "__main__":
    unittest.main()
