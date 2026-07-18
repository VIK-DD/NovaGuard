// Zod schemas mirroring docs/API.md — the single source of truth for the
// dashboard's view of the bot API. Update alongside the contract.
import { z } from "zod";

export const StatsSchema = z.object({
  version: z.string(),
  codename: z.string(),
  guilds: z.number(),
  members: z.number(),
  commands: z.number(),
  uptime_seconds: z.number(),
  ready: z.boolean(),
});
export type Stats = z.infer<typeof StatsSchema>;

export const MeSchema = z.object({
  user: z.object({
    id: z.string(),
    username: z.string(),
    avatar: z.string().nullable(),
  }),
});
export type Me = z.infer<typeof MeSchema>;

export const GuildSchema = z.object({
  id: z.string(),
  name: z.string(),
  icon: z.string().nullable(),
  owner: z.boolean(),
  permissions: z.number(),
  bot_present: z.boolean(),
});
export type Guild = z.infer<typeof GuildSchema>;

export const GuildsSchema = z.object({ guilds: z.array(GuildSchema) });

export const AutomodSchema = z.object({
  invites: z.boolean(),
  spam: z.boolean(),
  badwords: z.array(z.string()),
});

export const GuildSettingsSchema = z.object({
  welcome_channel: z.string().nullable(),
  goodbye_channel: z.string().nullable(),
  log_channel: z.string().nullable(),
  update_channel: z.string().nullable(),
  github_event_channel: z.string().nullable(),
  error_log_channel: z.string().nullable(),
  autorole: z.string().nullable(),
  ticket_staff_role: z.string().nullable(),
  automod: AutomodSchema,
});
export type GuildSettings = z.infer<typeof GuildSettingsSchema>;

export const GuildConfigSchema = z.object({
  guild: z.object({
    id: z.string(),
    name: z.string(),
    icon: z.string().nullable(),
    member_count: z.number(),
  }),
  settings: GuildSettingsSchema,
  channels: z.array(
    z.object({ id: z.string(), name: z.string(), category: z.string().nullable() }),
  ),
  roles: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      color: z.string(),
      assignable: z.boolean(),
    }),
  ),
});
export type GuildConfig = z.infer<typeof GuildConfigSchema>;
export type GuildChannel = GuildConfig["channels"][number];
export type GuildRole = GuildConfig["roles"][number];

export const AuditSchema = z.object({
  audit: z.array(
    z.object({
      username: z.string(),
      user_id: z.string(),
      action: z.string(),
      changes: z.record(z.unknown()),
      created_at: z.string(),
    }),
  ),
});
export type AuditEntry = z.infer<typeof AuditSchema>["audit"][number];

export const OkSchema = z.object({ ok: z.boolean() });

/** Partial body for PUT /guilds/{id}/config — only changed keys are sent. */
export type SettingsPatch = Partial<{
  welcome_channel: string | null;
  goodbye_channel: string | null;
  log_channel: string | null;
  update_channel: string | null;
  github_event_channel: string | null;
  error_log_channel: string | null;
  autorole: string | null;
  ticket_staff_role: string | null;
  automod: Partial<{ invites: boolean; spam: boolean; badwords: string[] }>;
}>;
