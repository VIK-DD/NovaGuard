"""Commands that scan the whole store carry a per-user cooldown.

None of these are privileged - /privacy export is a data-subject right, and a
leaderboard is an ordinary thing to want. That is exactly why they need a
cooldown rather than a permission: every one of them sorts or walks every
record for the guild (or, for the privacy commands, the whole store) and
builds a payload from the result, and on the 1 GB host this bot is written
for, an unthrottled full scan is a resource-exhaustion primitive any member
can reach.

The numbers are deliberately small. The point is to stop a tight loop, not to
make a command feel broken; a data-subject right honestly exercised is used
once, not once a second.
"""

import asyncio
import itertools
import os
import sys
import unittest
from datetime import UTC, datetime

from discord import app_commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs import (  # noqa: E402
    ai as ai_cog,
    economy as economy_cog,
    levels as levels_cog,
    privacy as privacy_cog,
    system as system_cog,
    voice_hours as voice_hours_cog,
)


_probe_ids = itertools.count(1)


class FakeUser:
    def __init__(self, ident):
        self.id = ident

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id


class FakeInteraction:
    """Enough of an Interaction for a cooldown check: a user and a clock.

    discord.py keys the default bucket on `interaction.user` and reads the
    current time from `interaction.created_at`, so both have to be real.
    """

    def __init__(self, user, at):
        self.user = user
        self.created_at = at


def _cooldown_of(command):
    """Exercise a command's cooldown rather than reading discord.py's internals.

    The decorator keeps its state in a closure whose shape has moved between
    versions, so introspecting it makes this file fail on a library upgrade
    for no good reason. Calling the check is the thing we actually care about:
    the first use passes, an immediate second one does not.

    Returns (rate, per) or None when the command has no cooldown at all.
    """
    for check in getattr(command, "checks", []):
        # A new identity each call. The decorator's bucket map is shared for
        # the life of the process and its own cleanup runs off
        # interaction.created_at, which is frozen here - so reusing a key
        # would make the second probe of a command read an exhausted bucket
        # left behind by the first.
        user = FakeUser(next(_probe_ids))
        start = datetime(2026, 1, 1, tzinfo=UTC)
        try:
            first = asyncio.run(check(FakeInteraction(user, start)))
        except app_commands.CommandOnCooldown:
            first = False
        except Exception:
            continue  # not a cooldown check
        if first is not True:
            continue
        try:
            asyncio.run(check(FakeInteraction(user, start)))
        except app_commands.CommandOnCooldown as cooling:
            return cooling.cooldown.rate, cooling.cooldown.per
    return None


# (label, command object, longest acceptable interval in seconds)
SCAN_HEAVY_COMMANDS = [
    ("privacy export", privacy_cog.Privacy.privacy_export, 60.0),
    ("privacy delete", privacy_cog.Privacy.privacy_delete, 60.0),
    ("privacy server-export", privacy_cog.Privacy.privacy_server_export, 60.0),
    ("rank", levels_cog.Levels.rank, 5.0),
    ("leaderboard", levels_cog.Levels.leaderboard, 10.0),
    ("richest", economy_cog.Economy.richest, 10.0),
    ("voicetop", voice_hours_cog.VoiceHours.voicetop, 10.0),
    ("doctor", system_cog.System.doctor, 30.0),
    ("ask", ai_cog.AI.ask, 15.0),  # already had one; pinned so it stays
]


class ScanHeavyCommandsAreThrottledTests(unittest.TestCase):
    def test_every_scan_heavy_command_has_a_cooldown(self):
        for label, command, _limit in SCAN_HEAVY_COMMANDS:
            with self.subTest(command=label):
                self.assertIsNotNone(
                    _cooldown_of(command),
                    f"/{label} walks the store for any member with no cooldown",
                )

    def test_the_cooldowns_are_one_use_per_window(self):
        for label, command, limit in SCAN_HEAVY_COMMANDS:
            with self.subTest(command=label):
                rate, per = _cooldown_of(command)
                self.assertEqual(rate, 1, f"/{label} allows more than one use per window")
                self.assertLessEqual(per, limit, f"/{label} cooldown is longer than intended")
                self.assertGreater(per, 0, f"/{label} cooldown is not a real window")

    def test_the_privacy_commands_are_the_most_throttled(self):
        # They are the only ones that walk the entire store rather than one
        # guild's slice of it.
        for label in ("privacy export", "privacy delete", "privacy server-export"):
            command = dict((name, cmd) for name, cmd, _ in SCAN_HEAVY_COMMANDS)[label]
            self.assertGreaterEqual(_cooldown_of(command)[1], 60.0, label)


if __name__ == "__main__":
    unittest.main()
