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
from unittest import mock

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


# ── reacting the moment something changes ─────────────────────────────


class FakeRole:
    def __init__(self, role_id=7, position=1):
        self.id = role_id
        self.name = "NovaGuard Client"
        self.position = position

    def __ge__(self, other):
        return self.position >= other.position

    def __lt__(self, other):
        return self.position < other.position

    def __eq__(self, other):
        return isinstance(other, FakeRole) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


class ReactingMember(FakeMember):
    """A member the cog can act on, not just classify."""

    def __init__(self, manage_guild, *, member_id=USER, guild=None, roles=()):
        super().__init__(manage_guild)
        self.id = member_id
        self.bot = False
        self.guild = guild
        self.roles = list(roles)


class ReactingGuild(FakeGuild):
    def __init__(self, guild_id, *, members=None, chunked=True):
        super().__init__(guild_id, members=members, chunked=chunked)
        for member in (members or {}).values():
            member.guild = self


class FakeBot:
    def __init__(self, guilds):
        self.guilds = guilds


class ReactionTests(unittest.IsolatedAsyncioTestCase):
    """Losing admin elsewhere is noticed at once, not a day later.

    The daily sweep alone left a revoked administrator wearing the role for up
    to 24 hours, which is exactly what Victor saw when he kicked a tester from
    the other server and nothing happened.
    """

    def setUp(self):
        import cogs.clientrole as clientrole

        self.clientrole = clientrole
        self.role = FakeRole()
        self.granted = []
        self.revoked = []

    def build(self, *, admin_elsewhere, present_elsewhere=True):
        """A home guild holding the member, plus another guild to be read."""
        member = ReactingMember(False, guild=None, roles=[self.role])
        home_guild = ReactingGuild(HOME, members={USER: member})
        others = {USER: ReactingMember(admin_elsewhere)} if present_elsewhere else {}
        other_guild = ReactingGuild(OTHER, members=others)

        cog = self.clientrole.ClientRole(FakeBot([home_guild, other_guild]))
        cog.grant = self._record(self.granted)
        cog.revoke = self._record(self.revoked)

        patcher = mock.patch.object(
            self.clientrole, "configured_role",
            lambda guild: self.role if guild.id == HOME else None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return cog, member

    def _record(self, sink):
        async def recorder(member, role):
            sink.append(member.id)
            return True
        return recorder

    async def test_leaving_the_other_server_revokes_here_immediately(self):
        cog, _member = self.build(admin_elsewhere=False, present_elsewhere=False)

        await cog.on_member_remove(ReactingMember(False, guild=ReactingGuild(OTHER)))

        self.assertEqual(self.revoked, [USER])

    async def test_losing_the_permission_without_leaving_also_revokes(self):
        cog, _member = self.build(admin_elsewhere=False)
        before = ReactingMember(True, guild=ReactingGuild(OTHER))
        after = ReactingMember(False, guild=ReactingGuild(OTHER))

        await cog.on_member_update(before, after)

        self.assertEqual(self.revoked, [USER])

    async def test_gaining_the_permission_grants_without_rejoining(self):
        cog, _member = self.build(admin_elsewhere=True)
        before = ReactingMember(False, guild=ReactingGuild(OTHER))
        after = ReactingMember(True, guild=ReactingGuild(OTHER))

        await cog.on_member_update(before, after)

        self.assertEqual(self.granted, [USER])

    async def test_an_unrelated_change_costs_nothing(self):
        # Nicknames and ordinary roles change constantly; only a change to the
        # permission this feature reads is worth acting on.
        cog, _member = self.build(admin_elsewhere=True)
        same = ReactingMember(True, guild=ReactingGuild(OTHER))

        await cog.on_member_update(same, ReactingMember(True, guild=ReactingGuild(OTHER)))

        self.assertEqual(self.granted, [])
        self.assertEqual(self.revoked, [])

    async def test_a_guild_without_the_role_configured_is_left_alone(self):
        cog, _member = self.build(admin_elsewhere=False, present_elsewhere=False)
        patcher = mock.patch.object(self.clientrole, "configured_role", lambda guild: None)
        patcher.start()
        self.addCleanup(patcher.stop)

        await cog.on_member_remove(ReactingMember(False, guild=ReactingGuild(OTHER)))

        self.assertEqual(self.revoked, [])


if __name__ == "__main__":
    unittest.main()
