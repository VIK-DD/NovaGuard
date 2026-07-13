# NovaGuard — Security Audit & Hardening Reference

_Last reviewed: 2026-07-13 · Scope: the Discord bot, its SQLite data layer, and
the embedded dashboard API (`core/webserver.py`)._

## Verdict

The backend has **no known remotely-exploitable vulnerabilities**. There is no
command execution, no SQL/`eval` injection, no deserialization sink, and no
secret exposure. Authentication, authorization, transport, rate-limiting, data
at rest, and the software supply chain are all hardened. Residual risk is low
and is limited to items outside the code (host/network posture, secret
rotation), documented in the runbook below.

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
| RCE / shell | No `subprocess`/`os.system`/`eval`/`exec`; update engine only hashes files | ✅ none |
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
- CI runs `pip-audit` (known-CVE gate) and a job that installs the lock with
  `--require-hashes` and imports the bot, proving reproducibility.
- GitHub Actions are pinned to commit SHAs; Dependabot keeps deps + Actions
  fresh via weekly PRs.

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
pip install pip-tools
pip-compile --generate-hashes -o requirements.lock requirements.txt
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
SD cards fail. Copy the newest `data/backups/*.zip` off the Pi on a schedule
(another host, or posted to a private Discord channel). This preserves economy,
levels, config, sessions, and the audit trail.

## 5. Verification
- `python tests/test_webserver.py` → 30 checks (auth, CORS, CSRF, encryption,
  rate-limit, error envelope, both SameSite modes).
- CI runs compile + import smoke + the dashboard test + `pip-audit` + a
  hash-locked install, on every push.
