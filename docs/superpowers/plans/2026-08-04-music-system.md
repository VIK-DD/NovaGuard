# Music System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give NovaGuard music playback — `/play` with a link or a search, a queue, and a button-driven player card — sourced from YouTube and SoundCloud, with Spotify links resolved to a searchable track.

**Architecture:** Pure logic (queue state, link parsing, card rendering) lives in `core/` modules with no discord.py import, so it is unit-testable without a bot — the same split the codebase already uses between `core/levels_settings.py` and `cogs/levels.py`. `cogs/music.py` owns the Discord surface: commands, buttons, voice clients, and the per-guild player loop. All `yt-dlp` work is pushed off the event loop through `asyncio.to_thread`, and results are cached in the existing SQLite database so repeat searches are instant.

**Tech Stack:** Python 3.11+, discord.py 2.7, `yt-dlp`, `PyNaCl`, system `ffmpeg`, SQLite (existing `data/novaguard.sqlite3`).

**Spec:** `docs/superpowers/specs/2026-08-04-music-system-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Never block the event loop.** Every `yt-dlp` call goes through `asyncio.to_thread`. This box also serves the dashboard API and the Discord gateway, and already alerts on event-loop lag above 3 s.
- **`MUSIC_MAX_SESSIONS` defaults to 3**, read from the environment. A request past the cap gets a clear message, never an exception.
- **Extraction timeout is 20 seconds.** One retry on failure, then skip the track.
- **Search cache TTL is 7 days; stream-URL cache TTL is 6 hours** (YouTube expires them anyway).
- **Autocomplete reads only from the cache** — never call `yt-dlp` from an autocomplete handler. Discord allows 3 s; extraction needs 1–3 s.
- **Idle disconnect after 5 minutes**, counted from whichever comes first: every human leaving the voice channel, or the queue emptying with nothing playing. Any activity cancels the timer.
- **The queue is never persisted.** No SQLite writes for queue state.
- **The player loop catches every exception and continues.** One bad track must never end the session permanently.
- **Control permission:** anyone in the same voice channel; Manage Server overrides. No configuration.
- **The player card is edited on state change only** — never on a timer.
- **Volume is 0–100**, per session, resets to 100 on disconnect; buttons step by 10.
- **Loop modes cycle off → track → queue.**
- Tests are `unittest`, runnable standalone (`python tests/test_x.py`) with a `sys.path` insert, matching every existing file in `tests/`.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `core/music_queue.py` | Queue state: add, advance, remove, clear, shuffle, loop modes. No discord.py. |
| `core/music_sources.py` | Link classification, Spotify→query conversion, duration formatting, `yt-dlp` extraction and search. |
| `core/music_session.py` | Per-guild session state and the bot-wide concurrency cap. |
| `core/music_card.py` | Renders the player embed from a snapshot. Pure function. |
| `core/database.py` (modify) | `music_cache` table plus `cache_get` / `cache_put` / `cache_prefix_search` / `cache_purge_expired`. |
| `cogs/music.py` | Commands, buttons, voice clients, per-guild playback chain. |
| `bot.py` (modify) | Register `"music"` in `COGS`. |
| `requirements.txt` (modify) | `yt-dlp`, `PyNaCl`. |
| `.env.example`, `README.md`, `SETUP.md` (modify) | Document `MUSIC_MAX_SESSIONS`, Spotify credentials, `ffmpeg`. |

---

### Task 1: Queue state machine

**Files:**
- Create: `core/music_queue.py`
- Test: `tests/test_music_queue.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Track` (dataclass: `title: str`, `url: str`, `duration: int`, `source: str`, `requester_id: str`, `thumbnail: str | None`, `uploader: str | None`, `stream_url: str | None`), `LoopMode` (`OFF`/`TRACK`/`QUEUE` string constants plus `next_mode(mode)`), `MusicQueue` with `add(track)`, `add_many(tracks)`, `current`, `upcoming`, `advance()`, `remove(position)`, `clear()`, `shuffle()`, `set_loop(mode)`, `loop`, `is_empty`, `__len__`, `MAX_QUEUE_LENGTH`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_music_queue.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_music_queue.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.music_queue'`

- [ ] **Step 3: Write the implementation**

Create `core/music_queue.py`:

```python
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
    """Ordered tracks plus a cursor. Not thread-safe; the cog touches it only
    from the event loop."""

    MAX_QUEUE_LENGTH = 500

    def __init__(self):
        self._tracks: list[Track] = []
        self._index = -1
        self.loop = LoopMode.OFF

    def __len__(self):
        return len(self._tracks)

    @property
    def is_empty(self):
        return not self._tracks

    @property
    def current(self):
        if 0 <= self._index < len(self._tracks):
            return self._tracks[self._index]
        return None

    @property
    def upcoming(self):
        return self._tracks[self._index + 1:]

    def add(self, track):
        """Append one track. Returns True when it fit under the cap."""
        if len(self._tracks) >= self.MAX_QUEUE_LENGTH:
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
        """Move to the next track under the current loop mode and return it,
        or None when the queue is finished."""
        if not self._tracks:
            self._index = -1
            return None

        if self.loop == LoopMode.TRACK and self.current is not None:
            return self.current

        if self._index + 1 < len(self._tracks):
            self._index += 1
            return self.current

        if self.loop == LoopMode.QUEUE:
            self._index = 0
            return self.current

        self._index = len(self._tracks)
        return None

    def remove(self, position):
        """Remove the 1-based `position` from `upcoming`. Returns the removed
        track, or None when the position does not exist."""
        if position < 1 or position > len(self.upcoming):
            return None
        return self._tracks.pop(self._index + position)

    def clear(self):
        """Drop everything after the current track."""
        del self._tracks[self._index + 1:]

    def shuffle(self):
        """Shuffle only what has not played yet."""
        rest = self._tracks[self._index + 1:]
        random.shuffle(rest)
        self._tracks[self._index + 1:] = rest

    def set_loop(self, mode):
        self.loop = mode if mode in LoopMode.ORDER else LoopMode.OFF
        return self.loop
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_music_queue.py -q`
Expected: PASS — 14 passed

Also verify the standalone path the VPS uses:
Run: `python3 tests/test_music_queue.py`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add core/music_queue.py tests/test_music_queue.py
git commit -m "Add the music queue state machine

Tracks, loop modes and cursor movement, with no discord.py import so the
rules are testable on their own — the same split levels_settings.py uses
against the levels cog. The queue keeps a cursor instead of popping,
which is what lets loop-track and loop-queue be expressed without
copying the list around.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Cache table

**Files:**
- Modify: `core/database.py` (add table inside `init_database`, add four functions after `load_economy_data`)
- Test: `tests/test_music_cache.py`

**Interfaces:**
- Consumes: existing `connect()`, `init_database()`, `_LOCK`, `encode_value()`, `decode_value()`, `DB_PATH`, `_INITIALIZED` from `core/database.py`.
- Produces: `cache_put(key, payload, ttl_seconds)`, `cache_get(key)` → payload dict or `None`, `cache_prefix_search(prefix, limit)` → `list[tuple[str, dict]]`, `cache_purge_expired()` → int.

- [ ] **Step 1: Write the failing test**

Create `tests/test_music_cache.py`:

```python
"""Tests for the music search/metadata cache."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as database  # noqa: E402


class MusicCacheTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._old_path = database.DB_PATH
        database.DB_PATH = Path(self._temp.name) / "test.sqlite3"
        database._INITIALIZED = False
        database.init_database()

    def tearDown(self):
        database.DB_PATH = self._old_path
        database._INITIALIZED = False
        self._temp.cleanup()

    def test_a_stored_payload_comes_back_unchanged(self):
        database.cache_put("yt:abc", {"title": "Song", "duration": 210}, 3600)
        self.assertEqual(database.cache_get("yt:abc"), {"title": "Song", "duration": 210})

    def test_a_missing_key_returns_none(self):
        self.assertIsNone(database.cache_get("nope"))

    def test_an_expired_entry_is_treated_as_missing(self):
        database.cache_put("yt:old", {"title": "Old"}, -1)
        self.assertIsNone(database.cache_get("yt:old"))

    def test_storing_the_same_key_twice_overwrites(self):
        database.cache_put("yt:abc", {"title": "First"}, 3600)
        database.cache_put("yt:abc", {"title": "Second"}, 3600)
        self.assertEqual(database.cache_get("yt:abc"), {"title": "Second"})

    def test_prefix_search_finds_matching_live_entries(self):
        database.cache_put("search:bohemian rhapsody", {"title": "Bohemian Rhapsody"}, 3600)
        database.cache_put("search:bohemian like you", {"title": "Bohemian Like You"}, 3600)
        database.cache_put("search:something else", {"title": "Something Else"}, 3600)
        found = database.cache_prefix_search("search:bohemian", 10)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(key.startswith("search:bohemian") for key, _ in found))

    def test_prefix_search_skips_expired_entries(self):
        database.cache_put("search:live", {"title": "Live"}, 3600)
        database.cache_put("search:dead", {"title": "Dead"}, -1)
        found = database.cache_prefix_search("search:", 10)
        self.assertEqual([key for key, _ in found], ["search:live"])

    def test_prefix_search_honours_the_limit(self):
        for index in range(10):
            database.cache_put(f"search:x{index}", {"title": str(index)}, 3600)
        self.assertEqual(len(database.cache_prefix_search("search:", 3)), 3)

    def test_a_percent_sign_in_the_prefix_is_not_a_wildcard(self):
        database.cache_put("search:100% pure", {"title": "Pure"}, 3600)
        database.cache_put("search:anything", {"title": "Anything"}, 3600)
        found = database.cache_prefix_search("search:100%", 10)
        self.assertEqual([key for key, _ in found], ["search:100% pure"])

    def test_purge_removes_only_expired_rows(self):
        database.cache_put("search:live", {"title": "Live"}, 3600)
        database.cache_put("search:dead", {"title": "Dead"}, -1)
        self.assertEqual(database.cache_purge_expired(), 1)
        self.assertIsNotNone(database.cache_get("search:live"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_music_cache.py -q`
