"""Queue state for the music player.

Deliberately free of discord.py so the rules stay unit-testable on their own,
the same split `core/levels_settings.py` uses against `cogs/levels.py`.

The queue holds a cursor rather than popping: `advance()` moves it forward and
returns the new current track, which is what makes loop modes expressible
without copying the list around.
"""

import random
from dataclasses import dataclass, field


@dataclass
class Track:
    title: str
    url: str
    duration: int
    source: str
    requester_id: str
    thumbnail: str | None = None
    uploader: str | None = None
    # An expiring CDN link, filled in by the extraction layer and refreshed
    # when playback rejects it. Excluded from equality: two references to the
    # same song are the same track even if one link has gone stale.
    stream_url: str | None = field(default=None, compare=False)
    # Some CDNs, especially SoundCloud, require the same HTTP headers yt-dlp
    # used while resolving the signed media URL.
    http_headers: dict = field(default_factory=dict, compare=False)


class LoopMode:
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"

    ORDER = (OFF, TRACK, QUEUE)

    @classmethod
    def next_mode(cls, mode):
        try:
            index = cls.ORDER.index(mode)
        except ValueError:
            return cls.OFF
        return cls.ORDER[(index + 1) % len(cls.ORDER)]


class MusicQueue:
    """Ordered tracks plus a cursor.

    Not thread-safe; the cog touches it only from the event loop.
    """

    MAX_QUEUE_LENGTH = 500

    def __init__(self):
        self._tracks: list[Track] = []
        self._index = -1
        # Set once the cursor has walked off the end. Kept as a flag rather
        # than by parking the index past the last track: a track queued after
        # the queue ran dry would land exactly under such an index and be
        # skipped by the next advance, leaving the player silent.
        self._finished = False
        self.loop = LoopMode.OFF

    def __len__(self):
        return len(self._tracks)

    @property
    def is_empty(self):
        return not self._tracks

    @property
    def current(self):
        if self._finished:
            return None
        if 0 <= self._index < len(self._tracks):
            return self._tracks[self._index]
        return None

    @property
    def upcoming(self):
        return self._tracks[self._index + 1 :]

    def add(self, track):
        """Append one track. Returns True when it fit under the cap.

        The cap counts what is still waiting, not what already played, so a
        long-lived session cannot lock itself out of queueing anything new.
        """
        if len(self.upcoming) >= self.MAX_QUEUE_LENGTH:
            return False
        self._tracks.append(track)
        return True

    def add_many(self, tracks):
        """Append as many as fit. Returns how many were accepted."""
        accepted = 0
        for track in tracks:
            if not self.add(track):
                break
            accepted += 1
        return accepted

    def advance(self):
        """Move to the next track under the current loop mode.

        Returns the new current track, or None when the queue is finished.
        """
        if not self._tracks:
            self._index = -1
            self._finished = False
            return None

        if self.loop == LoopMode.TRACK and self.current is not None:
            return self.current

        if self._index + 1 < len(self._tracks):
            self._index += 1
            self._finished = False
            return self.current

        if self.loop == LoopMode.QUEUE:
            self._index = 0
            self._finished = False
            return self.current

        # Park on the last track and mark the queue finished. Anything queued
        # from here lands in `upcoming`, so the next advance plays it.
        self._index = len(self._tracks) - 1
        self._finished = True
        return None

    def remove(self, position):
        """Remove the 1-based position from upcoming tracks."""
        if position < 1 or position > len(self.upcoming):
            return None
        return self._tracks.pop(self._index + position)

    def replace_current(self, track):
        """Replace the track currently under the cursor."""
        if not self._finished and 0 <= self._index < len(self._tracks):
            self._tracks[self._index] = track
            return True
        return False

    def clear(self):
        """Drop everything after the current track."""
        del self._tracks[self._index + 1 :]

    def shuffle(self):
        """Shuffle only what has not played yet."""
        rest = self._tracks[self._index + 1 :]
        random.shuffle(rest)
        self._tracks[self._index + 1 :] = rest

    def set_loop(self, mode):
        self.loop = mode if mode in LoopMode.ORDER else LoopMode.OFF
        return self.loop
