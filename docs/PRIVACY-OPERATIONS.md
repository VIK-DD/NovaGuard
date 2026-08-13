# NovaGuard Privacy Operations

This is the operational data-protection register and launch checklist for the
hosted NovaGuard service. It describes how the current code behaves; it is not
jurisdiction-specific legal advice. Review it whenever a feature, provider,
hosting region, retention value or public policy changes.

## Confirmed deployment facts

- Individual operator: Breabin Victor, Republic of Moldova.
- Private privacy/security and contact address: `breabinvc@gmail.com`.
- Main runtime and primary operational storage: Oracle Cloud Infrastructure,
  Germany.
- Encrypted off-site backup destination: Google Drive. The configured account
  does not currently pin a disclosed storage region; treat it as global
  processing. Archives are encrypted before upload and Google does not receive
  the NovaGuard backup key.
- Competent national authority: National Center for Personal Data Protection of
  the Republic of Moldova (CNPDCP), <https://datepersonale.md/about/contacts/>.

## Accountability and roles

- The NovaGuard operator controls account access, service security, abuse
  prevention, support, deployment, backups and the dashboard audit trail.
- A Discord server owner or administrator chooses which community features to
  enable, where logs are posted, which roles can act and how moderation is used.
  They must give members an understandable notice before enabling optional
  logging, AI or behavioural features and provide a route to human review.
- The legal role for community data depends on the actual arrangement. Do not
  promise that NovaGuard is always a processor or always an independent
  controller. An organisation that requires processor terms must have an
  Article 28-compatible data processing agreement before production use.
- Discord, Cloudflare, Oracle, GitHub and Anthropic have their own roles for the
  processing they independently determine. Their current terms, DPAs, regions
  and transfer mechanisms must be reviewed before launch and at least yearly.

The role analysis follows the EDPB controller/processor guidance:
<https://www.edpb.europa.eu/documents/guideline/guidelines-072020-on-the-concepts-of-controller-and-processor-in-the-gdpr_en>.

## Server-administrator notice and dashboard review

