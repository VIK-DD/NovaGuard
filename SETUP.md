# NovaGuard — Setup

Modern, fully slash-command Discord bot. Its public release (currently 2.0 Open Beta)
is derived automatically from the update history and is shared by Discord, the API,
dashboard and website.
Colorful embeds, interactive buttons & menus, automatic update changelogs, GitHub intelligence, XP levels, voice session reports and more.

## 1. Configure the bot

1. Copy `.env.example` to `.env`
2. Fill in your real values

Important values that should stay in `.env`:

- `TOKEN`: your Discord bot token
- `GUILD_ID`: **recommended** — your main server ID for default channel setup.
  Run `/resync scope:server` after a deploy when you need command changes immediately;
  global sync can take up to an hour to propagate.
- `GITHUB_USERNAME`: the GitHub profile used by `/github` and `/dev`
- `GITHUB_PRIMARY_REPO`: the default repo used by `/repo`, `/dev`, `/health`, `/commits`, `/release`
- `GITHUB_WATCH_REPOS`: comma-separated list of repos the watcher should monitor
- `GITHUB_TOKEN`: optional, but strongly recommended for smoother GitHub API access.
  Keep exactly one `GITHUB_TOKEN=` line in `.env`; a placeholder above the real
  token will be loaded first and GitHub will reject it as bad credentials.
- `GITHUB_POLL_SECONDS`: how often the watcher checks GitHub
- `UPTIME_URL`: optional link shown inside the developer dashboard
- `BOT_BRAND`: footer branding for embeds. Quote values that contain shell
  characters, for example `BOT_BRAND="Developed by VIK & CloudMedia"`.
- `STREAM_STATUSES`: rotating streaming texts separated by `|`
- `STREAM_STATUS_INTERVAL_SECONDS`: how often the streaming status rotates, in seconds (`15` recommended)

Channel setup is now easiest from Discord:

- Run `/setup` for the friendly setup wizard with dropdown menus
- Pick what you want to configure, then choose the channel from Discord
- Or run `/setup` inside a channel and click the quick buttons: Updates, GitHub, Admin Errors, Server Logs, Voice Reports, Welcome, Goodbye
- Settings are saved in SQLite at `data/novaguard.sqlite3`

Advanced config commands:

- `/config view` — shows saved server config in a clean admin embed
- `/config export` — exports this server config as JSON, without tokens/API keys
- `/config backup` — creates a manual backup archive
- `/config reset confirm:true` — clears this server's NovaGuard setup

Optional `.env` fallback values still work for your main server:

- `UPDATE_CHANNEL_ID`
- `GITHUB_EVENT_CHANNEL_ID`
- `ERROR_LOG_CHANNEL_ID`

## 2. Install & run locally

```bash
pip3 install -r requirements.txt
python3 bot.py
```

## 2b. Owner commands and the admin key

Some commands reach past a single server: `/backup` archives every guild's
data at once, `/maintenance` is a global kill switch, `/resync` republishes
commands everywhere. Those need the Discord application owner **and** a key,
because owning the account is not proof of who is at the keyboard — a stolen
Discord session passes the first check and fails the second.

Generate the key once, on the host:

```bash
cd /home/ubuntu/NovaGuard && venv/bin/python -m tools.admin_key
```

It is printed once and stored only as a hash. **Put it in your password
manager before closing the terminal** — losing it costs a rotation, but there
is no way to read it back.

