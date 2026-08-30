"""Every configuration group refuses a member who lacks the permission.

`default_permissions` is a default, not a gate: a server administrator can
override it in Server Settings → Integrations and hand a command to any role,
@everyone included. Most of the project already pairs it with a run-time
`checks.has_permissions`, but /automod, /welcome, /clientrole, /logs, /voice,
/giveaway and /warn relied on the default alone - so one Integrations override
was the only thing between an ordinary member and turning off the invite
filter or clearing someone's warnings.

The nested cases are the ones worth having a test for. discord.py's
Command._check_can_run consults only the *immediate* parent's
interaction_check, so `/automod badword add` never reaches the `/automod`
group's guard: `badword` has to carry its own. This file walks the real cogs
rather than a fixture, so a group added later without a guard fails here.
"""

import asyncio
import os
import sys
import unittest

import discord
from discord import app_commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs import (  # noqa: E402
    automod as automod_cog,
    clientrole as clientrole_cog,
    giveaways as giveaways_cog,
    levels as levels_cog,
    logs as logs_cog,
    moderation as moderation_cog,
    setup as setup_cog,
    voice as voice_cog,
    welcome as welcome_cog,
)
from core.command_guards import ManagerGroup, ModeratorGroup, _GuardedGroup  # noqa: E402


class FakeUser:
    def __init__(self, **permissions):
        self.guild_permissions = discord.Permissions(**permissions)


class FakeInteraction:
    def __init__(self, user):
        self.user = user


class NonMemberInteraction:
    """A DM, where there is no guild_permissions to read."""

    user = object()


# (group object, the permission a member needs to use it)
GUARDED_GROUPS = [
    (automod_cog.AutoMod.automod, "manage_guild"),
    (automod_cog.AutoMod.badword, "manage_guild"),
    (clientrole_cog.ClientRole.clientrole, "manage_guild"),
    (giveaways_cog.Giveaways.giveaway, "manage_guild"),
    (levels_cog.Levels.levels, "manage_guild"),
    (levels_cog.Levels.backfill, "manage_guild"),
    (logs_cog.Logs.logs, "manage_guild"),
    (moderation_cog.Moderation.warn, "moderate_members"),
    (voice_cog.VoiceReports.voice, "manage_guild"),
    (voice_cog.VoiceReports.resend, "manage_guild"),
    (welcome_cog.Welcome.welcome, "manage_guild"),
    (setup_cog.Setup.config, "manage_guild"),
]


class GuardBehaviourTests(unittest.TestCase):
    def test_the_right_permission_is_accepted(self):
        group = ManagerGroup(name="demo", description="d")
        allowed = asyncio.run(
            group.interaction_check(FakeInteraction(FakeUser(manage_guild=True)))
        )
        self.assertTrue(allowed)

    def test_a_member_without_it_is_told_what_is_missing(self):
        group = ManagerGroup(name="demo", description="d")
        with self.assertRaises(app_commands.MissingPermissions) as raised:
            asyncio.run(group.interaction_check(FakeInteraction(FakeUser(send_messages=True))))
        self.assertEqual(raised.exception.missing_permissions, ["manage_guild"])

    def test_an_administrator_passes_every_guard(self):
        for cls in (ManagerGroup, ModeratorGroup):
            group = cls(name="demo", description="d")
            self.assertTrue(
                asyncio.run(
                    group.interaction_check(FakeInteraction(FakeUser(administrator=True)))
                )
            )

    def test_a_different_permission_does_not_open_the_wrong_group(self):
        # Timeout Members must not open /automod, nor Manage Server /warn.
        with self.assertRaises(app_commands.MissingPermissions):
            asyncio.run(
                ManagerGroup(name="a", description="d").interaction_check(
                    FakeInteraction(FakeUser(moderate_members=True))
                )
            )
        with self.assertRaises(app_commands.MissingPermissions):
            asyncio.run(
                ModeratorGroup(name="b", description="d").interaction_check(
                    FakeInteraction(FakeUser(manage_guild=True))
                )
            )

    def test_a_non_member_caller_is_refused_rather_than_crashing(self):
        group = ManagerGroup(name="demo", description="d")
        with self.assertRaises(app_commands.NoPrivateMessage):
            asyncio.run(group.interaction_check(NonMemberInteraction()))


class RealCogGroupTests(unittest.TestCase):
    """The guard is on the actual groups, not merely available to them."""

    def test_every_configuration_group_is_guarded(self):
        for group, permission in GUARDED_GROUPS:
            with self.subTest(group=group.name):
                self.assertIsInstance(group, _GuardedGroup)
                self.assertEqual(group.required_permission, permission)

    def test_every_configuration_group_refuses_an_ordinary_member(self):
        member = FakeInteraction(FakeUser(send_messages=True, read_messages=True))
        for group, _permission in GUARDED_GROUPS:
            with self.subTest(group=group.name):
                with self.assertRaises(app_commands.MissingPermissions):
                    asyncio.run(group.interaction_check(member))

    def test_every_configuration_group_admits_the_permission_holder(self):
        for group, permission in GUARDED_GROUPS:
            with self.subTest(group=group.name):
                holder = FakeInteraction(FakeUser(**{permission: True}))
                self.assertTrue(asyncio.run(group.interaction_check(holder)))

    def test_nested_subgroups_carry_their_own_guard(self):
        # The trap: Command._check_can_run calls only the immediate parent's
        # interaction_check, so /automod badword add never reaches /automod's.
        nested = [
            automod_cog.AutoMod.badword,
            levels_cog.Levels.backfill,
            voice_cog.VoiceReports.resend,
        ]
        for group in nested:
            with self.subTest(group=group.name):
                self.assertIsNotNone(group.parent, "expected a nested subgroup")
                self.assertIsInstance(
                    group,
                    _GuardedGroup,
                    f"/{group.parent.name} {group.name} would inherit no check",
                )

    def test_the_declared_default_permission_is_kept_alongside_the_guard(self):
        # The default still decides who sees the command in the picker; the
        # guard decides who may run it. Both matter.
        for group, _permission in GUARDED_GROUPS:
            if group.parent is not None:
                continue  # subgroups inherit the parent's default
            with self.subTest(group=group.name):
                self.assertIsNotNone(
                    group.default_permissions,
                    f"/{group.name} lost its default_permissions",
                )


if __name__ == "__main__":
    unittest.main()
