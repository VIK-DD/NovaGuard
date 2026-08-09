# NovaGuard Dashboard API

Embedded aiohttp API served by the bot process (`core/webserver.py`). The
website consumes it to let server admins configure NovaGuard from the browser.

- **Base URL:** `/api/v1` (legacy `/api` aliases every route for backward compat)
- **Auth:** Discord OAuth2 → `HttpOnly` session cookie `ng_session`
- **Content type:** `application/json` on every response, success or error
- **Enable:** `WEB_ENABLED=true` + `DISCORD_CLIENT_ID` + `DISCORD_CLIENT_SECRET`

## Response envelope

Success bodies are endpoint-specific (below). **Every error** shares one shape:

```json
{ "error": "Human-readable message.", "code": "machine_readable_code" }
```

`validation_failed` errors add a `details` array of field messages. `429` and
`503 bot_starting` responses also send a `Retry-After` header (seconds).

### Error codes

| code | status | meaning |
|------|--------|---------|
| `bad_request` | 400 | Malformed input / invalid guild id / bad JSON body |
| `validation_failed` | 400 | Config values rejected — see `details[]` |
| `nothing_to_update` | 400 | PUT body contained no recognised keys |
| `voice_not_configured` | 400 | Voice test requested before a voice report channel was set |
| `update_channel_not_configured` | 400 | Update preview requested before this guild has an update channel |
| `update_preview_unavailable` | 400 | No saved update exists to preview |
| `invalid_state` | 400 | OAuth `state` mismatch — restart login |
| `unauthorized` | 401 | No / expired session cookie |
| `session_expired` | 401 | Discord token could not be refreshed |
| `forbidden` | 403 | Lacks Manage Server on the guild |
| `bad_origin` | 403 | Cross-origin mutation blocked (CSRF guard) |
| `backup_not_found` | 404 | Backup check requested before any archive exists |
| `guild_not_found` | 404 | Bot is not in that guild |
| `not_found` | 404 | Unknown route |
| `rate_limited` | 429 | Per-IP rate limit hit (`Retry-After`) |
| `upstream_rate_limited` | 429 | Discord is rate-limiting the bot |
| `upstream_error` | 502 | Discord API failure |
| `voice_test_failed` | 502 | Discord did not accept the voice preview in time |
| `update_preview_failed` | 502 | Discord did not accept the update preview in time |
| `bot_starting` | 503 | Bot not ready yet — retry shortly |
| `oauth_unavailable` | 503 | OAuth not configured on the bot |
| `internal_error` | 500 | Unexpected server error (details logged, not returned) |

## Rate limits (per client IP, sliding window)

| scope | limit | endpoints |
|-------|-------|-----------|
| auth | 10 / min | `/auth/login`, `/auth/callback` |
| read | 120 / min | `/stats`, `/me`, `/guilds`, `/guilds/*/config` (GET), `/guilds/*/dashboard`, `/guilds/*/audit` |
| write | 30 / min | `/guilds/*/config` (PUT), `/guilds/*/actions/*` (POST) |

## Endpoints

### `GET /health`
Public. `200` when the DB is reachable, `503` otherwise.
```json
{ "ok": true, "bot_ready": true, "db_ok": true }
```

### `GET /stats`
Public. Bot-wide counters.
```json
{ "version": "2.0", "phase": "open-beta", "phase_label": "Open Beta",
  "release_label": "2.0 Open Beta", "runtime_version": "3.1.0",
  "codename": "Nova", "guilds": 3, "members": 512,
  "commands": 78, "uptime_seconds": 8123, "ready": true }
```

### `GET /updates?limit=50`

Public. Newest-first release feed: the frozen Discord archive
(`core/updates_archive.json`) merged with the changelog engine's live history,
deduplicated by `created_at`. `limit` defaults to 50 and is clamped to 200.

```json
{ "updates": [ { "build": 16, "version": "3.0.0", "codename": "Nova",
                 "created_at": "2026-07-24T01:28:56+00:00",
                 "highlights": ["..."], "changes": ["..."],
                 "added_lines": 48, "removed_lines": 8, "changed_files": 1 } ],
  "count": 29,
  "release": { "version": "2.0", "phase": "open-beta", "phase_label": "Open Beta" } }
```

`version`, `codename`, `highlights`, `changes` and the line counts are all
optional; every entry has `created_at`. Note that `build` is the number the bot
printed in Discord and repeats across the archive — the engine's state was reset
several times — so it is not an identifier. The website numbers releases by date
order instead.

### `GET /invite`
Public. `302` redirect to the bot's Discord install URL.

### `GET /auth/login`
`302` to Discord's OAuth consent screen; sets a signed `ng_state` cookie.

### `GET /auth/callback?code&state`
OAuth redirect target. Validates `state`, exchanges the code, creates the
session, sets `ng_session`, then `302` to `WEB_AFTER_LOGIN`.

### `POST /auth/logout`
Revokes the Discord token and clears the session. Origin-guarded.
```json
{ "ok": true }
```

### `GET /me`
Auth required. The logged-in user.
```json
{ "user": { "id": "…", "username": "…", "avatar": "…|null" } }
```

### `GET /guilds`
Auth required. Guilds the user can manage, bot-present first.
```json
{ "guilds": [ { "id": "…", "name": "…", "icon": "…|null",
  "owner": true, "permissions": 32, "bot_present": true } ] }
```

### `GET /guilds/{guild_id}/config`
Auth + Manage Server. Current settings plus the pickers the UI needs.

`github_watch_configured` is instance-wide, not a per-guild setting — it's the
same value on every guild this bot serves, derived from the bot's
`GITHUB_WATCH_REPOS`/`GITHUB_PRIMARY_REPO` env config.