Then, in a **DM with the bot** (never in a server channel, where the command
lands in Discord's audit log):

```text
/admin unlock key:ng_admin_...
```

The unlock lasts 15 minutes and ends early on `/admin lock` or a bot restart.
`/admin status` shows whether a key exists and how long you have left, and
`/admin audit` lists recent privileged actions, including refused ones.

To rotate — after a leak, or if you typed the key in a channel by mistake:

```bash
cd /home/ubuntu/NovaGuard && venv/bin/python -m tools.admin_key --force
```

Server admins are unaffected: `/setup`, `/config view` and `/config export`
still work on `Manage Server`, so every guild keeps a way to configure itself
and to take its own data out.

## 3. Raspberry Pi with pm2

If your bot already runs in pm2, update the files and restart:

```bash
pm2 restart pythonbot
pm2 save
```

### Public website status and dashboard API

The bot already exposes live `GET /api/v1/health` and `GET /api/v1/stats`
endpoints from the embedded web server. To make them reachable by the website:

1. Publish the Pi's `http://localhost:8300` through an HTTPS Cloudflare Tunnel,
   for example at `https://api.novaguard.fun`.
2. On the host, bind only to loopback with `WEB_HOST=127.0.0.1`, then set
   `WEB_ENABLED=true`, `WEB_COOKIE_SECURE=true`,
   `WEB_TRUST_PROXY=true`, and add the website origin to `WEB_CORS_ORIGIN`:
   `WEB_CORS_ORIGIN=https://novaguard.fun`.
3. Set `WEB_OAUTH_REDIRECT=https://api.novaguard.fun/api/v1/auth/callback` and
   `WEB_AFTER_LOGIN=https://novaguard.fun/dashboard/`.
4. Production builds already use
   `website-3/.env.production` with
   `PUBLIC_API_BASE=https://api.novaguard.fun`. Rebuild and deploy the website;
   the Status page will show bot readiness, database health, uptime, guilds,
   members, commands and gateway state.
5. Restart the bot after changing `.env`:
   `pm2 restart pythonbot && pm2 save`.

Keep port `8300` closed to the public internet; Cloudflare Tunnel should be the
only public path to the API.

Before opening the site publicly, complete `LEGAL_OPERATOR_NAME`,
`LEGAL_OPERATOR_ADDRESS`, `LEGAL_OPERATOR_COUNTRY` and
`PRIVACY_CONTACT_EMAIL`. Also name the actual infrastructure and legal complaint
route in `LEGAL_HOSTING_PROVIDER`, `LEGAL_HOSTING_REGION`,
`LEGAL_BACKUP_PROVIDER`, `LEGAL_BACKUP_LOCATION` and
`LEGAL_SUPERVISORY_AUTHORITY_URL`. Generate separate random values for
`BACKUP_ENCRYPTION_KEY` and `WEB_TOKEN_KEY`, then run:

```bash
chmod 600 .env data/novaguard.sqlite3 .privacy_deletions.json
venv/bin/python tools/production_check.py --strict
```

Do not launch while it prints `NOT READY`.

## 4. Project layout

```
bot.py            entry point: loads cogs, syncs slash commands
core/             engine: config, theme, SQLite, backups, GitHub API, changelog
cogs/             one file per command category
data/             SQLite DB + remaining JSON feature data — auto-created
backups/          automatic/manual backup archives — auto-created
```

## 5. Command catalog

The canonical, machine-checked catalog lives in
`website-3/src/data/commands.json` and is rendered at `/commands`. It currently
contains all 112 slash commands the bot exposes, including Voice Reports,
Voice Hours, server-management commands and owner-only operations. A Python
test compares it directly with every command
decorator in `cogs/`, so adding or removing a bot command without updating the
public catalog fails CI.

Access is presented in three clear levels: **Everyone**, **Server managers**
and **Bot owner**. `/help` remains the interactive in-Discord command browser.

## 5b. New systems — one-time setup

1. **Discord Developer Portal → Bot → Privileged Gateway Intents**: enable
   **SERVER MEMBERS INTENT** (required for welcome/goodbye/auto-role and join/leave logs).
   Without it the bot refuses to start and prints instructions.
2. Install the AI SDK and set the key:
   ```bash
   pip3 install anthropic
   ```
   then put `ANTHROPIC_API_KEY=...` in `.env` (optional — `/ask` explains itself if missing).
3. In your server, run `/setup` and click the buttons from the relevant channels:
   - Updates channel
   - GitHub feed channel
   - Admin error digest channel
   - Server logs channel
   - Welcome / goodbye channels
4. Review advanced config when needed:
   - `/config view`
   - `/config export`
   - `/config backup`
   - `/config reset confirm:true`
5. Optional feature panels:
   - `/welcome set channel:#welcome autorole:@Member`
   - `/logs set channel:#logs`
   - `/ticketpanel channel:#support staff_role:@Staff`
   - `/rolepanel` wherever you want self-service roles
   - `/automod status` to review the filters (invites + spam are on by default)

## 5c. SQLite, backups and health

- `data/novaguard.sqlite3` stores server setup/config, XP levels, economy wallets, monthly voice hours and voice report state.
- `/voicehours` counts months on `VOICE_TIMEZONE`, falling back to `BACKUP_TIMEZONE` and then `Europe/Chisinau`. Set it only if voice hours should roll over on a different clock than the one backups run on.
- Voice hours are tracked on every server, configured or not — `/voice set` only controls session reports.
- Old `data/settings.json`, `data/levels.json` and `data/economy.json` are migrated automatically once and kept as safety backups.
- Automatic backups run at `07:00` and `19:00` Europe/Chisinau by default, and keep the newest 10 encrypted `.zip.ngbackup` archives in `backups/`.
- Generate a dedicated key with `openssl rand -base64 48`, set it as `BACKUP_ENCRYPTION_KEY` in `.env`, and keep the exact value in a password manager. The key is never stored in an archive and cannot be recovered from one.
- Set `BACKUP_SCHEDULE=07:00,19:00` and `BACKUP_TIMEZONE=Europe/Chisinau` if you want to make the schedule explicit.
- Set `BACKUP_REMOTE_DEST=gdrive:NovaGuard/backups` after configuring `rclone` to upload every verified full backup off-server under `full/YYYY/MM/`.
- Scheduled backups also export each Discord server as an encrypted `.json.ngbackup` file under `guilds/<server-name>-<guild-id>/YYYY/MM/`.
- `.privacy_deletions.json` is an independent HMAC deletion ledger and is intentionally excluded from snapshots. When off-site storage is configured, its encrypted recovery copy is replaced at `privacy/deletion-ledger.json.ngbackup` after every user or server erasure.
- Remote uploads are checked with `rclone size`; old remote files are pruned by `BACKUP_REMOTE_FULL_KEEP_DAYS` and `BACKUP_REMOTE_GUILD_KEEP_DAYS`.
- Google Drive transfers use a conservative 250 ms / one-request rclone pace by default. If the full upload is rate-limited, NovaGuard deliberately defers retention and per-server exports instead of multiplying requests to the same remote.
- `/config backup` and `/backup create` create a manual backup immediately.
- `/backup status`, `/backup remote`, `/backup inspect`, `/backup list`, `/backup test` and `/backup restore` inspect backup health score, restore readiness and off-site upload status without touching live data.
- Always restore through `tools/restore_backup.py`; it refuses a missing or wrong deletion ledger and removes any partially scrubbed restore directory on failure.
- `/doctor` checks database, JSON files, GitHub API, permissions, latency, uptime, backup status and event-loop lag.
- The health monitor sends admin error embeds if the event loop lag becomes dangerously high.

### Move NovaGuard to another host with one encrypted migration

Stop the bot on the old host, then create and verify the portable migration:

```bash
pm2 stop Novaguard
venv/bin/python tools/host_migration.py export
venv/bin/python tools/host_migration.py verify backups/novaguard-host-YYYY-MM-DD_HH-MM-SS.sql.ngbackup
```

Copy that single `.sql.ngbackup` file plus the independent
`.privacy_deletions.json` ledger to the new host. After cloning NovaGuard and
installing its dependencies there, import it and start the bot:

```bash
venv/bin/python tools/host_migration.py import novaguard-host-YYYY-MM-DD_HH-MM-SS.sql.ngbackup --confirm-replace
pm2 start bot.py --name Novaguard --interpreter venv/bin/python
pm2 save
```

The encrypted migration contains the complete SQLite database plus NovaGuard's
auxiliary JSON state. It intentionally excludes `.env`, cookies, the deletion
ledger and external credentials; configure/restore them separately on the new
host. Import authenticates the encrypted file, validates SQL, JSON checksums,
SQLite integrity and foreign keys, reapplies post-snapshot deletions, and saves
any previous destination state as another encrypted archive in `backups/`. Run
`/doctor` after the move for the final live check. Never import an SQL file from
an untrusted source.

## 6. Automatic update system (kept & upgraded)

- Tracks `bot.py`, `SETUP.md`, `.env.example` and every file in `core/` and `cogs/`
- On startup, if any tracked file changed, it posts a "Bot Update Deployed" embed
  with an auto-generated changelog (added/removed/changed slash commands, line stats, build number)
- `/updates` browses the full release timeline with pagination buttons
- `/latest` shows the most recent changelog, `/forceupdate` previews the pending one

## 7. Notes

- Slash command permissions: moderation commands are hidden from members without
  the right permissions (Discord-native `default_permissions`)
- The GitHub watcher posts new push, pull request, issue and release events
- `data/` and `backups/` are created automatically; configure off-site backups before deleting anything
- Old `!` prefix commands are gone — everything is `/` now
