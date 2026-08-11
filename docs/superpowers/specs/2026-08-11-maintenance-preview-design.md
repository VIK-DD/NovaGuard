# Maintenance preview access — design

**Date:** 2026-08-11
**Status:** approved, ready for an implementation plan

## What we are building

`/maintenance enable` closes the whole site. The operator still needs to walk
through it — to check an update before anyone else sees it. This adds a code,
generated fresh each time maintenance starts, that opens the closed site for
whoever holds it.

## The constraint that shapes everything

`GET /api/v1/health` is **public**. It is how the worker learns that maintenance
is on, and anyone can read it. The code can never travel on it — not in plain
text, and not as a hash, which would hand out material for an offline attack.
Verification has to happen somewhere private.

## Decisions

**A new code every time maintenance starts.** Not a fixed password. A code
shared with someone last week must not open the site this week.

**Rotated on the off → on transition only.** Running `enable` again while
maintenance is already on — to correct the message — keeps the current code.
Otherwise every wording fix would silently lock the operator out of their own
open session.

**Shown exactly once,** in the ephemeral Discord reply. Only the hash is stored.

**No link to it from anywhere.** The form lives at `/preview/`. The maintenance
page does not mention it, so nobody tries a door they cannot see. Sharing means
sharing two things: the address and the code.

**Access lasts 12 hours, and dies when maintenance restarts.**

## Approach: the worker asks the bot

Three ways to verify a submitted code were considered.

| Rejected approach | Why |
|---|---|
| Worker reads a hash from an authenticated bot endpoint and verifies locally | Sensitive material ends up in two places, and a third shared secret has to be managed |
| Worker derives the code from a Cloudflare secret; the bot fetches it to display | Inverts the trust without removing it — the bot must then authenticate to the worker — and the code becomes derivable if the algorithm leaks |

**Chosen:** the worker forwards the submitted code to the bot, which compares it
against the stored hash and answers yes or no. One secret, one owner, nothing
sensitive on a public endpoint, and a wrong guess costs an attacker a
rate-limited round trip.

It also reuses machinery that already exists and is already tested:
`core/admin_auth.py` has `generate_key`, `hash_key` and `verify_key` on scrypt,
plus failure counting and lockout.

## Architecture

### Bot

**Generating.** `save_maintenance_state(True, …)` gains a code when the previous
state was off. `data/maintenance.json` grows two fields — `preview_hash` and
`preview_salt` — and never the code itself. Turning maintenance off clears both.

**Showing.** The "Maintenance Enabled" embed gains the code in its own field,
with a line saying it will not be shown again and which address to use it at.
The reply is already ephemeral and already behind `/admin unlock`.

**Verifying.** A new route, `POST /api/v1/maintenance/preview`:

```json
→ {"code": "ng_preview_…"}
← 200 {"ok": true, "since": "2026-08-11T06:16:05+00:00"}
← 401 {"error": "…", "code": "invalid_preview_code"}
```

`since` is the current activation's timestamp. It is not a secret — it only says
when maintenance began — and the worker needs it to bind the cookie.

Every failure answers identically: a wrong code, an expired code, a code sent
when maintenance is off. Nothing tells a guesser they are close, or even that a
code currently exists.

**Throttling has to account for the proxy.** Every request arrives from a
Cloudflare edge address, so a per-IP lockout like the admin key's would let one
attacker lock out everyone. Instead the endpoint carries a global cap through
the existing `_rate_limit`, and a per-visitor counter keyed on the
`CF-Connecting-IP` the worker forwards. That header is advisory — the endpoint
is public, so anyone can post one — which is why the global cap is the real
limit and the per-visitor counter only sharpens it. The code itself is 24 random
bytes; guessing it is not the threat model, and throttling is depth, not the
wall.

**Publishing.** The `maintenance` object on `/health` gains `since`, so the
worker can tell one activation from the next. No hash, no salt, no code.

### Worker

`/preview/` serves a small form in the maintenance page's theme. Submitting it
posts to the worker, which calls the bot's endpoint. On success the worker sets
`ng_preview`, an HttpOnly, Secure, SameSite=Lax cookie signed with
`AUTH_PASSWORD` — the same signing the soft-launch session cookie already uses —
carrying the activation's `since` value and a 12-hour expiry.

The maintenance gate checks the cookie first. A valid one whose `since` matches
the current activation skips the maintenance page, and the site behaves
normally. A cookie from an earlier activation is ignored, which is what makes
last week's code worthless.

An unreachable bot means **no** bypass. Failing closed on the door is the
opposite of failing closed on the site, and both are the safe direction.

### The Sign out button

It is removed from the maintenance page. It made sense when maintenance covered
only routes reached after the soft-launch password; now the gate runs before
that check, so clearing the session changes nothing a visitor can see. The
button pointed at `/api/auth/logout`, which still clears the cookie and
redirects to `/login/` — a page that is itself closed during maintenance, so the
visible result was nothing at all.

## Failure handling

| Situation | Behaviour |
|---|---|
| Wrong, expired, or absent code | 401, one generic message |
| Maintenance not on | Same 401, same message |
| Repeated failures | Throttled globally, and per forwarded visitor address; generic message with the wait |
| Bot unreachable from the worker | No cookie set; the form says to try again |
| Cookie from a previous activation | Ignored; the maintenance page is served |

## Testing

**Python** (extending `tests/test_webserver.py`):

- enabling from off generates a code; the plaintext is never written to the file
- enabling again while already on keeps the existing hash
- disabling clears hash and salt
- `/health` carries `since` but never `preview_hash`, `preview_salt`, or a code
- the verify route accepts the right code and rejects a wrong one
- a wrong code and a code sent while maintenance is off return identical bodies
- repeated failures are throttled, and one visitor's failures cannot lock out
  another arriving through the same proxy address

**Worker** (`website-3/worker/index.test.js`):

- `/preview/` serves the form while maintenance is on
- a valid code sets `ng_preview`, and the next request gets the real site
- a cookie whose `since` predates the current activation is ignored
- an invalid code sets no cookie
- the bot being unreachable sets no cookie
- the maintenance page contains no link to `/preview/`

## Out of scope

No per-person codes, and no audit of who used one. No expiry other than the
twelve hours and the activation binding. No preview access while maintenance is
off — there is nothing to preview then.
