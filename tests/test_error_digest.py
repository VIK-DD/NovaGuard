"""Where an error digest is delivered, and where it must never be delivered.

This file exists because of a real defect: `send_error_digest` resolved the
private error-log channel into a local called `channel`, and the block that
builds the "Interaction" field then reused that same name for the channel the
command was typed in. Every slash-command traceback - file paths, module
layout, function names - was therefore published into whatever public channel
the member happened to be standing in, while `docs/SECURITY.md` claimed
tracebacks reached the admin log channel only.

The bug was invisible to the suite because every other test mocks
`send_error_digest` wholesale. These tests call the real thing.
"""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import error_digest  # noqa: E402


class RecordingChannel:
    """A channel that remembers what was sent to it."""

    def __init__(self, name):
        self.name = name
        self.mention = f"#{name}"
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)


class FakeUser:
    id = 4242
    mention = "<@4242>"


class FakeCommand:
    qualified_name = "remind"


class FakeInteraction:
    """An interaction raised in a public channel, as a member's would be."""

    def __init__(self, public_channel, guild=None):
        self.channel = public_channel
        self.channel_id = 99
        self.user = FakeUser()
        self.command = FakeCommand()
        self.guild = guild


class FakeBot:
    pass


def _error_with_traceback():
    try:
        raise OverflowError("Python int too large to convert to C int")
    except OverflowError as error:
        return error


class DigestDestinationTests(unittest.TestCase):
    """The digest goes to the configured error-log channel. Only there."""

    def setUp(self):
        self.admin_channel = RecordingChannel("bot-errors")
        self.public_channel = RecordingChannel("general")

    def _send(self, **kwargs):
        async def resolve(bot, guild=None):
            return self.admin_channel

        with mock.patch.object(error_digest, "resolve_error_channel", resolve):
            return asyncio.run(
                error_digest.send_error_digest(
                    FakeBot(), "Slash Command Error", _error_with_traceback(), **kwargs
                )
            )

    def test_a_command_error_reaches_the_admin_channel(self):
        self.assertTrue(self._send(interaction=FakeInteraction(self.public_channel)))
        self.assertEqual(len(self.admin_channel.sent), 1)

    def test_a_command_error_never_reaches_the_channel_it_came_from(self):
        # The regression itself. A member typing a command that raises must not
        # cause a traceback to be published where they are standing.
        self._send(interaction=FakeInteraction(self.public_channel))
        self.assertEqual(
            self.public_channel.sent,
            [],
            "traceback was published into the channel the command was run in",
        )

    def test_the_traceback_is_in_the_embed_that_went_to_the_admin_channel(self):
        self._send(interaction=FakeInteraction(self.public_channel))
        embed = self.admin_channel.sent[0]["embed"]
        fields = {field.name: field.value for field in embed.fields}
        self.assertIn("Traceback", fields)
        self.assertIn("OverflowError", fields["Traceback"])

    def test_the_interaction_field_still_names_the_originating_channel(self):
        # Reporting where it happened is the point of the field; it just must
        # not decide where the report is sent.
        self._send(interaction=FakeInteraction(self.public_channel))
        embed = self.admin_channel.sent[0]["embed"]
        fields = {field.name: field.value for field in embed.fields}
        self.assertIn("#general", fields["Interaction"])
        self.assertIn("/remind", fields["Interaction"])

    def test_a_digest_without_an_interaction_still_reaches_the_admin_channel(self):
        self.assertTrue(self._send(context="Scheduled backup failed."))
        self.assertEqual(len(self.admin_channel.sent), 1)

    def test_no_configured_channel_means_nothing_is_sent_anywhere(self):
        async def resolve(bot, guild=None):
            return None

        with mock.patch.object(error_digest, "resolve_error_channel", resolve):
            sent = asyncio.run(
                error_digest.send_error_digest(
                    FakeBot(),
                    "Slash Command Error",
                    _error_with_traceback(),
                    interaction=FakeInteraction(self.public_channel),
                )
            )
        self.assertFalse(sent)
        self.assertEqual(self.public_channel.sent, [])


class DigestDedupeTests(unittest.TestCase):
    """The dedupe window survived the rename; it is what keeps a loop quiet."""

    def test_the_same_error_twice_in_a_row_sends_once(self):
        admin_channel = RecordingChannel("bot-errors")

        async def resolve(bot, guild=None):
            return admin_channel

        async def twice():
            bot = FakeBot()
            first = await error_digest.send_error_digest(
                bot, "Slash Command Error", _error_with_traceback()
            )
            second = await error_digest.send_error_digest(
                bot, "Slash Command Error", _error_with_traceback()
            )
            return first, second

        with mock.patch.object(error_digest, "resolve_error_channel", resolve):
            first, second = asyncio.run(twice())

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(admin_channel.sent), 1)


if __name__ == "__main__":
    unittest.main()
