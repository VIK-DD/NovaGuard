"""Shared, bounded per-guild rules for both NovaGuard music backends."""

MUSIC_DEFAULTS = {
    "enabled": True,
    "default_volume": 80,
    "max_volume": 100,
    "max_queue_tracks": 100,
    "allow_playlists": True,
    "allow_filters": True,
}

_BOOL_KEYS = ("enabled", "allow_playlists", "allow_filters")
_INT_RANGES = {
    "default_volume": (0, 100),
    "max_volume": (10, 100),
    "max_queue_tracks": (1, 500),
}


def resolve_music(settings):
    saved = settings.get("music") if isinstance(settings, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    resolved = dict(MUSIC_DEFAULTS)
    for key in _BOOL_KEYS:
        if isinstance(saved.get(key), bool):
            resolved[key] = saved[key]
    for key, (minimum, maximum) in _INT_RANGES.items():
        value = saved.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            resolved[key] = min(max(value, minimum), maximum)
    resolved["default_volume"] = min(
        resolved["default_volume"], resolved["max_volume"]
    )
    return resolved


def validate_music(patch, current):
    if not isinstance(patch, dict):
        return None, ["music: must be an object"]

    unknown = sorted(set(patch) - set(MUSIC_DEFAULTS))
    errors = [f"music.{key}: unknown setting" for key in unknown]
    merged = {**resolve_music({"music": current}), **patch}

    for key in _BOOL_KEYS:
        if not isinstance(merged.get(key), bool):
            errors.append(f"music.{key}: must be true or false")
    for key, (minimum, maximum) in _INT_RANGES.items():
        value = merged.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            errors.append(
                f"music.{key}: must be a whole number from {minimum} to {maximum}"
            )
    if (
        isinstance(merged.get("default_volume"), int)
        and isinstance(merged.get("max_volume"), int)
        and merged["default_volume"] > merged["max_volume"]
    ):
        errors.append("music.default_volume: cannot be greater than max_volume")

    return (resolve_music({"music": merged}) if not errors else None), errors


def queue_room(settings, queued_count):
    """Number of additional tracks allowed under this guild's queue cap."""
    limit = resolve_music({"music": settings})["max_queue_tracks"]
    return max(limit - max(int(queued_count or 0), 0), 0)
