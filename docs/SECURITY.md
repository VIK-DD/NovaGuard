# NovaGuard — Security Audit & Hardening Reference

_Last reviewed: 2026-08-26 · Scope: Discord bot, SQLite/JSON state, backups,
dashboard API, Astro website, Cloudflare Worker and dependency manifests._

## Verdict

This document records implemented controls and checks; it is not a guarantee
that the service has no vulnerabilities. As of the review date, the locked
Python dependencies and Node dependencies pass their configured audits, and
the test suite covers the high-risk authorization, restore and edge-auth paths.
Residual risk still includes deployment posture, provider configuration,
credential handling, new dependency advisories and defects not represented by
the tests. Re-run the checks below for every release.

## Threat model

A self-hosted Discord bot on a home Raspberry Pi, exposing a small OAuth-gated
JSON API for a web dashboard. The adversaries we design against:

1. **Malicious Discord users** — crafting command input to escalate, spam, ping
   everyone, drain the AI budget, or corrupt state.
2. **Anonymous internet clients** — hitting the public API once it's tunnelled,
   trying auth bypass, CSRF, injection, or DoS.
3. **A leaked database file** — can it be replayed into a login or leak tokens?
4. **A compromised dependency or CI action** — supply-chain.

## Findings & controls

| Area | Control | Status |
|------|---------|--------|
| RCE / shell | No `eval`/`exec` or shell invocation; the bounded rclone call uses an argv list and fixed operation | ✅ guarded |
| Deserialization | No `pickle`/`yaml.load`/`__import__` of untrusted data | ✅ none |
| SQL injection | 100% parameterized queries (`?` placeholders) | ✅ none |
| Secrets | Env-only, `.env` git-ignored + untracked, no secrets in logs | ✅ |
| Tokens at rest | OAuth tokens Fernet-encrypted (key from client secret) | ✅ |
| Session ids | Cookie holds a 256-bit id; DB stores only its SHA-256 hash | ✅ |
| DB file perms | `chmod 600` on the SQLite files (owner-only) | ✅ |
| AuthN | Discord OAuth2, HttpOnly cookie, HMAC-signed state (double-submit) | ✅ |
| AuthZ | `Manage Server` required per guild; privileged cogs gated | ✅ |
| Input validation | Economy `Range`, web config validated, AI input capped | ✅ |
| Mentions | Global `allowed_mentions` blocks `@everyone`/role-ping injection | ✅ |
| CSRF | Origin check on mutations + SameSite + signed state | ✅ |
| CORS | Strict allow-list, never wildcard, credentials only for listed origins | ✅ |
| Rate limiting | Per-IP web buckets, per-user command cooldowns, button anti-spam | ✅ |
| AI cost | Input cap + per-user cooldown + global 30/min + 500/day ceiling | ✅ |
| Transport | HSTS on HTTPS, CSP (`default-src 'none'`), no-sniff, frame-deny | ✅ |
| Errors | Generic to users; full tracebacks only to the admin log channel | ✅ |
| Supply chain | Version caps, hash-locked `requirements.lock`, `pip-audit`, Actions pinned to SHA, Dependabot | ✅ |

## Layer notes

