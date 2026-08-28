"""Delivery behaviour for the persistent Discord status card."""

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import discord

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs import statuspanel as statuspanel_cog  # noqa: E402


class FakeMessage:
    def __init__(self, message_id):
        self.id = message_id
        self.edits = []
        self.deleted = False

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        return self

    async def delete(self):
        self.deleted = True


class FakeChannel:
    def __init__(self, *, now, existing=None):
        self.id = 200
        self.guild = SimpleNamespace(id=100)
        self.now = now
        self.messages = {}
        self.sent = []
        if existing is not None:
            self.messages[existing.id] = existing

    async def send(self, **kwargs):
        message_id = discord.utils.time_snowflake(self.now, high=True)
        message = FakeMessage(message_id)
        self.messages[message_id] = message
        self.sent.append(kwargs)
        return message

    def get_partial_message(self, message_id):
        return self.messages[message_id]


class StatusDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
        self.cog = statuspanel_cog.StatusPanel(SimpleNamespace())
        self.embed = object()

    async def test_a_scheduled_refresh_edits_a_recent_message(self):
        message_id = discord.utils.time_snowflake(self.now - timedelta(days=2))
        existing = FakeMessage(message_id)
        channel = FakeChannel(now=self.now, existing=existing)

        with (
            mock.patch.object(
                statuspanel_cog,
                "get_guild_settings",
                return_value={statuspanel_cog.STATUS_MESSAGE_KEY: str(message_id)},
            ),
            mock.patch.object(statuspanel_cog, "update_guild_settings") as update,
        ):
            returned = await self.cog.refresh(channel, self.embed, now=self.now)

        self.assertIs(returned, existing)
        self.assertEqual(existing.edits, [{"embed": self.embed}])
        self.assertEqual(channel.sent, [])
        update.assert_not_called()

    async def test_a_scheduled_refresh_replaces_a_fourteen_day_old_message(self):
        message_id = discord.utils.time_snowflake(self.now - timedelta(days=14))
        existing = FakeMessage(message_id)
        channel = FakeChannel(now=self.now, existing=existing)

        with (
            mock.patch.object(
                statuspanel_cog,
                "get_guild_settings",
                return_value={statuspanel_cog.STATUS_MESSAGE_KEY: str(message_id)},
            ),
            mock.patch.object(statuspanel_cog, "update_guild_settings") as update,
        ):
            returned = await self.cog.refresh(channel, self.embed, now=self.now)

        self.assertIsNot(returned, existing)
        self.assertEqual(channel.sent, [{"embed": self.embed}])
        self.assertTrue(existing.deleted)
        update.assert_called_once_with(
            channel.guild.id,
            **{statuspanel_cog.STATUS_MESSAGE_KEY: str(returned.id)},
        )

    async def test_startup_delivery_forces_a_new_message(self):
        channel = FakeChannel(now=self.now)
        snapshot = {"snapshot": True}
        rendered = object()
        self.cog.collect_snapshot = mock.AsyncMock(return_value=snapshot)
        self.cog.publish = mock.AsyncMock()
        self.cog.refresh = mock.AsyncMock()

        with (
            mock.patch.object(
                statuspanel_cog,
                "resolve_configured_channels",
                new=mock.AsyncMock(return_value=[channel]),
            ),
            mock.patch.object(statuspanel_cog, "build_status_embed", return_value=rendered),
        ):
            await self.cog._deliver_to_configured_channels(publish_new=True)

        self.cog.publish.assert_awaited_once_with(channel, rendered)
        self.cog.refresh.assert_not_awaited()

    async def test_scheduled_delivery_uses_editing_path(self):
        channel = FakeChannel(now=self.now)
        snapshot = {"snapshot": True}
        rendered = object()
        self.cog.collect_snapshot = mock.AsyncMock(return_value=snapshot)
        self.cog.publish = mock.AsyncMock()
        self.cog.refresh = mock.AsyncMock()

        with (
            mock.patch.object(
                statuspanel_cog,
                "resolve_configured_channels",
                new=mock.AsyncMock(return_value=[channel]),
            ),
            mock.patch.object(statuspanel_cog, "build_status_embed", return_value=rendered),
        ):
            await self.cog._deliver_to_configured_channels()

        self.cog.refresh.assert_awaited_once_with(channel, rendered)
        self.cog.publish.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
