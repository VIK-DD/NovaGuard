const OK_GREEN = "#3d8a57";
const STATUS_CACHE_KEY = "ng-status-snapshot-v1";
const STATUS_CACHE_TTL_MS = 60_000;

type StatusStats = {
  version: string;
  codename: string;
  guilds: number;
  members: number;
  commands: number;
  uptime_seconds: number;
  ready: boolean;
};

type StatusHealth = {
  ok: boolean;
  bot_ready: boolean;
  db_ok: boolean;
};

type StatusSnapshot = {
  stats: StatusStats;
  health: StatusHealth;
  fetched_at: number;
};

let stopRuntime: (() => void) | null = null;

const el = (sel: string) => document.querySelector<HTMLElement>(sel);
const set = (key: string, value: string) => {
  const node = el(`[data-f="${key}"]`);
  if (node) node.textContent = value;
};
const fmt = (n: number) => new Intl.NumberFormat("en").format(n);

const fmtUptime = (total: number) => {
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  return `${m}m ${s}s`;
};

const setHeadline = (headline: string, sub: string) => {
  const h = el("[data-status-headline]");
  const p = el("[data-status-sub]");
  if (h) h.textContent = headline;
  if (p) p.textContent = sub;
};

const setDot = (color: string) => {
  const dot = el("[data-status-dot]");
  if (dot) dot.style.backgroundColor = color;
};

const applySnapshot = (snapshot: StatusSnapshot) => {
  const { stats, health } = snapshot;
  const allGood = health.ok && health.db_ok && stats.ready;
  const uptime = stats.uptime_seconds + Math.max(0, (Date.now() - snapshot.fetched_at) / 1000);

  setHeadline(
    allGood ? "All systems operational." : "Running with a limp.",
    allGood
      ? "NovaGuard is awake and answering."
      : "The bot is up, but something needs attention.",
  );
  setDot(allGood ? OK_GREEN : "hsl(var(--primary))");
  set("status", allGood ? "Operational" : "Degraded");
  set("version", `v${stats.version} · ${stats.codename}`);
  set("uptime", fmtUptime(uptime));
  set("guilds", fmt(stats.guilds));
  set("members", fmt(stats.members));
  set("commands", fmt(stats.commands));
  set("database", health.db_ok ? "Healthy" : "Degraded");
  set("gateway", health.bot_ready ? "Connected" : "Connecting…");
  return uptime;
};

const isSnapshot = (value: unknown): value is StatusSnapshot => {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as Partial<StatusSnapshot>;
  return (
    Number.isFinite(snapshot.fetched_at) &&
    !!snapshot.stats &&
    Number.isFinite(snapshot.stats.uptime_seconds) &&
    !!snapshot.health
  );
};

const readCachedSnapshot = () => {
  try {
    const snapshot: unknown = JSON.parse(sessionStorage.getItem(STATUS_CACHE_KEY) || "null");
    if (!isSnapshot(snapshot)) return null;
    const age = Date.now() - snapshot.fetched_at;
    return age >= -5_000 && age <= STATUS_CACHE_TTL_MS ? snapshot : null;
  } catch {
    return null;
  }
};

const cacheSnapshot = (snapshot: StatusSnapshot) => {
  try {
    sessionStorage.setItem(STATUS_CACHE_KEY, JSON.stringify(snapshot));
  } catch {}
};

const stampChecked = (prefix = "Last checked") => {
  const node = el("[data-status-checked]");
  if (!node) return;
  const time = new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
  node.textContent = `${prefix} ${time} · refreshes every 30 s`;
};

function init() {
  stopRuntime?.();
  stopRuntime = null;

  if (!document.querySelector("[data-status-page]")) return;

  let stopped = false;
  let uptimeBase = 0;
  let fetchedAt = 0;
  let pollTimer = 0;
  let uptimeTimer = 0;
  let controller: AbortController | null = null;
  let hasSnapshot = false;

  const cachedSnapshot = readCachedSnapshot();
  if (cachedSnapshot) {
    uptimeBase = applySnapshot(cachedSnapshot);
    fetchedAt = Date.now();
    hasSnapshot = true;
    stampChecked("Refreshing live data · cached at");
  }

  const poll = async () => {
    if (stopped || document.hidden) return;
    let refreshFailed = false;
    controller?.abort();
    controller = new AbortController();
    const timeout = window.setTimeout(() => controller?.abort(), 5000);

    try {
      const response = await fetch("/api/status-snapshot", {
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`Status request failed: ${response.status}`);
      const snapshot: unknown = await response.json();
      if (!isSnapshot(snapshot)) throw new Error("Status response was malformed.");
      if (stopped) return;
      uptimeBase = applySnapshot(snapshot);
      fetchedAt = Date.now();
      hasSnapshot = true;
      cacheSnapshot(snapshot);
    } catch (error) {
      if (stopped || (error instanceof DOMException && error.name === "AbortError")) return;
      refreshFailed = true;
      if (hasSnapshot) {
        setHeadline(
          "Recent status is still available.",
          "The live refresh is reconnecting in the background.",
        );
        setDot("hsl(var(--primary))");
        set("status", "Unverified");
        return;
      }
      setHeadline(
        "The bot is resting.",
        "NovaGuard is unreachable right now — most likely an update or planned maintenance.",
      );
      setDot("hsl(var(--primary))");
      set("status", "Offline");
      for (const key of ["version", "uptime", "guilds", "members", "commands", "database", "gateway"]) {
        set(key, "—");
      }
      fetchedAt = 0;
    } finally {
      window.clearTimeout(timeout);
      if (!stopped) stampChecked(refreshFailed ? "Refresh attempted" : "Last checked");
    }
  };

  const schedule = () => {
    if (stopped) return;
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(async () => {
      await poll();
      schedule();
    }, 30_000);
  };

  const onVisibilityChange = () => {
    if (!document.hidden) {
      void poll();
      schedule();
    }
  };

  document.addEventListener("visibilitychange", onVisibilityChange);
  uptimeTimer = window.setInterval(() => {
    if (fetchedAt && !document.hidden) {
      set("uptime", fmtUptime(uptimeBase + (Date.now() - fetchedAt) / 1000));
    }
  }, 1000);

  void poll();
  schedule();

  stopRuntime = () => {
    stopped = true;
    controller?.abort();
    window.clearTimeout(pollTimer);
    window.clearInterval(uptimeTimer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
}

init();
