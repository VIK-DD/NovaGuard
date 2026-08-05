# NovaGuard Disaster Recovery

[RESTORE.md](RESTORE.md) covers rolling a working host back to an earlier
backup. This document covers the case where the host is **gone** — deleted,
reclaimed, locked out, or destroyed — and NovaGuard has to be rebuilt from
nothing on a new machine.

Read the inventory first. The gap it describes has already cost a rebuild
once.

## What lives where

| Piece | Location | In the zip backups? | In Git? |
| --- | --- | --- | --- |
| Bot and website code | GitHub | no | **yes** |
| Database (`data/novaguard.sqlite3`) | host + Litestream + zip backups | **yes** | no |
| JSON feature state (`data/*.json`) | host + zip backups | **yes** | no |
| Secrets (`.env`) | host only | **no** | no |
| rclone credentials (`~/.config/rclone/rclone.conf`) | host only | **no** | no |
| Litestream credentials (`/etc/litestream.env`) | host only | **no** | no |

The last three rows are the trap. A restore from Google Drive gives you every
byte of user data and a bot that still cannot start, because the token and the
backup credentials were never in the archive. That is deliberate — a Discord
token has no business sitting in cloud storage — but it means those three
files need their own home.

**Keep `.env` in a password manager**, not only on the server. Everything else
can be rebuilt from the sources below.

## Recovery point by source

| Source | You lose | Use when |
| --- | --- | --- |
| Litestream replica | seconds | first choice, always |
| Google Drive zip | up to 12 hours | Litestream missing or unreachable |
| Local `backups/` on the dead host | whatever it held | only if you still have the disk |

## Rebuild on a new host

### 1. Kill the old bot before starting a new one

If the old host is unreachable but might still be running, two bots on one
token fight over the gateway and behave erratically. Resetting the token in
the Discord Developer Portal disconnects the old instance immediately. Do this
whenever host access was lost rather than cleanly shut down.

### 2. System packages

```bash
sudo apt update && sudo apt install -y python3-venv ffmpeg openjdk-17-jre-headless unzip sqlite3 rclone
```

### 3. Code

```bash
cd /home/ubuntu && git clone https://github.com/VIK-DD/NovaGuard.git && cd NovaGuard
python3 -m venv venv && venv/bin/pip install -r requirements.txt
```

### 4. Data — Litestream first

```bash
curl -L https://github.com/benbjohnson/litestream/releases/latest/download/litestream-linux-amd64.deb -o /tmp/litestream.deb
sudo dpkg -i /tmp/litestream.deb
```

Recreate `/etc/litestream.env` (values from your password manager):

```bash
sudo install -m 600 /dev/null /etc/litestream.env
```

```env
NOVAGUARD_DB_PATH=/home/ubuntu/NovaGuard/data/novaguard.sqlite3
LITESTREAM_BUCKET=your-bucket-name
LITESTREAM_ENDPOINT=s3.eu-central-003.backblazeb2.com
LITESTREAM_REGION=eu-central-003
LITESTREAM_ACCESS_KEY_ID=...
LITESTREAM_SECRET_ACCESS_KEY=...
```

Restore the database:

```bash
set -a && . /etc/litestream.env && set +a && mkdir -p /home/ubuntu/NovaGuard/data
litestream restore -config /home/ubuntu/NovaGuard/deploy/litestream/litestream.yml "$NOVAGUARD_DB_PATH"
```

### 4b. Data — Google Drive fallback

When Litestream is unavailable, download the newest `novaguard-*.zip` from
Drive and verify it **before** trusting it:

```bash
unzip -o novaguard-*.zip -d restore-check && sqlite3 restore-check/data/novaguard.sqlite3 "PRAGMA integrity_check; SELECT 'guilds', COUNT(*) FROM guild_settings UNION ALL SELECT 'levels', COUNT(*) FROM level_records UNION ALL SELECT 'wallets', COUNT(*) FROM economy_wallets;"
```

`ok` plus non-zero counts means the archive is good. Copy
`restore-check/data/` over `NovaGuard/data/`.

### 5. Secrets and permissions

Restore `.env` from the password manager, then:

```bash
cd /home/ubuntu/NovaGuard && chmod 600 .env data/novaguard.sqlite3
```

Confirm nothing critical is missing — the bot logs a `[config]` report at
startup and `/health` shows the same checks in Discord.

### 6. Backups back on

```bash
rclone config
```

Recreate the remote under the **same name** used in `BACKUP_REMOTE_DEST`, or
the scheduled uploads will fail silently. Verify:

```bash
rclone lsd "$(grep '^BACKUP_REMOTE_DEST=' /home/ubuntu/NovaGuard/.env | cut -d= -f2- | cut -d: -f1):"
```

### 7. Start

```bash
sudo cp /home/ubuntu/NovaGuard/deploy/litestream/litestream.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now litestream
```

```bash
cd /home/ubuntu/NovaGuard && pm2 start venv/bin/python --name novaguard -- bot.py && pm2 save && pm2 startup
```

### 8. Verify replication is actually running

```bash
systemctl status litestream --no-pager && litestream snapshots -config /home/ubuntu/NovaGuard/deploy/litestream/litestream.yml "$NOVAGUARD_DB_PATH"
```

A recent snapshot means you are protected again. No output means you are not,
whatever the service status says.

## Keep it honest

- **Test a restore on a schedule**, not during an outage. `/backup test` in
  Discord and the `litestream snapshots` check above both take seconds.
- **An untested backup is not a backup.** The failure mode is always silent:
  credentials rotate, a bucket is renamed, a remote is dropped, and nothing
  complains until the day it matters.
- Litestream does not replace the zip backups. Litestream protects against
  losing the host; the zips protect against losing the data itself to a bad
  write, because you can go back to a known-good archive.
