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
  asks and however it was configured - and "carrying" means the guild-wide
  bitfield *and* what channel overwrites hand it, because a role whose
  permissions integer is 0 can still be Manage Messages somewhere;
* the person configuring a panel cannot expose a role above their own
  position, which is the hierarchy Discord would have enforced on them;
* the bot must still be able to manage it, and it must not be managed,
  default, or a boost role - the original checks, kept.

The permission check is repeated at click time as well as at publish time. A
role is not static: one that was harmless when the panel went up can be granted
Manage Roles a month later, and the panel would go on handing it out.

One thing deliberately not refused: a role that merely *opens* a private channel.
That is what role panels exist to do, and blocking it would break the ordinary
"press here for #valorant" case to catch the rare "press here for #staff-internal"
one. Visibility is reported instead - `channel_visibility_grants` - so whoever
publishes the panel is told which channels come with the role.
"""

from __future__ import annotations


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

# The same question, asked of a channel permission overwrite.
#
# `role.permissions` is the guild-wide bitfield and nothing else. Discord also
# lets a channel grant a permission to a role that the role does not hold
# server-wide, and that grant is invisible to `role_permission_risk` - a role
# whose permissions integer is 0 can still be Manage Messages in #general
# because an overwrite says so. Six audits' worth of care about which roles may
# be handed out meant nothing on that path, because nothing on it ever read an
# overwrite.
#
# Deliberately narrower than the guild-wide list. Two names that belong there
# do not belong here:
#
# * `view_channel` and `read_message_history` are how a role panel is supposed
#   to work. "Press this to see #valorant" is the feature, not an escalation,
#   and refusing it would break the common case to catch the rare one. They are
#   reported instead - see `channel_visibility_grants` - so the person
#   publishing a panel is told which private channels it opens rather than
#   discovering it afterwards.
# * `administrator` has no meaning in an overwrite; Discord ignores it there.
#
# What is left is unambiguous: no server grants a member Manage Webhooks in one
# channel as a hobby badge.
DANGEROUS_OVERWRITE_NAMES = (
    "manage_channels",
    "manage_permissions",
    "manage_webhooks",
    "manage_messages",
    "manage_threads",
    "mention_everyone",
    "moderate_members",
    "mute_members",
    "deafen_members",
    "move_members",
    "priority_speaker",
)

# Permissions worth telling the configurer about without refusing the role.
VISIBILITY_OVERWRITE_NAMES = ("view_channel", "read_message_history")


class _UnknownActor:
    """The configurer could not be resolved to a guild member.

    Distinct from `None`, which means "no configurer applies here" - the role
    panel button, where the person pressing it is not the person who set the
    panel up, and the hierarchy question is genuinely not being asked.

    Passing `None` for both cases is what made the hierarchy check fail open:
    `_actor_member` returns nothing when the dashboard user is not in the
    member cache, and the check that should have refused instead skipped.
    """

    __slots__ = ()

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<UNKNOWN_ACTOR>"


#: Sentinel for "we could not confirm who is configuring this". See _UnknownActor.
UNKNOWN_ACTOR = _UnknownActor()


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


def _channel_label(channel):
    name = getattr(channel, "name", None)
    return f"#{name}" if name else "a channel"


def guild_overwrite_index(guild):
    """What every role in this guild is granted by channel overwrites.

    Returns ``{role_id: {"elevated": [...], "unlocks": [...]}}`` where each
    entry names the channel and the permission, e.g. ``#mod-log:manage_messages``.

    Built in one pass over the guild's channels because the alternative is
    quadratic where it matters most. `_config_payload` asks the assignability
    question for every role in the guild, and `channel.overwrites_for(role)`
    rebuilds a full PermissionOverwrite per call - a hundred roles across two
    hundred channels is twenty thousand of them per dashboard load. Reading
    `channel.overwrites` once per channel and inverting it costs two hundred.

    Only permissions the role is *granted* count, and only where @everyone does
    not already have them: a channel that allows Send Messages to everyone is
    not a privilege a role is carrying.
    """
    everyone = getattr(guild, "default_role", None)
    everyone_id = getattr(everyone, "id", None)
    base_permissions = getattr(everyone, "permissions", None)
    index = {}

    for channel in getattr(guild, "channels", ()) or ():
        overwrites = getattr(channel, "overwrites", None)
        if not overwrites:
            continue
        everyone_overwrite = overwrites.get(everyone) if everyone is not None else None
        label = _channel_label(channel)

        def everyone_already_has(name):
            if everyone_overwrite is not None:
                granted = getattr(everyone_overwrite, name, None)
                if granted is not None:
                    return bool(granted)
            return bool(getattr(base_permissions, name, False))

        for target, overwrite in overwrites.items():
            target_id = getattr(target, "id", None)
            if target_id is None or target_id == everyone_id:
                continue
            # Member-specific overwrites are not this module's business: they
            # name one person, not a role anyone can press a button to get.
            if getattr(target, "top_role", None) is not None:
                continue

            entry = index.setdefault(target_id, {"elevated": [], "unlocks": []})
            for name in DANGEROUS_OVERWRITE_NAMES:
                if getattr(overwrite, name, None) is True and not everyone_already_has(name):
                    entry["elevated"].append(f"{label}:{name}")
            for name in VISIBILITY_OVERWRITE_NAMES:
                if getattr(overwrite, name, None) is True and not everyone_already_has(name):
                    entry["unlocks"].append(label)
                    break

    return index


def _overwrite_entry(role, guild, index=None):
    role_id = getattr(role, "id", None)
    if role_id is None:
        return {"elevated": [], "unlocks": []}
    if index is None:
        index = guild_overwrite_index(guild)
    return index.get(role_id) or {"elevated": [], "unlocks": []}


def channel_overwrite_risk(role, guild, index=None):
    """Staff-grade powers this role is handed by channel overwrites.

    The overwrite half of `role_permission_risk`. A non-empty result is a
    refusal, on the same reasoning: a member must not be able to award
    themselves Manage Messages anywhere by pressing a button.
    """
    return list(_overwrite_entry(role, guild, index)["elevated"])


def channel_visibility_grants(role, guild, index=None):
    """Private channels this role opens - reported, never refused.

    Opening a channel is what a role panel is *for*. What it must not do is
    open one quietly: the person publishing the panel should be told that
    "@Support" also carries #staff-internal with it, and then decide.
    """
    return list(dict.fromkeys(_overwrite_entry(role, guild, index)["unlocks"]))


def _actor_outranks(actor, role):
    """Whether `actor` may expose `role`, by Discord's own hierarchy rules."""
    if actor is UNKNOWN_ACTOR:
        # We were asked to check a configurer and could not resolve one. That
        # is the one case that must not fall through to "allowed": it is
        # exactly how a hierarchy check disappears without anybody noticing.
        return False
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


