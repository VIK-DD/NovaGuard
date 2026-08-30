# NovaGuard — Security Audit & Hardening Reference

_Last reviewed: 2026-08-30 (two passes) · Scope: Discord bot, SQLite/JSON state, backups,
dashboard API, Astro website, Cloudflare Worker and dependency manifests._

## Verdict

This document records implemented controls and checks; it is not a guarantee
that the service has no vulnerabilities. As of the review date, the locked
Python dependencies and Node dependencies pass their configured audits, and
the test suite covers the high-risk authorization, restore and edge-auth paths.
Residual risk still includes deployment posture, provider configuration,
credential handling, new dependency advisories and defects not represented by
the tests. Re-run the checks below for every release.

### What the 2026-08-30 review changed

The previous revision of this table asserted controls that the code did not
implement. That is worse than not claiming them, so the corrections are listed
here rather than quietly folded into the rows above.

- **Errors.** The table said "full tracebacks only to the admin log channel".
  `send_error_digest` resolved the admin channel into a local named `channel`
  and the interaction block then rebound that same name to
  `interaction.channel`, so every slash-command traceback was published in the
  public channel the member typed the command in. Fixed; `tests/test_error_digest.py`
  now asserts the destination, which nothing did before.
- **AuthZ.** "Privileged cogs gated" was true of the owner commands and untrue
  of seven command groups, which carried `default_permissions` and no run-time
  check. `default_permissions` is a default: a server administrator can
  override it in Server Settings → Integrations. The groups now enforce their
  own permission (`core/command_guards.py`).
- **Role assignment.** Not previously a row at all, and the gap it hid was the
  worst finding of the review: nothing that handed out a role ever looked at
  what the role could *do*, so Manage Server alone was enough to make an
  Administrator role self-assignable through a panel or an autorole. One rule
  now governs all six paths (`core/role_safety.py`).
- **Input validation.** `parse_duration` had no ceiling, so `/remind 99999999999w`
  raised out of `timedelta` and reached the global error handler - which, before
  the first item above, published a traceback in public.
- **Least privilege.** The invite requested `mention_everyone`, which no code
  path has ever used.

The lesson worth keeping: every row below is now expected to name the test that
holds it up. A control with no test is a claim, and this table has already been
wrong once.

### What the second, deeper pass found

The first pass covered the web/auth layer, the cogs' permission model and the
recovery path. A second pass went after the surfaces it had only skimmed —
the GitHub integration, the changelog engine, the React dashboard, CI and
deployment — with four reviewers working independently and every finding
re-verified against the code before being accepted.

The two that mattered most were both *injection into a path*:

- **The GitHub token could be steered.** `GitHubAPI.get_json` formats its URL
  as a string and aiohttp resolves dot segments through yarl, so
  `/github username:../user` turned `/users/<name>` into `/user` and
  `/users/<name>/repos` into `/user/repos` — the authenticated-user endpoints,
  under the operator's `GITHUB_TOKEN`, which lists **private** repositories.
  `/github` has no permission check and renders publicly, so any member could
  run it. Every path segment is percent-encoded now, and the
  repository-scoped commands accept only configured repositories.
- **The dashboard sent guild ids into API paths unencoded.** TanStack Router
  percent-decodes a path param, so `/dashboard/g/..%2F..%2Fadmin` arrived as
  `../../admin` and the browser collapsed it — an authenticated, preflight-free
  request to an attacker-chosen API path.

And two cross-boundary mistakes:

- **Giveaways were addressed by message id alone**, across a store shared by
  every guild, so a manager in one server could end and repeatedly reroll a
  giveaway running in another.
- **`safeNext` checked its input and returned its output.** `/..//evil.example`
  is not protocol-relative going in and is coming out, making the login
  endpoint an open redirect on the site's own domain.

The rest were denial-of-service and disclosure: unclamped text reaching
Discord's embed limits (a 257-character `/poll` was enough to force an admin
error digest), a `save_json_file` that shared one scratch filename between
writers and left state world-readable, an AST cycle that could permanently
stop the changelog engine, `/ghwatch` publishing the host's configuration to
anyone, and autocomplete callbacks bypassing the group permission check
because discord.py never runs `_check_can_run` for suggestions.

