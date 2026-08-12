import { LEGAL_EFFECTIVE_DATE } from "./legal";

export const PRIVACY_EFFECTIVE_DATE = LEGAL_EFFECTIVE_DATE;

export const DATA_CATEGORIES = [
  {
    name: "Discord account and access",
    data: "User ID, display name, avatar reference, the servers returned by Discord OAuth, and whether you can manage each server.",
    use: "Sign you into the dashboard and show only servers you are allowed to configure.",
    basis: "Providing the sign-in and dashboard you request; security and access-control interests.",
  },
  {
    name: "Server configuration",
    data: "Server, channel and role IDs; welcome, logging, AutoMod, levels, tickets and other feature settings.",
    use: "Run the features selected by a server administrator and keep them working after restarts.",
    basis: "Providing the configured service; reliable-operation and community-management interests.",
  },
  {
    name: "Community feature state",
    data: "User IDs with XP and message counts, voice minutes, economy balances, warnings, reminders, ticket metadata, giveaway entries and similar feature records.",
    use: "Provide the feature a member or server administrator chose to use.",
    basis: "Providing the requested feature; the server administrator must identify and communicate any additional basis required for its community.",
  },
  {
    name: "Message content",
    data: "Messages are inspected in real time for AutoMod and meaningful-message XP. Deleted or edited message excerpts may be sent to the server's chosen Discord log channel. Questions sent with /ask are sent to Anthropic when AI is enabled.",
    use: "Moderation, server-visible logs, XP eligibility and the optional AI response. NovaGuard does not build its own stored archive of ordinary message history.",
    basis: "Providing the requested feature and legitimate interests in community safety; optional features must be disclosed by the server administrator.",
  },
  {
    name: "Security and operations",
    data: "Dashboard IP address, Discord user ID, action, changed setting and timestamp; limited website request/error metadata at Cloudflare.",
    use: "Prevent abuse, diagnose failures and provide an accountable dashboard audit trail.",
    basis: "Legitimate interests in security, fraud prevention, accountability and service reliability; legal obligations where applicable.",
  },
] as const;

export const ESSENTIAL_COOKIES = [
  {
    name: "ng_state",
    lifetime: "10 minutes",
    purpose: "Protects the Discord sign-in callback against forged OAuth requests.",
    when: "Discord sign-in",
  },
  {
    name: "ng_session",
    lifetime: "7 days, or until logout",
    purpose: "Keeps the dashboard signed in. The browser stores a random ID; the server stores only its SHA-256 hash.",
    when: "Authenticated dashboard",
  },
  {
    name: "ng_gate",
    lifetime: "2 hours",
    purpose: "Opens the private pre-launch website after the correct access password is entered.",
    when: "Private launch gate only",
  },
  {
    name: "ng_preview",
    lifetime: "12 hours at most",
    purpose: "Lets an authorised tester view the website during one specific maintenance window.",
    when: "Maintenance preview only",
  },
] as const;

export const BROWSER_STORAGE = [
  {
    name: "ng-theme",
    lifetime: "Until browser storage is cleared",
    purpose: "Remembers the light or dark theme explicitly selected on this device.",
  },
  {
    name: "ng-maintenance-theme",
    lifetime: "Until browser storage is cleared",
    purpose: "Keeps the same theme preference on the standalone maintenance page for older visits.",
  },
] as const;

export const RETENTION_ROWS = [
  {
    data: "OAuth state",
    period: "10 minutes",
  },
  {
    data: "Dashboard login session and encrypted Discord OAuth tokens",
    period: "Up to 7 days; removed on logout or expiry",
  },
  {
    data: "Dashboard audit events, including IP address",
    period: "90 days",
  },
  {
    data: "Privileged bot-administration audit events",
    period: "365 days",
  },
  {
    data: "Closed ticket metadata / moderation warnings / completed giveaways",
    period: "180 days / 365 days / 90 days by default",
  },
  {
    data: "Monthly voice totals",
    period: "13 months by default",
  },
  {
    data: "Reminders",
    period: "Until delivered, cancelled or erased",
  },
  {
    data: "Other active server configuration and community feature state",
    period: "While needed for the selected feature, or until reset/erasure is requested",
  },
  {
    data: "Ordinary message content and /ask questions in NovaGuard storage",
    period: "Not stored as message/question history; Anthropic states standard API inputs and outputs are normally retained for up to 30 days",
  },
  {
    data: "Signed pseudonymous deletion tokens",
    period: "For the service lifetime, or until old backups can no longer restore erased records; raw Discord IDs are not stored in the ledger",
  },
  {
    data: "Local full backups",
    period: "Newest 10 archives",
  },
  {
    data: "Off-site full backups / per-server exports",
    period: "90 days / 60 days by default; the operator may configure shorter periods",
  },
] as const;

export const THIRD_PARTIES = [
  {
    name: "Discord",
    href: "https://discord.com/privacy/privacypolicy",
    detail: "Hosts the communities, messages and interactions; provides OAuth identity and server access data.",
  },
  {
    name: "Cloudflare",
    href: "https://www.cloudflare.com/privacypolicy/",
    detail: "Hosts and protects the website at the network edge and may process IP address and request metadata.",
  },
  {
    name: "Oracle Cloud Infrastructure",
    href: "https://www.oracle.com/cloud/public-cloud-regions/",
    detail: "Hosts NovaGuard's bot, API and primary operational storage in Germany.",
  },
  {
    name: "Google Drive",
    href: "https://policies.google.com/privacy/frameworks",
    detail: "Receives authenticated encrypted backup archives. NovaGuard encrypts them before upload and does not send Google the backup key. Google may process account, file and service metadata and the encrypted files on global infrastructure.",
  },
  {
    name: "GitHub",
    href: "https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement",
    detail: "Provides repository and release information when the GitHub integration is enabled.",
  },
  {
    name: "Anthropic",
    href: "https://privacy.anthropic.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data",
    detail: "Receives the text of a /ask question and returns an answer only when the optional AI feature is enabled. NovaGuard stores no question history; Anthropic states standard API inputs and outputs are normally retained for up to 30 days.",
  },
] as const;
