# NovaGuard release compliance evidence — private template

Copy this file to the ignored `compliance-evidence/` directory for each public
release. Do not commit the completed copy: it may contain provider account
details, contracts, infrastructure screenshots and personal data. A checkbox
means evidence was actually reviewed and retained, not merely that a setting
exists in the repository.

## Release record

- Release/version:
- Commit SHA:
- Review date and timezone:
- Reviewer and role:
- Decision: `approved` / `blocked`
- Blockers and owner:
- Next scheduled review:

## Public transparency

- [ ] Privacy Policy, Terms and Server Admin Notice return `200` anonymously.
- [ ] Operator legal name, contact address, country and monitored privacy email
      are accurate.
- [ ] The competent authority and complaint URL are accurate.
- [ ] Enabled providers, purposes, data categories, locations and retention
      periods match production.
- Evidence paths/permalinks and document versions:

## Roles, lawful basis and providers

- [ ] Controller/processor roles were decided for the bot operator and each
      server administrator/customer.
- [ ] Each enabled purpose has a recorded lawful basis and, where applicable,
      a legitimate-interest assessment.
- [ ] Current DPA/transfer terms for Discord, Oracle, Cloudflare, Google/rclone
      and optional Anthropic processing were reviewed and retained.
- [ ] DPIA screening and minimum-age review have named decisions and owners.
- [ ] Python and production Node dependency inventories were generated from
      the exact release locks; required license/NOTICE texts were reviewed.
- Evidence paths, contract versions and decisions:

## Rights and recovery tests

- [ ] Personal export and deletion were tested with a private test account.
- [ ] Server export and owner-only server deletion were tested.
- [ ] An encrypted local backup and its off-site existence check passed.
- [ ] A restore test reapplied the authenticated deletion ledger.
- [ ] The privacy/security inbox and incident alerts have a named monitor.
- Test timestamps, sanitized results and evidence paths:

## Infrastructure controls

- [ ] Provider evidence confirms encryption at rest for production boot/block
      volumes, snapshots and operational copies.
- [ ] The dashboard API binds to loopback and the origin is reachable only via
      the intended Cloudflare path/firewall posture.
- [ ] A current edge rate-limit rule covers the public API; a safe test burst
      returned `429` without disrupting real users.
- [ ] `venv/bin/python tools/production_check.py --strict` returned `READY`.
- Provider rule/config identifiers, sanitized command output and evidence paths:

## Sign-off

- Residual risks accepted and reason:
- Required follow-up and deadline:
- Reviewer signature/name and date:
