export const PRIVACY_EFFECTIVE_DATE = "August 11, 2026";

export const DATA_CATEGORIES = [
  {
    name: "Discord account and access",
    data: "User ID, display name, avatar reference, the servers returned by Discord OAuth, and whether you can manage each server.",
    use: "Sign you into the dashboard and show only servers you are allowed to configure.",
  },
  {
    name: "Server configuration",
    data: "Server, channel and role IDs; welcome, logging, AutoMod, levels, tickets and other feature settings.",
    use: "Run the features selected by a server administrator and keep them working after restarts.",
  },
  {
    name: "Community feature state",
    data: "User IDs with XP and message counts, voice minutes, economy balances, warnings, reminders, giveaway entries and similar feature records.",
    use: "Provide the feature a member or server administrator chose to use.",
  },
  {
    name: "Message content",
    data: "Messages are inspected in real time for AutoMod and meaningful-message XP. Deleted or edited message excerpts may be sent to the server's chosen Discord log channel. Questions sent with /ask are sent to Anthropic when AI is enabled.",
    use: "Moderation, server-visible logs, XP eligibility and the optional AI response. NovaGuard does not build its own stored archive of ordinary message history.",
  },
  {
    name: "Security and operations",
    data: "Dashboard IP address, Discord user ID, action, changed setting and timestamp; limited website request/error metadata at Cloudflare.",
    use: "Prevent abuse, diagnose failures and provide an accountable dashboard audit trail.",
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
  {
    name: "ng-status-snapshot-v1",
    lifetime: "Ignored after 10 minutes",
    purpose: "Reuses the latest public service-health snapshot so status remains useful during a brief network failure.",
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
    data: "Server configuration and community feature state",
    period: "While needed to operate the selected features, or until reset/deletion is requested",
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
    name: "GitHub",
    href: "https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement",
    detail: "Provides repository and release information when the GitHub integration is enabled.",
  },
  {
    name: "Anthropic",
    href: "https://www.anthropic.com/legal/privacy",
    detail: "Receives the text of a /ask question and returns an answer only when the optional AI feature is enabled.",
  },
] as const;
