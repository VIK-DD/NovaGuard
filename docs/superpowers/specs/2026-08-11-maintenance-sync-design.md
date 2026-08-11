# Maintenance sync — design

**Date:** 2026-08-11
**Status:** approved, ready for an implementation plan

## What we are building

`/maintenance enable` in Discord already stops the bot from answering ordinary
users. It should also close the website dashboard, with the same reason shown in
both places, without anyone editing config or redeploying.

## Where things stand today

Both halves exist and neither knows about the other.

| Half | State lives in | How it changes |
|---|---|---|
| Bot | `data/maintenance.json` on the VPS, via `core/maintenance.py` | `/maintenance enable\|disable\|status`, owner only |
| Website | `env.MAINTENANCE_MODE`, read at `worker/index.js:126` | Edit `wrangler.jsonc`, redeploy |

`website-3/src/pages/maintenance.astro` is a finished page that has never been
served: `MAINTENANCE_MODE` appears in no `vars` block, so the gate has never
fired. A second, older path exists as a commented-out rule in
`public/_redirects` pointing at `/coming-soon/`.

The link is short. The worker already fetches `api.novaguard.fun/api/v1/health`
every 30 seconds to build `/api/status-snapshot`. That response carries `ok`,
`bot_ready` and `db_ok` — it just does not carry maintenance state yet.

## Decisions

**Scope: the dashboard, not the whole site.** `/maintenance` closes
`/dashboard/*`. The homepage, updates and terms stay up. A two-minute bot
restart should not take the marketing site down, and the page's own copy —
*"Protected pages are paused"* — already says exactly this.

**Two levers, kept separate.** `/maintenance` from Discord closes the dashboard
automatically. `MAINTENANCE_MODE` in Cloudflare stays as the manual whole-site
override; it is the one that still works when the bot is dead. Neither replaces
the other.

**Fail closed, after a grace period.** The dashboard cannot function without the
API, so when `/health` is unreachable the maintenance page is more honest than a
dashboard full of network errors. But not on the first failure: the last known
state stands for two minutes, which makes an ordinary `pm2 restart` invisible.

**One message, two surfaces.** The text typed into `/maintenance enable
message:"…"` becomes both the Discord presence and a line on the website page.

**`/maintenance` moves behind the admin key.** Today it checks owner identity
only. Now that the command closes a public surface and not just the bot, both
`enable` and `disable` require an unlocked admin session — the same second
factor `/admin unlock` already grants for fifteen minutes.

**The page is rethemed after the Coming Soon face** and rewritten standalone.

## Architecture

### 1. The bot reports its state

`handle_health` in `core/webserver.py` gains one field:

```json
{
  "ok": true,
  "bot_ready": true,
  "db_ok": true,
  "maintenance": { "enabled": true, "message": "Se lucrează la muzică" }
}
```

When maintenance is off the object is `{"enabled": false}` with no `message`, so
yesterday's text cannot linger in a public payload.

`load_maintenance_state()` reads a file, so it goes through `asyncio.to_thread`
like `db_ping` beside it. Nothing blocking runs on the event loop.

`/health` keeps returning 200 while maintenance is on. The endpoint answers "is
this API alive", not "is the site open"; conflating the two would make the status
widget report an outage during a routine update.

No new commands. `/maintenance` keeps its shape; its confirmation embed gains a
line saying the dashboard closed too.

### 1b. The command moves behind the admin key

`ensure_maintenance_manager` in `cogs/system.py` is replaced by the existing
`require_admin(interaction, self.bot, action=…)` from `cogs/admin.py`, which
already sends its own refusal embed and records denied attempts in the audit
trail. `enable` records `maintenance.enable`, `disable` records
`maintenance.disable`. The old owner-identity helper is deleted rather than left
beside its replacement.

There is no circular lockout. `bot.py:101` lets the owner past the maintenance
block regardless, so `/admin unlock` still runs while maintenance is on.

Two escape hatches exist for a lost key, and both are documented in `SETUP.md`:
`python tools/admin_key.py --rotate` issues a new key from the VPS, and deleting
`data/maintenance.json` clears the state outright.

### 2. The worker reads it and gates the dashboard

A new `readMaintenance(request, env, ctx)` returns `{enabled, message}`:

- Edge cache key `${origin}/api/maintenance-state`, holding
  `{enabled, message, fetchedAt}`.
- Entry younger than **30 s** is returned as-is.
- Otherwise fetch `${apiBase}/health` with a **2.5 s** timeout, then cache and
  return. `apiBase` is resolved exactly as the status snapshot already resolves
  it: `env.STATUS_API_BASE || DEFAULT_STATUS_API_BASE`, trailing slashes
  stripped.
- On any failure, return the cached entry if it is younger than **120 s**.
- Past that, return `{enabled: true}` — fail closed.

Age is computed from the stored `fetchedAt`, not from HTTP cache age, so the
grace window is explicit and directly testable.

