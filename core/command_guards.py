"""Command groups that check their own permission at run time.

`default_permissions` is a default, not a gate. Discord uses it to decide who
sees a command in the picker, and a server administrator can override it in
Server Settings → Integrations and hand any command to any role - @everyone
included. Most of this project already knows that: /purge, /kick, /ban,
/setup and the rest carry `default_permissions` *and* a matching
`checks.has_permissions`, so the override changes who sees the command and
nothing more.

Six groups did not. `/automod`, `/welcome`, `/clientrole`, `/logs`, `/voice`,
`/giveaway` and `/warn` declared `default_permissions` on the group and then
relied on it alone, so a single Integrations override was the only thing
between an ordinary member and turning off the invite filter or clearing
someone's warnings.

The check lives on the group rather than on each subcommand deliberately: a
decorator has to be remembered on every new subcommand, and the one that is
forgotten is the hole. A group cannot forget.

One caveat drove the shape of this file. discord.py's Command._check_can_run
calls only the *immediate* parent's interaction_check:

    if self.parent is not None and self.parent is not self.binding:
        if not await maybe_coroutine(self.parent.interaction_check, interaction):
            return False

so a nested subgroup - `/automod badword add`, `/levels backfill run`,
`/voice resend last` - never reaches its grandparent's check. Nested groups
must therefore carry the guard themselves, which is why every group and
subgroup below is constructed from one of these classes rather than only the
top-level ones.
"""

from __future__ import annotations

import discord
from discord import app_commands


class _GuardedGroup(app_commands.Group):
    """A group whose permission is enforced when a subcommand actually runs."""

    #: Permission attribute on discord.Permissions, e.g. "manage_guild".
    required_permission: str = ""

    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions is None:
            # Not a Member - a DM, or an install context without guild state.
            # Every group built on this is guild_only, so this is the safe
            # answer rather than an expected one.
            raise app_commands.NoPrivateMessage()
        if getattr(permissions, "administrator", False):
            return True
        if getattr(permissions, self.required_permission, False):
            return True
        # MissingPermissions rather than a bare False: the tree's error handler
        # already turns it into "You need `manage_guild` to use this", which
        # tells the member what is missing instead of refusing anonymously.
        raise app_commands.MissingPermissions([self.required_permission])


class ManagerGroup(_GuardedGroup):
    """Server configuration. Requires Manage Server at run time."""

    required_permission = "manage_guild"


class ModeratorGroup(_GuardedGroup):
    """Member moderation. Requires Timeout Members at run time."""

    required_permission = "moderate_members"
