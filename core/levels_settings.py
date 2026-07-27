"""Per-guild Levels configuration: defaults, resolution and validation.

Deliberately free of discord.py and aiohttp, so the cog and the web API can both
depend on it and the rules stay unit-testable on their own. `core/guild_config.py`
cannot host this: it resolves channels through a live bot object.

One home for the defaults, on purpose. `AUTOMOD_DEFAULTS` is declared twice —
`cogs/automod.py` and `core/webserver.py` — and the two can drift apart without
anything noticing.

Ids are handled as strings throughout. Discord ids exceed 2^53, so letting them
reach JSON as numbers would corrupt them in a browser; the storage layer accepts
either and the API renders strings.
"""

LEVELS_DEFAULTS = {
    "enabled": True,
    "announce": "dm",
    "announce_channel": None,
    "xp_min": 5,
    "xp_max": 10,
    "cooldown": 120,
    "ignored_channels": [],
    "ignored_roles": [],
}

ANNOUNCE_MODES = ("dm", "channel", "off")
XP_MIN_BOUND = 1
XP_MAX_BOUND = 100
COOLDOWN_MIN_BOUND = 0
COOLDOWN_MAX_BOUND = 3600
MAX_IGNORED = 50

_LIST_KEYS = ("ignored_channels", "ignored_roles")


def _as_int(value):
    """Int from a JSON scalar, or None. Booleans are not integers here."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _as_id_list(value):
    """Deduplicated list of id strings, order preserved. Junk entries dropped."""
    if not isinstance(value, (list, tuple)):
        return None
    out = []
    for item in value:
        if isinstance(item, bool):
            continue
        text = str(item).strip()
        if text.isdigit() and text not in out:
            out.append(text)
    return out


def resolve_levels(settings):
    """A guild's effective Levels config: defaults under whatever is saved.

    Every field falls back independently, so one corrupt value cannot take the
    rest of the config with it. A missing or unreadable block resolves to the
    defaults rather than to "disabled" — a storage fault must not silently stop
    members earning XP.
    """
    resolved = dict(LEVELS_DEFAULTS)
    resolved["ignored_channels"] = []
    resolved["ignored_roles"] = []

    saved = settings.get("levels") if isinstance(settings, dict) else None
    if not isinstance(saved, dict):
        return resolved

    if "enabled" in saved:
        resolved["enabled"] = bool(saved["enabled"])

    if saved.get("announce") in ANNOUNCE_MODES:
        resolved["announce"] = saved["announce"]

    channel = saved.get("announce_channel")
    if channel is not None and str(channel).strip().isdigit():
        resolved["announce_channel"] = str(channel).strip()

    for key, low, high in (
        ("xp_min", XP_MIN_BOUND, XP_MAX_BOUND),
        ("xp_max", XP_MIN_BOUND, XP_MAX_BOUND),
        ("cooldown", COOLDOWN_MIN_BOUND, COOLDOWN_MAX_BOUND),
    ):
        number = _as_int(saved.get(key))
        if number is not None and low <= number <= high:
            resolved[key] = number

    for key in _LIST_KEYS:
        ids = _as_id_list(saved.get(key))
        if ids is not None:
            resolved[key] = ids[:MAX_IGNORED]

    # A saved pair can still be inverted if it predates validation or was edited
    # by hand. Rolling XP over an inverted range raises ValueError in the cog, so
    # neutralise it here rather than letting it reach random.randint.
    if resolved["xp_min"] > resolved["xp_max"]:
        resolved["xp_min"] = LEVELS_DEFAULTS["xp_min"]
        resolved["xp_max"] = LEVELS_DEFAULTS["xp_max"]

    return resolved


def validate_levels(raw, current, channel_ids, role_ids):
    """Check a Levels patch and return ``(clean, errors)``.

    ``raw`` is the untrusted patch, ``current`` the guild's resolved config, and
    ``channel_ids``/``role_ids`` the ids that exist in the guild, as strings.

    Only keys present in ``raw`` are taken from it; everything else comes from
    ``current``. That is what makes the ``xp_min <= xp_max`` check right when a
    patch moves only one side of the pair. ``clean`` is the whole merged object,
    because that is what gets stored — the same shape the automod branch writes.

    ``clean`` is only meaningful when ``errors`` is empty.
    """
    if not isinstance(raw, dict):
        return dict(current), ["levels: must be an object"]

    errors = []
    clean = dict(current)

    if "enabled" in raw:
        clean["enabled"] = bool(raw["enabled"])

    if "announce" in raw:
        if raw["announce"] in ANNOUNCE_MODES:
            clean["announce"] = raw["announce"]
        else:
            errors.append(f"levels.announce: must be one of {', '.join(ANNOUNCE_MODES)}")

    if "announce_channel" in raw:
        value = raw["announce_channel"]
        if value in (None, "", 0):
            clean["announce_channel"] = None
        elif str(value) in channel_ids:
            clean["announce_channel"] = str(value)
        else:
            errors.append("levels.announce_channel: not a text channel in this guild")

    for key, low, high in (
        ("xp_min", XP_MIN_BOUND, XP_MAX_BOUND),
        ("xp_max", XP_MIN_BOUND, XP_MAX_BOUND),
        ("cooldown", COOLDOWN_MIN_BOUND, COOLDOWN_MAX_BOUND),
    ):
        if key not in raw:
            continue
        number = _as_int(raw[key])
        if number is None or not low <= number <= high:
            errors.append(f"levels.{key}: must be a whole number between {low} and {high}")
        else:
            clean[key] = number

    for key, valid_ids, label in (
        ("ignored_channels", channel_ids, "text channel"),
        ("ignored_roles", role_ids, "role"),
    ):
        if key not in raw:
            continue
        ids = _as_id_list(raw[key])
        if ids is None:
            errors.append(f"levels.{key}: must be a list of ids")
            continue
        if len(ids) > MAX_IGNORED:
            errors.append(f"levels.{key}: at most {MAX_IGNORED} entries")
            continue
        unknown = [i for i in ids if i not in valid_ids]
        if unknown:
            errors.append(f"levels.{key}: not a {label} in this guild: {', '.join(unknown[:3])}")
        else:
            clean[key] = ids

    # Cross-field rules run on the merged result, so a one-sided patch is judged
    # against what is already saved rather than against a default.
    if clean["xp_min"] > clean["xp_max"]:
        errors.append("levels.xp_min: cannot be greater than xp_max")

    if clean["announce"] == "channel" and not clean["announce_channel"]:
        # Saving this would leave the module claiming to announce in a channel
        # while having nowhere to announce.
        errors.append("levels.announce_channel: required when announcing in a channel")

    return clean, errors
