import type { GuildChannel, GuildConfig, GuildRole, GuildSettings } from "../../lib/api/schemas";

export const channels: GuildChannel[] = [
  { id: "1", name: "general", category: null },
  { id: "2", name: "staff", category: "Team" },
];

export const roles: GuildRole[] = [
  { id: "10", name: "Member", color: "#5865f2", assignable: true, manages_threads: false },
  { id: "11", name: "Owner", color: "#ed4245", assignable: false, manages_threads: true },
];

export const createSettings = (): GuildSettings => ({
  welcome_channel: "1",
  goodbye_channel: null,
  log_channel: "2",
  voice_report_channel: null,
  update_channel: null,
  github_event_channel: null,
  error_log_channel: null,
  ticket_panel_channel: null,
  role_panel_channel: null,
  giveaway_channel: null,
  autorole: "10",
  ticket_staff_role: null,
  automod: {
    invites: true,
    spam: false,
    badwords: [],
    ignored_channels: [],
    ignored_roles: [],
    spam_messages: 6,
    spam_window_seconds: 6,
    spam_timeout_seconds: 60,
  },
  levels: {
    enabled: true,
    announce: "dm",
    announce_channel: null,
    xp_min: 5,
    xp_max: 10,
    cooldown: 120,
    ignored_channels: [],
    ignored_roles: [],
  },
  ai: {
    enabled: false,
    answer_mode: "private",
    channel_id: null,
    max_question_chars: 2000,
  },
  economy: {
    enabled: true,
    daily_base: 200,
    daily_streak_bonus: 50,
    work_min: 50,
    work_max: 150,
    work_cooldown_minutes: 60,
    transfers_enabled: true,
    games_enabled: true,
    shop_enabled: true,
    gamble_max_bet: 1000,
    slots_max_bet: 500,
  },
});

export const aiStatus = {
  available: true,
  model: "claude-test",
  minute_calls: 1,
  minute_cap: 10,
  daily_calls: 4,
  daily_cap: 100,
} satisfies GuildConfig["ai_status"];

export const economyStatus = {
  tracked_wallets: 12,
  total_coins: 3456,
  leaderboard: [
    {
      position: 1,
      user_id: "20",
      display_name: "Nova Tester",
      coins: 1200,
      daily_streak: 3,
    },
  ],
  shop: [
    {
      key: "crate",
      label: "Mystery crate",
      icon: "📦",
      price: 500,
      kind: "crate",
      description: null,
    },
  ],
} satisfies GuildConfig["economy_status"];
