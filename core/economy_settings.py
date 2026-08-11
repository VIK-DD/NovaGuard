"""Shared, bounded per-guild rules for NovaGuard's economy."""

ECONOMY_DEFAULTS = {
    "enabled": True,
    "daily_base": 200,
    "daily_streak_bonus": 50,
    "work_min": 50,
    "work_max": 150,
    "work_cooldown_minutes": 60,
    "transfers_enabled": True,
    "games_enabled": True,
    "shop_enabled": True,
    "gamble_max_bet": 1_000_000,
    "slots_max_bet": 100_000,
}

_BOOL_KEYS = ("enabled", "transfers_enabled", "games_enabled", "shop_enabled")
_INT_RANGES = {
    "daily_base": (0, 100_000),
    "daily_streak_bonus": (0, 10_000),
    "work_min": (0, 100_000),
    "work_max": (0, 100_000),
    "work_cooldown_minutes": (1, 1440),
    "gamble_max_bet": (10, 1_000_000),
    "slots_max_bet": (10, 100_000),
}


def resolve_economy(settings):
    saved = settings.get("economy") if isinstance(settings, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    resolved = dict(ECONOMY_DEFAULTS)
    for key in _BOOL_KEYS:
        if isinstance(saved.get(key), bool):
            resolved[key] = saved[key]
    for key, (minimum, maximum) in _INT_RANGES.items():
        value = saved.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            resolved[key] = min(max(value, minimum), maximum)
    if resolved["work_min"] > resolved["work_max"]:
        resolved["work_min"] = resolved["work_max"]
    return resolved


def validate_economy(patch, current):
    if not isinstance(patch, dict):
        return None, ["economy: must be an object"]

    unknown = sorted(set(patch) - set(ECONOMY_DEFAULTS))
    errors = [f"economy.{key}: unknown setting" for key in unknown]
    merged = {**resolve_economy({"economy": current}), **patch}

    for key in _BOOL_KEYS:
        if not isinstance(merged.get(key), bool):
            errors.append(f"economy.{key}: must be true or false")
    for key, (minimum, maximum) in _INT_RANGES.items():
        value = merged.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            errors.append(
                f"economy.{key}: must be a whole number from {minimum} to {maximum}"
            )
    if (
        isinstance(merged.get("work_min"), int)
        and isinstance(merged.get("work_max"), int)
        and merged["work_min"] > merged["work_max"]
    ):
        errors.append("economy.work_min: cannot be greater than work_max")

    return (resolve_economy({"economy": merged}) if not errors else None), errors
