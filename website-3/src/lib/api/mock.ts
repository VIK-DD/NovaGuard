// Dev-only mock of the NovaGuard bot API (docs/API.md).
//
// When PUBLIC_MOCK_API === "1" this patches window.fetch so every /api/v1/*
// request — from the React dashboard (apiFetch) AND the vanilla stats/status
// scripts — resolves against in-memory data instead of hitting a real bot.
// Lets the whole site be clicked through and verified with no backend running.
// Ships dormant: with the flag unset the patch is never installed.

// DEV-gated as well as flag-gated: import.meta.env.DEV is false in any
// `astro build`, so the mock can never ship to production even if a local
// .env with the flag is present at build time.
const ENABLED = import.meta.env.DEV && import.meta.env.PUBLIC_MOCK_API === "1";

type Json = Record<string, unknown>;

const now = () => new Date().toISOString();
const LATENCY = 260; // ms — enough to see loading skeletons animate

// Mock session: the dev preview starts LOGGED OUT so the real Discord sign-in
// screen is exercised, exactly as production behaves for an anonymous visitor.
// AuthGate's dev-only "Preview with demo data" button sets this flag; Sign out
// clears it. Nothing here ships to production (the whole module is DEV-gated).
const SESSION_KEY = "ng_mock_session";
const isAuthed = () => {
  try {
    return sessionStorage.getItem(SESSION_KEY) === "on";
  } catch {
    return false;
  }
};

// ── In-memory state (persists for the session, resets on reload) ───────────
const me = {
  user: { id: "204255221017214977", username: "Victor", avatar: null as string | null },
};

const guilds = [
  { id: "1001", name: "Nova Community", icon: null, owner: true, permissions: 8, bot_present: true },
  { id: "1002", name: "Indie Game Devs", icon: null, owner: false, permissions: 32, bot_present: true },
  { id: "1003", name: "Study Lounge", icon: null, owner: false, permissions: 32, bot_present: true },
  { id: "1004", name: "Weekend Raiders", icon: null, owner: true, permissions: 8, bot_present: false },
];

const channels = [
  { id: "c1", name: "welcome", category: "Information" },
  { id: "c2", name: "rules", category: "Information" },
  { id: "c3", name: "announcements", category: "Information" },
  { id: "c4", name: "general", category: "Community" },
  { id: "c5", name: "off-topic", category: "Community" },
  { id: "c6", name: "introductions", category: "Community" },
  { id: "c7", name: "bot-logs", category: "Staff" },
  { id: "c8", name: "mod-alerts", category: "Staff" },
  { id: "c9", name: "github-feed", category: "Staff" },
  { id: "c10", name: "errors", category: "Staff" },
];

const roles = [
  { id: "r1", name: "Member", color: "#4f545c", assignable: true, manages_threads: false },
  { id: "r2", name: "Regular", color: "#3ba55d", assignable: true, manages_threads: false },
  { id: "r3", name: "Contributor", color: "#5865f2", assignable: true, manages_threads: false },
  { id: "r4", name: "Moderator", color: "#faa61a", assignable: false, manages_threads: true },
  { id: "r5", name: "Admin", color: "#ed4245", assignable: false, manages_threads: true },
  { id: "r6", name: "Ticket Staff", color: "#eb459e", assignable: false, manages_threads: true },
];

type Settings = {
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
  automod: {
    invites: boolean;
    spam: boolean;
    badwords: string[];
    ignored_channels: string[];
    ignored_roles: string[];
    spam_messages: number;
    spam_window_seconds: number;
    spam_timeout_seconds: number;
  };
  levels: {
    enabled: boolean;
    announce: "dm" | "channel" | "off";
    announce_channel: string | null;
    xp_min: number;
    xp_max: number;
    cooldown: number;
    ignored_channels: string[];
    ignored_roles: string[];
  };
  ai: {
    enabled: boolean;
    answer_mode: "public" | "private";
    channel_id: string | null;
    max_question_chars: number;
  };
  economy: {
    enabled: boolean;
    daily_base: number;
    daily_streak_bonus: number;
    work_min: number;
    work_max: number;
    work_cooldown_minutes: number;
    transfers_enabled: boolean;
    games_enabled: boolean;
    shop_enabled: boolean;
    gamble_max_bet: number;
    slots_max_bet: number;
  };
};