Full detail is in the commit messages on `security/audit-fixes`.

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

Every row names the test that holds it up, so a claim here can be checked
rather than believed.

| Area | Control | Held up by |
|------|---------|------------|
| RCE / shell | No `eval`/`exec` or shell invocation; the bounded rclone call uses an argv list and fixed operation | `bandit` in CI (`ci.yml`) |
| Deserialization | No `pickle`/`yaml.load`/`__import__` of untrusted data | review |
| SQL injection | 100% parameterized queries; the few f-string identifiers come from module constants, each annotated and re-verified | `bandit` in CI, `test_audit_filter.py` |
| Secrets | Env-only, `.env` git-ignored + untracked, no secrets in logs | `test_config_check.py` |
| Tokens at rest | OAuth tokens Fernet-encrypted (dedicated `WEB_TOKEN_KEY`, client secret as legacy read) | `test_webserver_token_encryption.py` |
| Session ids | Cookie holds a 256-bit id; DB stores only its SHA-256 hash | `test_webserver.py` |
| DB file perms | `chmod 600` on the SQLite files (owner-only) | `test_production_check.py` |
| Archives at rest | AES-256-GCM, scrypt KDF, authenticated header, per-file salt+nonce | `test_secure_files.py` |
| AuthN | Discord OAuth2, HttpOnly cookie, HMAC-signed state (double-submit) | `test_webserver.py`, `test_dashboard_auth.py` |
| AuthZ — dashboard | `Manage Server` to read/write config; **`Manage Roles` additionally** to publish a role panel or set an autorole; a write re-checks permissions no more than 30s stale | `test_webserver.py` |
| AuthZ — owner commands | Application owner or team, **plus** a scrypt-hashed admin key, in-memory unlocks, 5-try lockout | `test_admin_auth.py`, `test_admin_gate.py` |
| AuthZ — command groups | Every configuration group enforces its permission at run time, nested subgroups included — `default_permissions` alone is only a default a server admin can override | `test_command_guards.py` |
| Role assignment | A role carrying privileged permissions is never self-assignable; a configurer cannot expose a role above their own position; re-checked at click and join time | `test_role_safety.py` |
| Input validation | Economy `Range`, web config validated, AI input capped, durations bounded so hostile input returns `None` rather than raising | `test_utils.py`, `test_levels_settings.py`, `test_economy_settings.py` |
| Mentions | Global `allowed_mentions` blocks `@everyone`/role-ping injection; the invite no longer requests `mention_everyone` at all | `test_invite_permissions.py` |
| CSRF | A mutation needs a valid `Origin` **or** a JSON content type, plus SameSite and the signed state (bot API); `__Host-` double-submit token (Worker) | `test_webserver.py`, `website-3/worker/index.test.js` |
| CORS | Strict allow-list, never wildcard, credentials only for listed origins | `test_webserver.py` |
| Rate limiting | Per-IP web buckets; the Worker's login gate keyed per client, not route-wide; per-user cooldowns on every command that walks the store; button anti-spam | `test_command_cooldowns.py`, `test_webserver.py`, `website-3/worker/index.test.js` |
| AI cost | Input cap + per-user cooldown + global 30/min + 500/day ceiling | `test_ai_settings.py` |
| Transport | HSTS on HTTPS, CSP (`default-src 'none'`), no-sniff, frame-deny | `test_api_security_headers.py` |
| Errors | Generic to users; full tracebacks only to the configured admin log channel, never to the channel the command came from | `test_error_digest.py` |
| Outbound requests | Every GitHub path segment is percent-encoded; repository commands accept only configured repositories | `test_github_api_safety.py` |
| Cross-guild isolation | Giveaway end/reroll match on guild as well as message id; the dashboard scopes every guild lookup | `test_giveaway_scope.py` |
| Embed limits | Member- and repository-supplied text is clamped, and free-text options declare a maximum length | `test_embed_limits.py` |
| State files | Atomic writes with a private scratch file, owner-only mode, fsync; settings patches in one transaction | `test_storage_durability.py` |
| Redirects | `safeNext` re-checks its normalized output, in the Worker and its client mirror | `website-3/worker/index.test.js` |
| CI permissions | Both workflows declare `contents: read` rather than inheriting the repo default | `.github/workflows/ci.yml` |
| Supply chain | Version caps, hash-locked `requirements.lock`, `pip-audit`, `npm audit`, Actions pinned to SHA, Dependabot | `.github/workflows/ci.yml` |

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
on it. The `beacon.min.js` hit came from Cloudflare Web Analytics, injected at
the edge — it was never in our source. Web Analytics/RUM was disabled in the
Cloudflare dashboard on 28 August 2026, so new responses no longer receive the
beacon after edge propagation. The public privacy policy records that disabled
state while continuing to disclose Cloudflare's network-level processing.

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