```json
{
  "guild": { "id": "…", "name": "…", "icon": "…|null", "member_count": 42 },
  "github_watch_configured": true,
  "settings": {
    "welcome_channel": "…|null", "goodbye_channel": "…|null",
    "log_channel": "…|null", "voice_report_channel": "…|null", "update_channel": "…|null",
    "github_event_channel": "…|null", "error_log_channel": "…|null",
    "autorole": "…|null", "ticket_staff_role": "…|null",
    "automod": { "invites": true, "spam": true, "badwords": ["…"] },
    "levels": {
      "enabled": true, "announce": "dm|channel|off", "announce_channel": "…|null",
      "xp_min": 5, "xp_max": 10, "cooldown": 120,
      "ignored_channels": ["…"], "ignored_roles": ["…"]
    }
  },
  "channels": [ { "id": "…", "name": "…", "category": "…|null" } ],
  "roles": [ { "id": "…", "name": "…", "color": "#RRGGBB", "assignable": true } ]
}
```

### `PUT /guilds/{guild_id}/config`
Auth + Manage Server + Origin-guarded. Body is a partial settings object —
only the keys present are changed. Returns the same payload as GET on success.

- Channel keys must be a text channel **in that guild** (or `null`/`""`/`0` to clear).
- `autorole` must be **below the bot's top role** and not managed.
- `automod.badwords`: list, each lowercased + trimmed, capped at 100 × 40 chars, deduped.
- `levels` is validated by `core/levels_settings.validate_levels`, the same rules
  the bot itself reads, so the two cannot disagree:
  - `xp_min`/`xp_max` are whole numbers 1–100 and `xp_min <= xp_max`. The pair is
    checked **after merging with the saved values**, so a patch that moves one
    side is judged against the stored other side — send both when either moves.
  - `cooldown` is a whole number 0–3600 seconds.
  - `announce` is `dm`, `channel` or `off`. `channel` requires a valid
    `announce_channel`; a mode with nowhere to announce is rejected rather than
    saved.
  - `ignored_channels`/`ignored_roles`: at most 50 ids each, all existing in that
    guild, duplicates dropped. Messages there earn no XP and are not counted.
  - The XP curve and level cap are **not** configurable: a member's level is
    derived from total XP, so changing them would move everyone at once.

```json
{ "welcome_channel": "123", "autorole": "456",
  "automod": { "invites": false, "badwords": ["spoiler"] },
  "levels": { "xp_min": 3, "xp_max": 30, "announce": "channel", "announce_channel": "789" } }
```

### `GET /guilds/{guild_id}/dashboard`
Auth + Manage Server. Compact control-center payload for the dashboard overview:
live bot status, module state, backup health, level leaderboard, recent voice
reports and newest update-feed entries.

```json
{
  "status": { "ready": true, "version": "2.0", "phase": "open-beta",
              "phase_label": "Open Beta", "release_label": "2.0 Open Beta",
              "runtime_version": "3.1.0", "codename": "Nova",
    "uptime_seconds": 1200, "commands": 66, "guilds": 5, "members": 132 },
  "guild": { "id": "…", "name": "…", "icon": "…|null", "member_count": 42 },
  "setup": { "configured_channels": 6, "total_channels": 7,
    "recommended_done": 4, "recommended_total": 4 },
  "modules": [ { "key": "voice", "label": "Voice reports", "enabled": true } ],
  "automod": { "invites": true, "spam": true, "badwords_count": 3 },
  "levels": { "enabled": true, "tracked_members": 139, "total_xp": 20420,
    "leaderboard": [ { "position": 1, "user_id": "…", "display_name": "…",
      "xp": 4400, "messages": 2200, "level": 37 } ] },
  "voice": { "configured": true, "report_channel_id": "…", "pending_count": 0,
    "recent_reports": [ { "id": "…", "channel_id": "…", "channel_name": "staff",
      "started_at": "…", "ended_at": "…", "sent_at": "…",
      "duration_seconds": 10800, "unique_members": 7, "peak_members": 5 } ] },
  "backup": { "available": true, "latest_name": "novaguard-backup-…zip",
    "latest_size": 812440, "latest_size_text": "793.4 KB", "latest_at": "…",
    "ok": true, "warnings": [], "errors": [] },
  "updates": [ { "build": 39, "created_at": "…", "highlights": ["…"] } ]
}
```

### `POST /guilds/{guild_id}/actions/{action}`
Auth + Manage Server + Origin-guarded. Runs one audited dashboard action. Valid
actions:

- `backup_check`: extracts and verifies the newest backup archive without
  touching live data.
- `voice_test`: sends a preview voice report to this guild's configured voice
  report channel.
- `update_preview`: sends the latest saved update embed to this guild's
  configured update channel only.

```json
{ "ok": true, "action": "backup_check",
  "message": "Latest backup passed the restore check.",
  "backup": { "name": "novaguard-backup-…zip", "size_text": "793.4 KB",
    "ok": true, "warnings": [], "errors": [] } }
```

### `GET /guilds/{guild_id}/audit?limit=50`
Auth + Manage Server. Recent dashboard changes (max `limit` 200).
```json
{ "audit": [ { "username": "…", "user_id": "…", "action": "config_update",
  "changes": { "welcome_channel": 123 }, "created_at": "2026-07-12T14:00:00+00:00" } ] }
```

## Notes for the frontend

- Send `credentials: "include"` on every fetch so the session cookie rides along.
- Start login by navigating the browser to `/api/v1/auth/login` (a redirect, not
  a fetch). On `401`/`session_expired`, send the user back through it.
- Branch on `code`, not on `error` text — messages may change, codes are stable.
- Cross-origin dashboards must be added to `WEB_CORS_ORIGIN`, and the same origin
  must send `Origin` on mutations (browsers do this automatically).