/** Mirrors LEVELS_DEFAULTS in core/levels_settings.py. */
const levelsDefaults = (): Settings["levels"] => ({
  enabled: true,
  announce: "dm",
  announce_channel: null,
  xp_min: 5,
  xp_max: 10,
  cooldown: 120,
  ignored_channels: [],
  ignored_roles: [],
});

const automodDefaults = (): Settings["automod"] => ({
  invites: true,
  spam: true,
  badwords: [],
  ignored_channels: [],
  ignored_roles: [],
  spam_messages: 6,
  spam_window_seconds: 6,
  spam_timeout_seconds: 60,
});

const aiDefaults = (): Settings["ai"] => ({
  enabled: true,
  answer_mode: "public",
  channel_id: null,
  max_question_chars: 2000,
});

const economyDefaults = (): Settings["economy"] => ({
  enabled: true,
  daily_base: 200,
  daily_streak_bonus: 50,
  work_min: 50,
  work_max: 150,
  work_cooldown_minutes: 60,
  transfers_enabled: true,
  games_enabled: true,
  shop_enabled: true,
  gamble_max_bet: 1_000_000,
  slots_max_bet: 100_000,
});

const settingsByGuild: Record<string, Settings> = {
  "1001": {
    welcome_channel: "c1",
    goodbye_channel: null,
    log_channel: "c7",
    voice_report_channel: "c8",
    update_channel: "c3",
    github_event_channel: "c9",
    error_log_channel: "c10",
    ticket_panel_channel: "c8",
    role_panel_channel: "c4",
    giveaway_channel: "c3",
    autorole: "r1",
    ticket_staff_role: "r6",
    automod: {
      ...automodDefaults(),
      badwords: ["scam", "freenitro", "raid"],
      ignored_channels: ["c2"],
      ignored_roles: ["r4"],
    },
    levels: {
      ...levelsDefaults(),
      announce: "channel",
      announce_channel: "c3",
      xp_min: 8,
      xp_max: 15,
      ignored_channels: ["c7"],
      ignored_roles: ["r6"],
    },
    ai: { ...aiDefaults(), channel_id: "c4", max_question_chars: 1200 },
    economy: economyDefaults(),
  },
  "1002": {
    welcome_channel: "c4",
    goodbye_channel: null,
    log_channel: "c7",
    voice_report_channel: null,
    update_channel: null,
    github_event_channel: "c9",
    error_log_channel: null,
    ticket_panel_channel: null,
    role_panel_channel: null,
    giveaway_channel: "c4",
    autorole: null,
    ticket_staff_role: null,
    automod: { ...automodDefaults(), invites: false },
    levels: levelsDefaults(),
    ai: { ...aiDefaults(), answer_mode: "private" },
    economy: { ...economyDefaults(), games_enabled: false },
  },
  "1003": {
    welcome_channel: null,
    goodbye_channel: null,
    log_channel: null,
    voice_report_channel: null,
    update_channel: null,
    github_event_channel: null,
    error_log_channel: null,
    ticket_panel_channel: null,
    role_panel_channel: "c4",
    giveaway_channel: null,
    autorole: "r1",
    ticket_staff_role: null,
    automod: { ...automodDefaults(), spam: false, badwords: ["spoiler"] },
    levels: { ...levelsDefaults(), enabled: false, announce: "off" },
    ai: { ...aiDefaults(), enabled: false },
    economy: { ...economyDefaults(), enabled: false },
  },
};

const guildMeta: Record<string, { name: string; member_count: number }> = {
  "1001": { name: "Nova Community", member_count: 1287 },
  "1002": { name: "Indie Game Devs", member_count: 4630 },
  "1003": { name: "Study Lounge", member_count: 812 },
};

