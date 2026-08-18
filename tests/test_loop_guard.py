"""A background loop must outlive a bad iteration.

discord.py ends a tasks.loop for good when its body raises: it sets
_has_failed, calls the error handler, and re-raises, so the task finishes and
never ticks again. Nothing restarts it. A single transient failure — Discord
returning 500, a disk hiccup during cleanup — therefore silences a feature
until someone restarts the bot, with no alert.

That matters most for the retention loop, which is what keeps NovaGuard's
published deletion promises true.
"""

import asyncio
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.loop_guard import keep_running  # noqa: E402


class RecordingLogger(logging.Logger):
    def __init__(self):
        super().__init__("test")
        self.exceptions = []

    def exception(self, msg, *args, **kwargs):
        self.exceptions.append(msg % args if args else msg)


class KeepRunningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = RecordingLogger()

    async def test_a_raising_body_does_not_escape(self):
        @keep_running(self.log, "retention sweep")
        async def body():
            raise RuntimeError("database is locked")

        await body()  # must not raise

    async def test_the_failure_is_reported_rather_than_swallowed(self):
        @keep_running(self.log, "retention sweep")
        async def body():
            raise RuntimeError("database is locked")

        await body()

        self.assertEqual(len(self.log.exceptions), 1)
        self.assertIn("retention sweep", self.log.exceptions[0])

    async def test_a_normal_result_passes_straight_through(self):
        @keep_running(self.log, "anything")
        async def body():
            return "done"

        self.assertEqual(await body(), "done")
        self.assertEqual(self.log.exceptions, [])

    async def test_cancellation_still_propagates(self):
        # cog_unload cancels these loops. Swallowing CancelledError would leave
        # the task alive through a reload and let two copies run at once.
        @keep_running(self.log, "anything")
        async def body():
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await body()

    async def test_arguments_reach_the_wrapped_body(self):
        seen = {}

        @keep_running(self.log, "anything")
        async def body(self_arg, value=None):
            seen["self"] = self_arg
            seen["value"] = value

        await body("cog", value=7)

        self.assertEqual(seen, {"self": "cog", "value": 7})

    async def test_the_next_iteration_still_runs_after_a_failure(self):
        calls = []

        @keep_running(self.log, "anything")
        async def body():
            calls.append(len(calls))
            if len(calls) == 1:
                raise RuntimeError("transient")

        await body()
        await body()

        self.assertEqual(calls, [0, 1])


class RealLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_guarded_tasks_loop_keeps_ticking_after_it_raises(self):
        from discord.ext import tasks

        log = RecordingLogger()
        ticks = []

        @tasks.loop(seconds=0.01)
        @keep_running(log, "flaky loop")
        async def flaky():
            ticks.append(len(ticks))
            if len(ticks) == 1:
                raise RuntimeError("first tick explodes")

        flaky.start()
        try:
            # Long enough for several ticks; the unguarded version stops at one.
            await asyncio.sleep(0.08)
        finally:
            flaky.cancel()

        self.assertGreater(len(ticks), 1, "the loop died on its first failure")
        self.assertFalse(flaky.failed(), "the loop was marked failed")


if __name__ == "__main__":
    unittest.main()
