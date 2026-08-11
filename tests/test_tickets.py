"""Ticket panel publishing updates in place instead of spamming channels."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.tickets import publish_ticket_panel, role_can_manage_tickets  # noqa: E402


class FakePermissions:
    def __init__(self, *, view_channel=True, manage_threads=True):
        self.view_channel = view_channel
        self.manage_threads = manage_threads


class FakePermissionChannel:
    def __init__(self, permissions):
        self.permissions = permissions

    def permissions_for(self, _role):
        return self.permissions


class FakeMessage:
    def __init__(self, message_id=55):
        self.id = message_id
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.messages = {}

    async def send(self, **kwargs):
        message = FakeMessage(55)
        self.sent.append(kwargs)
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        return self.messages[message_id]


class TicketPanelTests(unittest.IsolatedAsyncioTestCase):
    def test_staff_role_needs_channel_visibility_and_thread_management(self):
        role = object()
        self.assertTrue(
            role_can_manage_tickets(FakePermissionChannel(FakePermissions()), role)
        )
        self.assertFalse(
            role_can_manage_tickets(
                FakePermissionChannel(FakePermissions(manage_threads=False)), role
            )
        )
        self.assertFalse(
            role_can_manage_tickets(
                FakePermissionChannel(FakePermissions(view_channel=False)), role
            )
        )

    async def test_first_publish_sends_and_second_publish_edits(self):
        channel = FakeChannel()

        message, created = await publish_ticket_panel(channel)
        updated, created_again = await publish_ticket_panel(channel, message.id)

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertIs(updated, message)
        self.assertEqual(len(channel.sent), 1)
        self.assertEqual(len(message.edits), 1)
        self.assertIn("embed", message.edits[0])
        self.assertIn("view", message.edits[0])


if __name__ == "__main__":
    unittest.main()