const ticketPanelMessageByGuild: Record<string, string | null> = { "1001": "panel-1001" };
const openTicketsByGuild: Record<
  string,
  Array<{ thread_id: string; opener_id: string; opener_name: string; created_at: string }>
> = {
  "1001": [
    {
      thread_id: "ticket-42",
      opener_id: "member-42",
      opener_name: "Sorin",
      created_at: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
    },
  ],
};
const rolePanelsByGuild: Record<
  string,
  Array<{
    message_id: string;
    channel_id: string;
    title: string;
    description: string;
    role_ids: string[];
    updated_at: string;
  }>
> = {
  "1001": [
    {
      message_id: "9001001",
      channel_id: "c4",
      title: "Community roles",
      description: "Pick the updates and community groups you want to follow.",
      role_ids: ["r2", "r3"],
      updated_at: new Date(Date.now() - 1000 * 60 * 90).toISOString(),
    },
  ],
};
type MockGiveaway = {
  message_id: string;
  channel_id: string;
  prize: string;
  winners: number;
  host_name: string;
  ends_at: string;
  entrant_count: number;
  ended: boolean;
  winner_ids: string[];
};
const giveawaysByGuild: Record<string, MockGiveaway[]> = {
  "1001": [
    {
      message_id: "9100001",
      channel_id: "c3",
      prize: "One month of Nitro",
      winners: 1,
      host_name: "Victor",
      ends_at: new Date(Date.now() + 1000 * 60 * 60 * 6).toISOString(),
      entrant_count: 48,
      ended: false,
      winner_ids: [],
    },
    {
      message_id: "9100000",
      channel_id: "c3",
      prize: "Founder's badge",
      winners: 2,
      host_name: "Victor",
      ends_at: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(),
      entrant_count: 83,
      ended: true,
      winner_ids: ["member-1", "member-2"],
    },
  ],
};

type AuditEntry = {
  id: number;
  username: string;
  user_id: string;
  action: string;
  changes: Record<string, unknown>;
  created_at: string;
};

const auditByGuild: Record<string, AuditEntry[]> = {
  "1001": [
    {
      id: 3,
      username: "Victor",
      user_id: me.user.id,
      action: "update_automod",
      changes: { "automod.invites": true },
      created_at: new Date(Date.now() - 1000 * 60 * 42).toISOString(),
    },
    {
      id: 2,
      username: "Mira",
      user_id: "88820011",
      action: "update_channels",
      changes: { welcome_channel: "welcome", log_channel: "bot-logs" },
      created_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(),
    },
    {
      id: 1,
      username: "Victor",
      user_id: me.user.id,
      action: "update_roles",
      changes: { autorole: "Member" },
      created_at: new Date(Date.now() - 1000 * 60 * 60 * 26).toISOString(),
    },
  ],
};

// ── Request helpers ────────────────────────────────────────────────────────
function configPayload(id: string): Json | null {
  const meta = guildMeta[id];
  const settings = settingsByGuild[id];
  if (!meta || !settings) return null;
  return {
    github_watch_configured: false,
    guild: { id, name: meta.name, icon: null, member_count: meta.member_count },
    settings,
    ai_status: {
      available: true,
      model: "claude-opus-4-8",
      minute_calls: 4,
      minute_cap: 30,
      daily_calls: 83,
      daily_cap: 500,
    },
    economy_status: {
      tracked_wallets: 3,
      total_coins: 18_450,
      leaderboard: [
        { position: 1, user_id: "1", display_name: "Razban", coins: 9_400, daily_streak: 11 },
        { position: 2, user_id: "2", display_name: "Sorin", coins: 5_800, daily_streak: 4 },
        { position: 3, user_id: "3", display_name: "Victor", coins: 3_250, daily_streak: 7 },
      ],
      shop: [
        { key: "star", label: "Star", icon: "⭐", price: 1000, kind: "trophy", description: null },
        { key: "xp_boost", label: "XP Boost", icon: "⚡", price: 1200, kind: "booster", description: "1.5x XP for 6 hours." },
        { key: "crate", label: "Mystery Crate", icon: "📦", price: 500, kind: "crate", description: "Coins or perks." },
      ],
    },
    tickets: {
      panel_channel_id: settings.ticket_panel_channel,
      panel_message_id: ticketPanelMessageByGuild[id] ?? null,
      ready: Boolean(
        settings.ticket_panel_channel &&
          roles.some(
            (role) => role.id === settings.ticket_staff_role && role.manages_threads,
          ),
      ),
      open_count: (openTicketsByGuild[id] ?? []).length,
      open: openTicketsByGuild[id] ?? [],
    },
    role_panels: rolePanelsByGuild[id] ?? [],
    giveaways: giveawaysByGuild[id] ?? [],
    channels,
    roles,
  };
}

