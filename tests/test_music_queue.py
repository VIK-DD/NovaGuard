"""Tests for the queue state machine behind the music player."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_queue import LoopMode, MusicQueue, Track  # noqa: E402


def track(title, requester_id="1"):
    return Track(
        title=title,
        url=f"https://example.test/{title}",
        duration=180,
        source="youtube",
        requester_id=requester_id,
    )


class QueueBasicsTests(unittest.TestCase):
    def test_a_new_queue_is_empty_and_has_no_current_track(self):
        queue = MusicQueue()
        self.assertTrue(queue.is_empty)
        self.assertIsNone(queue.current)
        self.assertEqual(len(queue), 0)

    def test_the_first_added_track_becomes_current_on_advance(self):
        queue = MusicQueue()
        queue.add(track("a"))
        self.assertEqual(queue.advance().title, "a")
        self.assertEqual(queue.current.title, "a")

    def test_advance_walks_the_queue_in_order_then_returns_none(self):
        queue = MusicQueue()
        queue.add_many([track("a"), track("b")])
        self.assertEqual(queue.advance().title, "a")
        self.assertEqual(queue.advance().title, "b")
        self.assertIsNone(queue.advance())
        self.assertIsNone(queue.current)

    def test_upcoming_excludes_the_current_track(self):
        queue = MusicQueue()
        queue.add_many([track("a"), track("b"), track("c")])
        queue.advance()
        self.assertEqual([t.title for t in queue.upcoming], ["b", "c"])

    def test_queue_refuses_tracks_past_the_maximum(self):
        queue = MusicQueue()
        accepted = queue.add_many([track(str(i)) for i in range(MusicQueue.MAX_QUEUE_LENGTH + 10)])
        self.assertEqual(accepted, MusicQueue.MAX_QUEUE_LENGTH)
        self.assertEqual(len(queue), MusicQueue.MAX_QUEUE_LENGTH)


class LoopTests(unittest.TestCase):
    def test_loop_track_replays_the_same_track(self):
        queue = MusicQueue()
        queue.add_many([track("a"), track("b")])
        queue.advance()
        queue.set_loop(LoopMode.TRACK)
        self.assertEqual(queue.advance().title, "a")
        self.assertEqual(queue.advance().title, "a")

    def test_loop_queue_wraps_around_to_the_start(self):
        queue = MusicQueue()
        queue.add_many([track("a"), track("b")])
        queue.set_loop(LoopMode.QUEUE)
        self.assertEqual(queue.advance().title, "a")
        self.assertEqual(queue.advance().title, "b")
        self.assertEqual(queue.advance().title, "a")

    def test_loop_off_is_the_default_and_ends_the_queue(self):
        queue = MusicQueue()
        self.assertEqual(queue.loop, LoopMode.OFF)
        queue.add(track("a"))
        queue.advance()
        self.assertIsNone(queue.advance())

    def test_next_mode_cycles_off_track_queue(self):
        self.assertEqual(LoopMode.next_mode(LoopMode.OFF), LoopMode.TRACK)
        self.assertEqual(LoopMode.next_mode(LoopMode.TRACK), LoopMode.QUEUE)
        self.assertEqual(LoopMode.next_mode(LoopMode.QUEUE), LoopMode.OFF)
        self.assertEqual(LoopMode.next_mode("nonsense"), LoopMode.OFF)


class EditingTests(unittest.TestCase):
    def test_remove_takes_a_one_based_position_from_upcoming(self):
        queue = MusicQueue()
        queue.add_many([track("a"), track("b"), track("c")])
        queue.advance()
        removed = queue.remove(1)
        self.assertEqual(removed.title, "b")
        self.assertEqual([t.title for t in queue.upcoming], ["c"])

    def test_remove_returns_none_for_an_out_of_range_position(self):
        queue = MusicQueue()
        queue.add(track("a"))
        queue.advance()
        self.assertIsNone(queue.remove(5))
        self.assertIsNone(queue.remove(0))

    def test_clear_empties_upcoming_but_keeps_the_current_track(self):
        queue = MusicQueue()
        queue.add_many([track("a"), track("b")])
        queue.advance()
        queue.clear()
        self.assertEqual(queue.upcoming, [])
        self.assertEqual(queue.current.title, "a")

    def test_shuffle_keeps_every_upcoming_track(self):
        queue = MusicQueue()
        queue.add_many([track(str(i)) for i in range(20)])
        queue.advance()
        before = sorted(t.title for t in queue.upcoming)
        queue.shuffle()
        self.assertEqual(sorted(t.title for t in queue.upcoming), before)

    def test_shuffle_never_moves_the_current_track(self):
        queue = MusicQueue()
        queue.add_many([track(str(i)) for i in range(20)])
        current = queue.advance()
        queue.shuffle()
        self.assertIs(queue.current, current)


if __name__ == "__main__":
    unittest.main()
