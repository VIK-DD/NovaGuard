"""Focused tests for shared interaction response helpers and duration parsing."""

import asyncio
import os
import sys
import unittest
from datetime import timedelta
from types import SimpleNamespace

import discord

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.utils import (  # noqa: E402
    MAX_DURATION_SECONDS,
    MAX_DURATION_TEXT,
    defer_interaction,
    parse_duration,
)


class FakeResponse:
    def __init__(self, done=False):
        self.done = done
        self.calls = 0

    def is_done(self):
        return self.done

    async def defer(self, **_kwargs):
        self.calls += 1
        self.done = True


class AlreadyRespondedResponse(FakeResponse):
    async def defer(self, **_kwargs):
        self.calls += 1
        raise discord.InteractionResponded(SimpleNamespace())


class DeferInteractionTests(unittest.TestCase):
    def test_skips_a_second_acknowledgement(self):
        response = FakeResponse(done=True)
        result = asyncio.run(defer_interaction(SimpleNamespace(response=response)))

        self.assertFalse(result)
        self.assertEqual(response.calls, 0)

    def test_defers_an_unanswered_interaction_once(self):
        response = FakeResponse()
        result = asyncio.run(defer_interaction(SimpleNamespace(response=response), ephemeral=True))

        self.assertTrue(result)
        self.assertEqual(response.calls, 1)

    def test_handles_a_race_with_another_response(self):
        response = AlreadyRespondedResponse()
        result = asyncio.run(defer_interaction(SimpleNamespace(response=response)))

        self.assertFalse(result)
        self.assertEqual(response.calls, 1)


class ParseDurationTests(unittest.TestCase):
    """What /remind and /timeout accept from a text box any member can type in."""

    def test_reads_the_shapes_the_commands_advertise(self):
        self.assertEqual(parse_duration("10m"), timedelta(minutes=10))
        self.assertEqual(parse_duration("1h30m"), timedelta(hours=1, minutes=30))
        self.assertEqual(parse_duration("2d"), timedelta(days=2))
        self.assertEqual(parse_duration("1w"), timedelta(weeks=1))
        self.assertEqual(parse_duration("45 s"), timedelta(seconds=45))

    def test_is_case_insensitive(self):
        self.assertEqual(parse_duration("2H"), timedelta(hours=2))

    def test_nonsense_is_simply_not_a_duration(self):
        for probe in ("", None, "soon", "10", "m"):
            self.assertIsNone(parse_duration(probe), probe)

    def test_zero_is_not_a_duration(self):
        self.assertIsNone(parse_duration("0s"))

    def test_a_leading_sign_is_ignored_rather_than_read_as_negative(self):
        # The pattern matches digits only, so "-5m" reads as five minutes. That
        # is worth pinning: the alternative a reader might assume - a negative
        # timedelta reaching /timeout - is what would actually be dangerous.
        self.assertEqual(parse_duration("-5m"), timedelta(minutes=5))

    # ── the regression ───────────────────────────────────────────────
    #
    # These three used to raise instead of returning None. The exception
    # escaped to the global command error handler, which answers the member
    # and files an error digest, so any member could generate log traffic on
    # demand by typing into /remind.

    def test_an_enormous_amount_is_refused_instead_of_overflowing(self):
        # timedelta(seconds=99999999999 * 604800) raised OverflowError.
        self.assertIsNone(parse_duration("99999999999w"))

    def test_a_thousands_of_digits_amount_is_refused_instead_of_raising(self):
        # int() on >4300 digits raises ValueError in CPython 3.11+.
        self.assertIsNone(parse_duration("1" * 4600 + "s"))

    def test_many_large_parts_cannot_add_up_past_the_ceiling(self):
        # Each part is individually acceptable; the sum is not.
        self.assertIsNone(parse_duration("500w" * 20))

    def test_the_ceiling_itself_is_accepted(self):
        just_under = MAX_DURATION_SECONDS - 1
        self.assertEqual(parse_duration(f"{just_under}s"), timedelta(seconds=just_under))
        self.assertEqual(
            parse_duration(f"{MAX_DURATION_SECONDS}s"), timedelta(seconds=MAX_DURATION_SECONDS)
        )
        self.assertIsNone(parse_duration(f"{MAX_DURATION_SECONDS + 1}s"))

    def test_overlong_text_is_refused_before_any_parsing(self):
        self.assertIsNone(parse_duration("1m" * MAX_DURATION_TEXT))

    def test_every_caller_still_gets_a_value_it_can_clamp(self):
        # /timeout does min(delta, 28 days) and /remind checks delta.days > 90.
        # Both need a timedelta, and neither may ever see an exception.
        for probe in ("28d", "90d", "365d", "99999999999w", "1" * 4600 + "s"):
            result = parse_duration(probe)
            self.assertTrue(result is None or isinstance(result, timedelta), probe)


if __name__ == "__main__":
    unittest.main()
