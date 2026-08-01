# NovaGuard Backup And Restore

NovaGuard creates local zip backups in `backups/` at 07:00 and 19:00 Europe/Chisinau by default, and keeps the newest archives on disk. These backups include the SQLite database, JSON feature state, update state and GitHub watcher state.

## Check Backup Health

Use these in Discord before touching files:

```text
/backup status
/backup list
/backup test
```

`/backup test` extracts the newest archive into `backups/restore-check/` only. It does not overwrite live data.

## Manual Restore

Only do this when the bot is stopped and you know which archive you want.

```bash
cd ~/pythonbot
pm2 stop pythonbot
mkdir -p data-before-restore
cp -a data/. data-before-restore/
rm -rf backups/restore-check
unzip backups/novaguard-backup-YYYYMMDD-HHMMSS-auto.zip -d backups/restore-check
cp backups/restore-check/data/novaguard.sqlite3 data/novaguard.sqlite3
cp backups/restore-check/data/*.json data/ 2>/dev/null || true
cp backups/restore-check/.update_state.json . 2>/dev/null || true
cp backups/restore-check/.github_state.json . 2>/dev/null || true
pm2 restart pythonbot --update-env
pm2 logs pythonbot --lines 100
```

If something looks wrong, stop the bot again and restore `data-before-restore/`.

## Off-Site Backup

Local backups protect against bad commands and corrupted files, but they do not
protect against a dead server. Configure `rclone` once, then NovaGuard uploads
each verified backup zip to Google Drive automatically.

Recommended Google Drive setup on the VPS:

```bash
sudo apt update
sudo apt install -y rclone
rclone config
rclone mkdir gdrive:NovaGuard/backups
rclone lsd gdrive:
```

Use `gdrive` as the remote name during `rclone config`, or change the `.env`
destination to match the name you chose.

Add this to `.env`:

```bash
BACKUP_SCHEDULE=07:00,19:00
BACKUP_TIMEZONE=Europe/Chisinau
BACKUP_REMOTE_DEST=gdrive:NovaGuard/backups
BACKUP_REMOTE_FULL_PREFIX=full
BACKUP_REMOTE_GUILD_PREFIX=guilds
BACKUP_REMOTE_TIMEOUT_SECONDS=300
```

Then restart the bot and create one manual backup:

```bash
pm2 restart 0 --update-env
pm2 save
```

In Discord, run:

```text
/backup create
/backup status
/backup test
```

`/backup status` reports whether the latest local backup was also uploaded
off-site. If the local zip is created but the Google Drive upload fails, the bot
sends an admin error digest.

Google Drive layout:

```text
NovaGuard/
  backups/
    full/
      2026/
        08/
          novaguard-full-2026-08-01_07-00-00-auto.zip
          novaguard-full-2026-08-01_19-00-00-auto.zip
    guilds/
      MadCats-RPG-B-HOOD-1328794007748476939/
        2026/
          08/
            2026-08-01_07-00-00.json
            2026-08-01_19-00-00.json
```

Use `full/` for disaster recovery. Use `guilds/` when you need to inspect or
recover one server's settings, levels, economy and voice report state.

Alternatives still work:

- `rclone` to OneDrive, Dropbox or Cloudflare R2.
- `scp`/`rsync` to a Mac, NAS or another machine over Tailscale.
- A scheduled cron job that copies only new zip files.

Do not push backup zips to a public GitHub repo. They can contain server and user state.
