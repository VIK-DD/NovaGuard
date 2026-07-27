"""Rules for per-guild Levels config — pure, no bot and no database.

Run standalone:  python tests/test_levels_settings.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.levels_settings import (  # noqa: E402
    LEVELS_DEFAULTS,
    MAX_IGNORED,
    resolve_levels,
    validate_levels,
)

CHANNELS = {"111", "222", "333"}
ROLES = {"900", "901"}

results = []


def check(name, ok):
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), name)


def valid(raw, current=None):
    return validate_levels(raw, current or resolve_levels({}), CHANNELS, ROLES)


# ── resolution ───────────────────────────────────────────────────────
check("nothing saved resolves to the defaults", resolve_levels({}) == LEVELS_DEFAULTS)
check("no settings object at all still resolves", resolve_levels(None) == LEVELS_DEFAULTS)
check(
    "a corrupt levels block falls back to defaults, not to disabled",
    resolve_levels({"levels": "garbage"}) == LEVELS_DEFAULTS
    and resolve_levels({"levels": ["nope"]})["enabled"] is True,
)
check(
    "one bad field does not discard the good ones",
    resolve_levels({"levels": {"xp_min": "abc", "cooldown": 30}})["cooldown"] == 30
    and resolve_levels({"levels": {"xp_min": "abc", "cooldown": 30}})["xp_min"] == 5,
)
check(
    "out-of-range saved values fall back per field",
    resolve_levels({"levels": {"xp_max": 5000, "cooldown": -1}}) == LEVELS_DEFAULTS,
)
check(
    "saved ids resolve as strings, deduplicated",
    resolve_levels({"levels": {"ignored_channels": [111, "111", 222]}})["ignored_channels"]
    == ["111", "222"],
)
check(
    "an inverted saved pair is neutralised rather than reaching random.randint",
    resolve_levels({"levels": {"xp_min": 40, "xp_max": 9}})["xp_min"] == 5,
)
check(
    "a saved list longer than the cap is truncated",
    len(resolve_levels({"levels": {"ignored_roles": [str(i) for i in range(200)]}})["ignored_roles"])
    == MAX_IGNORED,
)

# ── validation: happy path ───────────────────────────────────────────
clean, errors = valid({"xp_min": 2, "xp_max": 20, "cooldown": 0, "enabled": False})
check(
    "a valid patch applies and reports no errors",
    not errors and clean["xp_min"] == 2 and clean["cooldown"] == 0 and clean["enabled"] is False,
)
clean, errors = valid({"announce": "channel", "announce_channel": "222"})
check("announcing in a real channel is accepted", not errors and clean["announce_channel"] == "222")
clean, errors = valid({"announce": "off"})
check("announcements can be turned off", not errors and clean["announce"] == "off")
clean, errors = valid({"ignored_channels": ["111", "333"], "ignored_roles": ["900"]})
check("known ignored ids are accepted", not errors and clean["ignored_channels"] == ["111", "333"])
clean, errors = valid({"ignored_channels": [111, "111", 333]})
check("duplicate ignored ids collapse", not errors and clean["ignored_channels"] == ["111", "333"])
clean, errors = valid({})
check("an empty patch is valid and changes nothing", not errors and clean == resolve_levels({}))

# ── validation: the pair ─────────────────────────────────────────────
_, errors = valid({"xp_min": 30, "xp_max": 10})
check("an inverted pair in one patch is rejected", any("xp_min" in e for e in errors))

saved = resolve_levels({"levels": {"xp_min": 5, "xp_max": 10}})
_, errors = valid({"xp_min": 40}, saved)
check(
    "raising only xp_min above the saved xp_max is rejected",
    any("greater than xp_max" in e for e in errors),
)
_, errors = valid({"xp_max": 2}, saved)
check(
    "lowering only xp_max below the saved xp_min is rejected",
    any("greater than xp_max" in e for e in errors),
)
clean, errors = valid({"xp_min": 40, "xp_max": 60}, saved)
check("moving both sides together is accepted", not errors and clean["xp_max"] == 60)

# ── validation: announce consistency ─────────────────────────────────
_, errors = valid({"announce": "channel"})
check(
    "switching to channel mode without a channel is rejected",
    any("required when announcing in a channel" in e for e in errors),
)
configured = resolve_levels({"levels": {"announce": "channel", "announce_channel": "111"}})
_, errors = valid({"announce_channel": None}, configured)
check(
    "clearing the channel while still in channel mode is rejected",
    any("required when announcing in a channel" in e for e in errors),
)
clean, errors = valid({"announce": "dm"}, configured)
check(
    "leaving channel mode keeps the picked channel for later",
    not errors and clean["announce"] == "dm" and clean["announce_channel"] == "111",
)
_, errors = valid({"announce": "sometimes"})
check("an unknown announce mode is rejected", any("levels.announce:" in e for e in errors))

# ── validation: rejections ───────────────────────────────────────────
_, errors = valid({"announce": "channel", "announce_channel": "999"})
check("a channel from another guild is rejected", any("not a text channel" in e for e in errors))
_, errors = valid({"ignored_roles": ["900", "12345"]})
check("an unknown role is rejected", any("not a role in this guild" in e for e in errors))
_, errors = valid({"ignored_channels": ["900"]})
check("a role id passed as a channel is rejected", any("not a text channel" in e for e in errors))
_, errors = valid({"xp_min": 0})
check("xp below the floor is rejected", any("levels.xp_min:" in e for e in errors))
_, errors = valid({"xp_max": 101})
check("xp above the ceiling is rejected", any("levels.xp_max:" in e for e in errors))
_, errors = valid({"cooldown": 3601})
check("a cooldown above the ceiling is rejected", any("levels.cooldown:" in e for e in errors))
_, errors = valid({"xp_min": True})
check("a boolean is not accepted as a number", any("levels.xp_min:" in e for e in errors))
_, errors = valid({"xp_min": 7.5})
check("a fractional xp value is rejected", any("levels.xp_min:" in e for e in errors))
_, errors = valid({"ignored_channels": "111"})
check("a bare string is not a list of ids", any("must be a list of ids" in e for e in errors))
_, errors = valid({"ignored_channels": [str(i) for i in range(MAX_IGNORED + 1)]})
check("more ids than the cap are rejected", any("at most" in e for e in errors))
_, errors = validate_levels("not-an-object", resolve_levels({}), CHANNELS, ROLES)
check("a non-object patch is rejected", errors == ["levels: must be an object"])

# ── the patch must not mutate what it was given ──────────────────────
saved = resolve_levels({})
before = dict(saved)
validate_levels({"xp_min": 9, "ignored_roles": ["900"]}, saved, CHANNELS, ROLES)
check("validation leaves the current config untouched", saved == before)

failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    raise SystemExit(1)