Expected: FAIL — `AttributeError: module 'core.database' has no attribute 'cache_put'`

- [ ] **Step 3: Add the table**

In `core/database.py`, inside `init_database()`, add this after the last existing `CREATE TABLE`/`CREATE INDEX` statement but before the function sets `_INITIALIZED`:

```python
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS music_cache (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_music_cache_expiry ON music_cache (expires_at)"
        )
```

- [ ] **Step 4: Add the cache functions**

Confirm `import time` is present at the top of `core/database.py`; add it if not.

Append to `core/database.py`, after `load_economy_data`:

```python
# ── music cache ──────────────────────────────────────────────────────
#
# Search results and track metadata, keyed by a normalised query or URL.
# Purely an optimisation: any entry may vanish without affecting correctness,
# which is why expiry is checked on read instead of swept on a schedule.


def cache_put(key, payload, ttl_seconds):
    init_database()
    expires_at = time.time() + ttl_seconds
    with _LOCK, connect() as connection:
        connection.execute(
            """
            INSERT INTO music_cache (key, payload, expires_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                payload = excluded.payload,
                expires_at = excluded.expires_at
            """,
            (str(key), encode_value(payload), expires_at),
        )
        connection.commit()


def cache_get(key):
    init_database()
    with _LOCK, connect() as connection:
        row = connection.execute(
            "SELECT payload, expires_at FROM music_cache WHERE key = ?", (str(key),)
        ).fetchone()
    if row is None or row["expires_at"] < time.time():
        return None
    return decode_value(row["payload"])


def cache_prefix_search(prefix, limit):
    """Live entries whose key starts with `prefix`, newest expiry first.

    Backs autocomplete, which must answer inside Discord's three seconds and
    so can never reach for yt-dlp. LIKE wildcards in the user's text are
    escaped: a query containing `%` would otherwise match everything.
    """
    init_database()
    escaped = str(prefix).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with _LOCK, connect() as connection:
        rows = connection.execute(
            """
            SELECT key, payload FROM music_cache
            WHERE key LIKE ? ESCAPE '\\' AND expires_at >= ?
            ORDER BY expires_at DESC LIMIT ?
            """,
            (escaped + "%", time.time(), int(limit)),
        ).fetchall()
    return [(row["key"], decode_value(row["payload"])) for row in rows]


def cache_purge_expired():
    init_database()
    with _LOCK, connect() as connection:
        cursor = connection.execute("DELETE FROM music_cache WHERE expires_at < ?", (time.time(),))
        connection.commit()
        return cursor.rowcount
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_music_cache.py -q`
Expected: PASS — 9 passed

Run: `python3 -m pytest tests -q`
Expected: PASS — nothing else broken

- [ ] **Step 6: Commit**

```bash
git add core/database.py tests/test_music_cache.py
git commit -m "Add a SQLite cache for music search results

Keyed by normalised query or URL, with expiry checked on read rather
than swept, because every entry can vanish without affecting
correctness. Prefix search backs autocomplete, which must answer inside
Discord's three seconds and so can never reach for yt-dlp itself; LIKE
wildcards in the user's text are escaped so a query containing a percent
sign cannot match the whole table.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Link parsing and formatting

**Files:**
- Create: `core/music_sources.py`
- Test: `tests/test_music_sources.py`

**Interfaces:**
- Consumes: nothing (pure helpers only in this task).
- Produces: `classify_input(text)` → `(kind, platform, identifier)` where `kind` ∈ `"search"|"track"|"playlist"` and `platform` ∈ `"youtube"|"soundcloud"|"spotify"|None`; `spotify_to_query(metadata)` → `str`; `format_duration(seconds, live_label=None)` → `str`; `normalise_query(text)` → `str`; `search_cache_key(text)` → `str`; `stream_cache_key(url)` → `str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_music_sources.py`:

```python
"""Tests for how user input is classified and normalised before extraction."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_sources import (  # noqa: E402
    classify_input,
    format_duration,
    normalise_query,
    search_cache_key,
    spotify_to_query,
    stream_cache_key,
)


class ClassifyInputTests(unittest.TestCase):
    def test_plain_words_are_a_search(self):
        kind, platform, identifier = classify_input("bohemian rhapsody queen")
        self.assertEqual(kind, "search")
        self.assertIsNone(platform)
        self.assertEqual(identifier, "bohemian rhapsody queen")

    def test_youtube_watch_url_is_a_track(self):
        kind, platform, _ = classify_input("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual((kind, platform), ("track", "youtube"))

    def test_youtube_short_url_is_a_track(self):
        kind, platform, _ = classify_input("https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual((kind, platform), ("track", "youtube"))

    def test_youtube_list_url_is_a_playlist(self):
        kind, platform, _ = classify_input("https://www.youtube.com/playlist?list=PL123")
        self.assertEqual((kind, platform), ("playlist", "youtube"))

    def test_a_watch_url_carrying_a_list_still_plays_the_single_video(self):
        kind, platform, _ = classify_input("https://www.youtube.com/watch?v=abc&list=PL123")
        self.assertEqual((kind, platform), ("track", "youtube"))

    def test_soundcloud_url_is_a_track(self):
        kind, platform, _ = classify_input("https://soundcloud.com/artist/some-song")
        self.assertEqual((kind, platform), ("track", "soundcloud"))

    def test_soundcloud_sets_url_is_a_playlist(self):
        kind, platform, _ = classify_input("https://soundcloud.com/artist/sets/my-mix")
        self.assertEqual((kind, platform), ("playlist", "soundcloud"))

    def test_spotify_track_url_is_recognised_with_its_id(self):
        kind, platform, identifier = classify_input(
            "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
        )
        self.assertEqual((kind, platform), ("track", "spotify"))
        self.assertEqual(identifier, "4cOdK2wGLETKBW3PvgPWqT")

    def test_spotify_playlist_and_album_are_playlists(self):
        for path in ("playlist", "album"):
            kind, platform, _ = classify_input(f"https://open.spotify.com/{path}/abc123")
            self.assertEqual((kind, platform), ("playlist", "spotify"))

    def test_a_localised_spotify_link_still_parses(self):
        kind, platform, identifier = classify_input("https://open.spotify.com/intl-ro/track/abc123")
        self.assertEqual((kind, platform), ("track", "spotify"))
        self.assertEqual(identifier, "abc123")

    def test_query_string_after_a_spotify_link_is_ignored(self):
        _, _, identifier = classify_input("https://open.spotify.com/track/abc123?si=xyz")
        self.assertEqual(identifier, "abc123")

    def test_an_unknown_url_falls_back_to_search(self):
        kind, platform, _ = classify_input("https://example.com/whatever")
        self.assertEqual((kind, platform), ("search", None))

    def test_surrounding_whitespace_and_angle_brackets_are_stripped(self):
        kind, platform, _ = classify_input("  <https://youtu.be/dQw4w9WgXcQ>  ")
        self.assertEqual((kind, platform), ("track", "youtube"))

    def test_empty_input_is_an_empty_search(self):
        self.assertEqual(classify_input(""), ("search", None, ""))
        self.assertEqual(classify_input(None), ("search", None, ""))


class SpotifyQueryTests(unittest.TestCase):
    def test_artist_and_title_are_combined(self):
        self.assertEqual(
            spotify_to_query({"title": "Bohemian Rhapsody", "artist": "Queen"}),
            "Queen - Bohemian Rhapsody",
        )

    def test_a_missing_artist_leaves_just_the_title(self):
        self.assertEqual(spotify_to_query({"title": "Untitled"}), "Untitled")

    def test_empty_metadata_yields_an_empty_string(self):
        self.assertEqual(spotify_to_query({}), "")


class FormattingTests(unittest.TestCase):
    def test_durations_under_an_hour_are_minutes_and_seconds(self):
        self.assertEqual(format_duration(65), "1:05")
        self.assertEqual(format_duration(599), "9:59")

    def test_durations_over_an_hour_include_hours(self):
        self.assertEqual(format_duration(3600), "1:00:00")
        self.assertEqual(format_duration(3725), "1:02:05")

    def test_zero_renders_as_the_live_label_when_one_is_given(self):
        self.assertEqual(format_duration(0, live_label="LIVE"), "LIVE")

    def test_unknown_or_negative_durations_render_as_zero(self):
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(None), "0:00")
        self.assertEqual(format_duration(-5), "0:00")


class CacheKeyTests(unittest.TestCase):
    def test_queries_normalise_case_and_whitespace(self):
        self.assertEqual(normalise_query("  Bohemian   RHAPSODY "), "bohemian rhapsody")

    def test_equivalent_queries_share_a_cache_key(self):
        self.assertEqual(search_cache_key("Daft Punk"), search_cache_key("  daft   punk  "))

    def test_search_and_stream_keys_never_collide(self):
        self.assertNotEqual(search_cache_key("abc"), stream_cache_key("abc"))
        self.assertTrue(search_cache_key("abc").startswith("search:"))
        self.assertTrue(stream_cache_key("abc").startswith("stream:"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_music_sources.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.music_sources'`

- [ ] **Step 3: Write the implementation**

Create `core/music_sources.py`:

```python
"""Turning user input into playable tracks.

