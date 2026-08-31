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


# ── the gate every other grant path already went through ──────────────


class PermissionBits:
    """Just enough of discord.Permissions for role_safety to read."""

    def __init__(self, **granted):
        self._granted = granted

    def __getattr__(self, name):
        return self._granted.get(name, False)


class SafetyRole(FakeRole):
    """A role role_safety can actually interrogate, unlike FakeRole."""

    def __init__(self, role_id=7, position=1, *, managed=False, **permissions):
        super().__init__(role_id=role_id, position=position)
        self.managed = managed
        self.permissions = PermissionBits(**permissions)
        self.mention = f"@{self.name}"

    def is_default(self):
        return False


class SafetyGuild(ReactingGuild):
    def __init__(self, guild_id=HOME, *, bot_top_position=90, members=None):
        super().__init__(guild_id, members=members)
        self.me = ReactingMember(True, guild=self)
        self.me.top_role = SafetyRole(role_id=999, position=bot_top_position)
        self.owner_id = 999
        self.channels = []
        self.name = "Home"


class GrantSafetyTests(unittest.IsolatedAsyncioTestCase):
    """The client role is granted with no click from the member at all.

    Hold Manage Server on any guild NovaGuard is on - a free server of your own
    qualifies - and joining is enough. That made this the one grant path where
    a privileged role becomes a complete takeover with no interaction, and it
    was the only one of six that never consulted role_safety.
    """

    def setUp(self):
        import cogs.clientrole as clientrole

        self.clientrole = clientrole
        self.guild = SafetyGuild()
        self.cog = clientrole.ClientRole(FakeBot([self.guild]))
        self.member = ReactingMember(False, guild=self.guild, roles=[])
        self.added = []

        async def add_roles(role, reason=None):
            self.added.append(role)

        self.member.add_roles = add_roles

    async def test_an_administrator_role_is_never_granted(self):
        role = SafetyRole(administrator=True)

        self.assertFalse(await self.cog.grant(self.member, role))
        self.assertEqual(self.added, [])

    async def test_a_staff_role_is_never_granted(self):
        # The same list every other path refuses, checked here too.
        for permission in ("manage_roles", "ban_members", "manage_guild", "mention_everyone"):
            with self.subTest(permission=permission):
                self.added.clear()
                role = SafetyRole(**{permission: True})

                self.assertFalse(await self.cog.grant(self.member, role))
                self.assertEqual(self.added, [])

    async def test_a_role_above_the_bot_is_never_granted(self):
        self.assertFalse(await self.cog.grant(self.member, SafetyRole(position=95)))
        self.assertEqual(self.added, [])

    async def test_an_ordinary_role_still_goes_through(self):
        role = SafetyRole()
        self.cog._notify = self._silent_notify

        self.assertTrue(await self.cog.grant(self.member, role))
        self.assertEqual(self.added, [role])

    async def test_the_check_is_re_asked_at_grant_time(self):
        # A role harmless when it was named can be granted Manage Roles a year
        # later; this loop runs unattended the whole time.
        role = SafetyRole()
        self.cog._notify = self._silent_notify
        self.assertTrue(await self.cog.grant(self.member, role))

        self.member.roles = []
        self.added.clear()
        role.permissions = PermissionBits(manage_roles=True)

        self.assertFalse(await self.cog.grant(self.member, role))
        self.assertEqual(self.added, [])

    async def _silent_notify(self, member, embed):
        return None


class ConfigurationSafetyTests(unittest.IsolatedAsyncioTestCase):
    """/clientrole set refuses what /welcome set autorole already refused."""

    def setUp(self):
        import cogs.clientrole as clientrole

        self.clientrole = clientrole
        self.guild = SafetyGuild()
        self.cog = clientrole.ClientRole(FakeBot([self.guild]))
        self.saved = []
        self.responses = []

        async def respond(interaction, embed, **kwargs):
            self.responses.append(embed)

        patcher = mock.patch.object(clientrole, "respond", respond)
        patcher.start()
        self.addCleanup(patcher.stop)

        saver = mock.patch.object(
            clientrole, "update_guild_settings",
            lambda guild_id, **kwargs: self.saved.append(kwargs),
        )
        saver.start()
        self.addCleanup(saver.stop)

    def interaction(self):
        actor = ReactingMember(True, guild=self.guild)
        actor.top_role = SafetyRole(role_id=500, position=80)
        return mock.Mock(guild=self.guild, guild_id=self.guild.id, user=actor)

    async def _set(self, role):
        await self.clientrole.ClientRole.clientrole_set.callback(
            self.cog, self.interaction(), role
        )

    async def test_a_privileged_role_is_refused(self):
        await self._set(SafetyRole(administrator=True))

        self.assertEqual(self.saved, [])
        self.assertEqual(len(self.responses), 1)

    async def test_a_role_above_the_configurer_is_refused(self):
        # The hierarchy Discord would have enforced on them directly.
        await self._set(SafetyRole(position=85))

        self.assertEqual(self.saved, [])

    async def test_an_ordinary_role_is_saved(self):
        role = SafetyRole()

        await self._set(role)

        self.assertEqual(self.saved, [{"client_role": str(role.id)}])


if __name__ == "__main__":
    unittest.main()
