"""Audio filter presets for the Lavalink backend.

Kept as plain data, separate from the cog, for two reasons. The numbers are
the part worth reviewing and testing — a pitch of 1.2 versus 2.0 is the
difference between nightcore and a chipmunk — and keeping them here means the
whole catalogue can be tested without a Lavalink node.

Equalizer bands are Lavalink's 15 fixed bands, 0 (25 Hz) through 14 (16 kHz).
Gains run from -0.25 (muted) to 1.0 (doubled); anything past ~0.3 on several
neighbouring bands clips audibly, so the presets stay conservative.

Filters are not free: Lavalink has to decode and re-encode the stream instead
of passing Opus straight through, which costs CPU on a small host. The node
also has to allow each filter in `application.yml` under
`lavalink.server.filters` - a disabled filter is silently ignored.
"""

BASS_BANDS = ((0, 0.25), (1, 0.25), (2, 0.20), (3, 0.10))
TREBLE_BANDS = ((11, 0.20), (12, 0.25), (13, 0.25), (14, 0.20))
MUFFLE_BANDS = ((10, -0.20), (11, -0.25), (12, -0.25), (13, -0.25), (14, -0.25))


def _bands(pairs):
    return [{"band": band, "gain": gain} for band, gain in pairs]


# Every preset lists the filters it needs so the cog can warn when the node
# has one switched off, instead of applying it and appearing to do nothing.
FILTER_PRESETS = {
    "off": {
        "label": "Off",
        "emoji": "🚫",
        "description": "Clear every effect and play the track as recorded.",
        "requires": (),
        "filters": {},
    },
    "bassboost": {
        "label": "Bass boost",
        "emoji": "🔈",
        "description": "Lifts the low end without muddying vocals.",
        "requires": ("equalizer",),
        "filters": {"equalizer": _bands(BASS_BANDS)},
    },
    "nightcore": {
        "label": "Nightcore",
        "emoji": "⚡",
        "description": "Faster and higher pitched.",
        "requires": ("timescale",),
        "filters": {"timescale": {"speed": 1.2, "pitch": 1.2, "rate": 1.0}},
    },
    "slowed": {
        "label": "Slowed",
        "emoji": "🌙",
        "description": "Slower and slightly lower - the slowed + reverb sound.",
        "requires": ("timescale",),
        "filters": {"timescale": {"speed": 0.85, "pitch": 0.95, "rate": 1.0}},
    },
    "vaporwave": {
        "label": "Vaporwave",
        "emoji": "🌴",
        "description": "Heavily slowed and dreamy, with the highs rolled off.",
        "requires": ("timescale", "equalizer"),
        "filters": {
            "timescale": {"speed": 0.80, "pitch": 0.80, "rate": 1.0},
            "equalizer": _bands(MUFFLE_BANDS),
        },
    },
    "8d": {
        "label": "8D",
        "emoji": "🎧",
        "description": "Sound circles around your head. Wear headphones.",
        "requires": ("rotation",),
        "filters": {"rotation": {"rotation_hz": 0.2}},
    },
    "karaoke": {
        "label": "Karaoke",
        "emoji": "🎤",
        "description": "Pushes the lead vocal down so you can sing over it.",
        "requires": ("karaoke",),
        "filters": {
            "karaoke": {
                "level": 1.0,
                "mono_level": 1.0,
                "filter_band": 220.0,
                "filter_width": 100.0,
            }
        },
    },
    "treble": {
        "label": "Treble",
        "emoji": "✨",
        "description": "Brightens the top end for muffled recordings.",
        "requires": ("equalizer",),
        "filters": {"equalizer": _bands(TREBLE_BANDS)},
    },
}

MAX_GAIN = 1.0
MIN_GAIN = -0.25


def preset_names():
    """Preset keys, with `off` first so it is easy to find."""
    rest = sorted(name for name in FILTER_PRESETS if name != "off")
    return ["off"] + rest


def resolve_preset(name):
    """Look up a preset, tolerating case and stray whitespace. None if absent."""
    return FILTER_PRESETS.get((name or "").strip().lower())


def preset_label(name):
    preset = resolve_preset(name)
    if not preset:
        return (name or "").strip() or "unknown"
    return f"{preset['emoji']} {preset['label']}"


def is_reset(name):
    return (name or "").strip().lower() == "off"


def required_filters(name):
    preset = resolve_preset(name)
    return tuple(preset["requires"]) if preset else ()
