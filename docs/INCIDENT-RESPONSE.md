# NovaGuard Incident Response

Use this runbook for a leaked credential, unauthorised dashboard access,
exposed backup, suspicious bot behaviour, host compromise or loss of personal
data. Do not improvise destructive cleanup before preserving enough evidence to
understand what happened.

## First 15 minutes

1. Record UTC detection time, reporter, affected host/account and what was
   observed. Never paste tokens, cookies, passwords or full private exports into
   an incident ticket or Discord channel.
2. If the bot account may be controlled, stop NovaGuard with `pm2 stop 0` and
   reset the bot token in Discord Developer Portal → **Bot → Reset Token**.
3. If the dashboard may be compromised, close public access at Cloudflare,
   rotate the Discord OAuth client secret and `WEB_TOKEN_KEY`, then invalidate
   sessions:

   ```bash
   sqlite3 data/novaguard.sqlite3 "DELETE FROM web_sessions;"
   pm2 restart 0 --update-env
   ```

4. If the website gate password leaked, rotate it as a Cloudflare secret from
   `website-3/` with `npx wrangler secret put AUTH_PASSWORD`.
5. Preserve PM2 logs, Cloudflare event/log timestamps, relevant dashboard audit
   rows and file hashes. Restrict access to the evidence; do not place it in the
   public Git repository.

Discord documents bot tokens as highly sensitive credentials that must not be
shared or committed, and its supported recovery action is **Reset Token**:
[Discord developer security guidance](https://docs.discord.com/developers/quick-start/getting-started).
Cloudflare requires sensitive Worker values to be stored as secrets rather than
plaintext variables: [Cloudflare Workers secrets](https://developers.cloudflare.com/workers/configuration/secrets/).

## Triage and containment

Classify the incident without minimising uncertainty:

| Severity | Example | Immediate action |
| --- | --- | --- |
| Critical | Bot/OAuth token exposed, host root compromise, unencrypted personal-data export public | Stop affected service, revoke credentials, restrict storage, begin breach assessment |
| High | Valid unauthorised dashboard session, encrypted backup plus key exposed, deletion ledger altered | Invalidate access, preserve audit evidence, verify scope and restored-data integrity |
| Medium | Repeated blocked login attempts, failed remote backup, accidental internal disclosure | Contain source, correct configuration, verify no successful access |
| Low | No-data availability issue or rejected attack with reliable controls | Document, monitor and close with evidence |

For each affected system, answer:

- What data and date range were accessible?
- Was confidentiality, integrity or availability affected?
- Were Discord IDs, message excerpts, IP addresses, OAuth tokens, moderation
  records, backups or deletion records involved?
- Which users and servers could be affected?
- Are encryption keys also exposed, or only encrypted data?
- Is access still possible?

## Personal-data breach decision

This is an operational checklist, not a substitute for jurisdiction-specific
legal advice. Because the operator is established in Moldova, Article 33 of
[Law no. 195/2024](https://datepersonale.md/data-controllers/data-breach-notification/)
requires notification to CNPDCP without undue delay and, where feasible, within
72 hours after awareness unless the breach is unlikely to risk people's rights
and freedoms. Article 34 requires communication to affected people without
undue delay when high risk is likely. GDPR Articles 33–34 impose the same core
timing and risk tests where GDPR also applies. Document the assessment even
when the decision is not to notify.

The incident record should contain the nature of the breach, affected data and
people, likely consequences, containment/remediation, decision maker, timeline,
notification decision and reason. Contact qualified counsel or the competent
authority when applicability or risk is uncertain.

## Recovery

1. Patch the root cause before restoring service.
2. Verify the repository revision and dependencies came from trusted sources.
3. Restore only through `tools/restore_backup.py`; never bypass the authenticated
   deletion ledger merely to make recovery faster.
4. Run:

   ```bash
   venv/bin/python tools/production_check.py --strict
   pm2 restart 0 --update-env
   pm2 logs 0 --lines 200
   ```

5. In Discord run `/doctor`, `/backup status`, `/backup remote` and `/privacy policy`.
6. Monitor Cloudflare and application errors closely for at least one full
   backup cycle. Confirm the new encrypted archive exists remotely.

## Post-incident

Within seven days, write a blameless review: timeline, root cause, why controls
did or did not work, affected scope, notification decisions, concrete owners
and deadlines. Update this runbook and add a regression test for every software
failure that contributed.
