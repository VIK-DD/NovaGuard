const OK_GREEN = "#3d8a57";

type StatusStats = {
  version: string;
  phase_label?: string;
  release_label?: string;
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
  stale?: boolean;
};

let stopRuntime: (() => void) | null = null;

type StatusSnapshotGetter = (refresh?: boolean) => Promise<unknown>;

const el = (sel: string) => document.querySelector<HTMLElement>(sel);
const set = (key: string, value: string) => {
  const node = el(`[data-f="${key}"]`);
  if (node) node.textContent = value;
};
const fmt = (n: number) => new Intl.NumberFormat("en").format(n);
// Bare path on purpose — see the matching note in Base.astro. The fetch sets
// `cache: "no-store"` and the worker's edge cache key ignores the query string.
const statusSnapshotUrl = () => "/api/status-snapshot";

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
  const stale = snapshot.stale === true;

  setHeadline(
    stale
      ? allGood
        ? "Last known: operational."
        : "Last known: degraded."
      : allGood
        ? "All systems operational."
        : "Running with a limp.",
    stale
      ? "Refreshing live status in the background."
      : allGood
        ? "NovaGuard is awake and answering."
        : "The bot is up, but something needs attention.",
  );
  setDot(allGood ? OK_GREEN : "hsl(var(--primary))");
  set("status", allGood ? "Operational" : "Degraded");
  set("version", stats.release_label ?? `${stats.version} · ${stats.phase_label ?? "Open Beta"}`);
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

const stampChecked = (prefix = "Last checked") => {
  const node = el("[data-status-checked]");
  if (!node) return;
  const time = new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
  // "refreshes" lowercase after the middot read as a typo, and the unit space
  // in "30 s" looked like a stray letter. Both cleaned up.
  node.textContent = `${prefix} ${time} · Refreshes every 30s`;
};

const getStatusSnapshot = async (refresh = false) => {
  const sharedGetter = (window as Window & { __ngGetStatusSnapshot?: StatusSnapshotGetter })
    .__ngGetStatusSnapshot;
  if (sharedGetter) return sharedGetter(refresh);

  return fetch(statusSnapshotUrl(), {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(4000) : undefined,
  }).then((response) => {
    if (!response.ok) throw new Error(`Status request failed: ${response.status}`);
    return response.json();
  });
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
  let hasSnapshot = false;

  const poll = async () => {
    if (stopped || document.hidden) return;
    let refreshFailed = false;

    try {
      const snapshot: unknown = await getStatusSnapshot(true);
      if (!isSnapshot(snapshot)) throw new Error("Status response was malformed.");
      if (stopped) return;
      uptimeBase = applySnapshot(snapshot);
      fetchedAt = Date.now();
      hasSnapshot = true;
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
        "Status is reconnecting.",
        "Live data is temporarily unavailable. NovaGuard may still be online.",
      );
      setDot("hsl(var(--primary))");
      set("status", "Unverified");
      set("version", "Unavailable");
      for (const key of ["uptime", "guilds", "members", "commands", "database", "gateway"]) {
        set(key, "—");
      }
      fetchedAt = 0;
    } finally {
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
    window.clearTimeout(pollTimer);
    window.clearInterval(uptimeTimer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
}

init();