This module holds two very different halves. Everything above the extraction
section is pure string work with no I/O, so it is cheap to test exhaustively —
which matters, because misreading a link is the most common way a music
command surprises someone. The extraction half wraps yt-dlp.
"""

import re
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
}
SOUNDCLOUD_HOSTS = {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}
SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com"}

SPOTIFY_PATH = re.compile(r"^/(?:intl-[a-z]{2}/)?(track|playlist|album)/([A-Za-z0-9]+)")
URL_START = re.compile(r"^https?://", re.IGNORECASE)


def classify_input(text):
    """Decide what the user gave us.

    Returns ``(kind, platform, identifier)``. ``kind`` is "search", "track" or
    "playlist"; ``platform`` is "youtube", "soundcloud", "spotify" or None.
    Anything unrecognised degrades to a plain search rather than erroring — a
    stray URL is far more likely to be someone pasting a title than an attempt
    to break the bot.
    """
    cleaned = (text or "").strip().strip("<>").strip()
    if not URL_START.match(cleaned):
        return "search", None, cleaned

    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return "search", None, cleaned

    host = (parsed.netloc or "").lower()
    query = parse_qs(parsed.query or "")

    if host in YOUTUBE_HOSTS:
        # A watch URL that also carries `list` is someone playing one video
        # from a playlist; honour the video, not the whole list.
        if "list" in query and "v" not in query:
            return "playlist", "youtube", query["list"][0]
        return "track", "youtube", cleaned

    if host in SOUNDCLOUD_HOSTS:
        kind = "playlist" if "/sets/" in (parsed.path or "") else "track"
        return kind, "soundcloud", cleaned

    if host in SPOTIFY_HOSTS:
        match = SPOTIFY_PATH.match(parsed.path or "")
        if match:
            resource, identifier = match.group(1), match.group(2)
            return ("track" if resource == "track" else "playlist"), "spotify", identifier

    return "search", None, cleaned


def spotify_to_query(metadata):
    """Build the search terms that stand in for a Spotify track.

    Spotify permits no audio streaming to third-party apps, so a Spotify link
    can only ever name a song we then find elsewhere.
    """
    title = (metadata or {}).get("title") or ""
    artist = (metadata or {}).get("artist") or ""
    if artist and title:
        return f"{artist} - {title}"
    return title or artist or ""


def format_duration(seconds, live_label=None):
    """Render a track length. Zero renders as `live_label` when one is given,
    because a zero-length track from yt-dlp means a livestream."""
    total = int(seconds or 0)
    if total <= 0:
        return live_label if live_label else "0:00"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def normalise_query(text):
    """Fold a query so trivially different spellings share a cache entry."""
    return " ".join((text or "").lower().split())


def search_cache_key(text):
    return f"search:{normalise_query(text)}"


def stream_cache_key(url):
    return f"stream:{(url or '').strip()}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_music_sources.py -q`
Expected: PASS — 24 passed

- [ ] **Step 5: Commit**

```bash
git add core/music_sources.py tests/test_music_sources.py
git commit -m "Classify music input before any extraction happens

Link parsing, Spotify-to-query conversion and duration formatting, all
pure string work and so tested exhaustively — misreading a link is the
most common way a music command surprises someone. Unrecognised URLs
degrade to a search rather than erroring, because a stray link is far
more likely to be a pasted title than an attack.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Extraction layer and dependencies

**Files:**
- Modify: `core/music_sources.py` (append the extraction section)
- Modify: `requirements.txt`
- Test: `tests/test_music_extract.py`

**Interfaces:**
- Consumes: `classify_input`, `search_cache_key`, `spotify_to_query` from Task 3; `cache_get`, `cache_put` from Task 2; `Track` from Task 1.
- Produces: `track_from_entry(entry, requester_id, source)` → `Track`; `async extract(text, requester_id)` → `list[Track]`; `async refresh_stream_url(track)` → `bool`; `async resolve_spotify(kind, identifier)` → `list[dict]`; constants `EXTRACT_TIMEOUT_SECONDS = 20`, `SEARCH_TTL_SECONDS`, `STREAM_TTL_SECONDS`, `MAX_PLAYLIST_TRACKS = 100`.

- [ ] **Step 1: Write the failing test**

`track_from_entry` is the piece worth pinning: it is where yt-dlp's loosely-typed dictionaries become our `Track`, and where a missing field turns into a crash if unguarded.

Create `tests/test_music_extract.py`:

```python
"""Tests for converting yt-dlp entries into Track objects."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_sources import track_from_entry  # noqa: E402


class TrackFromEntryTests(unittest.TestCase):
    def test_a_full_entry_maps_every_field(self):
        track = track_from_entry(
            {
                "title": "Bohemian Rhapsody",
                "webpage_url": "https://youtu.be/fJ9rUzIMcZQ",
                "duration": 355,
                "thumbnail": "https://img.test/x.jpg",
                "uploader": "Queen Official",
                "url": "https://stream.test/audio",
            },
            requester_id="42",
            source="youtube",
        )
        self.assertEqual(track.title, "Bohemian Rhapsody")
        self.assertEqual(track.url, "https://youtu.be/fJ9rUzIMcZQ")
        self.assertEqual(track.duration, 355)
        self.assertEqual(track.uploader, "Queen Official")
        self.assertEqual(track.requester_id, "42")
        self.assertEqual(track.source, "youtube")
        self.assertEqual(track.stream_url, "https://stream.test/audio")

    def test_missing_optional_fields_do_not_raise(self):
        track = track_from_entry({"title": "Bare"}, requester_id="1", source="soundcloud")
        self.assertEqual(track.title, "Bare")
        self.assertEqual(track.duration, 0)
        self.assertIsNone(track.thumbnail)
        self.assertIsNone(track.uploader)

    def test_an_entirely_empty_entry_gets_a_readable_placeholder(self):
        track = track_from_entry({}, requester_id="1", source="youtube")
        self.assertEqual(track.title, "Unknown track")

    def test_a_none_entry_does_not_raise(self):
        track = track_from_entry(None, requester_id="1", source="youtube")
        self.assertEqual(track.title, "Unknown track")

    def test_a_null_duration_becomes_zero_rather_than_none(self):
        track = track_from_entry(
            {"title": "Live", "duration": None}, requester_id="1", source="youtube"
        )
        self.assertEqual(track.duration, 0)

    def test_the_page_url_is_preferred_over_the_expiring_stream_url(self):
        track = track_from_entry(
            {"title": "T", "webpage_url": "https://page.test/t", "url": "https://cdn.test/expiring"},
            requester_id="1",
            source="youtube",
        )
        self.assertEqual(track.url, "https://page.test/t")
        self.assertEqual(track.stream_url, "https://cdn.test/expiring")

    def test_the_requester_id_is_always_stored_as_a_string(self):
        track = track_from_entry({"title": "T"}, requester_id=42, source="youtube")
        self.assertEqual(track.requester_id, "42")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_music_extract.py -q`
Expected: FAIL — `ImportError: cannot import name 'track_from_entry'`

- [ ] **Step 3: Add the dependencies**

Append to `requirements.txt`:

```
# Music. yt-dlp resolves and streams YouTube/SoundCloud; PyNaCl is
# discord.py's voice encryption backend. yt-dlp breaks whenever YouTube
# changes something, so expect to bump it more often than the rest.
yt-dlp>=2026.7.0
PyNaCl>=1.5,<2
```

Install locally: `python3 -m pip install "yt-dlp>=2026.7.0" "PyNaCl>=1.5,<2"`

- [ ] **Step 4: Write the implementation**

Append to `core/music_sources.py`:

```python
# ── extraction ───────────────────────────────────────────────────────

import asyncio
import base64
import json
import logging
import os
import urllib.parse
import urllib.request

from .database import cache_get, cache_put
from .music_queue import Track

log = logging.getLogger("novaguard.music")

EXTRACT_TIMEOUT_SECONDS = 20
SEARCH_TTL_SECONDS = 7 * 86400
STREAM_TTL_SECONDS = 6 * 3600
MAX_PLAYLIST_TRACKS = 100
HTTP_TIMEOUT_SECONDS = 10

