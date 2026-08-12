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

### Music (optional)

Music playback needs FFmpeg on the host, plus the Python voice packages from
`requirements.txt` (`PyNaCl` and `davey`). YouTube extraction also needs a
JavaScript runtime for yt-dlp's EJS challenge solver; Deno is the preferred
runtime:

```bash
sudo apt install -y ffmpeg unzip
curl -fsSL https://deno.land/install.sh | sh
python -m pip install -r requirements.txt
```

NovaGuard auto-detects the common Deno locations, including
`/home/ubuntu/.deno/bin/deno`. If your host uses a custom path, set it
explicitly:

```env
MUSIC_YTDLP_JS_RUNTIME=/home/ubuntu/.deno/bin/deno
```

`MUSIC_MAX_SESSIONS` caps how many servers can play at once (default `3`).
The limit exists for CPU, not RAM: YouTube streams are usually copied without
re-encoding, while SoundCloud has to be transcoded.

Searches prefer YouTube. `MUSIC_ENABLE_SOUNDCLOUD_FALLBACK=false` is the
recommended production default because SoundCloud CDN/HLS links can expire or
die mid-track. Set it to `true` only if you want the bot to try SoundCloud when
YouTube cannot resolve a playable stream.
Search uses multiple candidates and avoids YouTube cookies during the metadata
lookup, so a rotated cookie file does not poison normal `/play query` searches.

You can prefer higher bitrate audio without making popular YouTube tracks fail:

```env
MUSIC_MIN_AUDIO_BITRATE_KBPS=192
MUSIC_STRICT_MIN_AUDIO_BITRATE=false
```

Avoid strict `320` unless you intentionally want many tracks to fail instead of
falling back to a stable Opus stream.

Spotify credentials are optional. Without them a Spotify track link still
works; with them, playlists work too. `yt-dlp` breaks whenever YouTube changes
something, so bump it when playback starts failing:

```bash
.venv/bin/pip install --upgrade "yt-dlp[default]" davey PyNaCl
```

If YouTube returns `Sign in to confirm you're not a bot`, export YouTube cookies
from a browser in Netscape format, upload the file to the host, keep it private,
and set:

```env
MUSIC_YTDLP_COOKIES_FILE=/home/ubuntu/NovaGuard/data/youtube-cookies.txt
```

Then restart PM2. For local development only, `MUSIC_YTDLP_COOKIES_FROM_BROWSER`
can point yt-dlp at a browser profile, for example `firefox` or
`chrome:Default`.

Check the runtime exactly as the bot sees it:

```bash
venv/bin/python - <<'PY'
from core.music_sources import detected_deno_path, ydl_runtime_options
print("deno:", detected_deno_path())
print("yt-dlp options:", ydl_runtime_options())
PY
```

If YouTube logs `Signature solving failed`, `n challenge solving failed`, or
`Only images are available for download`, install/update Deno and
`yt-dlp[default]`. As a last resort while YouTube is changing things, allow
yt-dlp to fetch fresh EJS scripts dynamically:

```env
MUSIC_YTDLP_REMOTE_COMPONENTS=ejs:github
```

If YouTube still returns `Sign in to confirm you're not a bot` with Deno and
fresh cookies, the host IP is likely being challenged for playback. In that
case, install a yt-dlp PO Token provider and point NovaGuard at it:

```bash
cd /home/ubuntu/NovaGuard
venv/bin/python -m pip install -U bgutil-ytdlp-pot-provider

cd /home/ubuntu
git clone --single-branch --branch 1.3.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git
cd bgutil-ytdlp-pot-provider/server
/home/ubuntu/.deno/bin/deno install --allow-scripts=npm:canvas --frozen
```

```env
MUSIC_YTDLP_EXTRACTOR_ARGS=youtubepot-bgutilscript:server-home=/home/ubuntu/bgutil-ytdlp-pot-provider/server
```

#### When the host IP itself is flagged (proxy)

If Deno, fresh cookies **and** the PO Token provider are all in place and
YouTube still answers `Sign in to confirm you're not a bot`, the datacenter IP
itself is flagged — common on Oracle/AWS/Hetzner ranges. No client-side setting
clears an IP-level flag; the fix is a clean egress IP for music traffic only:

```env
MUSIC_YTDLP_PROXY=http://user:pass@proxy-host:3128
```

- The proxy applies to every yt-dlp call **and** to FFmpeg while it streams
  YouTube audio (Google CDN URLs only play from the IP that resolved them).
  SoundCloud streams stay on the direct connection.
- Use an `http://` proxy URL. A `socks5://` proxy works for yt-dlp but FFmpeg
  cannot tunnel through it, so playback would 403; NovaGuard refuses it for
  streaming and logs a warning.
- What works in practice, best first:
  1. A residential/ISP proxy with unmetered bandwidth (audio streaming uses
     real gigabytes; per-GB residential plans get expensive).
  2. A tiny VPS at a *different* provider (a home connection is even better)
     running Squid or tinyproxy with auth, port firewalled to the bot's IP.
  3. Rotating datacenter proxies — often flagged too; test before paying.
- After changing `.env`: `pm2 restart pythonbot && pm2 save`.

When YouTube challenges the host, NovaGuard now logs a clear
`YouTube is challenging this host IP` warning (throttled, at most one per
5 minutes) and `/play` tells the user the server IP is being challenged
instead of a generic "nothing found".

