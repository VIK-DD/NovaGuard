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

    def test_string_value_is_valid_for_the_oauth_query(self):
        self.assertEqual(int(DEFAULT_INVITE_PERMISSIONS), DEFAULT_INVITE_PERMISSIONS_VALUE)
        self.assertEqual(DEFAULT_INVITE_PERMISSIONS, "1460594273302")


if __name__ == "__main__":
    unittest.main()