def bot_cannot_manage_reason(role, guild):
    """Why NovaGuard cannot touch this role at all, or None when it can.

    Kept separate from the policy checks because the two need different
    answers at a role-panel button. A policy refusal - the role has since
    grown privileged permissions - must still allow *removal*, or whoever
    already holds it is stranded with it. A mechanical one cannot: if the role
    moved above NovaGuard's top role, Discord will refuse the removal too, and
    saying so plainly beats letting the call fail into a generic error.
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
    return None


def role_assignment_error(role, guild, actor=None, *, overwrite_index=None):
    """Why this role must not be self-assignable here, or None when it may be.

    `actor` is whoever is *configuring* the panel or the autorole, not whoever
    later presses the button. Pass it wherever it can be resolved to a Member;
    at click time there is no configurer and the permission and hierarchy
    checks below still stand on their own. Pass `UNKNOWN_ACTOR` when a
    configurer applies but could not be resolved - that refuses rather than
    skipping the hierarchy question.

    `overwrite_index` is an optional `guild_overwrite_index` result, for
    callers asking about many roles at once.
    """
    mechanical = bot_cannot_manage_reason(role, guild)
    if mechanical:
        return mechanical

    risky = role_permission_risk(role)
    if risky:
        listed = ", ".join(risky[:3]) + ("…" if len(risky) > 3 else "")
        return f"it carries privileged permissions ({listed}) and must not be self-assignable"

    # The same refusal, for permissions a channel hands the role directly.
    # Checked after the guild-wide list so the clearer message wins when a role
    # trips both.
    granted = channel_overwrite_risk(role, guild, overwrite_index)
    if granted:
        listed = ", ".join(granted[:3]) + ("…" if len(granted) > 3 else "")
        return (
            f"channel overwrites grant it privileged permissions ({listed}) "
            "and it must not be self-assignable"
        )

    if not _actor_outranks(actor, role):
        if actor is UNKNOWN_ACTOR:
            return "we could not confirm your own role position in this server"
        return "it sits above your own top role"

    return None


def role_is_self_assignable(role, guild, actor=None, *, overwrite_index=None):
    """True when NovaGuard may hand this role out. See role_assignment_error."""
    return role_assignment_error(role, guild, actor, overwrite_index=overwrite_index) is None
