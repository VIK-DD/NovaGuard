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
| `invalid_state` | 400 | OAuth `state` mismatch — restart login |
| `unauthorized` | 401 | No / expired session cookie |
| `session_expired` | 401 | Discord token could not be refreshed |
| `forbidden` | 403 | Lacks Manage Server on the guild |
| `bad_origin` | 403 | Cross-origin mutation blocked (CSRF guard) |
| `guild_not_found` | 404 | Bot is not in that guild |
| `not_found` | 404 | Unknown route |
| `rate_limited` | 429 | Per-IP rate limit hit (`Retry-After`) |
| `upstream_rate_limited` | 429 | Discord is rate-limiting the bot |
| `upstream_error` | 502 | Discord API failure |
| `bot_starting` | 503 | Bot not ready yet — retry shortly |
| `oauth_unavailable` | 503 | OAuth not configured on the bot |
| `internal_error` | 500 | Unexpected server error (details logged, not returned) |

## Rate limits (per client IP, sliding window)

| scope | limit | endpoints |
|-------|-------|-----------|
| auth | 10 / min | `/auth/login`, `/auth/callback` |
| read | 120 / min | `/stats`, `/me`, `/guilds`, `/guilds/*/config` (GET), `/guilds/*/audit` |
| write | 30 / min | `/guilds/*/config` (PUT) |

## Endpoints

### `GET /health`
Public. `200` when the DB is reachable, `503` otherwise.
```json
{ "ok": true, "bot_ready": true, "db_ok": true }
```

### `GET /stats`
Public. Bot-wide counters.
```json
{ "version": "…", "codename": "…", "guilds": 3, "members": 512,
  "commands": 78, "uptime_seconds": 8123, "ready": true }
```

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
```json
{
  "guild": { "id": "…", "name": "…", "icon": "…|null", "member_count": 42 },
  "settings": {
    "welcome_channel": "…|null", "goodbye_channel": "…|null",
    "log_channel": "…|null", "voice_report_channel": "…|null", "update_channel": "…|null",
    "github_event_channel": "…|null", "error_log_channel": "…|null",
    "autorole": "…|null", "ticket_staff_role": "…|null",
    "automod": { "invites": true, "spam": true, "badwords": ["…"] }
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

```json
{ "welcome_channel": "123", "autorole": "456",
  "automod": { "invites": false, "badwords": ["spoiler"] } }
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
