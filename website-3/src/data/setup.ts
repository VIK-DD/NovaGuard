// Reference data for the /setup page, sourced from cogs/setup.py so the page
// and the bot cannot silently drift apart. Two things are duplicated across
// languages on purpose: CHANNEL_KEYS' labels/descriptions (Python can't be
// imported into Astro) and RECOMMENDED_KEYS (same reason). The emoji in the
// Python labels are dropped here — the page shows text labels only.

export interface ChannelRefEntry {
  key: string;
  label: string;
  description: string;
  group: "core" | "community";
  recommended: boolean;
}

// Mirrors cogs/setup.py's CHANNEL_KEYS, in the same order.
export const CHANNEL_REFERENCE: ChannelRefEntry[] = [
  {
    key: "update_channel",
    label: "Bot Updates",
    description: "Automatic code changelog and restart summaries",
    group: "core",
    recommended: true,
  },
  {
    key: "github_event_channel",
    label: "GitHub Feed",
    description: "Push, PR, issue and release activity",
    group: "core",
    recommended: false,
  },
  {
    key: "error_log_channel",
    label: "Admin Errors",
    description: "Serious bot error digest embeds",
    group: "core",
    recommended: true,
  },
  {
    key: "log_channel",
    label: "Server Logs",
    description: "Deleted/edited messages, joins/leaves, bans",
    group: "core",
    recommended: true,
  },
  {
    key: "voice_report_channel",
    label: "Voice Reports",
    description: "Completed voice session attendance and duration reports",
    group: "community",
    recommended: false,
  },
  {
    key: "welcome_channel",
    label: "Welcome",
    description: "New member welcome cards",
    group: "community",
    recommended: true,
  },
  {
    key: "goodbye_channel",
    label: "Goodbye",
    description: "Leave messages",
    group: "community",
    recommended: false,
  },
];

// Mirrors cogs/setup.py's RECOMMENDED_KEYS. github_event_channel is not here —
// it only joins the count when github_watch_configured is true (Task 1).
export const RECOMMENDED_CHANNEL_KEYS = [
  "update_channel",
  "error_log_channel",
  "log_channel",
  "welcome_channel",
] as const;

export interface CommandRefEntry {
  name: string;
  purpose: string;
}

// Descriptions copied verbatim from the app_commands.command() decorators in
// cogs/setup.py, so this list can't quietly say something the bot doesn't.
export const SETUP_COMMANDS: CommandRefEntry[] = [
  { name: "/setup", purpose: "Open the NovaGuard setup dashboard" },
  { name: "/config view", purpose: "View the saved NovaGuard configuration" },
  { name: "/config export", purpose: "Export this server's NovaGuard config as JSON" },
  { name: "/config backup", purpose: "Create a manual backup archive now" },
  { name: "/config reset", purpose: "Reset NovaGuard setup/config for this server" },
];

export interface RecommendedCount {
  done: number;
  total: number;
  missing: string[];
}

/**
 * Mirrors cogs/setup.py's setup_score: four recommended channels, plus a
 * fifth (github_event_channel) only when the bot is configured to watch
 * GitHub repos. `settings` only needs to carry the keys this function reads —
 * callers pass the validated GuildSettings object from the dashboard API.
 */
export function countRecommended(
  settings: Record<string, unknown>,
  githubWatchConfigured: boolean,
): RecommendedCount {
  const keys: string[] = [...RECOMMENDED_CHANNEL_KEYS];
  if (githubWatchConfigured) keys.push("github_event_channel");

  const missing = keys.filter((key) => !settings[key]);
  return { done: keys.length - missing.length, total: keys.length, missing };
}

export type GuildSelection =
  | { kind: "none" }
  | { kind: "single"; guild: { id: string; name: string } }
  | { kind: "multiple"; guilds: { id: string; name: string }[] };

/**
 * A guild the visitor manages but NovaGuard hasn't joined has no config to
 * report on — same as an empty list. Mirrors the bot_present filter
 * GuildPicker.tsx already applies for the same reason.
 */
export function classifyGuilds(
  guilds: { id: string; name: string; bot_present: boolean }[],
): GuildSelection {
  const present = guilds.filter((g) => g.bot_present).map((g) => ({ id: g.id, name: g.name }));
  if (present.length === 0) return { kind: "none" };
  if (present.length === 1) return { kind: "single", guild: present[0] };
  return { kind: "multiple", guilds: present };
}
