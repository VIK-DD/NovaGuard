"""Focused tests for shared interaction response helpers."""

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace

import discord

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.utils import defer_interaction  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
