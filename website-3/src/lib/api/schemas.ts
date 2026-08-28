// Zod schemas mirroring docs/API.md — the single source of truth for the
// dashboard's view of the bot API. Update alongside the contract.
import { z } from "zod";

export const StatsSchema = z.object({
  version: z.string(),
  phase: z.string().optional(),
  phase_label: z.string().optional(),
  release_label: z.string().optional(),
  runtime_version: z.string().optional(),
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
  ignored_channels: z.array(z.string()),
  ignored_roles: z.array(z.string()),
  spam_messages: z.number(),
  spam_window_seconds: z.number(),
  spam_timeout_seconds: z.number(),
});

/** Ids stay strings: Discord snowflakes exceed 2^53 and would lose digits as numbers. */
export const LevelsSchema = z.object({
  enabled: z.boolean(),
  announce: z.enum(["dm", "channel", "off"]),
  announce_channel: z.string().nullable(),
  xp_min: z.number(),
  xp_max: z.number(),
  cooldown: z.number(),
  ignored_channels: z.array(z.string()),
  ignored_roles: z.array(z.string()),
});
export type Levels = z.infer<typeof LevelsSchema>;
export type AnnounceMode = Levels["announce"];

export const AiSettingsSchema = z.object({
  enabled: z.boolean(),
  answer_mode: z.enum(["public", "private"]),
  channel_id: z.string().nullable(),
  max_question_chars: z.number(),
});
export type AiSettings = z.infer<typeof AiSettingsSchema>;

export const EconomySettingsSchema = z.object({
  enabled: z.boolean(),
  daily_base: z.number(),
  daily_streak_bonus: z.number(),
  work_min: z.number(),
  work_max: z.number(),
  work_cooldown_minutes: z.number(),
  transfers_enabled: z.boolean(),
  games_enabled: z.boolean(),
  shop_enabled: z.boolean(),
  gamble_max_bet: z.number(),
  slots_max_bet: z.number(),
});
export type EconomySettings = z.infer<typeof EconomySettingsSchema>;

export const GuildSettingsSchema = z.object({
  welcome_channel: z.string().nullable(),
  goodbye_channel: z.string().nullable(),
  log_channel: z.string().nullable(),
  voice_report_channel: z.string().nullable(),
  update_channel: z.string().nullable(),
  github_event_channel: z.string().nullable(),
  error_log_channel: z.string().nullable(),
  ticket_panel_channel: z.string().nullable(),
  role_panel_channel: z.string().nullable(),
  giveaway_channel: z.string().nullable(),
  autorole: z.string().nullable(),
  ticket_staff_role: z.string().nullable(),
  automod: AutomodSchema,
  levels: LevelsSchema,
  ai: AiSettingsSchema,
  economy: EconomySettingsSchema,
});
export type GuildSettings = z.infer<typeof GuildSettingsSchema>;

export const GuildConfigSchema = z.object({
  // Instance-wide (same for every guild), not a per-guild setting — see
  // core/webserver.py's _config_payload. Used only to size the /setup page's
  // recommended-channel count the same way cogs/setup.py's setup_score does.
  github_watch_configured: z.boolean(),
  guild: z.object({
    id: z.string(),
    name: z.string(),
    icon: z.string().nullable(),
    member_count: z.number(),
  }),
  settings: GuildSettingsSchema,
  ai_status: z.object({
    available: z.boolean(),
    model: z.string().nullable(),
    minute_calls: z.number(),
    minute_cap: z.number(),
    daily_calls: z.number(),
    daily_cap: z.number(),
  }),
  economy_status: z.object({
    tracked_wallets: z.number(),
    total_coins: z.number(),
    leaderboard: z.array(
      z.object({
        position: z.number(),
        user_id: z.string(),
        display_name: z.string(),
        coins: z.number(),
        daily_streak: z.number(),
      }),
    ),
    shop: z.array(
      z.object({
        key: z.string(),
        label: z.string(),
        icon: z.string(),
        price: z.number(),
        kind: z.string(),
        description: z.string().nullable().optional(),
      }),
    ),
  }),
  tickets: z.object({
    panel_channel_id: z.string().nullable(),
    panel_message_id: z.string().nullable(),
    ready: z.boolean(),
    open_count: z.number(),
    open: z.array(
      z.object({
        thread_id: z.string(),
        opener_id: z.string(),
        opener_name: z.string(),
        created_at: z.string(),
      }),
    ),
  }),
  role_panels: z.array(
    z.object({
      message_id: z.string(),
      channel_id: z.string(),
      title: z.string(),
      description: z.string(),
      role_ids: z.array(z.string()),
      updated_at: z.string(),
    }),
  ),
  giveaways: z.array(
    z.object({
      message_id: z.string(),
      channel_id: z.string(),
      prize: z.string(),
      winners: z.number(),
      host_name: z.string(),
      ends_at: z.string(),
      entrant_count: z.number(),
      ended: z.boolean(),
      winner_ids: z.array(z.string()),
    }),
  ),
  channels: z.array(
    z.object({ id: z.string(), name: z.string(), category: z.string().nullable() }),
  ),
  roles: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      color: z.string(),
      assignable: z.boolean(),
      manages_threads: z.boolean(),
    }),
  ),
});
export type GuildConfig = z.infer<typeof GuildConfigSchema>;
export type GuildChannel = GuildConfig["channels"][number];
export type GuildRole = GuildConfig["roles"][number];

