"""One rule for every role NovaGuard hands out on someone's behalf.

Before this module the project had four separate role guards - `/rolepanel`,
the dashboard's role-panel publish, the dashboard's autorole setting, and the
button callback itself - and all four asked the same two questions: is the role
below my own top role, and is it managed by an integration. Neither question
is about what the role can *do*.

That left a straightforward escalation. A member holding only Manage Server -
who in Discord cannot assign a single role - could open the dashboard, point
`autorole` at a role carrying Administrator, and every member who joined
afterwards became an administrator. The same person could publish a role panel
for that role instead, and any member who pressed the button became one
immediately. The assignment is performed by the bot, whose top role is above,
so Discord allows it: the guild's own role hierarchy is bypassed entirely
because nothing on the path ever consulted it.

So the rule lives here, once, and says three things:

* a role carrying privileged permissions is never self-assignable, whoever
  asks and however it was configured;
* the person configuring a panel cannot expose a role above their own
  position, which is the hierarchy Discord would have enforced on them;
* the bot must still be able to manage it, and it must not be managed,
  default, or a boost role - the original checks, kept.

The permission check is repeated at click time as well as at publish time. A
role is not static: one that was harmless when the panel went up can be granted
Manage Roles a month later, and the panel would go on handing it out.
"""

from __future__ import annotations

import discord

# Permissions that make a role a staff role. A role holding any of these is
# something a server grants deliberately, to a named person - never something a
# member awards themselves by pressing a button.
#
# `mention_everyone` is here because a self-assignable @everyone ping is a
# spam primitive; the voice moderation trio because they are moderation.
# Names are probed with getattr so a discord.py rename cannot turn this list
# into an import-time crash - the cost of a missing name is one unchecked
# permission, the cost of a crash is the whole bot.
DANGEROUS_PERMISSION_NAMES = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "manage_messages",
    "manage_threads",
    "manage_nicknames",
    "manage_events",
    "manage_emojis_and_stickers",
    "manage_expressions",
    "moderate_members",
    "kick_members",
    "ban_members",
    "mention_everyone",
    "view_audit_log",
    "mute_members",
    "deafen_members",
    "move_members",
)


def role_permission_risk(role):
    """The privileged permissions this role carries, newest concern first.

    Administrator short-circuits: it implies everything at Discord's end, so
    listing the rest alongside it only makes the refusal harder to read.
    """
    permissions = getattr(role, "permissions", None)
    if permissions is None:
        return []
    if getattr(permissions, "administrator", False):
        return ["administrator"]
    return [name for name in DANGEROUS_PERMISSION_NAMES if getattr(permissions, name, False)]


def _actor_outranks(actor, role):
    """Whether `actor` may expose `role`, by Discord's own hierarchy rules."""
    if actor is None:
        return True
    guild = getattr(actor, "guild", None)
    if guild is not None and getattr(guild, "owner_id", None) == getattr(actor, "id", None):
        return True
    permissions = getattr(actor, "guild_permissions", None)
    if permissions is not None and getattr(permissions, "administrator", False):
        return True
    actor_top = getattr(actor, "top_role", None)
    if actor_top is None:
        # The actor could not be resolved to a member. Fall back to the
        # permission checks alone rather than silently allowing anything.
        return True
    return role < actor_top


def role_assignment_error(role, guild, actor=None):
    """Why this role must not be self-assignable here, or None when it may be.

    `actor` is whoever is *configuring* the panel or the autorole, not whoever
    later presses the button. Pass it wherever it can be resolved to a Member;
    at click time there is no configurer and the permission and hierarchy
    checks below still stand on their own.
    """
    if role is None:
        return "the role no longer exists"
    if getattr(role, "is_default", lambda: False)():
        return "@everyone cannot be handed out"
    if getattr(role, "managed", False):
        return "it is managed by an integration and Discord will not allow it"

    me = getattr(guild, "me", None)
    bot_top = getattr(me, "top_role", None)
    if bot_top is not None and role >= bot_top:
        return "it sits above NovaGuard's own top role"

    risky = role_permission_risk(role)
    if risky:
        listed = ", ".join(risky[:3]) + ("…" if len(risky) > 3 else "")
        return f"it carries privileged permissions ({listed}) and must not be self-assignable"

    if not _actor_outranks(actor, role):
        return "it sits above your own top role"

    return None


def role_is_self_assignable(role, guild, actor=None):
    """True when NovaGuard may hand this role out. See role_assignment_error."""
    return role_assignment_error(role, guild, actor) is None