function dashboardPayload(id: string): Json | null {
  const meta = guildMeta[id];
  const settings = settingsByGuild[id];
  if (!meta || !settings) return null;

  const configuredChannels = [
    settings.welcome_channel,
    settings.goodbye_channel,
    settings.log_channel,
    settings.voice_report_channel,
    settings.update_channel,
    settings.github_event_channel,
    settings.error_log_channel,
  ].filter(Boolean).length;

  return {
    status: {
      ready: true,
      version: "3.0",
      phase: "stable",
      phase_label: "",
      release_label: "3.0",
      runtime_version: "3.1.0",
      codename: "Nova",
      uptime_seconds: 142_331,
      commands: 70,
      guilds: 5,
      members: 6132,
    },
    guild: { id, name: meta.name, icon: null, member_count: meta.member_count },
    setup: {
      configured_channels: configuredChannels,
      total_channels: 7,
      recommended_done: [
        settings.update_channel,
        settings.error_log_channel,
        settings.log_channel,
        settings.welcome_channel,
      ].filter(Boolean).length,
      recommended_total: 4,
    },
    modules: [
      {
        key: "welcome",
        label: "Welcome",
        enabled: Boolean(settings.welcome_channel || settings.goodbye_channel || settings.autorole),
      },
      {
        key: "moderation",
        label: "Moderation",
        enabled: Boolean(
          settings.log_channel ||
            settings.error_log_channel ||
            settings.automod.invites ||
            settings.automod.spam ||
            settings.automod.badwords.length,
        ),
      },
      { key: "levels", label: "Levels", enabled: settings.levels.enabled },
      { key: "voice", label: "Voice reports", enabled: Boolean(settings.voice_report_channel) },
      { key: "tickets", label: "Tickets", enabled: Boolean(settings.ticket_staff_role) },
      { key: "roles", label: "Role panels", enabled: Boolean(settings.role_panel_channel) },
      { key: "giveaways", label: "Giveaways", enabled: Boolean(settings.giveaway_channel) },
      { key: "ai", label: "AI assistant", enabled: settings.ai.enabled },
      { key: "economy", label: "Economy", enabled: settings.economy.enabled },
      {
        key: "updates",
        label: "Updates",
        enabled: Boolean(settings.update_channel || settings.github_event_channel),
      },
    ],
    automod: {
      invites: settings.automod.invites,
      spam: settings.automod.spam,
      badwords_count: settings.automod.badwords.length,
    },
    levels: {
      enabled: settings.levels.enabled,
      tracked_members: 139,
      total_xp: 20_420,
      leaderboard: [
        { position: 1, user_id: "1", display_name: "Razban", xp: 4400, messages: 2200, level: 19 },
        { position: 2, user_id: "2", display_name: "Sorin", xp: 4240, messages: 2120, level: 18 },
        { position: 3, user_id: "3", display_name: "KingPtVoi", xp: 4000, messages: 2000, level: 18 },
        { position: 4, user_id: "4", display_name: "Denwer", xp: 3820, messages: 1910, level: 17 },
        { position: 5, user_id: "5", display_name: "Victor", xp: 3210, messages: 1605, level: 15 },
      ],
    },
    voice: {
      configured: Boolean(settings.voice_report_channel),
      report_channel_id: settings.voice_report_channel,
      pending_count: 0,
      recent_reports: [
        {
          id: "voice-1",
          channel_id: "v1",
          channel_name: "staff-voice",
          started_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(),
          ended_at: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
          sent_at: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
          duration_seconds: 10_800,
          unique_members: 7,
          peak_members: 5,
        },
      ],
    },
    updates: [
      {
        build: 39,
        version: "3.1.0",
        codename: "Nova",
        created_at: new Date(Date.now() - 1000 * 60 * 20).toISOString(),
        highlights: ["Dashboard overview and backup safety checks"],
        added_lines: 438,
        removed_lines: 12,
        changed_files: 7,
      },
      {
        build: 38,
        created_at: new Date(Date.now() - 1000 * 60 * 60 * 8).toISOString(),
        changes: ["Voice report history, retry queue and CSV export"],
      },
    ],
  };
}

