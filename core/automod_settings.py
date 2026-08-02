"""Shared AutoMod defaults and resolution.

One home on purpose: cogs/automod.py (enforcement) and core/webserver.py
(dashboard API) both need the same defaults, and the two copies they used to
declare could drift apart without anything noticing.

Free of discord.py and aiohttp so both sides can import it cheaply.
"""

AUTOMOD_DEFAULTS = {"invites": True, "spam": True, "badwords": []}


def resolve_automod(settings):
    """A guild's effective AutoMod config, built from fresh copies.

    Never hands out the module-level default objects: the old pattern
    (``dict(AUTOMOD_DEFAULTS)`` then ``update``) shared the default badwords
    *list* with every guild that had nothing saved, so one guild appending a
    word mutated the default and leaked that word into every other guild
    until the next restart.
    """
    config = {"invites": True, "spam": True, "badwords": []}
    saved = settings.get("automod") if isinstance(settings, dict) else None
    if isinstance(saved, dict):
        config.update(saved)
    if not isinstance(config.get("badwords"), list):
        config["badwords"] = []
    return config
