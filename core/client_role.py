"""Whether someone administers another server NovaGuard is on.

Manage Server is the reading, because that is the permission /setup,
/automod and /welcome all require: holding it somewhere means actually
running NovaGuard there, not merely being present.

The answer has three values on purpose. discord.py's get_member returns None
both for "not in this guild" and for "this guild's members are not loaded
yet", and nothing distinguishes them. Reading the second as a negative would
strip the role off a real customer after any reconnect, so a negative counts
only from a guild whose member list is actually loaded. Everything else is
UNKNOWN, and callers must never revoke on UNKNOWN — the same rule the guild
grace period follows: an irreversible step is not taken on missing data.
"""

ADMIN = "admin"
NOT_ADMIN = "not-admin"
UNKNOWN = "unknown"


def client_status(guilds, user_id, *, home_guild_id):
    """Classify ``user_id`` across every guild except the one they joined.

    Returns ADMIN as soon as one loaded guild shows Manage Server, NOT_ADMIN
    when at least one guild could be read and none did, and UNKNOWN when
    nothing could be read at all.
    """
    looked_anywhere = False

    for guild in guilds:
        if guild.id == home_guild_id:
            continue
        # An unloaded member list cannot produce a trustworthy "no".
        if not getattr(guild, "chunked", False):
            continue
        looked_anywhere = True
        member = guild.get_member(user_id)
        if member is not None and member.guild_permissions.manage_guild:
            return ADMIN

    return NOT_ADMIN if looked_anywhere else UNKNOWN
