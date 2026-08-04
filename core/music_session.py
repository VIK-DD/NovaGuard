"""Per-guild player state and the bot-wide concurrency cap.

Separate from the cog so the cap can be tested without Discord. That rule is
the one most likely to fail silently until the host is under load.
"""

import os
import time

from .music_queue import MusicQueue

DEFAULT_MAX_SESSIONS = 3
IDLE_DISCONNECT_SECONDS = 300


def configured_max_sessions():
    """Read MUSIC_MAX_SESSIONS, falling back rather than crashing at import."""
    try:
        value = int(os.getenv("MUSIC_MAX_SESSIONS", "").strip() or DEFAULT_MAX_SESSIONS)
    except ValueError:
        return DEFAULT_MAX_SESSIONS
    return max(1, value)


class MusicSession:
    """Everything one guild's player needs."""

    def __init__(self, guild_id):
        self.guild_id = str(guild_id)
        self.queue = MusicQueue()
        self.volume = 100
        self.text_channel_id = None
        self.card_message_id = None
        self.voice_client = None
        self.started_at = None
        self._idle_since = time.monotonic()

    def touch(self):
        """Mark activity, cancelling any pending idle disconnect."""
        self._idle_since = time.monotonic()

    def idle_seconds(self):
        return time.monotonic() - self._idle_since


class SessionRegistry:
    """Guild id -> MusicSession, capped bot-wide.

    A guild that already holds a session is always served, cap or not. Refusing
    someone mid-playlist because another server started playing would feel
    broken and save very little load.
    """

    def __init__(self, max_sessions=None):
        self.MAX_SESSIONS = max_sessions if max_sessions is not None else configured_max_sessions()
        self._sessions: dict[str, MusicSession] = {}

    def get(self, guild_id):
        return self._sessions.get(str(guild_id))

    def create(self, guild_id):
        key = str(guild_id)
        if key not in self._sessions:
            self._sessions[key] = MusicSession(key)
        return self._sessions[key]

    def drop(self, guild_id):
        self._sessions.pop(str(guild_id), None)

    def active_count(self):
        return len(self._sessions)

    def has_capacity(self):
        return len(self._sessions) < self.MAX_SESSIONS

    def all_sessions(self):
        return list(self._sessions.values())
