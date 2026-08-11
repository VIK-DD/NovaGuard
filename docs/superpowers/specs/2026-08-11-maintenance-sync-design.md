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

**Scope: the whole site.** `/maintenance` closes every page — `/`, `/home`,
`/updates`, `/terms`, the dashboard. Only the assets the maintenance page is
itself built from keep answering, or it could not render.

*Revised 2026-08-11.* This first read "the dashboard only, so a restart cannot
take the marketing site down". The operator wanted the stronger version: if
NovaGuard is being worked on, the site says so, everywhere.

**But an outage is not maintenance.** Deliberate maintenance closes everything.
An unreachable `/health` closes only the dashboard, which genuinely cannot work
without the API — the marketing pages never needed the bot, so a dead API is no
reason to take them down too. The two cases are told apart by the `unreachable`
flag on the state the worker computes.

The gate runs **before** the soft-launch password check, so a visitor with no
session sees the notice instead of a login form for a site that is shut anyway.

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

**The admin key already guards `/maintenance`, and stays that way.** The command
calls `require_admin` before it does anything, so `enable`, `disable` and
`status` all need the unlocked session `/admin unlock` grants for fifteen
minutes. Closing a public surface as well as the bot does not change that
requirement — it justifies it. No work here; it is written down because the
website half now depends on it.

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

### 1b. Access, for the record

`/maintenance` already runs `require_admin(interaction, self.bot,
action="maintenance")` as its first act, and `tests/test_admin_gate.py` pins
that. It then also calls `ensure_maintenance_manager`, an owner-identity check
that `require_admin` subsumes. The two use different owner definitions
(`is_bot_owner` versus `user_can_bypass_maintenance`), so the redundancy is left
alone: collapsing them would quietly change who is allowed, which is not this
change's business.

There is no circular lockout. `bot.py:101` lets the owner past the maintenance
block regardless, so `/admin unlock` still runs while maintenance is on.

Two escape hatches exist for a lost key: `python tools/admin_key.py` issues a new
one from the VPS, and deleting `data/maintenance.json` clears the state outright.

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

No new admin-gate tests: `tests/test_admin_gate.py` already asserts that
`/maintenance` calls `require_admin`, and that assertion keeps holding.

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