All eight items this review recorded as "known and deliberately not fixed"
have since been fixed — the list is kept below with what was done, because a
security document that quietly deletes its own open items teaches the reader
nothing about how it is maintained.

| Was | Now |
|-----|-----|
| Mutations allowed a missing `Origin`, leaving a `text/plain` simple cross-origin POST unguarded | A mutation needs a valid `Origin` or a JSON content type; a wrong `Origin` is always refused (`test_webserver.py`) |
| `WEB_HOST` defaulted to `0.0.0.0` | Defaults to `127.0.0.1`, matching the tunnel deployment the docs already describe |
| OAuth token key was a single SHA-256 | scrypt, with the old derivations kept as read-only fallbacks so no one is logged out (`test_webserver_token_encryption.py`) |
| Guild permissions cached 120s for reads *and* writes | Writes require a permission set no older than 30s; reads keep the long cache |
| `/gamble`, `/slots` and crates drew from Mersenne Twister | `secrets.SystemRandom` |
| The ticket close button archived whatever thread it was pressed in | Checks the thread is a tracked ticket and the clicker opened it or holds Manage Threads |
| The Worker's login limiter used one route-wide key | Keyed per client on a hashed address; a missing address still lands in a capped bucket (`website-3/worker/index.test.js`) |
| The audit `actor` filter passed LIKE wildcards unescaped | Escaped, with `ESCAPE` declared per clause (`test_audit_filter.py`) |

What genuinely remains, and why:

- **`core/secure_files.py` uses scrypt at `n=2**14`**, below current guidance
  for passphrase input. Raising it is not a one-line change: the parameters
  are not stored in the archive header, so a new cost factor makes every
  existing backup undecryptable. That trade — a stronger KDF against a broken
  restore path — is the wrong way round, and `BACKUP_ENCRYPTION_KEY` is
  required to be at least 32 characters. Fixing it properly means a format
  version that carries its own parameters.
- **The token KDF salt is fixed**, not per-install. There is nowhere to keep a
  random one: the key must be derivable from the environment alone at import,
  with no stored state to read. The salt buys domain separation; the work
  factor does the rest.
- **A dashboard write can still use a permission set up to 30 seconds old.**
  Closing that completely means an upstream call per write, which puts
  Discord's availability in front of every save.

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
- **Rate limiting rules (Free-plan compatible):** create one rule named
  `NovaGuard public API burst guard` whose path starts with `/api/v1/`.
  Count by IP, trigger at 30 requests per 10 seconds, choose *Block*, and use a
  10-second mitigation timeout. Cloudflare Free currently exposes only Path
  and Verified Bot in the match expression, one IP counting characteristic,
  a 10-second counting period, a 10-second mitigation timeout and one rule.
  The path-only match is safe for the current `novaguard.fun` zone because the
  website Worker does not expose its own endpoints below `/api/v1/`; revisit
  the rule if that routing changes. This sits in front of the app's separate
  auth/read/write per-IP limiters (defense in depth).
- **Verify before attesting:** send a controlled burst only to the public
  health endpoint and confirm that at least one response is `429`:
  ```bash
  for i in {1..40}; do
    curl -sS -o /dev/null -w '%{http_code}\n' \
      https://api.novaguard.fun/api/v1/health
  done | sort | uniq -c
  ```
  Wait at least 10 seconds afterwards. Retain a screenshot/configuration export
  and the sanitized result, then set `API_EDGE_RATE_LIMIT_CONFIRMED=true`.
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