While the challenge is active (seen in the last 15 minutes), NovaGuard also
switches itself to SoundCloud automatically: searches go straight to
SoundCloud, and a YouTube track whose stream cannot resolve is rescued with a
SoundCloud match — even when `MUSIC_ENABLE_SOUNDCLOUD_FALLBACK` is off. A
degraded stream beats silence; once YouTube stops challenging the host,
behaviour returns to normal on its own.

A note on bitrate expectations: SoundCloud free streams top out around
128 kbps and YouTube Opus around 130–160 kbps, and Discord voice channels cap
the output at the channel bitrate (64–96 kbps unboosted). A strict 320 kbps
requirement would therefore reject nearly everything; prefer
`MUSIC_MIN_AUDIO_BITRATE_KBPS=192` with strict mode off, which picks the best
available stream without failing tracks.

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

### Optional: Lavalink music backend

NovaGuard can use Lavalink instead of the in-process yt-dlp/FFmpeg player:

```env
MUSIC_BACKEND=lavalink
LAVALINK_URI=http://127.0.0.1:2333
LAVALINK_PASSWORD=use-a-long-random-password
MUSIC_LAVALINK_SEARCH_SOURCE=ytmsearch
```

Lavalink v4 works with Wavelink 3.x. The Lavalink documentation notes that v4
requires Java 17+, and the Wavelink migration docs show the v4 connection model
through `wavelink.Pool.connect`. The default built-in YouTube source is
deprecated, so the bundled example config uses the official `youtube-source`
plugin and disables Lavalink's built-in YouTube source.

Install and start a local node on Ubuntu:

```bash
sudo apt update
sudo apt install -y openjdk-17-jre-headless

mkdir -p /home/ubuntu/lavalink
cd /home/ubuntu/lavalink
curl -L -o Lavalink.jar https://github.com/lavalink-devs/Lavalink/releases/latest/download/Lavalink.jar

cp /home/ubuntu/NovaGuard/deploy/lavalink/application.yml /home/ubuntu/lavalink/application.yml
sed -i 's|CHANGE_ME_TO_A_LONG_RANDOM_PASSWORD|use-a-long-random-password|' application.yml

pm2 start java --name lavalink --cwd /home/ubuntu/lavalink -- -jar Lavalink.jar
pm2 save
```

Then enable the backend in the bot:

```bash
cd /home/ubuntu/NovaGuard
venv/bin/python -m pip install -r requirements.txt

grep -q '^MUSIC_BACKEND=' .env \
  && sed -i 's|^MUSIC_BACKEND=.*|MUSIC_BACKEND=lavalink|' .env \
  || echo 'MUSIC_BACKEND=lavalink' >> .env

grep -q '^LAVALINK_URI=' .env \
  && sed -i 's|^LAVALINK_URI=.*|LAVALINK_URI=http://127.0.0.1:2333|' .env \
  || echo 'LAVALINK_URI=http://127.0.0.1:2333' >> .env

grep -q '^LAVALINK_PASSWORD=' .env \
  && sed -i 's|^LAVALINK_PASSWORD=.*|LAVALINK_PASSWORD=use-a-long-random-password|' .env \
  || echo 'LAVALINK_PASSWORD=use-a-long-random-password' >> .env

grep -q '^MUSIC_LAVALINK_SEARCH_SOURCE=' .env \
  && sed -i 's|^MUSIC_LAVALINK_SEARCH_SOURCE=.*|MUSIC_LAVALINK_SEARCH_SOURCE=ytmsearch|' .env \
  || echo 'MUSIC_LAVALINK_SEARCH_SOURCE=ytmsearch' >> .env

pm2 restart novaguard --update-env
pm2 save
```

If you want to go back instantly:

```bash
cd /home/ubuntu/NovaGuard
sed -i 's|^MUSIC_BACKEND=.*|MUSIC_BACKEND=yt-dlp|' .env
pm2 restart novaguard --update-env
```

The bot loads `.env` automatically on startup — no manual exports needed.

If an existing Lavalink node logs `youtube-plugin-1.14.0` or fails popular
YouTube links with `This video is unavailable`, refresh the deployed
`application.yml` from the repo and restart Lavalink. The example config tracks
the current `youtube-source` plugin release because YouTube client behavior
changes often.

If the node is already on `youtube-plugin-1.18.2` but playback logs say
`This video requires login` or `All clients failed to load the item`, the VPS IP
is still challenged by YouTube. At that point Lavalink is working, but YouTube
will not stream anonymously from that host. Use one of these fixes:

1. Enable `plugins.youtube.oauth.enabled: true` in
   `/home/ubuntu/lavalink/application.yml`, make sure the YouTube client list
   includes `TV`, restart Lavalink, and follow the OAuth code printed in
   `pm2 logs lavalink`. Use a burner YouTube account.
2. After Lavalink prints a refresh token, paste it under
   `plugins.youtube.oauth.refreshToken` so future restarts do not ask again.
3. If OAuth is not acceptable, run the music node through a cleaner egress
   IP/proxy. Updating only the bot cannot bypass a YouTube host-level login
   challenge.

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
contains all 120 slash commands exposed by the standard and Lavalink backends,
including Music, Voice Reports, Voice Hours, server-management commands and
owner-only operations. A Python test compares it directly with every command
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
