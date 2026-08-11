import type { GuildSettings } from "../lib/api/schemas";
import type { IconName } from "./components/Icon";

export const CONFIG_MODULES = [
  {
    key: "welcome",
    label: "Welcome",
    description: "Greet new members, say goodbye and assign their first role.",
    icon: "users-three",
    fields: ["welcome_channel", "goodbye_channel", "autorole"],
  },
  {
    key: "moderation",
    label: "Moderation",
    description: "Filter harmful messages and route moderation activity.",
    icon: "shield-check",
    fields: ["log_channel", "error_log_channel", "automod"],
  },
  {
    key: "levels",
    label: "Levels",
    description: "Reward activity with XP and level-up announcements.",
    icon: "trophy",
    fields: ["levels"],
  },
  {
    key: "voice",
    label: "Voice reports",
    description: "Publish attendance and duration reports after voice sessions.",
    icon: "users-three",
    fields: ["voice_report_channel"],
  },
  {
    key: "tickets",
    label: "Tickets",
    description: "Choose the staff role that can handle support tickets.",
    icon: "clipboard-text",
    fields: ["ticket_panel_channel", "ticket_staff_role"],
  },
  {
    key: "roles",
    label: "Role panels",
    description: "Publish self-service role panels and keep them editable from the web.",
    icon: "users-three",
    fields: ["role_panel_channel"],
  },
  {
    key: "giveaways",
    label: "Giveaways",
    description: "Create, monitor, end and reroll giveaways without slash commands.",
    icon: "trophy",
    fields: ["giveaway_channel"],
  },
  {
    key: "ai",
    label: "AI assistant",
    description: "Control where /ask works, answer privacy and question limits.",
    icon: "hash",
    fields: ["ai"],
  },
  {
    key: "economy",
    label: "Economy",
    description: "Tune rewards, cooldowns, transfers, games and shop access.",
    icon: "trophy",
    fields: ["economy"],
  },
  {
    key: "music",
    label: "Music",
    description: "Set playback limits and control the server's active voice session.",
    icon: "arrows-clockwise",
    fields: ["music"],
  },
  {
    key: "updates",
    label: "Updates",
    description: "Send NovaGuard releases and GitHub activity to Discord.",
    icon: "arrows-clockwise",
    fields: ["update_channel", "github_event_channel"],
  },
] as const satisfies ReadonlyArray<{
  key: string;
  label: string;
  description: string;
  icon: IconName;
  fields: ReadonlyArray<keyof GuildSettings>;
}>;

export type ConfigModuleKey = (typeof CONFIG_MODULES)[number]["key"];

export function getConfigModule(key: string | undefined) {
  return CONFIG_MODULES.find((module) => module.key === key);
}

/** Resolve compact dashboard module keys to their focused settings page. */
export function dashboardModuleKey(key: string): ConfigModuleKey {
  const direct = getConfigModule(key);
  if (direct) return direct.key;
  if (key === "logs" || key === "automod") return "moderation";
  return "moderation";
}

export function configModulePath(guildId: string, key: ConfigModuleKey) {
  return `/dashboard/g/${encodeURIComponent(guildId)}/settings/${key}`;
}

export function isModuleActive(settings: GuildSettings, key: ConfigModuleKey): boolean {
  switch (key) {
    case "welcome":
      return Boolean(settings.welcome_channel || settings.goodbye_channel || settings.autorole);
    case "moderation":
      return Boolean(
        settings.log_channel ||
          settings.error_log_channel ||
          settings.automod.invites ||
          settings.automod.spam ||
          settings.automod.badwords.length,
      );
    case "levels":
      return settings.levels.enabled;
    case "voice":
      return Boolean(settings.voice_report_channel);
    case "tickets":
      return Boolean(settings.ticket_panel_channel || settings.ticket_staff_role);
    case "roles":
      return Boolean(settings.role_panel_channel);
    case "giveaways":
      return Boolean(settings.giveaway_channel);
    case "ai":
      return settings.ai.enabled;
    case "economy":
      return settings.economy.enabled;
    case "music":
      return settings.music.enabled;
    case "updates":
      return Boolean(settings.update_channel || settings.github_event_channel);
  }
}