The public [Server Admin Notice](https://novaguard.fun/server-admin-notice)
is the copy-and-adapt notice for Discord communities. It covers the optional
features that are most likely to affect members: moderation/logging, levels,
voice reports, AI, tickets and economy. It must be adapted to the modules a
server actually enables; do not paste it unchanged while claiming features are
off when they are configured.

The authenticated dashboard's **Privacy & Safety** tab reads the live server
configuration and labels those feature effects as active or off. It is a review
aid, not an automated compliance attestation: it cannot know whether a server
owner has a lawful basis, published a community notice, restricted staff access
or provided human review. The release owner must keep those decisions outside
the dashboard and review them whenever the configuration changes.

Before enabling or materially changing one of these modules in a community:

1. Open Dashboard → Privacy & Safety and compare every active item with the
   server's visible notice and rules.
2. Restrict log, ticket and moderation channels to authorised staff roles.
3. Tell members where they can ask for a moderation review and use
   `/privacy export` or `/privacy delete` privately.
4. For organisations, record who made the enablement decision, its purpose,
   the notice location and the review date in the restricted processing log.

## Processing register

| Activity | People and data | Purpose | Working legal-basis assessment | Recipient/location | Live retention |
| --- | --- | --- | --- | --- | --- |
| Discord OAuth and dashboard | Administrator Discord ID, display name, avatar, manageable servers, encrypted OAuth tokens, hashed session ID | Authenticate and show only manageable servers | Requested service/contract; security is legitimate interest | Discord; Oracle-hosted NovaGuard API; Cloudflare website | OAuth state 10 minutes; session and token up to 7 days or logout |
| Configuration and administration | Guild/channel/role IDs, settings, acting administrator ID, setting changes | Run requested server features and maintain accountability | Requested service/contract; legitimate interests in reliable and secure operation | Oracle host; Discord for resulting actions | Configuration while needed; privileged bot audit 365 days; dashboard audit/IP 90 days; server data 30 days after removal |
| AutoMod and message XP | Discord ID and message content inspected in real time; XP/message totals | Apply configured moderation rules and award XP for meaningful participation | Server administrator's documented purpose and applicable lawful basis | Discord event stream; Oracle process memory and totals storage | Ordinary content is not archived by NovaGuard; XP totals while feature is active or until deletion |
| Edited/deleted message logging | Message author/channel identifiers and excerpt | Send the event to the log channel selected by the server administrator | Server administrator's documented purpose and applicable lawful basis | Reposted inside Discord; not retained as a separate NovaGuard archive | Controlled by Discord/server retention after reposting |
| Levels, economy and voice | Discord/guild IDs, XP, message count, balances, rewards, voice seconds and session/report metadata | Community progression and requested statistics | Requested feature; legitimate interests identified by the server administrator | Oracle host; results displayed in Discord/dashboard | Active totals while needed; voice history 13 months by default |
| Moderation, tickets, reminders and giveaways | Discord/guild/channel IDs, warning reason/moderator, ticket opener/name/timestamps, reminder text/time, giveaway host/entrants/winners | Deliver the user/admin-requested feature and keep an accountable record | Requested feature; moderation/community safety legitimate interests | Oracle host; relevant output in Discord | Closed tickets 180 days; warnings 365 days; completed giveaways 90 days; reminders until delivered/cancelled |
| `/ask` AI request | Discord ID for command/rate control and question text | Return an answer specifically requested by the member | Steps requested by the user; do not repurpose for profiling or advertising | Anthropic via its API; transient Oracle process memory | NovaGuard stores no question history; Anthropic's standard API retention is currently up to 30 days unless another arrangement applies |
| GitHub integration | Public repository, release and commit metadata; configured destination channel | Publish repository updates selected by the administrator | Requested service and legitimate interest | GitHub, Oracle host and Discord | Current configuration plus limited delivery state while enabled |
| Security, diagnostics and backups | IP address, Discord actor ID, timestamps, action metadata, errors; encrypted service state; keyed deletion tokens without raw Discord IDs | Detect abuse, investigate incidents, recover safely and prevent erased data from returning | Legitimate interests; legal obligation where applicable | Oracle host, Cloudflare, configured encrypted rclone destination | Dashboard audit/IP 90 days; local newest 10 backups; remote full/guild backups 90/60 days by default; deletion ledger for service lifetime |

The final public policy must state the operator's actual legal bases and
jurisdiction. “Legitimate interest” is not a label-only shortcut: record the
purpose, necessity and balancing assessment for each use that relies on it.

## Data sources and necessity

Data comes from Discord, the member using a command, the server administrator,
GitHub for configured public repositories and technical request metadata from
Cloudflare/the NovaGuard API. Discord IDs and requested command fields are
necessary for their corresponding features. Optional logging, levels, economy,
voice statistics, GitHub and AI can remain disabled. Refusing essential OAuth
cookies means the authenticated dashboard cannot work; the bot remains usable
from Discord where applicable.

NovaGuard must not use Discord API data for advertising, profiling people or
training machine-learning models. Review every new data use against Discord's
Developer Policy before implementation:
<https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy>.

## Individual-rights procedure

1. Accept requests at the published private privacy address or through the
   self-service Discord commands. Never ask someone to post personal data in a
   public GitHub issue.
2. `/privacy export` creates a private export tied to the caller's Discord ID.
   `/privacy delete` creates a final export and erases/anonymises live records.
   A server administrator can use `/privacy server-export` and
   `/privacy server-delete` for the server scope.
3. For manual access, correction, restriction, objection or deletion requests,
   verify control of the relevant Discord account or authority over the guild.
   Collect no more proof than necessary.
4. Record received time, scope, verification, searches performed, decision,
   delivery time and any refusal reason in a restricted case log. Target 30
   calendar days; escalate immediately if the applicable law is stricter.
5. Deliver exports privately. Never place them in support channels, public issue
   trackers or ordinary logs.
6. Live erasure writes a signed pseudonymous deletion token. Restore and host
   migration tools reapply that ledger so an old backup cannot resurrect erased
   data. The ledger contains no raw Discord ID and is stored outside full
   backups, with an encrypted off-site recovery copy.
7. Removing NovaGuard from a server is not treated as a deletion request. An
   accidental kick and a deliberate cleanup arrive as the same event, and
   erasure is irreversible, so the server's data is erased 30 days after
   removal and adding the bot back within that window cancels it. A server
   owner who wants immediate erasure uses `/privacy server-delete`, which is
   authenticated and does not wait. `PRIVACY_GUILD_GRACE_DAYS` configures the
   window; state the deployed value in the public policy.
8. If a record must be retained for a legal claim or security obligation,
   isolate it, restrict use, document the reason and erase it when that purpose
   ends.

Relevant GDPR rights include erasure, portability and objection:
<https://eur-lex.europa.eu/eli/reg/2016/679/art_17/oj/eng>.

## Automated moderation and human review

AutoMod uses administrator-configured rules; it does not make legal or similarly
significant decisions. Still, false positives can affect community access.
Server administrators must disclose enabled rules at an appropriate level,
provide a moderator appeal/review route and avoid inferring sensitive traits.
NovaGuard should expose reasons for actions in the server's moderation workflow
where doing so does not undermine abuse prevention.

Run a documented data-protection impact assessment before introducing large-
scale monitoring, sensitive-data inference, biometric data, cross-community
profiling, AI decisions that act without human review or a materially broader
message archive.

## Cookies and browser storage

The current website uses only first-party storage necessary for a requested
security/sign-in flow (`ng_state`, `ng_session`, `ng_gate`, `ng_preview`) and
explicit theme preferences (`ng-theme`, `ng-maintenance-theme`). It has no
advertising or analytics tracker. A consent banner would create a false choice
and is not required for strictly necessary storage; the policy must still
explain it. Add a real prior-consent control before any non-essential analytics,
marketing, fingerprinting or cross-site storage is introduced.

The strictly-necessary exception is in Article 5(3) of the ePrivacy Directive:
<https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32002L0058>.

## Vendors and international transfers

Maintain a restricted record of the selected Oracle region and backup remote.
Before launch, record for each provider: service, data categories, countries,
contract/DPA version, transfer mechanism, security review date and deletion
route. Do not claim all data stays in one country unless logs, edge processing,
support access and backups have all been verified.

- Cloudflare customer DPA: <https://www.cloudflare.com/cloudflare-customer-dpa/>
- Oracle privacy terms: <https://www.oracle.com/legal/privacy/privacy-policy/>
- Anthropic controller/processor explanation: <https://support.anthropic.com/en/articles/9267385-does-anthropic-act-as-a-data-processor-or-controller>
- Anthropic API retention: <https://privacy.anthropic.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data>
- Discord Developer Terms: <https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service>

## Incident and breach handling

Follow [INCIDENT-RESPONSE.md](INCIDENT-RESPONSE.md). Preserve a restricted
decision record for every personal-data incident, including the facts, affected
people/data, likely consequences, containment, notification decision and
reason. If GDPR applies, the supervisory-authority deadline is generally 72
hours after awareness unless the breach is unlikely to risk people's rights and
freedoms; high-risk cases also require communication to affected people.

## Pre-launch sign-off

The operator must complete and retain evidence for every item:

- [ ] Publish the legal operator's full name, contact address, country and a
      monitored private privacy/security email.
- [ ] Verify `/privacy policy` lists personal export/deletion and both
      server-scoped controls, including owner-only server deletion.
- [ ] In a test server, open Dashboard → Privacy & Safety, compare each active
      item with the enabled configuration, adapt the Server Admin Notice and
      post it in a visible rules, onboarding or privacy channel.
- [ ] Identify the competent supervisory authority and complaint route.
- [ ] Confirm the Oracle region and every rclone backup destination/country.
- [ ] Record the lawful basis and legitimate-interest assessment for every
      enabled purpose.
- [ ] Execute/review applicable provider DPAs and transfer safeguards.
- [ ] Decide whether organisational server customers need a NovaGuard data
      processing addendum; do not represent one as signed when it is not.
- [ ] Test `/privacy export`, `/privacy delete`, server export/delete and a
      restore that reapplies the deletion ledger.
- [ ] Generate an encrypted backup, verify the off-site copy and pass
      `venv/bin/python tools/production_check.py --strict`.
- [ ] Assign a person who monitors the privacy inbox and incident alerts.
- [ ] Complete the DPIA screen and record the release decision.
- [ ] Recheck minimum-age handling against Discord's current Terms.

### Evidence to retain for this release

Keep a restricted release record with the date, person performing the check and
result for: the public Privacy Policy and Terms URLs; a screenshot or permalink
to the adapted server notice; the selected module configuration; a private
privacy export/deletion test; encrypted backup and off-site verification; and
the output of the following command from the production host:

```bash
venv/bin/python tools/production_check.py --strict
```

The command demonstrates the host configuration and backup/ledger state. It
does not replace provider contract review, a legal assessment or the human
server-administration checks above.

If the operator is established in Moldova, obtain local advice before the
September launch: Law no. 195/2024 enters into force on 23 August 2026 and
introduces GDPR-style accountability, transparency, rights, records, DPIAs and
breach duties. Official CNPDCP summary:
<https://datepersonale.md/legea-nr-195-2024-privind-protectia-datelor-cu-caracter-personal-principalele-prevederi-si-noutati-legislative/>.
