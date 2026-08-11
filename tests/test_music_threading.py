"""Playback callbacks must hand work back to the event loop safely.

discord.py runs the ``after=`` callback on the audio player's own thread, not
on the event loop — ``AudioPlayer._call_after`` calls ``self.after`` directly
from ``Thread.run``. Touching the loop from there is unsafe, and a task created
without a strong reference can be collected before it finishes. The callback in
question is the one that advances the queue, so losing it means the music stops
with no error anywhere.

Run standalone:  python3 tests/test_music_threading.py
"""

import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cogs.music as music_cog  # noqa: E402


def after_callback_bodies(source):
    """Every ``def after_playing(...)`` body, sliced by indentation."""
    bodies = []
    lines = source.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"(\s*)def after_playing\(", line)
        if not match:
            continue
        indent = len(match.group(1))
        body = []
        for following in lines[index + 1 :]:
            if following.strip() and (len(following) - len(following.lstrip())) <= indent:
                break
            body.append(following)
        bodies.append("\n".join(body))
    return bodies


class AudioThreadHandoffTests(unittest.TestCase):
    def setUp(self):
        self.source = inspect.getsource(music_cog)
        self.bodies = after_callback_bodies(self.source)

    def test_the_callbacks_exist_to_be_checked(self):
        # Guards the rest of the file: a rename would otherwise let these tests
        # pass by finding nothing to inspect.
        self.assertGreaterEqual(len(self.bodies), 2)

    def test_no_after_callback_creates_a_task_on_the_loop(self):
        for body in self.bodies:
            self.assertNotIn(
                "loop.create_task",
                body,
                "after= runs on the audio thread; use run_coroutine_threadsafe",
            )

    def test_after_callbacks_hand_off_thread_safely(self):
        for body in self.bodies:
            self.assertTrue(
                "run_coroutine_threadsafe" in body or "_schedule_from_audio_thread" in body,
                f"callback does not hand work back to the loop safely:\n{body}",
            )

    def test_the_handoff_keeps_a_reference_to_what_it_scheduled(self):
        # asyncio holds only a weak reference to a running task. Without a
        # strong one the coroutine that advances the queue can be collected
        # mid-flight, and playback stops silently.
        handoff = inspect.getsource(music_cog.Music._schedule_from_audio_thread)

        self.assertIn("run_coroutine_threadsafe", handoff)
        self.assertIn("add_done_callback", handoff)


if __name__ == "__main__":
    unittest.main()
