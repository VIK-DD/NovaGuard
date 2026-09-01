<div align="center">

<img src="docs/assets/logo-shield.png" alt="NovaGuard shield logo" width="160"/>

# NovaGuard

### An open-source Discord bot and web control plane for modern communities.

NovaGuard combines moderation, onboarding, automation, privacy controls,
economy, levels, tickets, giveaways, voice analytics, GitHub intelligence and
an OAuth-secured browser dashboard in one self-hosted project.

<br />

[Website](https://novaguard.fun) ·
[Commands](https://novaguard.fun/commands) ·
[Status](https://novaguard.fun/status) ·
[Updates](https://novaguard.fun/updates) ·
[FAQ](https://novaguard.fun/faq) ·
[Discord](https://discord.gg/CbDy3GyhWm)

<br />

[![Release](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.novaguard.fun%2Fapi%2Fv1%2Fstats&query=%24.release_label&label=release&color=0f766e)](https://novaguard.fun/updates)
[![CI](https://img.shields.io/github/actions/workflow/status/VIK-DD/NovaGuard/ci.yml?branch=main&label=CI)](https://github.com/VIK-DD/NovaGuard/actions/workflows/ci.yml)
[![ZAP baseline](https://img.shields.io/github/actions/workflow/status/VIK-DD/NovaGuard/zap-baseline.yml?label=ZAP%20baseline)](https://github.com/VIK-DD/NovaGuard/actions/workflows/zap-baseline.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![discord.py](https://img.shields.io/badge/discord.py-2.7%2B-5865F2)](https://discordpy.readthedocs.io/)
[![Astro](https://img.shields.io/badge/Astro-7-BC52EE?logo=astro&logoColor=white)](https://astro.build/)
[![Cloudflare Workers](https://img.shields.io/badge/Cloudflare-Workers-F38020?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/)
[![SQLite](https://img.shields.io/badge/SQLite-state-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

</div>

---

> [!NOTE]
> The codebase, slash commands and public documentation are written in
> **English**. NovaGuard is free to use under the Apache License 2.0 and can run
> on a VPS, Raspberry Pi or another Linux host.

## Contents

- [What ships](#what-ships)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Production on Linux with PM2](#production-on-linux-with-pm2)
- [Configuration](#configuration)
- [Discord setup and commands](#discord-setup-and-commands)
- [Website and dashboard](#website-and-dashboard)
- [Updates, health and backups](#updates-health-and-backups)
- [Security and privacy](#security-and-privacy)
- [Testing and CI](#testing-and-ci)
- [Project structure](#project-structure)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## What ships

#### Community operations

- Slash-native moderation, warnings, AutoMod, welcome/goodbye messages and
  server logs.
- Tickets, giveaways, self-role panels, client-recognition roles and a public
  server information panel.
- Economy, levels, reminders, polls, utilities, games and optional Claude AI.
- Voice-session reports plus persistent monthly voice-hour leaderboards.

#### Configuration and transparency

- `/setup` provides a guided Discord setup flow with channel pickers and quick
  actions.
- `/config view`, `/config export` and `/config reset` keep configuration
  reviewable and portable per server.
- `/privacy policy`, `/privacy export` and `/privacy delete` give members
  direct access to privacy information and data-rights workflows.
- Server owners can export or request deletion of their server's NovaGuard
  records.

#### Web control plane

- Editorial public website, command catalog, setup guide, FAQ, status and
  release archive.
- Discord OAuth dashboard for per-server configuration and operational
  insights.
- Embedded `aiohttp` API exposed only through Cloudflare Tunnel in production.
- Astro + React frontend served by a Cloudflare Worker with strict security
  headers, edge rate limits, maintenance routing and structured telemetry.

#### Operations

- SQLite persistence, encrypted local/off-site backups, restore drills and a
  deletion ledger that prevents erased records from returning after a restore.
- PM2 crash-loop protection, memory limits, timestamped logs and graceful
  shutdown.
- Automated release notes, GitHub event feeds, health checks and a public
  service-status message that is edited in place.
- Reproducible Python installs, dependency audits, secret scanning, static
  analysis, website security checks and a scoped ZAP passive baseline.

## Architecture

| Layer | Current implementation |
| --- | --- |
| Discord bot | Python 3.11+ and `discord.py` 2.7+ |
| Dashboard API | `aiohttp`, loopback-only in production |
| Application state | SQLite plus selected JSON state |
| Website | Astro 7, React 19, TypeScript 6 and Tailwind CSS 4 |
| Edge | Cloudflare Worker, Tunnel, WAF/rate limiting and security headers |
| Process manager | PM2, one forked bot process |
| Backups | AES-256-GCM authenticated archives and optional `rclone` off-site copy |
| Optional AI | Anthropic Claude |

SQLite keeps the installation simple without sacrificing structured storage.
It holds guild configuration, dashboard sessions and audit records, levels,
economy, tickets, warnings, giveaways, voice totals and other durable state.

## Quick start

Requires **Python 3.11+**.

```bash
git clone https://github.com/VIK-DD/NovaGuard.git
cd NovaGuard

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.lock

cp .env.example .env
# Fill at least TOKEN, then keep .env private.
chmod 600 .env

python bot.py
```

Enable **Server Members Intent** in the Discord Developer Portal before using
welcome, goodbye, autorole or member-log features. Set `GUILD_ID` while
developing if you want immediate guild-scoped command sync.

See [SETUP.md](SETUP.md) for the complete first-run and production guide.

## Production on Linux with PM2

The same deployment works on a VPS or Raspberry Pi. The repository ships the
PM2 process definition used by NovaGuard:

```bash
cd ~/Novaguard
python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install --require-hashes -r requirements.lock

pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

The PM2 application name is **`NovaGuard`**. Use the same capitalization in
every operational command:

```bash
pm2 logs NovaGuard --lines 80
pm2 describe NovaGuard
pm2 restart NovaGuard --update-env
```

For a normal code update:

```bash
cd ~/Novaguard
git pull --ff-only origin main
venv/bin/python -m pip install --require-hashes -r requirements.lock
pm2 restart NovaGuard --update-env
```

`--update-env` matters after an environment change. NovaGuard treats `.env` as
the local source of truth and warns when it overrides stale values inherited
from PM2.

In the documented public deployment, the API listens on `127.0.0.1:8300`,
Cloudflare Tunnel is the only public route to it, and the host firewall exposes
SSH only. Do not open port `8300` to the internet.

## Configuration

Copy [.env.example](.env.example); it is the canonical list of supported
variables and safe development defaults.

| Area | Important variables |
| --- | --- |
| Discord | `TOKEN`, `GUILD_ID`, `BOT_OWNER_IDS` |
| GitHub | `GITHUB_USERNAME`, `GITHUB_PRIMARY_REPO`, `GITHUB_WATCH_REPOS`, `GITHUB_TOKEN`, `GITHUB_POLL_SECONDS` |
| Bot presentation | `BOT_BRAND`, `STREAM_STATUSES`, `STREAM_STATUS_INTERVAL_SECONDS` |
| Dashboard API | `WEB_ENABLED`, `WEB_HOST`, `WEB_PORT`, `WEB_CORS_ORIGIN`, `WEB_TRUST_PROXY` |
| Discord OAuth | `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `WEB_OAUTH_REDIRECT`, `WEB_AFTER_LOGIN` |
| Session protection | `WEB_TOKEN_KEY`, `WEB_COOKIE_SECURE`, `WEB_COOKIE_SAMESITE` |
| Backups | `BACKUP_SCHEDULE`, `BACKUP_TIMEZONE`, `BACKUP_ENCRYPTION_KEY`, `BACKUP_REMOTE_DEST` |
| Privacy retention | `PRIVACY_*_KEEP_DAYS`, `PRIVACY_VOICE_KEEP_MONTHS` |
| Legal disclosure | `LEGAL_OPERATOR_*`, `LEGAL_HOSTING_*`, `LEGAL_BACKUP_*`, `PRIVACY_CONTACT_EMAIL` |
| Production attestations | `HOST_STORAGE_ENCRYPTION_CONFIRMED`, `API_EDGE_RATE_LIMIT_CONFIRMED` |
| Optional AI | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |

Secrets belong in `.env`, the host's password manager or encrypted CI secret
storage—never in Git. Use separate random values for backup encryption, web
token encryption and Worker cookie signing.

Before treating a host as production-ready, run:

```bash
venv/bin/python tools/production_check.py --strict
```

`NOT READY` means an operational requirement is missing. The check covers
private file modes, required launch values, SQLite integrity and foreign keys,
the authenticated deletion ledger, backup freshness, archive verification and
the confirmed off-site copy.

## Discord setup and commands

1. Invite the bot with the permissions it actually needs.
2. Run `/setup` in the server.
3. Configure the update, GitHub, error, log, welcome, voice and ticket channels.
4. Review the result with `/config view` and `/doctor`.
5. Publish `/infopanel`, `/statuspanel`, `/ticketpanel` or `/rolepanel` where
   appropriate.

The canonical public catalog is
[novaguard.fun/commands](https://novaguard.fun/commands) and is generated from
[`website-3/src/data/commands.json`](website-3/src/data/commands.json). CI
compares that catalog with every command decorator in `cogs/`.

Discord and the website intentionally show different-looking totals:

- Discord and `/api/v1/stats` count **top-level slash entries** once.
- The website lists grouped signatures such as `/privacy export` and
  `/giveaway start` separately.
- Host-wide maintenance, backup and admin-key commands are deliberately absent
  from the public catalog.

This avoids presenting a misleading hard-coded command count while ensuring
that every supported command is either public or explicitly classified as a
host-only operation.

## Website and dashboard

The website lives in [`website-3/`](website-3/) and currently uses:

- Astro static pages for public content and legal documents;
- a React dashboard island with TanStack Router and React Query;
- Zod validation at the API boundary;
- a Cloudflare Worker for assets, security headers, maintenance mode, launch
  routing and rate-limited preview/login endpoints;
- the bot's `aiohttp` API for OAuth, guild configuration, dashboard data and
  privileged actions.

Local website workflow:

```bash
cd website-3
npm ci
npm test
npm run build:launch
npm run dev
```

Production website deploys run through
[`deploy-website.yml`](.github/workflows/deploy-website.yml). The workflow
tests, audits and builds the site before publishing it to Cloudflare Workers.
The Worker requires encrypted `AUTH_PASSWORD` and `GATE_SIGNING_KEY` secrets;
the dashboard continues to use its separate Discord OAuth session.

## Updates, health and backups

#### Release and GitHub intelligence

- `/github`, `/repo`, `/dev`, `/health`, `/commits`, `/release` and `/ghwatch`
  provide GitHub cards and repository activity inside Discord.
- The watcher posts pushes, pull requests, issues and releases to configured
  server channels.
- The update engine tracks bot, cog, core and relevant website source files.
  Generated archives, tests, build output and dependencies are excluded so
  they cannot create recursive or meaningless releases.
- One release-history source determines the version displayed by Discord, the
  API, dashboard and website. Alpha is 1.x, Beta is 2.x and 3.0+ is Stable.

#### Health and service status

- `/status` is public; `/doctor` provides detailed server-manager diagnostics.
- `/statuspanel` publishes a durable service card, edits it at the configured
  twice-daily schedule, and replaces it after a restart or 14 days online.
- `/api/v1/health` reports process/database availability, while
  `/api/v1/ready` also requires the Discord bot to be ready.
- Admin error digests and loop-lag monitoring surface failures without posting
  tracebacks in public channels.

#### Backups and recovery

- Automatic backups run at `07:00` and `19:00` Europe/Chisinau by default.
- Every full archive and per-server export is encrypted and authenticated
  before it is eligible for off-site upload.
- `rclone` uploads can be verified and pruned using the configured retention
  windows; plaintext archives are never uploaded.
- `/backup status`, `/backup inspect` and `/backup test` verify health and
  restore readiness without touching live data.
- Restore tooling authenticates the archive, checks SQLite and JSON, reapplies
  the independent deletion ledger, and cleans temporary decrypted files.
- An optional encrypted Litestream disaster-recovery template is available in
  `deploy/litestream/`; it is not enabled automatically.

Read [docs/RESTORE.md](docs/RESTORE.md) and
[docs/DISASTER-RECOVERY.md](docs/DISASTER-RECOVERY.md) before restoring or
migrating production data.

## Security and privacy

NovaGuard is designed around a self-hosted threat model, but no automated check
or document is a guarantee that software has no vulnerabilities.

Implemented controls include:

- runtime authorization checks in addition to Discord's default command
  visibility;
- owner commands protected by both application ownership and a short-lived
  admin-key unlock;
- OAuth state signed with a dedicated HMAC key and dashboard tokens encrypted
  at rest;
- host-only secure cookies, CSRF protection, strict CORS and API rate limits;
- build-generated CSP hashes without `unsafe-eval`, plus security headers at
  the Worker edge;
- role-safety checks across panels, autoroles and channel overwrites;
- encrypted backups, verified off-site copies and deletion-ledger enforcement;
- retention controls, user/server export and deletion workflows;
- hash-locked production dependencies, full-history secret scanning, Bandit,
  `pip-audit`, `npm audit` and the website's build security audit;
- a manual ZAP plan restricted to `novaguard.fun` and
  `api.novaguard.fun`, failing on any Low-or-higher alert.

Report vulnerabilities privately to **support@novaguard.fun**. Scope,
expectations and the current threat model are documented in
[docs/SECURITY.md](docs/SECURITY.md).

## Testing and CI

Run the Python checks from the repository root:

```bash
python -m compileall -q bot.py core cogs
python -m pytest tests --ignore=tests/test_webserver.py -q
python tests/test_webserver.py
```

Run the website checks from `website-3/`:

```bash
npm ci
npm test
npm run build:launch
npm run security:audit:build
```

GitHub Actions additionally verifies Python 3.11 and 3.12, the hash-locked
install, dependency advisories, secret history, static security analysis,
React/Astro tests, the production build and the committed CSP hash manifest.
The scoped ZAP workflow is manual because it scans the live public deployment
and retains its report as an artifact.

## Project structure

```text
bot.py                    entry point, startup checks and command sync
cogs/                     Discord commands and event listeners
core/                     storage, API, auth, backups, releases and helpers
website-3/                Astro/React website and Cloudflare Worker
data/                     runtime SQLite and selected JSON state (ignored)
backups/                  encrypted archives (ignored)
deploy/                   optional host and disaster-recovery definitions
tools/                    production checks, restore and migration utilities
scripts/                  repository maintenance and secret scanning
tests/                    Python test suite
.github/workflows/        CI, website deployment and ZAP baseline
.zap/                     scoped passive-scan plan and instructions
SETUP.md                  detailed operator setup guide
```

## Documentation

| Document | Purpose |
| --- | --- |
| [SETUP.md](SETUP.md) | Installation, PM2, dashboard API and one-time feature setup |
| [docs/API.md](docs/API.md) | Dashboard API contract, limits and authorization |
| [docs/SECURITY.md](docs/SECURITY.md) | Security findings, controls, threat model and reporting |
| [docs/PRIVACY-OPERATIONS.md](docs/PRIVACY-OPERATIONS.md) | Processing register and privacy operations |
| [docs/INCIDENT-RESPONSE.md](docs/INCIDENT-RESPONSE.md) | Credential and personal-data incident procedure |
| [docs/RESTORE.md](docs/RESTORE.md) | Backup inspection and safe restore workflow |
| [docs/DISASTER-RECOVERY.md](docs/DISASTER-RECOVERY.md) | Host loss and recovery runbook |
| [docs/COMPLIANCE-EVIDENCE-TEMPLATE.md](docs/COMPLIANCE-EVIDENCE-TEMPLATE.md) | Private release evidence/sign-off template |

## Contributing

Issues and pull requests are welcome. Keep changes aligned with NovaGuard's
principles: clear member UX, explicit authorization, privacy by design,
reviewable operations and lightweight self-hosting.

Before opening a pull request, run the Python and website checks above, update
the public command catalog when commands change, and avoid committing generated
runtime data, archives, credentials or local virtual environments.

---

<!-- The heading is HTML so GitHub does not generate a duplicate anchor. -->
<a id="license"></a>

<h2 align="center">License</h2>

<p align="center">
  Licensed under the <strong>Apache License 2.0</strong> — see
  <a href="LICENSE"><strong>LICENSE</strong></a>.
  Project identity is clarified in <a href="NOTICE"><strong>NOTICE</strong></a>.
  Third-party components remain under their respective licenses — see
  <a href="THIRD_PARTY_NOTICES.md"><strong>THIRD_PARTY_NOTICES.md</strong></a>.
</p>

<p align="center">
  <strong>Copyright © 2019–2026 VIK-DD</strong><br />
  Developed by <strong>VIK &amp; CloudMedia</strong>
</p>

<p align="center">
  <strong>Calm, capable and yours</strong> · Made in Moldova 🇲🇩
</p>