# `default_search` is deliberately unset: the search prefix is chosen in code
# so a query that happens to look like a URL cannot send yt-dlp somewhere
# unexpected.
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "extract_flat": False,
    "socket_timeout": 15,
    "retries": 1,
    "ignoreerrors": True,
    # IPv6-first resolution often stalls on small VPS hosts.
    "source_address": "0.0.0.0",
}


def track_from_entry(entry, requester_id, source):
    """Build a Track from one yt-dlp result.

    Defensive throughout: yt-dlp entries are loosely typed, and a field that
    is present for one extractor is absent or null for another. `url` holds an
    expiring CDN link, so `webpage_url` is preferred as the stable identity.
    """
    entry = entry or {}
    return Track(
        title=entry.get("title") or "Unknown track",
        url=entry.get("webpage_url") or entry.get("original_url") or entry.get("url") or "",
        duration=int(entry.get("duration") or 0),
        source=source,
        requester_id=str(requester_id),
        thumbnail=entry.get("thumbnail"),
        uploader=entry.get("uploader") or entry.get("channel"),
        stream_url=entry.get("url"),
    )


def _blocking_extract(target, flat=False):
    """Run yt-dlp. Called only through asyncio.to_thread."""
    import yt_dlp

    options = dict(YDL_OPTIONS)
    if flat:
        options["extract_flat"] = "in_playlist"
        options["noplaylist"] = False
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(target, download=False)


async def _extract(target, *, flat=False):
    """Extraction with the shared timeout, off the event loop.

    Returns None on any failure. This layer never raises: a dead link must not
    be able to take down a player loop.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_blocking_extract, target, flat),
            timeout=EXTRACT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning("Music extraction timed out for %s", target)
        return None
    except Exception as error:
        log.warning("Music extraction failed for %s: %r", target, error)
        return None


async def refresh_stream_url(track):
    """Re-resolve a track whose CDN link expired. Returns True on success."""
    if not track.url:
        return False
    info = await _extract(track.url)
    if not info:
        return False
    fresh = track_from_entry(info, track.requester_id, track.source)
    if not fresh.stream_url:
        return False
    track.stream_url = fresh.stream_url
    return True


async def extract(text, requester_id):
    """Resolve user input into playable tracks.

    Returns a list, empty when nothing could be resolved. Search results are
    cached for a week; the expiring stream link inside a cached entry is never
    trusted, so the player refreshes it before playing.
    """
    kind, platform, identifier = classify_input(text)

    if kind == "search" or platform == "spotify":
        return await _extract_by_search(kind, platform, identifier, requester_id)

    if kind == "playlist":
        target = identifier if platform == "youtube" else text
        info = await _extract(target, flat=True)
        entries = [e for e in ((info or {}).get("entries") or []) if e][:MAX_PLAYLIST_TRACKS]
        return [track_from_entry(entry, requester_id, platform) for entry in entries]

    info = await _extract(text)
    if not info:
        return []
    return [track_from_entry(info, requester_id, platform or "youtube")]


async def _extract_by_search(kind, platform, identifier, requester_id):
    """Search YouTube for a query, or for the song a Spotify link names."""
    if platform == "spotify":
        metadata = await resolve_spotify(kind, identifier)
        queries = [q for q in (spotify_to_query(item) for item in metadata) if q]
    else:
        queries = [identifier] if identifier else []

    tracks = []
    for query in queries[:MAX_PLAYLIST_TRACKS]:
        key = search_cache_key(query)
        cached = cache_get(key)
        if cached:
            tracks.append(track_from_entry(cached, requester_id, cached.get("_source") or "youtube"))
            continue
        info = await _extract(f"ytsearch1:{query}")
        entries = (info or {}).get("entries") or []
        if not entries or not entries[0]:
            continue
        entry = entries[0]
        cache_put(key, {**entry, "_source": "youtube"}, SEARCH_TTL_SECONDS)
        tracks.append(track_from_entry(entry, requester_id, "youtube"))
    return tracks


def _fetch_json(url, headers=None, data=None):
    """Blocking HTTP GET/POST returning parsed JSON. Only via to_thread."""
    request = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.load(response)


async def resolve_spotify(kind, identifier):
    """Metadata for a Spotify track or playlist, as ``[{"title", "artist"}]``.

    Degrades on purpose. Without credentials a single track still resolves
    through the public oEmbed endpoint; playlists and albums need the Web API
    and return nothing when it is unconfigured.
    """
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    has_credentials = bool(client_id and client_secret)

    if kind == "track" and not has_credentials:
        link = f"https://open.spotify.com/track/{identifier}"
        url = "https://open.spotify.com/oembed?url=" + urllib.parse.quote(link, safe="")
        try:
            oembed = await asyncio.to_thread(_fetch_json, url)
        except Exception as error:
            log.warning("Spotify oEmbed lookup failed: %r", error)
            return []
        return [{"title": oembed.get("title") or "", "artist": ""}]

    if not has_credentials:
        return []

    try:
        auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        token_payload = await asyncio.to_thread(
            _fetch_json,
            "https://accounts.spotify.com/api/token",
            {
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            b"grant_type=client_credentials",
        )
        token = token_payload.get("access_token")
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token}"}

        if kind == "track":
            data = await asyncio.to_thread(
                _fetch_json, f"https://api.spotify.com/v1/tracks/{identifier}", headers
            )
            items = [data]
        else:
            data = await asyncio.to_thread(
                _fetch_json,
                f"https://api.spotify.com/v1/playlists/{identifier}/tracks"
                f"?limit={MAX_PLAYLIST_TRACKS}",
                headers,
            )
            items = [row.get("track") for row in (data.get("items") or []) if row.get("track")]
    except Exception as error:
        log.warning("Spotify API lookup failed: %r", error)
        return []

    return [
        {
            "title": item.get("name") or "",
            "artist": ", ".join(a.get("name", "") for a in (item.get("artists") or [])),
        }
        for item in items
        if item
    ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_music_extract.py -q`
Expected: PASS — 7 passed

Run: `python3 -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/music_sources.py requirements.txt tests/test_music_extract.py
git commit -m "Add the yt-dlp extraction layer

Every extraction runs through asyncio.to_thread under a 20s ceiling and
returns None rather than raising, because a dead link must never take
down a player loop. track_from_entry is defensive throughout: yt-dlp
entries are loosely typed, and a field present for one extractor is null
for another.

Spotify degrades deliberately — a single track resolves through the
public oEmbed endpoint with no credentials, while playlists need the Web
API and simply return nothing when it is unconfigured.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Sessions and the cog skeleton

**Files:**
- Create: `core/music_session.py`
- Create: `cogs/music.py`
- Modify: `bot.py`
- Test: `tests/test_music_session.py`

**Interfaces:**
- Consumes: `MusicQueue` from Task 1.
- Produces: `configured_max_sessions()` → int; `MusicSession(guild_id)` with `guild_id`, `queue`, `volume`, `text_channel_id`, `card_message_id`, `voice_client`, `started_at`, `touch()`, `idle_seconds()`; `SessionRegistry(max_sessions=None)` with `get`, `create`, `drop`, `active_count`, `has_capacity`, `all_sessions`, `MAX_SESSIONS`; constant `IDLE_DISCONNECT_SECONDS = 300`; cog `Music` with `in_voice_with_bot(interaction, session)` helper and `/disconnect`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_music_session.py`:

```python
"""Tests for the session registry that enforces the concurrency cap."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_session import MusicSession, SessionRegistry  # noqa: E402


class SessionRegistryTests(unittest.TestCase):
    def test_a_new_registry_has_capacity_and_no_sessions(self):
        registry = SessionRegistry(max_sessions=3)
        self.assertEqual(registry.active_count(), 0)
        self.assertTrue(registry.has_capacity())

    def test_create_returns_a_session_bound_to_its_guild(self):
        registry = SessionRegistry(max_sessions=3)
        session = registry.create("123")
        self.assertIsInstance(session, MusicSession)
        self.assertEqual(session.guild_id, "123")
        self.assertIs(registry.get("123"), session)

    def test_a_guild_id_given_as_an_int_finds_the_same_session(self):
        registry = SessionRegistry(max_sessions=3)
        session = registry.create(123)
        self.assertIs(registry.get("123"), session)

    def test_creating_twice_for_one_guild_reuses_the_session(self):
        registry = SessionRegistry(max_sessions=3)
        first = registry.create("123")
        self.assertIs(registry.create("123"), first)
        self.assertEqual(registry.active_count(), 1)

    def test_capacity_runs_out_at_the_limit(self):
        registry = SessionRegistry(max_sessions=2)
        registry.create("1")
        registry.create("2")
        self.assertFalse(registry.has_capacity())
        self.assertEqual(registry.active_count(), 2)

    def test_an_existing_guild_is_served_even_at_the_cap(self):
        registry = SessionRegistry(max_sessions=1)
        registry.create("1")
        self.assertFalse(registry.has_capacity())
        self.assertIsNotNone(registry.create("1"))

    def test_drop_frees_capacity(self):
        registry = SessionRegistry(max_sessions=1)
        registry.create("1")
        registry.drop("1")
        self.assertTrue(registry.has_capacity())
        self.assertIsNone(registry.get("1"))

    def test_dropping_an_unknown_guild_is_harmless(self):
        registry = SessionRegistry(max_sessions=1)
        registry.drop("nope")
        self.assertEqual(registry.active_count(), 0)


