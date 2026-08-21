"""The gate in front of every irreversible moderation action.

`can_act_on` is the only thing standing between a moderator and kicking or
banning someone they outrank on paper but not in Discord's hierarchy. Getting
it wrong in either direction is expensive: too strict and moderation stops
working, too loose and a moderator removes people above them, or the bot
attempts an action Discord will refuse.

The warning store is here too. Warnings are the one moderation record
NovaGuard keeps itself, so losing or mangling them loses history no Discord
audit log holds.
"""

import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cogs.moderation as moderation  # noqa: E402
from cogs.moderation import can_act_on  # noqa: E402


class FakeRole:
    """Ordered the way discord.Role is: by position in the role list."""

    def __init__(self, position):
        self.position = position

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position

    def __lt__(self, other):
        return self.position < other.position

    def __le__(self, other):
        return self.position <= other.position


class FakeMember:
    def __init__(self, member_id, role_position, guild=None, name="Member"):
        self.id = member_id
        self.display_name = name
        self.mention = f"<@{member_id}>"
        self.top_role = FakeRole(role_position)
        self.guild = guild

    def __eq__(self, other):
        return isinstance(other, FakeMember) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


def build_guild(*, bot_role=9, owner_role=10):
    """A guild whose bot sits below the owner and above ordinary members."""
    guild = SimpleNamespace()
    guild.id = 1
    guild.name = "Test Guild"
    guild.me = FakeMember(99, bot_role, name="NovaGuard")
    guild.owner = FakeMember(1, owner_role, name="Owner")
    guild.me.guild = guild
    guild.owner.guild = guild
    return guild


def member(guild, member_id, role_position, name="Member"):
    return FakeMember(member_id, role_position, guild=guild, name=name)


class CanActOnTests(unittest.TestCase):
    def setUp(self):
        self.guild = build_guild()

    def test_the_server_owner_is_untouchable_even_by_themselves(self):
        moderator = member(self.guild, 20, 8)

        self.assertFalse(can_act_on(moderator, self.guild.owner))
        self.assertFalse(can_act_on(self.guild.owner, self.guild.owner))

    def test_the_owner_is_untouchable_even_holding_a_low_role(self):
        # Owners often keep an unremarkable role, or none at all, and rely on
        # ownership alone. Without an explicit owner check, a moderator whose
        # role outranks theirs would sail past the hierarchy comparison and
        # kick the person who owns the server.
        guild = build_guild(bot_role=9, owner_role=2)
        moderator = member(guild, 20, 8)

        self.assertFalse(can_act_on(moderator, guild.owner))

    def test_a_moderator_cannot_act_on_someone_ranked_above_them(self):
        moderator = member(self.guild, 20, 5)
        higher = member(self.guild, 30, 6)

        self.assertFalse(can_act_on(moderator, higher))

    def test_an_equal_rank_is_refused_too(self):
        # Discord itself refuses this, so allowing it would only produce a
        # failed API call presented to the moderator as a bot error.
        moderator = member(self.guild, 20, 5)
        peer = member(self.guild, 30, 5)

        self.assertFalse(can_act_on(moderator, peer))

    def test_a_moderator_cannot_act_on_themselves(self):
        moderator = member(self.guild, 20, 5)

        self.assertFalse(can_act_on(moderator, moderator))

    def test_a_moderator_can_act_on_someone_below_them(self):
        moderator = member(self.guild, 20, 5)
        target = member(self.guild, 30, 1)

        self.assertTrue(can_act_on(moderator, target))

    def test_the_owner_may_act_above_their_own_role(self):
        # An owner's top role can sit below a member's; ownership still wins,
        # as long as the bot can carry the action out.
        guild = build_guild(bot_role=9, owner_role=2)
        target = member(guild, 30, 5)

        self.assertTrue(can_act_on(guild.owner, target))

    def test_nobody_can_act_on_a_member_the_bot_cannot_reach(self):
        # The bot sits at 9; a target at 9 or above is beyond it, so the
        # action would fail at the API even for the owner.
        moderator = member(self.guild, 20, 8)
        out_of_reach = member(self.guild, 30, 9)

        self.assertFalse(can_act_on(moderator, out_of_reach))
        self.assertFalse(can_act_on(self.guild.owner, out_of_reach))

    def test_the_bot_cannot_be_acted_on_through_this_gate(self):
        moderator = member(self.guild, 20, 8)

        self.assertFalse(can_act_on(moderator, self.guild.me))


class FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    def is_done(self):
        return bool(self.sent)

    async def defer(self, **kwargs):
        pass


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeInteraction:
    def __init__(self, guild, user):
        self.guild = guild
        self.guild_id = guild.id
        self.user = user
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.extras = {}


class FakeBot:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, *args):
        self.dispatched.append(args)


class WarningStoreTests(unittest.IsolatedAsyncioTestCase):
    """Warnings survive a full add / list / clear cycle without losing data."""

    def setUp(self):
        self.store = {}
        self.dms = []
        self.responses = []

        self.guild = build_guild()
        self.moderator = member(self.guild, 20, 5, name="Mod")
        self.target = member(self.guild, 30, 1, name="Target")
        self.target.send = self._record_dm

        self.cog = moderation.Moderation(FakeBot())

        for target, name, replacement in (
            (moderation, "load_data", lambda name, default: self.store.get(name, default)),
            (moderation, "save_data", lambda name, value: self.store.__setitem__(name, value)),
            (moderation, "respond", self._record_response),
        ):
            patcher = mock.patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _record_dm(self, **kwargs):
        self.dms.append(kwargs)

    async def _record_response(self, interaction, embed, **kwargs):
        self.responses.append(embed)

    def interaction(self):
        return FakeInteraction(self.guild, self.moderator)

    async def test_a_warning_is_recorded_with_its_reason_and_moderator(self):
        await self.cog.warn_add.callback(self.cog, self.interaction(), self.target, "Spamming")

        entries = self.store["warns"]["1"]["30"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "Spamming")
        self.assertEqual(entries[0]["moderator_id"], self.moderator.id)
        # Stored as ISO-8601 so it survives a JSON round trip unambiguously.
        datetime.fromisoformat(entries[0]["created_at"])

    async def test_warnings_accumulate_rather_than_replace(self):
        for reason in ("First", "Second", "Third"):
            await self.cog.warn_add.callback(self.cog, self.interaction(), self.target, reason)

        entries = self.store["warns"]["1"]["30"]
        self.assertEqual([e["reason"] for e in entries], ["First", "Second", "Third"])

    async def test_one_members_warnings_do_not_touch_another(self):
        other = member(self.guild, 40, 1, name="Other")
        other.send = self._record_dm

        await self.cog.warn_add.callback(self.cog, self.interaction(), self.target, "Theirs")
        await self.cog.warn_add.callback(self.cog, self.interaction(), other, "Someone else's")

        guild_warns = self.store["warns"]["1"]
        self.assertEqual(len(guild_warns["30"]), 1)
        self.assertEqual(len(guild_warns["40"]), 1)
        self.assertEqual(guild_warns["30"][0]["reason"], "Theirs")

    async def test_the_member_is_told_they_were_warned(self):
        await self.cog.warn_add.callback(self.cog, self.interaction(), self.target, "Spamming")

        self.assertEqual(len(self.dms), 1)

    async def test_clearing_removes_only_the_named_member(self):
        other = member(self.guild, 40, 1, name="Other")
        other.send = self._record_dm
        await self.cog.warn_add.callback(self.cog, self.interaction(), self.target, "Theirs")
        await self.cog.warn_add.callback(self.cog, self.interaction(), other, "Someone else's")

        await self.cog.warn_clear.callback(self.cog, self.interaction(), self.target)

        guild_warns = self.store["warns"]["1"]
        self.assertNotIn("30", guild_warns)
        self.assertEqual(len(guild_warns["40"]), 1)

    async def test_clearing_a_member_with_no_warnings_is_harmless(self):
        await self.cog.warn_clear.callback(self.cog, self.interaction(), self.target)

        self.assertEqual(self.store.get("warns", {}), {})

    async def test_listing_a_clean_record_invents_nothing(self):
        await self.cog.warn_list.callback(self.cog, self.interaction(), self.target)

        self.assertEqual(len(self.responses), 1)
        self.assertNotIn("30", self.store.get("warns", {}).get("1", {}))

    async def test_listing_numbers_the_last_ten_from_their_true_position(self):
        for index in range(15):
            await self.cog.warn_add.callback(
                self.cog, self.interaction(), self.target, f"Reason {index}"
            )
        self.responses.clear()

        await self.cog.warn_list.callback(self.cog, self.interaction(), self.target)

        body = self.responses[0].description
        # Fifteen warnings, ten shown: the first line is #6, not #1.
        self.assertIn("`#6`", body)
        self.assertIn("`#15`", body)
        self.assertNotIn("`#5`", body)


