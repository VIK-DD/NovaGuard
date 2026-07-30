# NovaGuard Backup And Restore

NovaGuard creates local zip backups in `backups/` every 6 hours and keeps the newest archives on disk. These backups include the SQLite database, JSON feature state, update state and GitHub watcher state.

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

Local backups protect against bad commands and corrupted files, but they do not protect against a dead SD card. Copy `backups/*.zip` off the Pi with one of these:

- `rclone` to Google Drive, OneDrive, Dropbox or Cloudflare R2.
- `scp`/`rsync` to a Mac, NAS or another machine over Tailscale.
- A scheduled cron job that copies only new zip files.

Do not push backup zips to a public GitHub repo. They can contain server and user state.
