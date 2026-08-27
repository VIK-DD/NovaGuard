# NovaGuard Backup And Restore

NovaGuard creates authenticated, encrypted `.zip.ngbackup` archives in `backups/` at 07:00 and 19:00 Europe/Chisinau by default, and keeps the newest archives on disk. These backups include the SQLite database, remaining JSON feature state, update state and GitHub watcher state. Voice report state lives in SQLite.

The archive key comes only from `BACKUP_ENCRYPTION_KEY`. Generate it once with
`openssl rand -base64 48`, keep the exact value in a password manager and put
it in `.env` on each recovery host. Losing this key makes every archive created
with it unrecoverable. Do not reuse the Discord token, OAuth secret or web
session secret as the backup key.

NovaGuard also maintains `.privacy_deletions.json` outside every snapshot. It
contains keyed hashes rather than Discord IDs and prevents an old backup from
reviving records erased after that backup was created. If off-site storage is
enabled, the encrypted current copy is stored at
`privacy/deletion-ledger.json.ngbackup`. A normal restore refuses to proceed
without a valid ledger made with the same key.

> Lost the host entirely — deleted, reclaimed or locked out? This page assumes
> the server still exists. See [DISASTER-RECOVERY.md](DISASTER-RECOVERY.md) for
> rebuilding from nothing, including the pieces these archives deliberately do
> **not** contain: `.env`, `rclone.conf` and the Litestream credentials.

## Check Backup Health

Use these in Discord before touching files:

```text
/backup status
/backup remote
/backup inspect
/backup list
/backup test
/backup restore
```

`/backup test` authenticates and extracts the newest archive into a unique
temporary directory, applies the signed deletion ledger, reruns SQLite
integrity and foreign-key checks, and then removes the plaintext test files. It
does not overwrite live data and fails if the ledger is absent or invalid.
`/backup restore` prints a safe manual restore plan only; it does not overwrite live data.

## Manual Restore

Only do this when the bot is stopped and you know which archive you want.
The helper rejects legacy plaintext ZIPs by default. During a one-time migration
of a trusted old archive, add `--allow-plaintext`, restore it locally, then
immediately create a new encrypted backup and securely remove the old copy.

```bash
cd ~/NovaGuard
pm2 stop 0
mkdir -p data-before-restore
cp -a data/. data-before-restore/
venv/bin/python tools/restore_backup.py backups/novaguard-full-YYYY-MM-DD_HH-MM-SS-auto.zip.ngbackup --output backups/restore-check --replace
cp backups/restore-check/data/novaguard.sqlite3 data/novaguard.sqlite3
cp backups/restore-check/data/*.json data/ 2>/dev/null || true
cp backups/restore-check/.update_state.json . 2>/dev/null || true
cp backups/restore-check/.github_state.json . 2>/dev/null || true
pm2 restart 0 --update-env
pm2 logs 0 --lines 100
```

If something looks wrong, stop the bot again and restore `data-before-restore/`.
Do not use `--allow-missing-deletion-ledger` in a normal recovery. That escape
hatch exists only for an operator who has independently proved that no deletion
requests occurred after the chosen snapshot.

## Off-Site Backup

Local backups protect against bad commands and corrupted files, but they do not
protect against a dead server. Configure `rclone` once, then NovaGuard uploads
each verified encrypted archive to Google Drive automatically. NovaGuard
refuses to upload legacy plaintext ZIP files.

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
BACKUP_REMOTE_FULL_KEEP_DAYS=90
BACKUP_REMOTE_GUILD_KEEP_DAYS=60
BACKUP_REMOTE_RETENTION_ENABLED=true
BACKUP_REMOTE_TIMEOUT_SECONDS=300
BACKUP_RCLONE_DRIVE_PACER_MIN_SLEEP=250ms
BACKUP_RCLONE_DRIVE_PACER_BURST=1
BACKUP_ENCRYPTION_KEY=<the-random-value-kept-in-your-password-manager>
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
/backup remote
/backup inspect
/backup test
```

`/backup status` reports whether the latest local backup was also uploaded
off-site, shows a health score, and includes the latest remote check state.
`/backup remote` runs a live `rclone size` check against the last uploaded file.
If the local encrypted archive is created but Google Drive upload, remote verification or
retention fails, the bot sends an admin error digest.

Google Drive layout:

```text
NovaGuard/
  backups/
    full/
      2026/
        08/
          novaguard-full-2026-08-01_07-00-00-auto.zip.ngbackup
          novaguard-full-2026-08-01_19-00-00-auto.zip.ngbackup
    guilds/
      MadCats-RPG-B-HOOD-1328794007748476939/
        2026/
          08/
            2026-08-01_07-00-00.json.ngbackup
            2026-08-01_19-00-00.json.ngbackup
    privacy/
      deletion-ledger.json.ngbackup
```

Use `full/` for disaster recovery. Use `guilds/` when you need to inspect or
recover one server's settings, levels, economy and voice report state.

Alternatives still work:

- `rclone` to OneDrive, Dropbox or Cloudflare R2.
- `scp`/`rsync` to a Mac, NAS or another machine over Tailscale.
- A scheduled cron job that copies only new `.ngbackup` files.

Do not push backups to GitHub or send them through Discord. Encryption limits
the impact of storage exposure, but the archives still contain private server
and user state and must remain access-controlled.