function applyPatch(
  id: string,
  patch: Partial<Settings> & {
    automod?: Partial<Settings["automod"]>;
    levels?: Partial<Settings["levels"]>;
    ai?: Partial<Settings["ai"]>;
    economy?: Partial<Settings["economy"]>;
  },
) {
  const s = settingsByGuild[id];
  if (!s) return;
  const { automod, levels, ai, economy, ...rest } = patch;
  Object.assign(s, rest);
  if (automod) s.automod = { ...s.automod, ...automod };
  if (levels) s.levels = { ...s.levels, ...levels };
  if (ai) s.ai = { ...s.ai, ...ai };
  if (economy) s.economy = { ...s.economy, ...economy };

  const flat: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(rest)) flat[k] = v;
  if (automod) for (const [k, v] of Object.entries(automod)) flat[`automod.${k}`] = v;
  if (levels) for (const [k, v] of Object.entries(levels)) flat[`levels.${k}`] = v;
  if (ai) for (const [k, v] of Object.entries(ai)) flat[`ai.${k}`] = v;
  if (economy) for (const [k, v] of Object.entries(economy)) flat[`economy.${k}`] = v;

  (auditByGuild[id] ??= []).unshift({
    id: Math.max(0, ...(auditByGuild[id] ?? []).map((entry) => entry.id)) + 1,
    username: me.user.username,
    user_id: me.user.id,
    action: "update_settings",
    changes: flat,
    created_at: now(),
  });
}

