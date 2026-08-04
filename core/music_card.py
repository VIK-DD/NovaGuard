"""Rendering the player card.

A pure function over a snapshot, with no discord.py import, so every state the
card can be in is cheap to assert, including the idle one.

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
        lines = [f"`{i}.` {track.title}" for i, track in enumerate(upcoming[:NEXT_UP_LIMIT], start=1)]
        remainder = len(upcoming) - NEXT_UP_LIMIT
        if remainder > 0:
            lines.append(f"...and `{remainder}` more")
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