The gate runs **only** on `/dashboard/*`, after the existing session check.
Public pages issue no extra request and pay nothing.

```
/dashboard/*  →  readMaintenance()  →  enabled ? maintenance page : dashboard shell
```

Worst-case propagation after `/maintenance enable` is one cache window, about
30 seconds.

### 3. The message reaches the page

`serveMaintenancePage` fetches the static asset and pipes it through
`HTMLRewriter`, filling the element marked `data-maintenance-message`.
`setInnerContent` escapes by default, so the injected text cannot introduce
markup even though only the owner can set it. With no message the element is
removed and the page reads as it would on its own.
`normalize_maintenance_message` already collapses whitespace and caps the string
at 120 characters, so no second limit is needed.

The response carries **`Cache-Control: no-store`**, status **503** and
**`Retry-After: 120`**. Without `no-store`, a browser or CDN would keep serving
the maintenance page after maintenance ended — a failure that only shows up an
hour later, to one person.

### 4. The page, rebuilt

`maintenance.astro` is rewritten **standalone**, without `Base.astro`. This page
has to render precisely when something else is broken, so every dependency it
drops is one less way for it to fail.

It adopts the Coming Soon composition and palette:

| Token | Dark (default) | Light |
|---|---|---|
| background | `#0a0a0a` | `#fafafa` |
| foreground | `#f5f5f5` | `#101010` |
| muted | `#8a8a8a` | `#747474` |
| line | `#2a2a2a` | `#dedede` |

Wordmark at `clamp(3rem, 10vw, 8rem)`, weight 800, tracking `-0.075em`,
line-height `0.9`. Mono eyebrow at `0.08em` tracking. Transitions at `0.18s
ease`. The 36 px round theme toggle sits top-right, same as Coming Soon.

**Fonts: Manrope and DM Mono from Google Fonts**, matching Coming Soon exactly,
loaded with `preconnect` and `display=swap` so the text paints immediately in a
system fallback rather than leaving the page blank if Google is slow.

**Theme storage:** Coming Soon writes `localStorage["ng-maintenance-theme"]`; the
rest of the site writes `ng-theme`. The page reads both, prefers `ng-theme`, and
writes both, so a theme picked on one surface holds on the other.

Structure, top to bottom: theme toggle · NovaGuard wordmark · mono eyebrow ·
fixed explanatory line · `<p data-maintenance-message>` (empty, hidden via
`:empty { display: none }` so a direct visit outside maintenance looks right) ·
Sign out link, restyled in the toggle's border language · credit line.

Dropped from the Coming Soon layout: the countdown, which means nothing here,
and the Spotify link — this page should be quiet.

## Failure handling

| Situation | Behaviour |
|---|---|
| `/health` 5xx, timeout, or network error | Cached state if under 120 s old, else maintenance |
| Malformed JSON from `/health` | Treated as a failure, same path |
| `maintenance` field absent | **Not** maintenance — never a failure |
| Maintenance page asset itself missing | Fall through to the dashboard shell rather than serving nothing |

The absent-field rule is what makes deployment order irrelevant. The worker will
be live before the bot restarts with the new `/health`; if a missing field read
as an error, the dashboard would black out in the gap between the two deploys.

## Testing

**Worker** (`website-3/worker/index.test.js`, existing vitest suite):

- maintenance on → `/dashboard/` serves the maintenance page, status 503
- maintenance off → `/dashboard/` serves the dashboard shell
- deep link `/dashboard/g/123` follows the same branch in both states
- upstream fails, cache under 120 s → last known state
- upstream fails, cache older than 120 s or absent → maintenance
- `maintenance` field missing from `/health` → not maintenance
- message is injected into `data-maintenance-message`
- markup in a message is escaped, not rendered
- no message → the element is removed
- public paths trigger no upstream request
- maintenance response carries `no-store`

**Python** (new `tests/test_maintenance_health.py`, `unittest`, standalone-runnable
with the `sys.path` insert every other test file has):

- `/health` reports `enabled: true` with the message when maintenance is on
- `/health` reports `enabled: false` and **no** message when off
- `/health` still returns 200 while maintenance is on

**Admin gate** (extending `tests/test_admin_gate.py`, which already covers this
pattern for other commands):

- `/maintenance enable` refused when the admin session is locked
- `/maintenance disable` refused when the admin session is locked
- both proceed once the session is unlocked
- a refusal is written to the audit trail

## Out of scope

The public status widget keeps reporting `ok` only — it does not turn amber
during maintenance. No ETA or countdown on the page. No history of past
maintenance windows. The `/coming-soon/` redirect rule in `_redirects` stays as
it is.

## Deployment notes

Order does not matter, but nothing reaches production until two things happen
that are outside this work: `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`
must be set as repository secrets, and the website must deploy at least once —
it has not been redeployed since the August audit began.