function route(pathname: string, method: string, body: Json | null): { status: number; data: Json } {
  const search = new URLSearchParams(pathname.includes("?") ? pathname.split("?", 2)[1] : "");
  const p = pathname.replace(/^.*\/api\/v1/, "").replace(/\?.*$/, "");

  if (p === "/me") {
    return isAuthed()
      ? { status: 200, data: me }
      : { status: 401, data: { error: "Sign in to continue.", code: "unauthorized" } };
  }
  if (p === "/auth/logout") {
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* ignore */
    }
    return { status: 200, data: { ok: true } };
  }
  if (p === "/guilds") return { status: 200, data: { guilds } };
  // /stats and /health are deliberately NOT mocked: the public landing + status
  // numbers must reflect the real bot (or its honest "offline" fallback), never
  // fabricated figures. They 404 here, so the fetchers fall back gracefully.

  const cfg = p.match(/^\/guilds\/([^/]+)\/config$/);
  if (cfg) {
    const id = cfg[1];
    if (method === "PUT" && body) applyPatch(id, body as Partial<Settings>);
    const payload = configPayload(id);
    return payload
      ? { status: 200, data: payload }
      : { status: 404, data: { error: "NovaGuard is not in this server.", code: "guild_not_found" } };
  }

  const dash = p.match(/^\/guilds\/([^/]+)\/dashboard$/);
  if (dash) {
    const payload = dashboardPayload(dash[1]);
    return payload
      ? { status: 200, data: payload }
      : { status: 404, data: { error: "NovaGuard is not in this server.", code: "guild_not_found" } };
  }

  const action = p.match(/^\/guilds\/([^/]+)\/actions\/([^/]+)$/);
  if (action) {
    const id = action[1];
    const settings = settingsByGuild[id];
    if (!settings) return { status: 404, data: { error: "NovaGuard is not in this server.", code: "guild_not_found" } };
    const actionName = action[2].replace(/-/g, "_");
    if (actionName === "voice_test" && !settings.voice_report_channel) {
      return { status: 400, data: { error: "Voice reports are not configured.", code: "voice_not_configured" } };
    }
    if (
      actionName === "ticket_panel_publish" &&
      (!settings.ticket_panel_channel || !settings.ticket_staff_role)
    ) {
      return {
        status: 400,
        data: {
          error: "Choose a ticket channel and staff role, then save before publishing.",
          code: "ticket_setup_incomplete",
        },
      };
    }
    if (actionName === "role_panel_publish" && !settings.role_panel_channel) {
      return {
        status: 400,
        data: {
          error: "Choose and save a default role-panel channel first.",
          code: "role_panel_channel_missing",
        },
      };
    }
    if (actionName === "giveaway_start" && !settings.giveaway_channel) {
      return {
        status: 400,
        data: {
          error: "Choose and save a giveaway channel first.",
          code: "giveaway_channel_missing",
        },
      };
    }
    const messages: Record<string, string> = {
      voice_test: "Voice report preview sent to #voice-reports.",
      update_preview: "Latest update was sent to the configured update channel.",
      ticket_panel_publish: "Ticket panel updated in #mod-alerts.",
      role_panel_publish: "Role panel published in #general.",
      giveaway_start: "Giveaway started in #announcements.",
      giveaway_end: "Giveaway ended and the draw was saved.",
      giveaway_reroll: "New winner announced in the original channel.",
    };
    if (!messages[actionName]) return { status: 404, data: { error: "Unknown dashboard action.", code: "unknown_action" } };
    if (actionName === "ticket_panel_publish") ticketPanelMessageByGuild[id] = `panel-${id}`;
    let panel: (typeof rolePanelsByGuild)[string][number] | undefined;
    if (actionName === "role_panel_publish") {
      const payload = (body ?? {}) as Record<string, unknown>;
      const previousId = typeof payload.panel_message_id === "string" ? payload.panel_message_id : null;
      const previous = (rolePanelsByGuild[id] ?? []).find((item) => item.message_id === previousId);
      panel = {
        message_id: previous?.message_id ?? String(Date.now()),
        channel_id: previous?.channel_id ?? settings.role_panel_channel!,
        title: typeof payload.title === "string" ? payload.title : "Role panel",
        description: typeof payload.description === "string" ? payload.description : "Choose a role.",
        role_ids: Array.isArray(payload.role_ids)
          ? payload.role_ids.map(String).slice(0, 5)
          : [],
        updated_at: now(),
      };
      rolePanelsByGuild[id] = [
        panel,
        ...(rolePanelsByGuild[id] ?? []).filter((item) => item.message_id !== previousId),
      ];
    }
    if (actionName.startsWith("giveaway_")) {
      const payload = (body ?? {}) as Record<string, unknown>;
      if (actionName === "giveaway_start") {
        const giveaway: MockGiveaway = {
          message_id: String(Date.now() + 1),
          channel_id: settings.giveaway_channel!,
          prize: typeof payload.prize === "string" ? payload.prize : "Prize",
          winners: typeof payload.winners === "number" ? payload.winners : 1,
          host_name: me.user.username,
          ends_at: new Date(Date.now() + 1000 * 60 * 60).toISOString(),
          entrant_count: 0,
          ended: false,
          winner_ids: [],
        };
        giveawaysByGuild[id] = [giveaway, ...(giveawaysByGuild[id] ?? [])];
      } else {
        const giveaway = (giveawaysByGuild[id] ?? []).find(
          (item) => item.message_id === String(payload.message_id ?? ""),
        );
        if (!giveaway) {
          return {
            status: 404,
            data: { error: "Giveaway not found.", code: "giveaway_not_found" },
          };
        }
        if (actionName === "giveaway_end") {
          giveaway.ended = true;
          giveaway.winner_ids = giveaway.entrant_count > 0 ? ["member-1"] : [];
        } else if (actionName === "giveaway_reroll" && giveaway.entrant_count === 0) {
          return {
            status: 409,
            data: { error: "That giveaway has no entries to reroll.", code: "giveaway_no_entries" },
          };
        }
      }
    }
    (auditByGuild[id] ??= []).unshift({
      id: Math.max(0, ...(auditByGuild[id] ?? []).map((entry) => entry.id)) + 1,
      username: me.user.username,
      user_id: me.user.id,
      action: `dashboard_${actionName}`,
      changes: { ok: true },
      created_at: now(),
    });
    return {
      status: 200,
      data: { ok: true, action: actionName, message: messages[actionName], ...(panel ? { panel } : {}) },
    };
  }

  const aud = p.match(/^\/guilds\/([^/]+)\/audit$/);
  if (aud) {
    const limit = Math.min(Math.max(Number(search.get("limit")) || 50, 1), 200);
    const cursor = Number(search.get("cursor")) || Number.POSITIVE_INFINITY;
    const kind = search.get("kind");
    const actor = search.get("actor")?.toLowerCase();
    const after = search.get("after");
    const before = search.get("before");
    const filtered = (auditByGuild[aud[1]] ?? []).filter((entry) => {
      if (entry.id >= cursor) return false;
      if (kind === "settings" && entry.action !== "config_update" && !entry.action.startsWith("update_")) return false;
      if (kind === "actions" && !entry.action.startsWith("dashboard_")) return false;
      if (kind === "login" && entry.action !== "login") return false;
      if (actor && !entry.username.toLowerCase().includes(actor) && entry.user_id !== actor) return false;
      if (after && entry.created_at < after) return false;
      if (before && entry.created_at >= before) return false;
      return true;
    });
    const page = filtered.slice(0, limit);
    return {
      status: 200,
      data: {
        audit: page,
        next_cursor: filtered.length > limit && page.length ? page[page.length - 1].id : null,
      },
    };
  }

  return { status: 404, data: { error: "Unknown endpoint.", code: "not_found" } };
}

