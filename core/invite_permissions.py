"""Discord permissions requested by NovaGuard's public bot invite.

Keep this list explicit. It is both the security boundary for new installs and
the documentation for why the invite asks for each capability. The bit
positions follow Discord's official Permissions reference.
"""

from types import MappingProxyType


INVITE_PERMISSION_BITS = MappingProxyType(
    {
        # Moderation commands and AutoMod actions.
        "kick_members": 1 << 1,
        "ban_members": 1 << 2,
        "manage_channels": 1 << 4,
        "manage_messages": 1 << 13,
        "moderate_members": 1 << 40,
        # Normal replies, embeds, transcripts and ticket staff notifications.
        "view_channel": 1 << 10,
        "send_messages": 1 << 11,
        "embed_links": 1 << 14,
        "attach_files": 1 << 15,
        "read_message_history": 1 << 16,
        # mention_everyone (1 << 17) was requested here and used by nothing.
        # Every send path already passes allowed_mentions with everyone=False,
        # /say refuses @everyone explicitly, and bot.py sets the same default
        # process-wide - so the permission bought nothing and asked every
        # server that installs NovaGuard to trust it with a mass ping.
        # Voice presence tracking.
        "connect": 1 << 20,
        "speak": 1 << 21,
        "use_voice_activation": 1 << 25,
        # Auto-role and role panels.
        "manage_roles": 1 << 28,
        # Private ticket creation, replies and closure.
        "manage_threads": 1 << 34,
        "create_private_threads": 1 << 36,
        "send_messages_in_threads": 1 << 38,
    }
)

DEFAULT_INVITE_PERMISSIONS_VALUE = sum(INVITE_PERMISSION_BITS.values())
DEFAULT_INVITE_PERMISSIONS = str(DEFAULT_INVITE_PERMISSIONS_VALUE)
