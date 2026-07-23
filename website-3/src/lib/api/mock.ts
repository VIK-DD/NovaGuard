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
  { id: "r1", name: "Member", color: "#4f545c", assignable: true },
  { id: "r2", name: "Regular", color: "#3ba55d", assignable: true },
  { id: "r3", name: "Contributor", color: "#5865f2", assignable: true },
  { id: "r4", name: "Moderator", color: "#faa61a", assignable: false },
  { id: "r5", name: "Admin", color: "#ed4245", assignable: false },
  { id: "r6", name: "Ticket Staff", color: "#eb459e", assignable: false },
];

type Settings = {
  welcome_channel: string | null;
  goodbye_channel: string | null;
  log_channel: string | null;
  update_channel: string | null;
  github_event_channel: string | null;
  error_log_channel: string | null;
  autorole: string | null;
  ticket_staff_role: string | null;
  automod: { invites: boolean; spam: boolean; badwords: string[] };
};

const settingsByGuild: Record<string, Settings> = {
  "1001": {
    welcome_channel: "c1",
    goodbye_channel: null,
    log_channel: "c7",
    update_channel: "c3",
    github_event_channel: "c9",
    error_log_channel: "c10",
    autorole: "r1",
    ticket_staff_role: "r6",
    automod: { invites: true, spam: true, badwords: ["scam", "freenitro", "raid"] },
  },
  "1002": {
    welcome_channel: "c4",
    goodbye_channel: null,
    log_channel: "c7",
    update_channel: null,
    github_event_channel: "c9",
    error_log_channel: null,
    autorole: null,
    ticket_staff_role: null,
    automod: { invites: false, spam: true, badwords: [] },
  },
  "1003": {
    welcome_channel: null,
    goodbye_channel: null,
    log_channel: null,
    update_channel: null,
    github_event_channel: null,
    error_log_channel: null,
    autorole: "r1",
    ticket_staff_role: null,
    automod: { invites: true, spam: false, badwords: ["spoiler"] },
  },
};

const guildMeta: Record<string, { name: string; member_count: number }> = {
  "1001": { name: "Nova Community", member_count: 1287 },
  "1002": { name: "Indie Game Devs", member_count: 4630 },
  "1003": { name: "Study Lounge", member_count: 812 },
};

type AuditEntry = {
  username: string;
  user_id: string;
  action: string;
  changes: Record<string, unknown>;
  created_at: string;
};

const auditByGuild: Record<string, AuditEntry[]> = {
  "1001": [
    {
      username: "Victor",
      user_id: me.user.id,
      action: "update_automod",
      changes: { "automod.invites": true },
      created_at: new Date(Date.now() - 1000 * 60 * 42).toISOString(),
    },
    {
      username: "Mira",
      user_id: "88820011",
      action: "update_channels",
      changes: { welcome_channel: "welcome", log_channel: "bot-logs" },
      created_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(),
    },
    {
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
    guild: { id, name: meta.name, icon: null, member_count: meta.member_count },
    settings,
    channels,
    roles,
  };
}

function applyPatch(id: string, patch: Partial<Settings> & { automod?: Partial<Settings["automod"]> }) {
  const s = settingsByGuild[id];
  if (!s) return;
  const { automod, ...rest } = patch;
  Object.assign(s, rest);
  if (automod) s.automod = { ...s.automod, ...automod };

  const flat: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(rest)) flat[k] = v;
  if (automod) for (const [k, v] of Object.entries(automod)) flat[`automod.${k}`] = v;

  (auditByGuild[id] ??= []).unshift({
    username: me.user.username,
    user_id: me.user.id,
    action: "update_settings",
    changes: flat,
    created_at: now(),
  });
}

function route(pathname: string, method: string, body: Json | null): { status: number; data: Json } {
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

  const aud = p.match(/^\/guilds\/([^/]+)\/audit$/);
  if (aud) return { status: 200, data: { audit: auditByGuild[aud[1]] ?? [] } };

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

  const { status, data } = route(new URL(url, window.location.origin).pathname, method, body);
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