// ── request handler ─────────────────────────────────────────────────────────
// Resolves one /api/v1 request against the in-memory data.
type Handler = (
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  real: typeof fetch,
) => Promise<Response>;

const handler: Handler = async (input, init, real) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (!url.includes("/api/v1")) return real(input, init);

  const method = (init?.method ?? "GET").toUpperCase();
  let body: Json | null = null;
  if (init?.body && typeof init.body === "string") {
    try {
      body = JSON.parse(init.body);
    } catch {
      body = null;
    }
  }

  const parsed = new URL(url, window.location.origin);
  const { status, data } = route(`${parsed.pathname}${parsed.search}`, method, body);
  await new Promise((r) => setTimeout(r, LATENCY));
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
};

// The Base.astro inline bootstrap patches window.fetch synchronously (before any
// component script fetches) and waits on window.__ngMockResolve for this handler.
// If that bootstrap didn't run (e.g. a page without it), patch fetch directly.
interface MockWindow {
  __ngMock?: boolean;
  __ngMockResolve?: (h: Handler) => void;
}

export function installMockApi() {
  if (!ENABLED || typeof window === "undefined") return;
  const w = window as unknown as MockWindow;

  if (w.__ngMockResolve) {
    w.__ngMockResolve(handler);
  } else if (!w.__ngMock) {
    w.__ngMock = true;
    const real = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => handler(input, init, real);
  }

  console.info("[NovaGuard] Mock API active — dashboard, stats and status use in-memory data.");
}

installMockApi();
