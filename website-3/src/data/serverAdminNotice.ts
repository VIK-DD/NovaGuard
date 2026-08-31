export type MemberNoticeFeature = {
  id: string;
  label: string;
  detail: string;
};

export const MEMBER_NOTICE_FEATURES: readonly MemberNoticeFeature[] = [
  {
    id: "moderation",
    label: "Moderation and AutoMod",
    detail:
      "Enabled AutoMod rules may inspect messages in real time. Warnings and moderation actions may create records linked to Discord IDs.",
  },
  {
    id: "server-logs",
    label: "Server Logs",
    detail:
      "Deleted or edited message excerpts and selected server events may be reposted to this server's restricted Discord log channel. NovaGuard does not create a separate archive of ordinary message history.",
  },
  {
    id: "levels",
    label: "Levels and XP",
    detail:
      "NovaGuard keeps XP, qualifying message counts, levels and configured reward state for participating members.",
  },
  {
    id: "economy",
    label: "Economy",
    detail:
      "NovaGuard keeps virtual balances, rewards, cooldowns and other economy feature state linked to Discord IDs.",
  },
  {
    id: "voice",
    label: "Voice statistics",
    detail:
      "NovaGuard keeps voice participation time and report metadata. It does not record or store voice audio.",
  },
  {
    id: "tickets",
    label: "Tickets",
    detail:
      "NovaGuard uses Discord IDs and ticket or channel metadata needed to create and manage support tickets inside Discord.",
  },
  {
    id: "reminders",
    label: "Reminders",
    detail:
      "NovaGuard keeps the requesting Discord ID, reminder text and delivery time while a reminder is pending.",
  },
  {
    id: "giveaways",
    label: "Giveaways",
    detail:
      "NovaGuard keeps giveaway configuration and participating Discord IDs while the giveaway is active and its result is maintained.",
  },
  {
    id: "community-automation",
    label: "Welcome, goodbye and role panels",
    detail:
      "NovaGuard uses member, channel and role IDs plus the server's configured messages to deliver these community automations.",
  },
  {
    id: "ai",
    label: "AI-assisted answers (/ask)",
    detail:
      "Only when a member runs /ask, the submitted question is sent to Anthropic to generate an answer. NovaGuard keeps no local question history; members should not include sensitive information in prompts.",
  },
  {
    id: "github",
    label: "GitHub updates",
    detail:
      "NovaGuard reads the public repository information configured by this server to provide GitHub activity updates.",
  },
] as const;

const featureById = new Map(MEMBER_NOTICE_FEATURES.map((feature) => [feature.id, feature]));

export function buildMemberNotice(
  selectedFeatureIds: readonly string[],
  privacyEmail: string,
): string {
  const selected = [...new Set(selectedFeatureIds)]
    .map((id) => featureById.get(id))
    .filter((feature): feature is MemberNoticeFeature => feature !== undefined);

  const declaredFeatures = selected.length
    ? selected.map((feature) => feature.label).join(", ")
    : "Core server management only; no optional modules are declared active in this notice.";

  const featureDetails = selected.length
    ? selected.map((feature) => `- **${feature.label}:** ${feature.detail}`).join("\n")
    : "- **Optional modules:** None are declared active in this notice.";

  return `## NovaGuard privacy notice

This server uses NovaGuard for server management and member-requested features. Server administrators choose which optional modules are active and restrict staff-only channels to authorized moderators.

**Features declared active here:** ${declaredFeatures}

**Data used for the service:** NovaGuard processes the Discord user, server, channel or role IDs and configuration needed to respond to commands, apply this server's settings and keep the declared features working.

**Feature-specific processing:**
${featureDetails}

**Your controls:** Use /privacy export to receive the NovaGuard records linked to your Discord ID, or /privacy delete to receive a final export and request erasure or anonymisation of live records. For a server-specific privacy question or moderation appeal, contact this server's moderators first.

**NovaGuard Privacy Policy:** https://novaguard.fun/privacy
**Administrator notice guide:** https://novaguard.fun/server-admin-notice
**NovaGuard privacy contact:** ${privacyEmail}`;
}
