# NovaGuard — Setup

Modern, fully slash-command Discord bot (v3.0.0 "Nova").
Colorful embeds, interactive buttons & menus, automatic update changelogs, GitHub intelligence, XP levels and more.

## 1. Configure the bot

1. Copy `.env.example` to `.env`
2. Fill in your real values

Important values that should stay in `.env`:

- `TOKEN`: your Discord bot token
- `GUILD_ID`: **recommended** — your server ID for instant slash command sync.
  Without it, sync is global and can take up to 1 hour to appear the first time.
- `GITHUB_USERNAME`: the GitHub profile used by `/github` and `/dev`
- `GITHUB_PRIMARY_REPO`: the default repo used by `/repo`, `/dev`, `/health`, `/commits`, `/release`
- `GITHUB_WATCH_REPOS`: comma-separated list of repos the watcher should monitor
- `GITHUB_TOKEN`: optional, but strongly recommended for smoother GitHub API access
- `GITHUB_POLL_SECONDS`: how often the watcher checks GitHub
- `UPTIME_URL`: optional link shown inside the developer dashboard
- `BOT_BRAND`: footer branding for embeds
- `STREAM_STATUSES`: rotating streaming texts separated by `|`
- `STREAM_STATUS_INTERVAL_SECONDS`: how often the streaming status rotates, in seconds (`15` recommended)

Channel setup is now easiest from Discord:

- Run `/setup` for the friendly setup wizard with dropdown menus
- Pick what you want to configure, then choose the channel from Discord
- Or run `/setup` inside a channel and click the quick buttons: Updates, GitHub, Admin Errors, Server Logs, Welcome, Goodbye
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

## 3. Raspberry Pi with pm2

If your bot already runs in pm2, update the files and restart:

```bash
pm2 restart pythonbot
pm2 save
```

The bot loads `.env` automatically on startup — no manual exports needed.

### Public website status and dashboard API

The bot already exposes live `GET /api/v1/health` and `GET /api/v1/stats`
endpoints from the embedded web server. To make them reachable by the website:

1. Publish the Pi's `http://localhost:8300` through an HTTPS Cloudflare Tunnel,
   for example at `https://api.novaguard.fun`.
2. On the Pi, set `WEB_ENABLED=true`, `WEB_COOKIE_SECURE=true`,
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

## 4. Project layout

```
bot.py            entry point: loads cogs, syncs slash commands
core/             engine: config, theme, SQLite, backups, GitHub API, changelog
cogs/             one file per command category
data/             SQLite DB + remaining JSON feature data — auto-created
backups/          automatic/manual backup archives — auto-created
```

## 5. Command catalog

### 🚀 Setup
`/setup` — one-command setup dashboard with buttons, select menus and channel picker
`/config view|export|backup|reset` — advanced admin config tools

### ⚙️ System
`/ping` `/uptime` `/status` `/botinfo` `/doctor` `/help` `/latest` `/updates` `/forceupdate`

### 🐙 Developer
`/github` `/repo` `/dev` `/health` `/commits` `/release` `/ghwatch`

### 🧰 Utility
`/userinfo` `/serverinfo` `/avatar` `/roleinfo` `/poll` `/remind` `/reminders` `/timestamp` `/choose` `/color`

### 🎉 Fun
`/8ball` `/coinflip` `/dice` `/rps` `/trivia` `/joke` `/ship` `/vibecheck`

### 🛡️ Moderation
`/purge` `/kick` `/ban` `/timeout` `/untimeout` `/slowmode` `/announce` `/warn add|list|clear`

### 🏆 Levels
`/rank` `/leaderboard` (+ slower automatic chat XP, private DM level-up cards with progress bars)
Admin: `/levels backfill preview` estimates historical XP, `/levels backfill run confirm:true` rebuilds the current XP totals after a backup.

### 👋 Welcome
`/welcome set` `/welcome off` `/welcome test` (+ auto join/leave embeds, auto-role)

### 📋 Logs
`/logs set` `/logs off` (+ deleted/edited messages, joins/leaves, bans, mod actions)

### 🎭 Roles
`/rolepanel` — button panels where members pick their own roles (persist across restarts)

### 🎁 Giveaways
`/giveaway start|end|reroll` — button entry, live counter, automatic winner draw

### 🎫 Tickets
`/ticketpanel` — one button opens a private thread with the staff role pinged

### 🤖 AutoMod
`/automod status|invites|spam` `/automod badword add|remove|list`

### 💰 Economy
`/balance` `/daily` `/work` `/pay` `/gamble` `/slots` `/richest` `/shop` `/buy`

### 🧠 AI
`/ask` — Claude answers right in the chat (needs `ANTHROPIC_API_KEY`)

Tip: `/help` opens an interactive hub with a category menu.

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

- `data/novaguard.sqlite3` stores server setup/config, XP levels and economy wallets.
- Old `data/settings.json`, `data/levels.json` and `data/economy.json` are migrated automatically once and kept as safety backups.
- Automatic backups run every 6 hours and keep the newest 10 zip archives in `backups/`.
- `/config backup` creates a manual backup immediately.
- `/doctor` checks database, JSON files, GitHub API, permissions, latency, uptime, backup status and event-loop lag.
- The health monitor sends admin error embeds if the event loop lag becomes dangerously high.

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
- `data/` and `backups/` are created automatically; back them up before deleting anything
- Old `!` prefix commands are gone — everything is `/` now
