import type { GuildSettings } from "../../lib/api/schemas";
import type { ConfigModuleKey } from "../moduleCatalog";

export type PrivacySafetySettings = Pick<
  GuildSettings,
  "log_channel" | "voice_report_channel" | "ticket_panel_channel" | "ticket_staff_role"
> & {
  automod: Pick<GuildSettings["automod"], "invites" | "spam" | "badwords">;
  levels: Pick<GuildSettings["levels"], "enabled">;
  ai: Pick<GuildSettings["ai"], "enabled">;
  economy: Pick<GuildSettings["economy"], "enabled">;
};

export type PrivacySafetySignal = {
  moduleId: ConfigModuleKey;
  title: string;
  active: boolean;
  activeLabel: string;
  activeDetail: string;
  inactiveDetail: string;
};

/**
 * Maps the actual guild configuration to the member-facing effects worth
 * reviewing. This intentionally does not report a legal "pass": a website
 * cannot know whether an admin posted a notice or has authority for a server.
 */
export function getPrivacySafetySignals(
  settings: PrivacySafetySettings,
): PrivacySafetySignal[] {
  const automodActive =
    settings.automod.invites || settings.automod.spam || settings.automod.badwords.length > 0;

  return [
    {
      moduleId: "moderation",
      title: "Moderation and server logs",
      active: Boolean(settings.log_channel) || automodActive,
      activeLabel: settings.log_channel ? "Logs active" : "AutoMod active",
      activeDetail: settings.log_channel
        ? "Edited or deleted message excerpts can be reposted in your private log channel. AutoMod may also inspect messages as they are sent."
        : "AutoMod may inspect messages as they are sent. It does not create NovaGuard's own ordinary message-history archive.",
      inactiveDetail: "Server Logs and the configured AutoMod rules are currently off.",
    },
    {
      moduleId: "levels",
      title: "Levels and activity records",
      active: settings.levels.enabled,
      activeLabel: "Levels active",
      activeDetail: "Levels records XP and eligible message counts so members can receive progression and rankings.",
      inactiveDetail: "Levels are currently off.",
    },
    {
      moduleId: "voice",
      title: "Voice reports",
      active: Boolean(settings.voice_report_channel),
      activeLabel: "Voice reports active",
      activeDetail: "Voice reports can publish attendance and duration information after a voice session ends.",
      inactiveDetail: "No voice-report channel is configured.",
    },
    {
      moduleId: "ai",
      title: "AI-assisted answers",
      active: settings.ai.enabled,
      activeLabel: "AI active",
      activeDetail: "Questions submitted with /ask are sent to Anthropic to generate an answer. Tell members not to include sensitive information.",
      inactiveDetail: "The /ask AI feature is currently off.",
    },
    {
      moduleId: "tickets",
      title: "Support tickets",
      active: Boolean(settings.ticket_panel_channel || settings.ticket_staff_role),
      activeLabel: "Tickets configured",
      activeDetail: "Ticket metadata and support content are available to the staff members you authorize. Keep the staff role and ticket channels restricted.",
      inactiveDetail: "No ticket panel or ticket staff role is configured.",
    },
    {
      moduleId: "economy",
      title: "Economy records",
      active: settings.economy.enabled,
      activeLabel: "Economy active",
      activeDetail: "Economy records balances and activity needed for rewards, transfers, games and the shop.",
      inactiveDetail: "The economy module is currently off.",
    },
  ];
}
