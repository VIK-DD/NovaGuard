"""The /setup panel: one message, explicit state, no silent writes.

The old panel kept the chosen setting in a variable that nothing ever reset,
defaulted that variable to "update_channel", and answered the target menu with
a brand new ephemeral message instead of updating the panel. Between them,
picking a second channel either overwrote the first setting or wrote to Bot
Updates without saying so, while the panel itself scrolled away behind
confirmations. Each test below pins one of those.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import database  # noqa: E402
from core.storage import get_guild_settings  # noqa: E402

GUILD_ID = 1


class FakeChannel:
    def __init__(self, channel_id, name):
        self.id = channel_id
        self.name = name
        self.mention = f"#{name}"


class FakeGuild:
    def __init__(self, channels):
        self.id = GUILD_ID
        self._channels = {c.id: c for c in channels}

    def get_channel(self, channel_id):
        return self._channels.get(int(channel_id))

    def get_role(self, _role_id):
        return None


class FakeResponse:
    """Records how the panel answered, so a test can prove it edited in place."""

    def __init__(self):
        self.edits = []
        self.messages = []

    async def edit_message(self, **kwargs):
        self.edits.append(kwargs)

    async def send_message(self, content=None, **kwargs):
        self.messages.append(content)


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


class FakeInteraction:
    def __init__(self, guild, channel):
        self.guild = guild
        self.guild_id = guild.id
        self.channel = channel
        self.channel_id = channel.id
        self.response = FakeResponse()
        self.followup = FakeFollowup()


def find_button(view, label):
    for child in view.children:
        if getattr(child, "label", None) == label:
            return child
    raise AssertionError(f"no button labelled {label!r}")


class SetupFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._old_path = database.DB_PATH
        self._old_initialized = database._INITIALIZED
        database.DB_PATH = Path(self._temp.name) / "test.sqlite3"
        # init_database() is a no-op once it has run, so the flag has to be
        # cleared or the new file never gets its tables.
        database._INITIALIZED = False
        database.init_database()

        self.general = FakeChannel(100, "general")
        self.logs = FakeChannel(200, "logs")
        self.guild = FakeGuild([self.general, self.logs])

        import cogs.setup as setup_module

        self.setup = setup_module

    async def asyncSetUp(self):
        # discord.ui.View reaches for the running loop in its constructor, so
        # the panel has to be built inside the async phase of the test.
        self.view = self.setup.SetupView()

    def tearDown(self):
        database.DB_PATH = self._old_path
        database._INITIALIZED = self._old_initialized
        self._temp.cleanup()

    def interaction(self, channel=None):
        return FakeInteraction(self.guild, channel or self.general)

    async def choose_target(self, key):
        select = self.view.target_select
        select._values = [key]
        interaction = self.interaction()
        await select.callback(interaction)
        return interaction

    async def choose_channel(self, channel):
        select = self.view.channel_select
        select._values = [channel]
        interaction = self.interaction()
        await select.callback(interaction)
        return interaction

    # --- the panel refuses to guess -------------------------------------

    def test_a_fresh_panel_has_no_target_and_cannot_take_a_channel_yet(self):
        self.assertIsNone(self.view.pending_key)
        # Disabled is what stops the old silent write to update_channel: with
        # nothing chosen there is no correct place to put a channel.
        self.assertTrue(self.view.channel_select.disabled)

    async def test_a_channel_offered_with_no_target_writes_nothing(self):
        await self.choose_channel(self.general)

        settings = get_guild_settings(GUILD_ID)
        for key in self.setup.CHANNEL_KEYS:
            self.assertIsNone(settings.get(key), f"{key} was written without a target")

    # --- choosing a target ----------------------------------------------

    async def test_choosing_a_target_names_it_on_the_channel_picker(self):
        await self.choose_target("welcome_channel")

        self.assertEqual(self.view.pending_key, "welcome_channel")
        self.assertFalse(self.view.channel_select.disabled)
        self.assertIn("Welcome", self.view.channel_select.placeholder)

    # --- saving ----------------------------------------------------------

    async def test_picking_a_channel_saves_it_to_the_chosen_target(self):
        await self.choose_target("welcome_channel")
        await self.choose_channel(self.general)

        settings = get_guild_settings(GUILD_ID)
        self.assertEqual(str(settings.get("welcome_channel")), str(self.general.id))

    async def test_the_target_clears_after_a_save(self):
        await self.choose_target("welcome_channel")
        await self.choose_channel(self.general)

        # The heart of the reported bug: the old panel kept "welcome_channel"
        # here forever, so the next channel picked silently replaced it.
        self.assertIsNone(self.view.pending_key)
        self.assertTrue(self.view.channel_select.disabled)

    async def test_a_second_channel_cannot_overwrite_the_first_setting(self):
        await self.choose_target("welcome_channel")
        await self.choose_channel(self.general)

        # Straight to a second channel, without touching the target menu.
        await self.choose_channel(self.logs)

        settings = get_guild_settings(GUILD_ID)
        self.assertEqual(str(settings.get("welcome_channel")), str(self.general.id))

    async def test_two_settings_in_a_row_each_land_where_they_were_sent(self):
        await self.choose_target("welcome_channel")
        await self.choose_channel(self.general)
        await self.choose_target("log_channel")
        await self.choose_channel(self.logs)

        settings = get_guild_settings(GUILD_ID)
        self.assertEqual(str(settings.get("welcome_channel")), str(self.general.id))
        self.assertEqual(str(settings.get("log_channel")), str(self.logs.id))

    # --- one panel, not a pile of messages -------------------------------

    async def test_every_step_edits_the_one_panel_instead_of_sending_messages(self):
        steps = [
            await self.choose_target("welcome_channel"),
            await self.choose_channel(self.general),
            await self.choose_target("log_channel"),
            await self.choose_channel(self.logs),
        ]

        for index, interaction in enumerate(steps):
            self.assertEqual(len(interaction.response.edits), 1, f"step {index} did not edit")
            self.assertEqual(interaction.response.messages, [], f"step {index} sent a message")
            self.assertEqual(interaction.followup.sent, [], f"step {index} sent a followup")

    # --- clearing --------------------------------------------------------

    async def test_clear_without_a_target_changes_nothing(self):
        await self.choose_target("welcome_channel")
        await self.choose_channel(self.general)  # clears the target

        button = find_button(self.view, "Clear")
        await button.callback(self.interaction())

        settings = get_guild_settings(GUILD_ID)
        self.assertEqual(str(settings.get("welcome_channel")), str(self.general.id))

    async def test_clear_unsets_the_chosen_target(self):
        await self.choose_target("welcome_channel")
        await self.choose_channel(self.general)
        await self.choose_target("welcome_channel")

        button = find_button(self.view, "Clear")
        await button.callback(self.interaction())

        settings = get_guild_settings(GUILD_ID)
        self.assertIsNone(settings.get("welcome_channel"))

    # --- shortcuts and completion ----------------------------------------

    async def test_use_this_channel_saves_the_channel_setup_was_run_in(self):
        await self.choose_target("log_channel")

        button = find_button(self.view, "Use this channel")
        await button.callback(self.interaction(self.logs))

        settings = get_guild_settings(GUILD_ID)
        self.assertEqual(str(settings.get("log_channel")), str(self.logs.id))

    async def test_mark_complete_records_the_flag(self):
        button = find_button(self.view, "Mark complete")
        await button.callback(self.interaction())

        self.assertTrue(get_guild_settings(GUILD_ID).get("setup_completed"))


if __name__ == "__main__":
    unittest.main()
