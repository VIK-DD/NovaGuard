"""The rule that decides which roles NovaGuard will hand out.

Two escalation paths existed before core/role_safety.py, and both are
reproduced below against the guard so they stay closed:

1. autorole - someone holding only Manage Server points it at a role carrying
   Administrator, and every member who joins afterwards becomes one.
2. role panel - the same person publishes a panel for that role instead, and
   any member who presses the button becomes an administrator immediately.

Both worked because every guard in the project asked only whether the role sat
below the *bot's* top role. The bot's role is above, so Discord permitted the
assignment; the guild's own hierarchy never entered into it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.role_safety import (  # noqa: E402
    DANGEROUS_PERMISSION_NAMES,
    UNKNOWN_ACTOR,
    bot_cannot_manage_reason,
    channel_overwrite_risk,
    channel_visibility_grants,
    guild_overwrite_index,
    role_assignment_error,
    role_is_self_assignable,
    role_permission_risk,
)


class Permissions:
    """Just enough of discord.Permissions to answer getattr(name, False)."""

    def __init__(self, **granted):
        self._granted = granted

    def __getattr__(self, name):
        return self._granted.get(name, False)


class Role:
    _next_id = 1000

    def __init__(self, name, position, *, managed=False, default=False, **permissions):
        Role._next_id += 1
        self.id = Role._next_id
        self.name = name
        self.position = position
        self.managed = managed
        self._default = default
        self.permissions = Permissions(**permissions)
        self.mention = f"@{name}"

    def is_default(self):
        return self._default

    def __lt__(self, other):
        return self.position < other.position

    def __ge__(self, other):
        return self.position >= other.position


class Member:
    def __init__(self, top_role, *, guild=None, ident=1, administrator=False):
        self.top_role = top_role
        self.guild = guild
        self.id = ident
        self.guild_permissions = Permissions(administrator=administrator)


class Guild:
    def __init__(self, bot_top_role, owner_id=999):
        self.me = Member(bot_top_role)
        self.owner_id = owner_id


# A guild where NovaGuard sits high, as it must to manage anything.
BOT_TOP = Role("NovaGuard", 90)
GUILD = Guild(BOT_TOP)

ORDINARY = Role("Gamer", 10)
ALSO_ORDINARY = Role("Announcements", 12)
ADMIN_ROLE = Role("Admin", 50, administrator=True)
MOD_ROLE = Role("Moderator", 40, ban_members=True, manage_messages=True)
PINGER = Role("Pinger", 20, mention_everyone=True)
BOOSTER = Role("Server Booster", 30, managed=True)
EVERYONE = Role("@everyone", 0, default=True)
ABOVE_BOT = Role("Owner", 95)


class OrdinaryRolesTests(unittest.TestCase):
    def test_a_plain_cosmetic_role_is_assignable(self):
        self.assertIsNone(role_assignment_error(ORDINARY, GUILD))
        self.assertTrue(role_is_self_assignable(ORDINARY, GUILD))

    def test_the_original_checks_are_still_enforced(self):
        self.assertIn("@everyone", role_assignment_error(EVERYONE, GUILD))
        self.assertIn("managed", role_assignment_error(BOOSTER, GUILD))
        self.assertIn("top role", role_assignment_error(ABOVE_BOT, GUILD))

    def test_a_missing_role_is_refused_rather_than_crashing(self):
        self.assertIsNotNone(role_assignment_error(None, GUILD))


class PrivilegedRolesTests(unittest.TestCase):
    """The check the project did not have."""

    def test_an_administrator_role_is_never_self_assignable(self):
        refusal = role_assignment_error(ADMIN_ROLE, GUILD)
        self.assertIsNotNone(refusal)
        self.assertIn("administrator", refusal)

    def test_a_moderation_role_is_never_self_assignable(self):
        refusal = role_assignment_error(MOD_ROLE, GUILD)
        self.assertIsNotNone(refusal)
        self.assertIn("privileged permissions", refusal)

    def test_a_role_that_can_ping_everyone_is_not_self_assignable(self):
        self.assertIsNotNone(role_assignment_error(PINGER, GUILD))

    def test_administrator_is_reported_alone_rather_than_with_every_implied_bit(self):
        self.assertEqual(role_permission_risk(ADMIN_ROLE), ["administrator"])

    def test_every_listed_permission_is_actually_caught(self):
        # Guards the getattr-based probing: a rename in discord.py would show
        # up here as a permission that silently stops being checked.
        for name in DANGEROUS_PERMISSION_NAMES:
            role = Role(f"holder-of-{name}", 10, **{name: True})
            self.assertFalse(
                role_is_self_assignable(role, GUILD),
                f"a role holding {name} was treated as self-assignable",
            )


class ActorHierarchyTests(unittest.TestCase):
    """A configurer cannot expose a role above their own position."""

    def test_a_role_above_the_configurer_is_refused(self):
        actor = Member(Role("Helper", 15), guild=GUILD, ident=1)
        higher = Role("Veteran", 60)
        refusal = role_assignment_error(higher, GUILD, actor)
        self.assertIsNotNone(refusal)
        self.assertIn("your own top role", refusal)

    def test_a_role_below_the_configurer_is_allowed(self):
        actor = Member(Role("Helper", 15), guild=GUILD, ident=1)
        self.assertIsNone(role_assignment_error(ORDINARY, GUILD, actor))

    def test_the_guild_owner_is_bound_only_by_the_permission_rule(self):
        owner = Member(Role("Owner role", 1), guild=GUILD, ident=GUILD.owner_id)
        self.assertIsNone(role_assignment_error(ALSO_ORDINARY, GUILD, owner))
        # Still not allowed to make an Administrator role self-assignable.
        self.assertIsNotNone(role_assignment_error(ADMIN_ROLE, GUILD, owner))

    def test_an_administrator_is_bound_only_by_the_permission_rule(self):
        admin = Member(Role("Staff", 5), guild=GUILD, ident=2, administrator=True)
        self.assertIsNone(role_assignment_error(ALSO_ORDINARY, GUILD, admin))
        self.assertIsNotNone(role_assignment_error(ADMIN_ROLE, GUILD, admin))

    def test_an_unresolvable_actor_falls_back_to_the_permission_checks(self):
        # The dashboard cannot always resolve the member. That must weaken the
        # hierarchy check only - never the permission check.
        self.assertIsNone(role_assignment_error(ORDINARY, GUILD, None))
        self.assertIsNotNone(role_assignment_error(ADMIN_ROLE, GUILD, None))


class EscalationRegressionTests(unittest.TestCase):
    """The two paths that were exploitable, stated as scenarios."""

    def test_manage_server_cannot_route_autorole_at_an_administrator_role(self):
        # The dashboard resolves the configurer to a member with a low role.
        configurer = Member(Role("Manage-Server-only", 5), guild=GUILD, ident=7)
        self.assertIsNotNone(role_assignment_error(ADMIN_ROLE, GUILD, configurer))

    def test_a_panel_cannot_expose_an_administrator_role(self):
        configurer = Member(Role("Manage-Server-only", 5), guild=GUILD, ident=7)
        self.assertIsNotNone(role_assignment_error(ADMIN_ROLE, GUILD, configurer))

    def test_a_role_that_gains_permissions_later_stops_being_handed_out(self):
        # Published while harmless, granted Manage Roles a month later. The
        # click-time check is what catches this; the panel is unchanged.
        promoted = Role("Gamer", 10, manage_roles=True)
        self.assertIsNotNone(role_assignment_error(promoted, GUILD))


class MechanicalVersusPolicyTests(unittest.TestCase):
    """Two kinds of refusal, because a role panel must treat them differently.

    A policy refusal - the role grew privileged permissions after the panel was
    published - has to keep allowing *removal*, or whoever already holds it is
    stranded with exactly the thing the check exists to prevent. A mechanical
    one cannot: Discord refuses the removal as readily as the grant.
    """

    def test_a_now_privileged_role_is_still_mechanically_manageable(self):
        promoted = Role("Gamer", 10, manage_roles=True)
        self.assertIsNone(bot_cannot_manage_reason(promoted, GUILD))
        self.assertIsNotNone(role_assignment_error(promoted, GUILD))

    def test_a_role_above_the_bot_is_mechanically_blocked(self):
        self.assertIsNotNone(bot_cannot_manage_reason(ABOVE_BOT, GUILD))

    def test_managed_and_default_roles_are_mechanically_blocked(self):
        self.assertIsNotNone(bot_cannot_manage_reason(BOOSTER, GUILD))
        self.assertIsNotNone(bot_cannot_manage_reason(EVERYONE, GUILD))
        self.assertIsNotNone(bot_cannot_manage_reason(None, GUILD))

    def test_an_ordinary_role_is_blocked_by_neither(self):
        self.assertIsNone(bot_cannot_manage_reason(ORDINARY, GUILD))
        self.assertIsNone(role_assignment_error(ORDINARY, GUILD))

    def test_every_mechanical_reason_is_also_an_assignment_refusal(self):
        # role_assignment_error must remain the strictly wider check, or a
        # caller that only asks it would let a mechanically impossible role
        # through.
        for role in (ABOVE_BOT, BOOSTER, EVERYONE, None):
            self.assertIsNotNone(role_assignment_error(role, GUILD))


# ── channel permission overwrites ────────────────────────────────────
#
# `role.permissions` is the guild-wide bitfield. Discord also lets a *channel*
# grant a permission to a role that the role does not hold server-wide, and
# nothing in this project ever read one - so a role whose permissions integer
# is 0 could be Manage Messages in #general and still be handed out by a panel.


class Overwrite:
    """discord.PermissionOverwrite: True, False, or None for "not set"."""

    def __init__(self, **states):
        self._states = states

    def __getattr__(self, name):
        return self._states.get(name)


class Channel:
    def __init__(self, name, overwrites):
        self.name = name
        self.overwrites = overwrites


class GuildWithChannels(Guild):
    def __init__(self, bot_top_role, channels, everyone=None, owner_id=999):
        super().__init__(bot_top_role, owner_id=owner_id)
        self.channels = channels
        self.default_role = everyone if everyone is not None else Role("@everyone", 0, default=True)


class ChannelOverwriteTests(unittest.TestCase):
    """The escalation the guild-wide bitfield cannot see."""

    def test_a_role_with_no_guild_permissions_is_refused_for_an_elevated_overwrite(self):
        sneaky = Role("Helper", 15)  # permissions integer 0
        everyone = Role("@everyone", 0, default=True)
        guild = GuildWithChannels(
            BOT_TOP,
            [Channel("general", {sneaky: Overwrite(manage_messages=True)})],
            everyone=everyone,
        )
        self.assertEqual(role_permission_risk(sneaky), [])  # invisible guild-side
        refusal = role_assignment_error(sneaky, guild)
        self.assertIsNotNone(refusal)
        self.assertIn("channel overwrites", refusal)
        self.assertIn("#general:manage_messages", refusal)
        self.assertFalse(role_is_self_assignable(sneaky, guild))

    def test_visibility_alone_is_reported_but_never_refused(self):
        # "Press this button for #valorant" is the feature, not an escalation.
        hobby = Role("Valorant", 15)
        everyone = Role("@everyone", 0, default=True)
        guild = GuildWithChannels(
            BOT_TOP,
            [Channel("valorant", {hobby: Overwrite(view_channel=True),
                                  everyone: Overwrite(view_channel=False)})],
            everyone=everyone,
        )
        self.assertIsNone(role_assignment_error(hobby, guild))
        self.assertEqual(channel_visibility_grants(hobby, guild), ["#valorant"])

    def test_a_permission_everyone_already_has_is_not_a_privilege(self):
        role = Role("Chatty", 15)
        everyone = Role("@everyone", 0, default=True)
        guild = GuildWithChannels(
            BOT_TOP,
            [Channel("open", {role: Overwrite(view_channel=True),
                              everyone: Overwrite(view_channel=True)})],
            everyone=everyone,
        )
        self.assertEqual(channel_visibility_grants(role, guild), [])
        self.assertIsNone(role_assignment_error(role, guild))

    def test_a_permission_everyone_holds_guild_wide_is_not_a_privilege(self):
        role = Role("Chatty", 15)
        everyone = Role("@everyone", 0, default=True, view_channel=True)
        guild = GuildWithChannels(
            BOT_TOP,
            [Channel("open", {role: Overwrite(view_channel=True)})],
            everyone=everyone,
        )
        self.assertEqual(channel_visibility_grants(role, guild), [])

    def test_a_denied_overwrite_grants_nothing(self):
        role = Role("Muted", 15)
        everyone = Role("@everyone", 0, default=True)
        guild = GuildWithChannels(
            BOT_TOP,
            [Channel("general", {role: Overwrite(manage_messages=False, view_channel=False)})],
            everyone=everyone,
        )
        self.assertEqual(channel_overwrite_risk(role, guild), [])
        self.assertIsNone(role_assignment_error(role, guild))

    def test_member_overwrites_are_not_role_grants(self):
        # An overwrite naming one person is not something anyone can press a
        # button to obtain, so it is not this module's business.
        role = Role("Helper", 15)
        person = Member(role, ident=4242)
        everyone = Role("@everyone", 0, default=True)
        guild = GuildWithChannels(
            BOT_TOP,
            [Channel("general", {person: Overwrite(manage_messages=True)})],
            everyone=everyone,
        )
        self.assertEqual(guild_overwrite_index(guild), {})

    def test_a_category_overwrite_counts_like_any_other_channel(self):
        role = Role("Helper", 15)
        everyone = Role("@everyone", 0, default=True)
        guild = GuildWithChannels(
            BOT_TOP,
            [Channel("Staff Area", {role: Overwrite(manage_threads=True)})],
            everyone=everyone,
        )
        self.assertIn("#Staff Area:manage_threads", channel_overwrite_risk(role, guild))

    def test_a_guild_without_channels_still_answers(self):
        # Test doubles and uncached guilds both look like this; it must not raise.
        self.assertIsNone(role_assignment_error(ORDINARY, GUILD))
        self.assertEqual(guild_overwrite_index(GUILD), {})

    def test_the_index_is_reusable_across_roles(self):
        one = Role("One", 15)
        two = Role("Two", 16)
        everyone = Role("@everyone", 0, default=True)
        guild = GuildWithChannels(
            BOT_TOP,
            [Channel("general", {one: Overwrite(manage_webhooks=True),
                                 two: Overwrite(view_channel=True)})],
            everyone=everyone,
        )
        index = guild_overwrite_index(guild)
        self.assertIsNotNone(role_assignment_error(one, guild, overwrite_index=index))
        self.assertIsNone(role_assignment_error(two, guild, overwrite_index=index))


class UnknownActorTests(unittest.TestCase):
    """A configurer we could not resolve is not a configurer we may ignore."""

    def test_an_unresolved_actor_is_refused_rather_than_skipped(self):
        refusal = role_assignment_error(ORDINARY, GUILD, UNKNOWN_ACTOR)
        self.assertIsNotNone(refusal)
        self.assertIn("could not confirm", refusal)

    def test_no_actor_at_all_still_means_no_hierarchy_question(self):
        # The role-panel button: the presser is not the configurer, and asking
        # about their position would refuse ordinary members an ordinary role.
        self.assertIsNone(role_assignment_error(ORDINARY, GUILD, None))


if __name__ == "__main__":
    unittest.main()