### Authentication & sessions
- Cookie `ng_session` is `HttpOnly` (no JS access → XSS can't steal it), `Secure`
  under HTTPS, and `SameSite` is configurable (`WEB_COOKIE_SAMESITE`).
- OAuth `state` is a self-verifying HMAC token — the login survives a bot
  restart and cannot be forged without the client secret.
- Tokens refresh under a per-session lock so parallel requests can't spend the
  single-use refresh token and log the user out.
- Sessions expire (7 days), are capped at 5 per user, and are GC'd hourly.

### Cross-origin cookie rule (important for a split-host deploy)
- **Same site** (incl. subdomains of one registrable domain, e.g.
  `app.novaguard.app` + `api.novaguard.app`): `WEB_COOKIE_SAMESITE=Lax`.
- **Different domains** (e.g. dashboard on Vercel, API on the Pi): set
  `WEB_COOKIE_SAMESITE=None` — Secure is forced on automatically, and the
  dashboard origin must be in `WEB_CORS_ORIGIN`.

### Supply chain
- `requirements.txt` = human-edited direct deps with major-version caps.
- `requirements.lock` = fully resolved, **hash-pinned** (`pip-compile
  --generate-hashes`). Production installs from the lock so a tampered or
  swapped package fails the hash check.
- CI audits both the direct version ranges and the exact production lock, then
  installs the lock with `--require-hashes` and imports the bot. Auditing the
  lock separately prevents a stale production pin from hiding behind a newer
  version selected from `requirements.txt`.
- GitHub Actions are pinned to commit SHAs; Dependabot keeps deps + Actions
  fresh via weekly PRs.

## Reading a ZAP report against novaguard.fun

Point the scan at the site and the spider will find the **Add to Discord** button
on `/setup/`. That link goes to `api.novaguard.fun/api/v1/invite`, which redirects
to `discord.com/oauth2/authorize` — so ZAP walks off our origin and starts
reporting Discord's headers back to us under our scan.

That is where every Medium alert in the last report came from. Check the URL
under an alert before touching any code:

| Alert | Reported on | Ours? |
|-------|-------------|-------|
| CSP: `script-src unsafe-eval` | `discord.com/oauth2/authorize` | ❌ Discord's CSP |
| CSP: `style-src unsafe-inline` | `discord.com/oauth2/authorize` | ❌ Discord's CSP |
| CSP: Failure to Define Directive with No Fallback | `discord.com/oauth2/authorize` | ❌ Discord's CSP |
| Cross-Domain Misconfiguration ×3 | `discord.com/cdn-cgi/…`, `novaguard.fun/cdn-cgi/…`, `static.cloudflareinsights.com/beacon.min.js` | ❌ Cloudflare's |

Note the middle one: `/cdn-cgi/*` is on our hostname but is served by Cloudflare's
edge **before** the Worker runs, so nothing in `website-3/worker/` can set headers
on it. The `beacon.min.js` hit is Cloudflare Web Analytics, injected at the edge —
it is not in our source either. Turning Web Analytics off in the Cloudflare
dashboard is the only way to drop that one. While it remains enabled, its
performance measurements and Cloudflare's stated privacy properties are
disclosed in the public privacy policy.

The Low and Informational rows split the same way. What was genuinely ours has
been fixed; the rest is either another host's or not a defect at all:

| Alert | Whose | Disposition |
|-------|-------|-------------|
| Timestamp Disclosure — Unix | ours | **Fixed.** The `/api/status-snapshot?t=…` cache-buster published the visitor's own clock. Both callers already send `cache: "no-store"` and the worker keys its edge cache on the bare path, so the parameter was removed outright. |
| User Controllable HTML Element Attribute (×2) | ours | **Fixed.** The `?next=` value reaching the login form's hidden input. The client now parses it with `new URL` exactly as the worker's `safeNext()` does. |
| Information Disclosure — localStorage | ours | **Won't fix.** It is `ng-theme`, a light/dark preference. ZAP flags any `localStorage` write; dropping it buys a theme flash on every page load and no security. |
| Information Disclosure — sessionStorage | not ours | `ng_mock_session` exists only in the dev mock API and is absent from the production bundle — verify with `grep -r ng_mock_session website-3/dist/`. |
| Cookie with SameSite Attribute None | Cloudflare | `__cf_bm`. Our cookies are `SameSite=Lax` (session) and `Strict` (CSRF). |
| Loosely Scoped Cookie | Cloudflare | Same `__cf_bm`, which carries `Domain=.novaguard.fun`. Ours set no `Domain` at all, so they are host-only — the tight scope this rule asks for. |
| Strict-Transport-Security Not Set | Cloudflare | Raised on `/cdn-cgi/*`. Every response the Worker produces carries HSTS via `SECURITY_HEADERS`. |
| X-Content-Type-Options Missing | Cloudflare | Same `/cdn-cgi/*` path; we set `nosniff` on everything we serve. |
| Modern Web Application | — | Not a finding. ZAP raises it on any site that uses JavaScript. |
| User Agent Fuzzer | — | Output of the fuzzer rule itself, not a vulnerability. |
| Re-examine Cache-control / Retrieved from Cache | — | Informational. Password-gated pages are already `private, max-age=60` or `no-store`; see `assetCacheControl()`. |

Two rows still need their URL checked before anyone acts on them — expand them in
ZAP and read the host first. **Private IP Disclosure** matches no address in this
repo (`grep -rE '10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.' website-3/`), and
**Sensitive Information in URL** is most likely the `client_id` and `redirect_uri`
on Discord's own `oauth2/authorize`.

**Scope the scan** so this does not recur every time: in ZAP, put
`https://novaguard\.fun/.*` in the context and enable *Scan only in scope*. Our
own responses carry `script-src 'self' 'nonce-…'` with no `unsafe-eval` or
`unsafe-inline`, and define all four directives that do not fall back to
`default-src` (`base-uri`, `form-action`, `frame-ancestors`, `object-src`), so
none of the three CSP rules can fire on a page we serve. See
`contentSecurityPolicy()` in `website-3/worker/index.js`.

## Residual / accepted risks
- **Host compromise of the Pi** is out of scope for app code — mitigate with OS
  updates, SSH key-only auth, and the network posture below.
- **Discord token / client secret leakage** would require re-issuing them; rotate
  periodically (see runbook).
- **AI answer content** is model-generated; treated as untrusted display text
  (rendered in embeds, which never execute markup).

---

# Operational security runbook

## 1. Reproducible, hash-verified deploy (the Pi)
```bash
cd ~/pythonbot && git pull
.venv/bin/pip install --require-hashes -r requirements.lock
pm2 restart pythonbot
```
Regenerate the lock only when you change `requirements.txt`:
```bash
pip install uv
uv pip compile --universal --generate-hashes --python-version 3.11 -o requirements.lock requirements.txt
```

## 2. Expose the API safely — Cloudflare Tunnel + WAF
Keep the Pi's ports closed; publish only through Cloudflare so the home IP is
never exposed and you get HTTPS + a WAF for free.

**Tunnel**
```bash
# on the Pi
curl -L https://pkg.cloudflare.com/cloudflared-linux-arm64 -o cloudflared && sudo install cloudflared /usr/local/bin/
cloudflared tunnel login
cloudflared tunnel create novaguard
cloudflared tunnel route dns novaguard api.novaguard.app
# config.yml → ingress: api.novaguard.app -> http://localhost:8300
cloudflared tunnel run novaguard
```
Then in `.env`: `WEB_COOKIE_SECURE=true`, `WEB_TRUST_PROXY=true`, and
`WEB_CORS_ORIGIN=https://<your-dashboard-origin>`.

**WAF & rate limiting (Cloudflare dashboard → your domain → Security)**
- **WAF → Managed Rules:** enable the Cloudflare Managed Ruleset (OWASP core).
- **Rate limiting rules:** add a rule on `api.novaguard.app/api/*` →
  e.g. 100 requests / 10s per IP → *Block* for 1 min. This sits *in front of*
  the app's own per-IP limiter (defense in depth).
- **Bot Fight Mode:** on (blocks known bad bots).
- **Security Level:** Medium/High; enable **Always Use HTTPS** and **HSTS** at
  the edge too.
- Optionally lock the dashboard behind **Cloudflare Access** (email/OTP) while
  it's pre-launch.

## 3. Secret rotation
- Rotate the Discord **bot token** and **OAuth client secret** from the Discord
  Developer Portal if ever exposed; update `.env` and restart.
- Rotating the client secret re-keys token encryption → all users simply
  re-login (expected, safe).

## 4. Backups (off the SD card)
SD cards fail. Set a unique `BACKUP_ENCRYPTION_KEY` (32+ random characters),
keep it in a password manager, and copy only authenticated `.ngbackup` files
off the host on a schedule. NovaGuard encrypts both full archives and per-guild
exports with AES-256-GCM and refuses to upload plaintext ZIP files. Never post
backups in Discord or commit them to Git; access to the storage destination and
the encryption key must be separated where practical.

The pseudonymous `.privacy_deletions.json` ledger is deliberately kept outside
normal snapshots and mirrored as an encrypted off-site object. Never bypass it
during restore: doing so can resurrect data that was already erased after a
valid user or server deletion request.

## 5. Verification
- `python tests/test_webserver.py` → 30 checks (auth, CORS, CSRF, encryption,
  rate-limit, error envelope, both SameSite modes).
- CI runs compile + import smoke + the dashboard test + `pip-audit` + a
  hash-locked install, on every push.
