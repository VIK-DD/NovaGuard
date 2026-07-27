# Per-guild Levels configuration — design

**Date:** 2026-07-28
**Status:** approved, ready for implementation planning

## Goal

Make the Levels module configurable per server from both the website dashboard
and Discord, instead of running on constants shared by every guild. This is the
first module to get per-guild settings; it is meant to be the template the other
modules follow, so the shape matters as much as the feature.

## Why this, and why not more

The dashboard already writes every per-guild setting the bot has: seven
channels, two roles and the automod block. Nothing configurable is
Discord-only. The gap against a bot like MEE6 is not the dashboard's layout —
it is that `levels.py`, `economy.py` and `giveaways.py` have no per-guild
settings at all. Their behaviour is frozen in module constants
(`XP_GAIN_MIN = 5`, `DAILY_BASE = 200`, `SPAM_MESSAGES = 6`). Restructuring the
dashboard without adding settings would produce cards with nothing in them.

## What is deliberately not configurable

`XP_PER_LEVEL` and `MAX_LEVEL` stay module constants.

A member's level is not stored — `level_from_xp` (`cogs/levels.py:53`) derives
it from total XP on every read. Exposing the curve would mean that the moment
an owner changed it, every member in the server would jump or drop a level at
once, with no warning and no undo. Making that safe needs a migration path and
an explicit confirmation step, which is a separate piece of work.

## Settings

Stored as one nested object under the `levels` key, matching how `automod` is
already stored and patched.

| key | type | default | effect |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | when false, no XP accrues at all |
| `announce` | `"dm"` \| `"channel"` \| `"off"` | `"dm"` | where a level-up is announced |
| `announce_channel` | channel id \| `null` | `null` | required when `announce` is `"channel"` |
| `xp_min` | int 1–100 | `5` | lower bound of the per-message XP roll |
| `xp_max` | int 1–100 | `10` | upper bound; must be ≥ `xp_min` |
| `cooldown` | int 0–3600 | `120` | seconds between two XP gains for one member |
| `ignored_channels` | list of channel ids, ≤50 | `[]` | no XP earned in these channels |
| `ignored_roles` | list of role ids, ≤50 | `[]` | members holding any of these earn no XP |

Every default is the module's current behaviour, so a guild that saves nothing
behaves exactly as it does today. `announce: "dm"` preserves the existing
direct-message level-up.

`announce` is a mode rather than a single overloaded field. Encoding "DM" as a
sentinel string inside a channel-id column would make the type a lie and force
every reader to know the sentinel. The cost is one consistency rule, stated
below, which the server enforces.

## Components

### 1. `core/levels_settings.py` — new, pure

Holds `LEVELS_DEFAULTS`, `resolve_levels(settings)` (defaults merged with what
is saved) and `validate_levels(raw, current, channel_ids, role_ids)` returning
`(clean, errors)`.

It imports neither discord.py nor aiohttp, so it is unit-testable on its own and
both the cog and the web API can depend on it. This is the one thing automod got
wrong: `AUTOMOD_DEFAULTS` is declared twice, in `cogs/automod.py:17` and again
in `core/webserver.py:123`, and the two can drift. Levels gets one home.

The validator takes plain sets of valid ids rather than a guild object, which is
what keeps it pure — the caller resolves the guild.

### 2. Settings cache in `core/storage.py`

`get_guild_settings` currently runs a locked SQLite query on every call, and
`cogs/automod.py:26` already calls it for every message. Reading levels config
per message as well would put two locked queries on the hot path of a bot
running on a Raspberry Pi.

A process-local dict cache keyed by guild id, invalidated in
`update_guild_settings` and `reset_guild_settings`, removes both. The web API
runs inside the bot process and writes through the same functions, so there is
no second process to go stale against. Access is guarded by a lock because
writes arrive from `asyncio.to_thread` while reads happen on the event loop.

### 3. `cogs/levels.py`

`on_message` reads the resolved config instead of the constants: honour
`enabled`, skip ignored channels and roles, roll XP between `xp_min` and
`xp_max`, apply `cooldown`, and route the level-up embed by `announce`. The
existing constants stay as the defaults, so behaviour is unchanged for a guild
with nothing saved.

If the announce channel is gone or unwritable, the level-up is dropped silently,
exactly as a failed DM is today. A missing channel must not break XP.

### 4. `core/webserver.py`

`levels` joins the settings block in `GET /guilds/{id}/config`, and
`handle_config_put` validates a `levels` patch through `validate_levels`,
merging over current values the same way the automod branch does. Errors join
the existing `validation_failed` details list.

### 5. Website

`LevelsSchema` in `schemas.ts`, a `levels` branch in `diffSettings`, and one new
`<Section kicker="Levels">` in `GuildConfig.tsx`.

No redesign. The section reuses `Section`, `Toggle`, `ChannelSelect` and
`RoleSelect` exactly as the AutoMod and Roles sections use them. New controls
are limited to what has no existing equivalent: a mode `<select>` for
`announce` (already styled by the `#app select` rule) and number inputs for the
XP range and cooldown. Ignored channels and roles are multi-value, so they
render as the existing selects plus a removable list, in the same visual
language as `BadwordsEditor`.

## Validation rules

Server-side, in `validate_levels`:

- `xp_min` and `xp_max` are integers in 1–100, and `xp_min <= xp_max`. The pair
  is checked after both are resolved, so patching only one of them is validated
  against the saved value of the other.
- `cooldown` is an integer in 0–3600.
- `announce` is one of the three modes.
- `announce == "channel"` requires an `announce_channel` that is a text channel
  in this guild. Changing the mode without supplying a channel is rejected
  rather than silently saved in a state that cannot announce.
- `ignored_channels` and `ignored_roles` hold at most 50 ids each; every id must
  exist in the guild; duplicates are dropped.

Any failure returns `validation_failed` with per-field details, which
`mapValidationDetails` already pairs to fields in the form.

## Error handling

- The whole patch is rejected on any error; nothing is saved partially. This is
  the existing PUT contract, not a new rule.
- An unparseable saved `levels` value resolves to the defaults rather than
  disabling the module, because a storage fault should not silently stop XP.
- A deleted announce channel or ignored channel is ignored at read time and left
  in storage; the next save through the dashboard drops it naturally.

## Testing

- `tests/test_levels_settings.py`, new and pure: defaults resolve when nothing
  is saved; each range boundary; `xp_min > xp_max` rejected, including when only
  one side is patched; `announce: "channel"` without a channel rejected; unknown
  channel and role ids rejected; the 50-id cap; duplicates dropped; a corrupt
  saved value falling back to defaults.
- `tests/test_webserver.py`: `levels` present in the config payload; a valid
  levels PUT persists; an invalid one returns `validation_failed`.
- Cache behaviour: a write through `update_guild_settings` is visible to the
  next `get_guild_settings`, and `reset_guild_settings` clears it.
- `configForm.test.ts`: the diff emits only changed levels keys, and an
  unchanged levels block produces no patch.

## Out of scope

- Configuring the XP curve or level cap, for the reason given above.
- Level roles / rewards.
- Any change to the dashboard's layout or navigation beyond adding one section.
- Settings for economy, giveaways or tickets. Those follow this template once
  the shape is proven.

## Deployment

Bot and website both change. The bot needs `git pull` plus `pm2 restart
pythonbot` on the Pi; the website needs `npm run deploy` from `website-3`. The
API is additive — an older dashboard against a newer bot simply does not show
the section.