class MusicSessionTests(unittest.TestCase):
    def test_a_fresh_session_starts_at_full_volume_with_an_empty_queue(self):
        session = MusicSession("1")
        self.assertEqual(session.volume, 100)
        self.assertTrue(session.queue.is_empty)
        self.assertIsNone(session.voice_client)

    def test_touch_resets_the_idle_clock(self):
        session = MusicSession("1")
        session._idle_since = 0.0
        self.assertGreater(session.idle_seconds(), 1000)
        session.touch()
        self.assertLess(session.idle_seconds(), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_music_session.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.music_session'`

- [ ] **Step 3: Write the session module**

Create `core/music_session.py`:

```python
"""Per-guild player state and the bot-wide concurrency cap.

Separate from the cog so the cap — the rule most likely to be wrong in a way
nobody notices until the VPS is on its knees — can be tested without Discord.
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
    """Everything one guild's player needs. Holds no discord.py types beyond
    the voice client the cog hands it."""

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

    A guild that already holds a session is always served, cap or not:
    refusing someone mid-playlist because a third server started playing would
    be worse than the load it saves.
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
```

- [ ] **Step 4: Write the cog skeleton**

Create `cogs/music.py`:

```python
"""🎵 Music category — playback from YouTube and SoundCloud with a button player."""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.music_session import IDLE_DISCONNECT_SECONDS, SessionRegistry
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, respond

IDLE_CHECK_SECONDS = 30


def in_voice_with_bot(interaction, session):
    """True when the caller may control this session.

    Anyone sharing the bot's voice channel may drive it; Manage Server
    overrides. Deliberately unconfigurable — every server wants this rule, and
    a setting for it would be one more thing to explain.
    """
    if interaction.user.guild_permissions.manage_guild:
        return True
    voice = getattr(interaction.user, "voice", None)
    if voice is None or voice.channel is None:
        return False
    client = session.voice_client if session else None
    return bool(client and client.channel and client.channel.id == voice.channel.id)


def not_in_voice_embed():
    embed = make_embed(
        "Join the voice channel first",
        "You have to be in my voice channel to control playback.",
        color=Palette.WARNING,
    )
    brand_footer(embed, "Music")
    return embed


def nothing_playing_embed(detail="There is nothing playing here."):
    embed = make_embed("Nothing playing", detail, color=Palette.WARNING)
    brand_footer(embed, "Music")
    return embed


class Music(commands.Cog):
    """Music playback with a queue and a button-driven player."""

    EMOJI = "🎵"
    COLOR = Palette.FUN
    DESCRIPTION = "Play music from YouTube and SoundCloud, with a queue and a button player."

    def __init__(self, bot):
        self.bot = bot
        self.sessions = SessionRegistry()
        # Strong references to in-flight prefetch tasks (Task 6). A bare
        # create_task can be garbage collected mid-flight.
        self._prefetch_tasks: set = set()

    async def cog_load(self):
        self.idle_watcher.start()

    async def cog_unload(self):
        self.idle_watcher.cancel()
        for session in self.sessions.all_sessions():
            await self._teardown(session)

    async def _teardown(self, session):
        """Disconnect and forget a session. Safe to call twice."""
        client = session.voice_client
        session.voice_client = None
        if client is not None:
            try:
                await client.disconnect(force=True)
            except Exception:
                pass
        self.sessions.drop(session.guild_id)

    @tasks.loop(seconds=IDLE_CHECK_SECONDS)
    async def idle_watcher(self):
        """Leave channels nobody is listening in.

        The whole sweep is wrapped: an exception here would stop the loop for
        the process lifetime and every session would linger forever — exactly
        how the voice-report tasks used to fail.
        """
        try:
            for session in self.sessions.all_sessions():
                client = session.voice_client
                if client is None or not client.is_connected():
                    await self._teardown(session)
                    continue
                humans = [m for m in client.channel.members if not m.bot] if client.channel else []
                playing = client.is_playing() or client.is_paused()
                if humans and playing:
                    session.touch()
                    continue
                if session.idle_seconds() >= IDLE_DISCONNECT_SECONDS:
                    await self._teardown(session)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Music idle watcher sweep failed, will retry: {error!r}")

    @idle_watcher.before_loop
    async def before_idle_watcher(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="disconnect", description="Stop the music and leave the voice channel")
    @app_commands.guild_only()
    async def disconnect(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None or session.voice_client is None:
            return await respond(
                interaction, nothing_playing_embed("I am not in a voice channel here."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        await self._teardown(session)
        embed = make_embed(
            "Disconnected", "Playback stopped and the queue was cleared.", color=Palette.SUCCESS
        )
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Music(bot))
```

- [ ] **Step 5: Register the cog**

In `bot.py`, add `"music",` to the `COGS` tuple after `"economy",`:

```python
    "economy",
    "music",
    "ai",
)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_music_session.py -q`
Expected: PASS — 10 passed

Run: `python3 -c "import bot; print('cogs', len(bot.COGS))"`
Expected: `cogs 17`

Run: `python3 -m pytest tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/music_session.py cogs/music.py bot.py tests/test_music_session.py
git commit -m "Add music sessions with a bot-wide concurrency cap

Session state and the cap live in core/ so the rule most likely to be
wrong in a way nobody notices — until the VPS is on its knees — can be
tested without Discord. A guild that already holds a session is always
served, because refusing someone mid-playlist would be worse than the
load it saves.

The idle watcher wraps its whole sweep: an exception there would stop
the loop for the process lifetime and leave every session connected
forever, which is exactly how the voice-report tasks used to fail.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Playback — `/play` and `/skip`

**Files:**
- Modify: `cogs/music.py`

**Interfaces:**
- Consumes: `extract`, `refresh_stream_url`, `format_duration` from Tasks 3–4; `SessionRegistry` from Task 5.
- Produces: `Music.FFMPEG_BEFORE`, `Music.MAX_CONSECUTIVE_SKIPS`, `Music._connect(interaction)` → `(session, error_embed)`, `Music._audio_source(track, volume)`, `Music._play_next(session)`, `Music._on_track_finished(session)`, `Music._schedule_prefetch(session)`, `Music._prefetch(track)`, `Music._notify(session, text)`, `Music._announce_track(session, track)`, commands `/play`, `/skip`. Requires `self._prefetch_tasks` from Task 5.

- [ ] **Step 1: Add the imports**

Add to the imports in `cogs/music.py`:

```python
from core.music_sources import extract, format_duration, refresh_stream_url
```

- [ ] **Step 2: Add the playback machinery**

Add to `Music`, before `disconnect`:

```python
    # Reconnect flags matter on a small VPS: without them a brief network
    # hiccup ends the track silently instead of resuming it.
    FFMPEG_BEFORE = (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-nostdin -loglevel warning"
    )
    MAX_CONSECUTIVE_SKIPS = 5

    async def _connect(self, interaction):
        """Join the caller's voice channel, honouring the session cap.

        Returns ``(session, error_embed)``; exactly one is None.
        """
        voice = getattr(interaction.user, "voice", None)
        if voice is None or voice.channel is None:
            embed = make_embed(
                "Join a voice channel first",
                "Hop into a voice channel and run the command again.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Music")
            return None, embed

        existing = self.sessions.get(interaction.guild_id)
        if existing is None and not self.sessions.has_capacity():
            embed = make_embed(
                "All music slots are busy",
                f"I can play in `{self.sessions.MAX_SESSIONS}` servers at once and they are all "
                "in use right now. Try again in a few minutes.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Music")
            return None, embed

        session = self.sessions.create(interaction.guild_id)
        session.text_channel_id = interaction.channel_id
        session.touch()

        client = session.voice_client
        try:
            if client is None or not client.is_connected():
                session.voice_client = await voice.channel.connect(self_deaf=True, timeout=20)
            elif client.channel.id != voice.channel.id:
                await client.move_to(voice.channel)
        except (discord.ClientException, asyncio.TimeoutError, discord.HTTPException) as error:
            print(f"Music connect failed in guild {interaction.guild_id}: {error!r}")
            await self._teardown(session)
            embed = make_embed(
                "Could not join",
                "Check that I can view and connect to that voice channel.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Music")
            return None, embed

        return session, None

    async def _audio_source(self, track, volume):
        """Build the audio source, refreshing an expired link once if needed.

        Volume control and stream-copy are mutually exclusive, so the path is
        chosen per track. At 100% — the default and overwhelmingly the common
        case — FFmpegOpusAudio.from_probe copies YouTube's webm/opus straight
        through and costs almost no CPU. The moment someone actually lowers the
        volume the audio has to be decoded to PCM, scaled, and re-encoded; that
        is the price of the feature, and it is only paid by sessions that use
        it. Anything but Opus (SoundCloud mp3) is transcoded either way.
        """
        if not track.stream_url and not await refresh_stream_url(track):
            return None

        for attempt in (1, 2):
            try:
                if volume >= 100:
                    return await discord.FFmpegOpusAudio.from_probe(
                        track.stream_url, before_options=self.FFMPEG_BEFORE, options="-vn"
                    )
                pcm = discord.FFmpegPCMAudio(
                    track.stream_url, before_options=self.FFMPEG_BEFORE, options="-vn"
                )
                return discord.PCMVolumeTransformer(pcm, volume=volume / 100)
            except Exception as error:
                if attempt == 2 or not await refresh_stream_url(track):
                    print(f"Music source failed for {track.url}: {error!r}")
                    return None
        return None

    async def _play_next(self, session):
        """Advance the queue and start the next track.

        Failures skip forward rather than stopping: one unplayable track must
        never end the session.
        """
        client = session.voice_client
        if client is None or not client.is_connected():
            await self._teardown(session)
            return

        for _ in range(self.MAX_CONSECUTIVE_SKIPS):
            track = session.queue.advance()
            if track is None:
                session.started_at = None
                session.touch()
                await self.refresh_card(session)
                return

            source = await self._audio_source(track, session.volume)
            if source is None:
                await self._notify(session, f"Skipped **{track.title}** — it could not be played.")
                continue

            def after_playing(error, session=session):
                if error:
                    print(f"Music playback error in guild {session.guild_id}: {error!r}")
                self.bot.loop.create_task(self._on_track_finished(session))

            try:
                client.play(source, after=after_playing)
            except discord.ClientException as error:
                print(f"Music play call failed in guild {session.guild_id}: {error!r}")
                continue

            session.touch()
            await self._announce_track(session, track)
            self._schedule_prefetch(session)
            return

        await self._notify(session, "Too many tracks in a row failed. Stopping here.")

    def _schedule_prefetch(self, session):
        """Resolve the next track's stream link while this one plays.

        Extraction takes one to three seconds; done at the moment a track ends
        it becomes an audible gap. A strong reference is kept because a bare
        create_task can be garbage collected mid-flight.
        """
        upcoming = session.queue.upcoming
        if not upcoming or upcoming[0].stream_url:
            return
        task = self.bot.loop.create_task(self._prefetch(upcoming[0]))
        self._prefetch_tasks.add(task)
        task.add_done_callback(self._prefetch_tasks.discard)

    async def _prefetch(self, track):
        """Best-effort warm-up. A failure here costs nothing: the player
        resolves the link again when it actually reaches the track."""
        try:
            await refresh_stream_url(track)
        except Exception as error:
            print(f"Music prefetch skipped for {track.url}: {error!r}")

    async def _on_track_finished(self, session):
        """Chain to the next track. Wrapped so a failure cannot kill the chain
        silently and strand the session connected but idle."""
        try:
            await self._play_next(session)
        except Exception as error:
            print(f"Music advance failed in guild {session.guild_id}: {error!r}")
            session.touch()

    async def _notify(self, session, text):
        channel = self.bot.get_channel(session.text_channel_id) if session.text_channel_id else None
        if channel is None:
            return
        try:
            await channel.send(text)
        except discord.HTTPException:
            pass

    async def _announce_track(self, session, track):
        """Placeholder replaced by the player card in Task 7."""
        import time

        session.started_at = time.monotonic()
        await self._notify(
            session, f"▶️ Now playing **{track.title}** `{format_duration(track.duration)}`"
        )

    async def refresh_card(self, session, interaction=None):
        """Placeholder replaced by the player card in Task 7."""
        return
```

- [ ] **Step 3: Add the commands**

Add to `Music`, after `refresh_card`:

```python
    @app_commands.command(name="play", description="Play a song from a link or a search")
    @app_commands.describe(query="A YouTube/SoundCloud/Spotify link, or words to search for")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str):
        await defer_interaction(interaction, thinking=True)

        session, error = await self._connect(interaction)
        if error is not None:
            return await respond(interaction, error, ephemeral=True)

        tracks = await extract(query, interaction.user.id)
        if not tracks:
            embed = make_embed(
                "Nothing found", f"I could not find anything for `{query[:120]}`.", color=Palette.WARNING
            )
            brand_footer(embed, "Music")
            return await respond(interaction, embed, ephemeral=True)

        accepted = session.queue.add_many(tracks)
        session.touch()

        client = session.voice_client
        was_idle = not (client.is_playing() or client.is_paused())
        if was_idle:
            await self._play_next(session)

        first = tracks[0]
        if accepted == 1:
            title = "Playing now" if was_idle else "Added to the queue"
            description = f"**{first.title}** `{format_duration(first.duration)}`"
        else:
            title = "Playlist added"
            description = f"Queued `{accepted}` tracks, starting with **{first.title}**."
        embed = make_embed(title, description, color=Palette.FUN)
        if first.thumbnail:
            embed.set_thumbnail(url=first.thumbnail)
        brand_footer(embed, "Music")
        await respond(interaction, embed)

    @app_commands.command(name="skip", description="Skip the current track")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None or session.voice_client is None:
            return await respond(
                interaction, nothing_playing_embed("There is nothing to skip."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        current = session.queue.current
        session.voice_client.stop()  # fires `after`, which chains onward
        session.touch()
        embed = make_embed(
            "Skipped",
            f"**{current.title}** was skipped." if current else "Moving on.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)
```

- [ ] **Step 4: Verify**

Run: `python3 -m compileall -q cogs/music.py core/music_session.py core/music_sources.py`
Expected: no output

Run: `python3 -m pytest tests -q`
Expected: PASS

- [ ] **Step 5: Manual smoke test**

Needs `ffmpeg` installed and the bot running. In Discord: join a voice channel, run `/play never gonna give you up`, confirm audio starts, then `/skip`, then `/disconnect`.

- [ ] **Step 6: Commit**

```bash
git add cogs/music.py
git commit -m "Play and skip tracks

FFmpegOpusAudio.from_probe picks stream-copy when the source is already
Opus, which YouTube's webm/opus is, so the common path costs almost no
CPU on the VPS. The reconnect flags matter there too: without them a
brief network hiccup ends a track silently instead of resuming it.

Playback skips forward through a short run of dead tracks rather than
stopping, and the after-callback chain is wrapped so a failure cannot
strand a session connected but idle.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Player card and buttons

**Files:**
- Create: `core/music_card.py`
- Modify: `cogs/music.py` (replace the two placeholders from Task 6)
- Test: `tests/test_music_card.py`

**Interfaces:**
- Consumes: `LoopMode` from Task 1; `format_duration` from Task 3.
- Produces: `progress_bar(elapsed, total, slots=14)` → `str`; `card_fields(*, current, upcoming, elapsed, volume, loop, paused)` → dict with keys `title`, `description`, `progress`, `footer`, `next_up`; `MusicControls(cog)` view; `Music.build_card(session)`, real `Music.refresh_card`, real `Music._announce_track`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_music_card.py`:

```python
"""Tests for rendering the player card."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_card import card_fields, progress_bar  # noqa: E402
from core.music_queue import LoopMode, Track  # noqa: E402


def track(title="Song", duration=200):
    return Track(
        title=title,
        url="https://example.test/x",
        duration=duration,
        source="youtube",
        requester_id="7",
        uploader="Uploader",
    )


def fields(**overrides):
    base = dict(
        current=track(), upcoming=[], elapsed=0,
        volume=100, loop=LoopMode.OFF, paused=False,
    )
    base.update(overrides)
    return card_fields(**base)


class ProgressBarTests(unittest.TestCase):
    def test_the_bar_is_always_the_requested_width(self):
        for elapsed in (0, 50, 200, 5000):
            self.assertEqual(len(progress_bar(elapsed, 200, slots=12)), 12)

    def test_an_unknown_total_renders_an_empty_bar(self):
        self.assertEqual(len(progress_bar(30, 0, slots=10)), 10)

    def test_progress_never_overflows_past_the_end(self):
        self.assertEqual(len(progress_bar(999, 100, slots=10)), 10)


class CardFieldsTests(unittest.TestCase):
    def test_the_title_and_uploader_reach_the_card(self):
        result = fields(current=track("Bohemian Rhapsody"))
        self.assertIn("Bohemian Rhapsody", result["description"])
        self.assertIn("Uploader", result["description"])

    def test_an_idle_session_says_so_instead_of_crashing(self):
        result = fields(current=None)
        self.assertIn("Nothing playing", result["title"])
        self.assertEqual(result["next_up"], "The queue is empty.")

    def test_paused_state_is_visible_in_the_title(self):
        self.assertIn("Paused", fields(paused=True)["title"])

    def test_next_up_lists_the_queue_and_counts_the_remainder(self):
        result = fields(current=track("Current"), upcoming=[track(f"Song {i}") for i in range(8)])
        self.assertIn("Song 0", result["next_up"])
        self.assertIn("more", result["next_up"])

    def test_a_short_queue_is_listed_without_a_remainder(self):
        result = fields(upcoming=[track("Only One")])
        self.assertIn("Only One", result["next_up"])
        self.assertNotIn("more", result["next_up"])

    def test_an_empty_queue_after_the_current_track_says_so(self):
        self.assertIn("Nothing queued", fields()["next_up"])

    def test_the_footer_reports_volume_and_loop_mode(self):
        result = fields(volume=40, loop=LoopMode.QUEUE)
        self.assertIn("40%", result["footer"])
        self.assertIn("queue", result["footer"].lower())

    def test_a_livestream_shows_LIVE_rather_than_a_zero_length(self):
        self.assertIn("LIVE", fields(current=track(duration=0))["progress"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_music_card.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.music_card'`

- [ ] **Step 3: Write the card renderer**

Create `core/music_card.py`:

```python
"""Rendering the player card.

A pure function over a snapshot, with no discord.py import, so every state the
card can be in is cheap to assert — including the idle one, where a card
renderer usually crashes first.

The card is redrawn on state change only, never on a timer, so the bar is
computed at render time rather than polled.
"""

from .music_queue import LoopMode
from .music_sources import format_duration

FILLED = "▰"
EMPTY = "▬"
NEXT_UP_LIMIT = 5

LOOP_LABELS = {
    LoopMode.OFF: "loop off",
    LoopMode.TRACK: "looping track",
    LoopMode.QUEUE: "looping queue",
}


def progress_bar(elapsed, total, slots=14):
    if total <= 0:
        return EMPTY * slots
    ratio = min(max(elapsed / total, 0), 1)
    filled = round(ratio * slots)
    return FILLED * filled + EMPTY * (slots - filled)


def card_fields(*, current, upcoming, elapsed, volume, loop, paused):
    """Everything the embed needs, as plain strings."""
    footer = f"Volume {volume}% • {LOOP_LABELS.get(loop, 'loop off')}"

    if current is None:
        return {
            "title": "🎵 Nothing playing",
            "description": "Use `/play` with a link or a search to start.",
            "progress": progress_bar(0, 0),
            "footer": footer,
            "next_up": "The queue is empty.",
        }

    uploader = f"\n{current.uploader}" if current.uploader else ""
    bar = progress_bar(elapsed, current.duration)
    timing = (
        f"`{format_duration(elapsed)} / "
        f"{format_duration(current.duration, live_label='LIVE')}`"
    )

    if upcoming:
        lines = [f"`{i}.` {t.title}" for i, t in enumerate(upcoming[:NEXT_UP_LIMIT], start=1)]
        remainder = len(upcoming) - NEXT_UP_LIMIT
        if remainder > 0:
            lines.append(f"…and `{remainder}` more")
        next_up = "\n".join(lines)
    else:
        next_up = "Nothing queued after this."

    return {
        "title": "⏸️ Paused" if paused else "🎵 Now playing",
        "description": f"**[{current.title}]({current.url})**{uploader}",
        "progress": f"{bar} {timing}",
        "footer": footer,
        "next_up": next_up,
    }
```

- [ ] **Step 4: Run the card tests**

Run: `python3 -m pytest tests/test_music_card.py -q`
Expected: PASS — 12 passed

- [ ] **Step 5: Add the buttons**

Add to `cogs/music.py` imports:

```python
from core.music_card import card_fields
from core.music_queue import LoopMode
```

Add above `class Music`:

```python
class MusicControls(discord.ui.View):
    """The player buttons.

    The spec called for DynamicItem, as giveaways and tickets use. A plain
    persistent view is the right tool here instead: DynamicItem exists to
    encode per-message state in the custom id, and these buttons carry none —
    they resolve their session by guild on every press. Fixed custom ids plus
    `bot.add_view` in cog_load give the same restart survival with less
    machinery, so a card left over from before a restart still answers
    plainly, with "this session has ended", instead of looking broken.
    """

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def _session_or_refusal(self, interaction):
        session = self.cog.sessions.get(interaction.guild_id)
        if session is None or session.voice_client is None:
            await interaction.response.send_message("This session has ended.", ephemeral=True)
            return None
        if not in_voice_with_bot(interaction, session):
            await interaction.response.send_message(
                "You have to be in my voice channel to control playback.", ephemeral=True
            )
            return None
        return session

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary, custom_id="ng:music:toggle")
    async def toggle(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        client = session.voice_client
        if client.is_paused():
            client.resume()
        else:
            client.pause()
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="ng:music:skip")
    async def skip_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.voice_client.stop()
        session.touch()
        await interaction.response.defer()

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="ng:music:stop")
    async def stop_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        await self.cog._teardown(session)
        await interaction.response.edit_message(content="Playback stopped.", embed=None, view=None)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="ng:music:shuffle")
    async def shuffle_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.queue.shuffle()
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="ng:music:loop")
    async def loop_button(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.queue.set_loop(LoopMode.next_mode(session.queue.loop))
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=1, custom_id="ng:music:voldown")
    async def volume_down(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.volume = max(0, session.volume - 10)
        session.touch()
        await self.cog.refresh_card(session, interaction)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=1, custom_id="ng:music:volup")
    async def volume_up(self, interaction, button):
        session = await self._session_or_refusal(interaction)
        if session is None:
            return
        session.volume = min(100, session.volume + 10)
        session.touch()
        await self.cog.refresh_card(session, interaction)
```

- [ ] **Step 6: Replace the placeholders**

In `cogs/music.py`, replace the placeholder `_announce_track` and `refresh_card` from Task 6 with:

```python
    def build_card(self, session):
        import time

        elapsed = int(time.monotonic() - session.started_at) if session.started_at else 0
        client = session.voice_client
        fields = card_fields(
            current=session.queue.current,
            upcoming=session.queue.upcoming,
            elapsed=elapsed,
            volume=session.volume,
            loop=session.queue.loop,
            paused=bool(client and client.is_paused()),
        )
        embed = make_embed(fields["title"], fields["description"], color=Palette.FUN)
        current = session.queue.current
        if current and current.thumbnail:
            embed.set_thumbnail(url=current.thumbnail)
        embed.add_field(name="Progress", value=fields["progress"], inline=False)
        embed.add_field(name="Next up", value=fields["next_up"], inline=False)
        brand_footer(embed, fields["footer"])
        return embed

    async def refresh_card(self, session, interaction=None):
        """Redraw the card in place. Called on state change only."""
        embed = self.build_card(session)
        if interaction is not None:
            try:
                await interaction.response.edit_message(embed=embed, view=MusicControls(self))
            except discord.HTTPException:
                pass
            return
        if session.text_channel_id is None or session.card_message_id is None:
            return
        channel = self.bot.get_channel(session.text_channel_id)
        if channel is None:
            return
        try:
            message = await channel.fetch_message(session.card_message_id)
            await message.edit(embed=embed, view=MusicControls(self))
        except discord.HTTPException:
            pass

    async def _announce_track(self, session, track):
        """Post a fresh card, deleting the previous one so the channel keeps
        exactly one player rather than a wall of stale embeds."""
        import time

        session.started_at = time.monotonic()
        channel = self.bot.get_channel(session.text_channel_id) if session.text_channel_id else None
        if channel is None:
            return

        if session.card_message_id is not None:
            try:
                old = await channel.fetch_message(session.card_message_id)
                await old.delete()
            except discord.HTTPException:
                pass
            session.card_message_id = None

        try:
            message = await channel.send(embed=self.build_card(session), view=MusicControls(self))
            session.card_message_id = message.id
        except discord.HTTPException as error:
            print(f"Music card could not be posted in guild {session.guild_id}: {error!r}")
```

Register the persistent view in `cog_load`, before `self.idle_watcher.start()`:

```python
        self.bot.add_view(MusicControls(self))
```

- [ ] **Step 7: Verify**

Run: `python3 -m compileall -q cogs/music.py core/music_card.py`
Expected: no output

Run: `python3 -m pytest tests -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add core/music_card.py cogs/music.py tests/test_music_card.py
git commit -m "Add the player card and its buttons

The card renders from a pure snapshot function with no discord.py
import, so every state it can be in is cheap to assert — including the
idle one, where a card renderer usually crashes first.

It is redrawn on state change only, never on a timer: a ticking progress
bar would spend one edit every few seconds per session on nothing, so
the bar is computed at render time and is correct whenever it is read.
Buttons carry fixed custom ids and resolve their session by guild, so a
card from before a restart answers plainly instead of looking broken.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Queue commands and autocomplete

**Files:**
- Modify: `cogs/music.py`

**Interfaces:**
- Consumes: `cache_prefix_search` from Task 2; `normalise_query` from Task 3; `build_card`, `MusicControls`, `refresh_card` from Task 7.
- Produces: commands `/queue`, `/nowplaying`, `/volume`, `/remove`, `/clear`; autocomplete handlers `play_autocomplete`, `remove_autocomplete`.

- [ ] **Step 1: Add the imports**

Add to `cogs/music.py`:

```python
from core.database import cache_prefix_search
from core.music_sources import normalise_query
```

- [ ] **Step 2: Add the autocomplete handlers**

Add to `Music`, before the `/play` command (they must be defined above the decorator that references them):

```python
    async def play_autocomplete(self, interaction: discord.Interaction, current: str):
        """Suggestions from the cache only.

        Discord allows three seconds here and a yt-dlp search needs one to
        three, so searching live would be both slow and a way to hammer the
        VPS on every keystroke. With nothing cached we say so plainly rather
        than appearing broken.
        """
        text = (current or "").strip()
        if not text:
            return []
        try:
            rows = await asyncio.to_thread(
                cache_prefix_search, f"search:{normalise_query(text)}", 20
            )
        except Exception:
            rows = []

        choices = []
        for _, payload in rows:
            title = (payload or {}).get("title")
            if not title:
                continue
            choices.append(app_commands.Choice(name=title[:100], value=title[:100]))
            if len(choices) == 24:
                break
        if not choices:
            return [app_commands.Choice(name=f"Press Enter to search “{text}”"[:100], value=text[:100])]
        return choices

    async def remove_autocomplete(self, interaction: discord.Interaction, current: str):
        session = self.sessions.get(interaction.guild_id)
        if session is None:
            return []
        text = (current or "").lower()
        choices = []
        for position, track in enumerate(session.queue.upcoming[:25], start=1):
            label = f"{position}. {track.title}"[:100]
            if text and text not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label, value=position))
        return choices[:25]
```

- [ ] **Step 3: Attach autocomplete to `/play`**

Add this decorator directly above the existing `async def play` (below its other decorators):

```python
    @app_commands.autocomplete(query=play_autocomplete)
```

- [ ] **Step 4: Add the queue commands**

Add to `Music`, after `skip`:

```python
    @app_commands.command(name="queue", description="Show what is playing and what comes next")
    @app_commands.guild_only()
    async def queue_command(self, interaction: discord.Interaction):
        await defer_interaction(interaction)
        session = self.sessions.get(interaction.guild_id)
        if session is None or session.queue.current is None:
            return await respond(
                interaction, nothing_playing_embed("Use `/play` to start."), ephemeral=True
            )
        await respond(interaction, self.build_card(session), view=MusicControls(self))

    @app_commands.command(name="nowplaying", description="Show the player card")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction):
        await self.queue_command.callback(self, interaction)

    @app_commands.command(name="volume", description="Set playback volume (0-100)")
    @app_commands.describe(level="Volume percentage")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None or session.voice_client is None:
            return await respond(
                interaction, nothing_playing_embed("There is nothing to adjust."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        session.volume = level
        session.touch()
        await self.refresh_card(session)
        # The audio source is built when a track starts, so a mid-track change
        # lands on the next one. Say so rather than letting it read as a bug.
        embed = make_embed(
            "Volume set",
            f"Playback volume is now `{level}%`. It applies from the next track.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="remove", description="Remove a track from the queue")
    @app_commands.describe(position="Which queued track to remove")
    @app_commands.autocomplete(position=remove_autocomplete)
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, position: int):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None:
            return await respond(
                interaction, nothing_playing_embed("There is nothing to remove."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        removed = session.queue.remove(position)
        if removed is None:
            embed = make_embed(
                "Not in the queue", f"There is no track at position `{position}`.", color=Palette.WARNING
            )
        else:
            embed = make_embed("Removed", f"**{removed.title}** left the queue.", color=Palette.SUCCESS)
            await self.refresh_card(session)
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="clear", description="Clear the queue without stopping the current track")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if session is None:
            return await respond(
                interaction, nothing_playing_embed("The queue is already empty."), ephemeral=True
            )
        if not in_voice_with_bot(interaction, session):
            return await respond(interaction, not_in_voice_embed(), ephemeral=True)

        removed = len(session.queue.upcoming)
        session.queue.clear()
        session.touch()
        await self.refresh_card(session)
        embed = make_embed(
            "Queue cleared", f"Removed `{removed}` queued track(s).", color=Palette.SUCCESS
        )
        brand_footer(embed, "Music")
        await respond(interaction, embed, ephemeral=True)
```

- [ ] **Step 5: Verify**

Run: `python3 -m compileall -q cogs/music.py`
Expected: no output

Run: `python3 -c "import bot; print('ok')"`
Expected: `ok`

Run: `python3 -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add cogs/music.py
git commit -m "Add queue commands and cache-backed autocomplete

Autocomplete answers only from the cache. Discord allows three seconds
and a yt-dlp search needs one to three, so searching live would be both
slow and a way to hammer the VPS on every keystroke; with nothing cached
it offers a single honest entry instead of appearing broken.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Documentation and the voice-report boundary

**Files:**
- Modify: `.env.example`, `README.md`, `SETUP.md`
- Test: `tests/test_music_regression.py`

**Interfaces:**
- Consumes: `configured_max_sessions`, `SessionRegistry` from Task 5.
- Produces: documentation, plus one regression test.

- [ ] **Step 1: Write the regression test**

Create `tests/test_music_regression.py`:

```python
"""Boundary between the music player and the voice attendance reports."""

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cogs.voice as voice_cog  # noqa: E402
from core.music_session import SessionRegistry, configured_max_sessions  # noqa: E402


class VoiceReportBoundaryTests(unittest.TestCase):
    def test_voice_reports_still_ignore_bots(self):
        """The music player joins voice channels constantly while the
        attendance tracker watches the same events. If that filter ever goes
        away, every music session becomes a phantom participant in the
        reports."""
        source = inspect.getsource(voice_cog.VoiceReports.on_voice_state_update)
        self.assertIn("member.bot", source)


class SessionCapTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("MUSIC_MAX_SESSIONS", None)

    def tearDown(self):
        os.environ.pop("MUSIC_MAX_SESSIONS", None)
        if self._saved is not None:
            os.environ["MUSIC_MAX_SESSIONS"] = self._saved

    def test_the_cap_falls_back_to_the_default_when_unset(self):
        self.assertEqual(configured_max_sessions(), 3)

    def test_a_nonsense_cap_falls_back_rather_than_crashing_at_import(self):
        os.environ["MUSIC_MAX_SESSIONS"] = "banana"
        self.assertEqual(configured_max_sessions(), 3)

    def test_the_cap_is_never_below_one(self):
        os.environ["MUSIC_MAX_SESSIONS"] = "0"
        self.assertEqual(configured_max_sessions(), 1)

    def test_a_configured_cap_is_honoured(self):
        os.environ["MUSIC_MAX_SESSIONS"] = "5"
        self.assertEqual(SessionRegistry().MAX_SESSIONS, 5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

Run: `python3 -m pytest tests/test_music_regression.py -q`
Expected: PASS — 5 passed

- [ ] **Step 3: Document the settings**

Append to `.env.example`:

```
# Music
# How many servers may play audio at once. Raise only if the host has CPU to
# spare: SoundCloud needs transcoding, YouTube usually does not.
MUSIC_MAX_SESSIONS=3
# Optional. Without these, Spotify track links still resolve through the
# public oEmbed endpoint; with them, playlists and albums work too.
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
```

- [ ] **Step 4: Document the feature**

Add a row to the command-categories table in `README.md`:

```markdown
| 🎵 **Music** | `/play` `/skip` `/queue` `/nowplaying` `/volume` `/remove` `/clear` `/disconnect` | Play from YouTube and SoundCloud with a button-driven player. Spotify links are resolved to a track and found on those sources — Spotify permits no direct streaming. |
```

Add to `SETUP.md`, under the installation steps:

````markdown
### Music (optional)

Music playback needs FFmpeg on the host:

```bash
sudo apt install -y ffmpeg
```

`MUSIC_MAX_SESSIONS` caps how many servers can play at once (default `3`).
The limit exists for CPU, not RAM: YouTube streams are copied without
re-encoding, while SoundCloud has to be transcoded.

Spotify credentials are optional. Without them a Spotify *track* link still
works; with them, playlists and albums do too. `yt-dlp` breaks whenever
YouTube changes something, so bump it when playback starts failing:

```bash
./venv/bin/pip install --upgrade yt-dlp
```
````

- [ ] **Step 5: Full verification**

Run: `python3 -m pytest tests -q`
Expected: PASS

Run every test standalone, the way the VPS does:
```bash
for f in tests/test_*.py; do python3 "$f" >/dev/null 2>&1 && echo "OK   $f" || echo "FAIL $f"; done
```
Expected: every line `OK`

- [ ] **Step 6: Commit**

```bash
git add tests/test_music_regression.py .env.example README.md SETUP.md
git commit -m "Document the music system and pin the voice-report boundary

The music player joins voice channels constantly while the attendance
tracker watches the same events. It filters bots today; the regression
test makes sure it keeps doing so, because otherwise every music session
would appear as a phantom participant in the reports.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Deploy**

On the VPS:

```bash
cd ~/NovaGuard && sudo apt install -y ffmpeg && git pull --ff-only && ./venv/bin/pip install -r requirements.txt && ./venv/bin/python -m py_compile bot.py core/*.py cogs/*.py && for f in tests/test_*.py; do ./venv/bin/python "$f" >/dev/null && echo "OK   $f" || echo "FAIL $f"; done && pm2 restart 0 --update-env && pm2 save
```

Then in Discord: join a voice channel, run `/play bohemian rhapsody`, confirm
the card appears with working buttons, and check `/doctor` still reports clean.