class _Resp:
    def __init__(self, status):
        self.status = status
        self.reason = "forbidden"


class FakeChannel:
    def __init__(self, *, fails=False):
        self.sent = []
        self.fails = fails
        self.mention = "#general"

    async def send(self, content=None, **kwargs):
        if self.fails:
            raise moderation.discord.Forbidden(_Resp(403), "no access")
        self.sent.append((content, kwargs))


class SayCommandTests(unittest.IsolatedAsyncioTestCase):
    """/say speaks in the bot's voice, so the guard rails matter more than the happy path."""

    def setUp(self):
        self.guild = build_guild()
        self.mod = member(self.guild, 20, 5, name="Mod")
        self.channel = FakeChannel()
        self.bot = FakeBot()
        self.cog = moderation.Moderation(self.bot)

    def interaction(self):
        i = FakeInteraction(self.guild, self.mod)
        i.channel = self.channel
        return i

    async def say(self, message, channel=None):
        i = self.interaction()
        await self.cog.say.callback(self.cog, i, message, channel)
        return i

    async def test_it_posts_the_message_in_the_channel(self):
        await self.say("Server maintenance at 20:00.")

        self.assertEqual(len(self.channel.sent), 1)
        content, _ = self.channel.sent[0]
        self.assertEqual(content, "Server maintenance at 20:00.")

    async def test_it_posts_a_plain_message_not_an_embed(self):
        # "say" means the bot speaks; an embed would look like an announcement.
        await self.say("hello")
        _, kwargs = self.channel.sent[0]

        self.assertNotIn("embed", kwargs)

    async def test_it_never_lets_the_bot_ping_everyone_or_roles(self):
        # The whole reason this command is gated and guarded: a manager must
        # not be able to turn the bot into a mass-ping.
        await self.say("Heads up @everyone and @here")

        _, kwargs = self.channel.sent[0]
        mentions = kwargs["allowed_mentions"]
        self.assertFalse(mentions.everyone)
        self.assertFalse(mentions.roles)

    async def test_backslash_n_becomes_a_real_newline(self):
        await self.say("line one\\nline two")

        content, _ = self.channel.sent[0]
        self.assertEqual(content, "line one\nline two")

    async def test_empty_text_posts_nothing(self):
        await self.say("   ")

        self.assertEqual(self.channel.sent, [])

    async def test_a_message_over_the_discord_limit_is_refused(self):
        await self.say("x" * 2001)

        self.assertEqual(self.channel.sent, [])

    async def test_using_it_is_recorded_in_the_mod_log(self):
        # A command that can impersonate staff must leave a trace of who did it.
        await self.say("This is official.")

        modlogs = [d for d in self.bot.dispatched if d and d[0] == "modlog"]
        self.assertEqual(len(modlogs), 1)
        embed = modlogs[0][2]
        body = (embed.description or "") + " ".join(f.value for f in embed.fields)
        self.assertIn("This is official.", body)

    async def test_a_channel_it_cannot_post_in_is_reported_not_swallowed(self):
        blocked = FakeChannel(fails=True)

        i = self.interaction()
        await self.cog.say.callback(self.cog, i, "hi", blocked)

        # Nothing reaches the mod log, and no message was posted.
        self.assertFalse([d for d in self.bot.dispatched if d and d[0] == "modlog"])
        self.assertEqual(blocked.sent, [])


if __name__ == "__main__":
    unittest.main()
