"""Regression tests for the least-privilege Discord invite."""

import unittest

import discord

from core.invite_permissions import (
    DEFAULT_INVITE_PERMISSIONS,
    DEFAULT_INVITE_PERMISSIONS_VALUE,
    INVITE_PERMISSION_BITS,
)


class InvitePermissionsTest(unittest.TestCase):
    def test_default_contains_exactly_the_documented_permissions(self):
        permissions = discord.Permissions(DEFAULT_INVITE_PERMISSIONS_VALUE)
        enabled = {name for name, value in permissions if value}

        # discord.py calls Discord's VIEW_CHANNEL flag ``read_messages`` when
        # iterating, while accepting ``view_channel`` as the public alias.
        expected = set(INVITE_PERMISSION_BITS)
        expected.remove("view_channel")
        expected.add("read_messages")

        self.assertEqual(enabled, expected)
        self.assertFalse(permissions.administrator)

    def test_the_invite_does_not_ask_to_ping_everyone(self):
        # Requested for a long time and used by nothing: every send path
        # already passes allowed_mentions with everyone=False, /say refuses
        # @everyone explicitly, and bot.py sets that default process-wide.
        # Asking a server to trust a bot with a mass ping it never sends is
        # exactly the privilege that should not be requested.
        permissions = discord.Permissions(DEFAULT_INVITE_PERMISSIONS_VALUE)
        self.assertFalse(permissions.mention_everyone)
        self.assertNotIn("mention_everyone", INVITE_PERMISSION_BITS)

    def test_the_permissions_the_bot_genuinely_needs_are_still_requested(self):
        # The trim must not quietly cost a capability the bot actually uses.
        permissions = discord.Permissions(DEFAULT_INVITE_PERMISSIONS_VALUE)
        for name in (
            "manage_roles",              # auto-role and role panels
            "moderate_members",          # /timeout and AutoMod
            "manage_threads",            # tickets
            "create_private_threads",
            "send_messages_in_threads",
            "manage_messages",           # /purge and AutoMod deletions
            "manage_channels",           # /slowmode
            "kick_members",
            "ban_members",
            "embed_links",
            "attach_files",
            "read_message_history",
            "connect",                   # voice presence tracking
        ):
            self.assertTrue(getattr(permissions, name), f"invite lost {name}")

    def test_string_value_is_valid_for_the_oauth_query(self):
        self.assertEqual(int(DEFAULT_INVITE_PERMISSIONS), DEFAULT_INVITE_PERMISSIONS_VALUE)
        self.assertEqual(DEFAULT_INVITE_PERMISSIONS, "1460594142230")


if __name__ == "__main__":
    unittest.main()
