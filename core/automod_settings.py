"""Shared AutoMod defaults, normalisation and validation.

Enforcement and the dashboard import this module so a value accepted by the
web UI can never mean something different inside the Discord listener.
"""

MAX_BADWORDS = 100
MAX_BADWORD_LENGTH = 40
MAX_AUTOMOD_EXCLUSIONS = 50

AUTOMOD_NUMBER_LIMITS = {
    "spam_messages": (3, 20),
    "spam_window_seconds": (2, 60),
    "spam_timeout_seconds": (10, 86400),
}

AUTOMOD_DEFAULTS = {
    "invites": True,
    "spam": True,
    "badwords": [],
    "ignored_channels": [],
    "ignored_roles": [],
    "spam_messages": 6,
    "spam_window_seconds": 6,
    "spam_timeout_seconds": 60,
}


def _fresh_defaults():
    return {
        **AUTOMOD_DEFAULTS,
        "badwords": [],
        "ignored_channels": [],
        "ignored_roles": [],
    }


def normalize_badwords(raw):
    if not isinstance(raw, list):
        return []
    words = []
    for value in raw[:MAX_BADWORDS]:
        word = str(value).strip().lower()[:MAX_BADWORD_LENGTH]
        if word and word not in words:
            words.append(word)
    return words


def normalize_ids(raw, limit=MAX_AUTOMOD_EXCLUSIONS):
    if not isinstance(raw, list):
        return []
    result = []
    for value in raw[:limit]:
        item = str(value).strip()
        if item and item not in result:
            result.append(item)
    return result


def _valid_whole_number(value, minimum, maximum):
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def resolve_automod(settings):
    """Return one safe, detached AutoMod configuration for a guild."""
    config = _fresh_defaults()
    saved = settings.get("automod") if isinstance(settings, dict) else None
    if not isinstance(saved, dict):
        return config

    for flag in ("invites", "spam"):
        if isinstance(saved.get(flag), bool):
            config[flag] = saved[flag]
    config["badwords"] = normalize_badwords(saved.get("badwords"))
    config["ignored_channels"] = normalize_ids(saved.get("ignored_channels"))
    config["ignored_roles"] = normalize_ids(saved.get("ignored_roles"))
    for key, (minimum, maximum) in AUTOMOD_NUMBER_LIMITS.items():
        if _valid_whole_number(saved.get(key), minimum, maximum):
            config[key] = saved[key]
    return config


def validate_automod(patch, current, channel_ids, role_ids):
    """Validate a partial dashboard patch against the effective saved block."""
    config = resolve_automod({"automod": current})
    if not isinstance(patch, dict):
        return config, ["automod: must be an object"]

    errors = []
    known = {
        "invites",
        "spam",
        "badwords",
        "ignored_channels",
        "ignored_roles",
        *AUTOMOD_NUMBER_LIMITS,
    }
    for key in sorted(set(patch) - known):
        errors.append(f"automod.{key}: unknown setting")

    for flag in ("invites", "spam"):
        if flag not in patch:
            continue
        if not isinstance(patch[flag], bool):
            errors.append(f"automod.{flag}: must be true or false")
        else:
            config[flag] = patch[flag]

    if "badwords" in patch:
        if not isinstance(patch["badwords"], list):
            errors.append("automod.badwords: must be a list of words")
        elif len(patch["badwords"]) > MAX_BADWORDS:
            errors.append(f"automod.badwords: at most {MAX_BADWORDS} entries")
        else:
            config["badwords"] = normalize_badwords(patch["badwords"])

    allowed_ids = {
        "ignored_channels": {str(value) for value in channel_ids},
        "ignored_roles": {str(value) for value in role_ids},
    }
    labels = {"ignored_channels": "channel", "ignored_roles": "role"}
    for key, valid_ids in allowed_ids.items():
        if key not in patch:
            continue
        raw = patch[key]
        if not isinstance(raw, list):
            errors.append(f"automod.{key}: must be a list")
            continue
        if len(raw) > MAX_AUTOMOD_EXCLUSIONS:
            errors.append(f"automod.{key}: at most {MAX_AUTOMOD_EXCLUSIONS} entries")
            continue
        normalized = normalize_ids(raw)
        if any(value not in valid_ids for value in normalized):
            errors.append(f"automod.{key}: contains a {labels[key]} from another guild")
            continue
        config[key] = normalized

    for key, (minimum, maximum) in AUTOMOD_NUMBER_LIMITS.items():
        if key not in patch:
            continue
        value = patch[key]
        if not _valid_whole_number(value, minimum, maximum):
            errors.append(
                f"automod.{key}: must be a whole number between {minimum} and {maximum}"
            )
        else:
            config[key] = value

    return config, errors


def is_automod_exempt(config, channel_ids=(), role_ids=()):
    """True when a message belongs to an explicitly exempt channel or role."""
    ignored_channels = set(config.get("ignored_channels") or ())
    ignored_roles = set(config.get("ignored_roles") or ())
    return bool(
        ignored_channels.intersection(str(value) for value in channel_ids if value)
        or ignored_roles.intersection(str(value) for value in role_ids if value)
    )