export const AuditSchema = z.object({
  audit: z.array(
    z.object({
      id: z.number(),
      username: z.string(),
      user_id: z.string(),
      action: z.string(),
      // Zod 4 wants the key type spelled out; z.record(value) is gone.
      changes: z.record(z.string(), z.unknown()),
      created_at: z.string(),
    }),
  ),
  next_cursor: z.number().nullable(),
});
export type AuditEntry = z.infer<typeof AuditSchema>["audit"][number];

export const DashboardSchema = z.object({
  status: z.object({
    ready: z.boolean(),
    version: z.string(),
    phase: z.string().optional(),
    phase_label: z.string().optional(),
    release_label: z.string().optional(),
    runtime_version: z.string().optional(),
    codename: z.string(),
    uptime_seconds: z.number(),
    commands: z.number(),
    guilds: z.number(),
    members: z.number(),
  }),
  guild: z.object({
    id: z.string(),
    name: z.string(),
    icon: z.string().nullable(),
    member_count: z.number(),
  }),
  setup: z.object({
    configured_channels: z.number(),
    total_channels: z.number(),
    recommended_done: z.number(),
    recommended_total: z.number(),
  }),
  modules: z.array(z.object({ key: z.string(), label: z.string(), enabled: z.boolean() })),
  automod: z.object({
    invites: z.boolean(),
    spam: z.boolean(),
    badwords_count: z.number(),
  }),
  levels: z.object({
    enabled: z.boolean(),
    tracked_members: z.number(),
    total_xp: z.number().optional(),
    leaderboard: z.array(
      z.object({
        position: z.number(),
        user_id: z.string(),
        display_name: z.string(),
        xp: z.number(),
        messages: z.number(),
        level: z.number(),
      }),
    ),
  }),
  voice: z.object({
    configured: z.boolean(),
    report_channel_id: z.string().nullable(),
    pending_count: z.number(),
    recent_reports: z.array(
      z.object({
        id: z.string(),
        channel_id: z.string(),
        channel_name: z.string(),
        started_at: z.string().nullable(),
        ended_at: z.string().nullable(),
        sent_at: z.string().nullable().optional(),
        duration_seconds: z.number(),
        unique_members: z.number(),
        peak_members: z.number(),
      }),
    ),
  }),
  updates: z.array(
    z.object({
      build: z.number().optional(),
      // The public version this update shipped in. Lifecycle data stays
      // machine-readable; public UI prints the version only.
      // Optional so a bot that has not been updated yet still parses; the
      // dashboard falls back to the build number when it is missing.
      release: z.string().optional(),
      phase_label: z.string().optional(),
      version: z.string().optional(),
      codename: z.string().optional(),
      created_at: z.string(),
      highlights: z.array(z.string()).optional(),
      changes: z.array(z.string()).optional(),
      added_lines: z.number().optional(),
      removed_lines: z.number().optional(),
      changed_files: z.number().optional(),
    }),
  ),
});
export type Dashboard = z.infer<typeof DashboardSchema>;

export const DashboardActionSchema = z.object({
  ok: z.boolean(),
  action: z.string(),
  message: z.string(),
  channel_id: z.string().optional(),
  panel: z
    .object({
      message_id: z.string(),
      channel_id: z.string(),
      title: z.string(),
      description: z.string(),
      role_ids: z.array(z.string()),
      updated_at: z.string(),
    })
    .optional(),
});
export type DashboardAction = z.infer<typeof DashboardActionSchema>;

export const OkSchema = z.object({ ok: z.boolean() });

/** Partial body for PUT /guilds/{id}/config — only changed keys are sent. */
export type SettingsPatch = Partial<{
  welcome_channel: string | null;
  goodbye_channel: string | null;
  log_channel: string | null;
  voice_report_channel: string | null;
  update_channel: string | null;
  github_event_channel: string | null;
  error_log_channel: string | null;
  ticket_panel_channel: string | null;
  role_panel_channel: string | null;
  giveaway_channel: string | null;
  autorole: string | null;
  ticket_staff_role: string | null;
  automod: Partial<z.infer<typeof AutomodSchema>>;
  levels: Partial<Levels>;
  ai: Partial<AiSettings>;
  economy: Partial<EconomySettings>;
}>;
