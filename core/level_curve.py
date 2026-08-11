"""The single XP curve used by Discord commands and the web dashboard."""

MAX_LEVEL = 169
BASE_LEVEL_XP = 118
LEVEL_XP_GROWTH = 12


def xp_needed(level):
    """XP needed to advance from ``level`` to the next level."""
    current = max(int(level or 0), 0)
    if current >= MAX_LEVEL:
        return 0
    return BASE_LEVEL_XP + current * LEVEL_XP_GROWTH


def total_xp_for_level(level):
    """Cumulative XP at the exact start of ``level``."""
    target = min(max(int(level or 0), 0), MAX_LEVEL)
    return target * BASE_LEVEL_XP + LEVEL_XP_GROWTH * target * (target - 1) // 2


def level_from_xp(total_xp):
    """Return ``(level, progress_inside_level)`` for cumulative XP."""
    total = max(int(total_xp or 0), 0)
    if total >= total_xp_for_level(MAX_LEVEL):
        return MAX_LEVEL, 0

    # The cap is deliberately small, so a binary search is clearer and less
    # error-prone at exact boundaries than rearranging the quadratic formula.
    low, high = 0, MAX_LEVEL
    while low < high:
        middle = (low + high + 1) // 2
        if total_xp_for_level(middle) <= total:
            low = middle
        else:
            high = middle - 1
    return low, total - total_xp_for_level(low)
