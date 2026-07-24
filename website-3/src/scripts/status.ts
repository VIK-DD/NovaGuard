const base = (import.meta.env.PUBLIC_API_BASE || "").replace(/\/+$/, "");
const OK_GREEN = "#3d8a57";

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

const setQuickStats = (stats: {
  version: string;
  codename: string;
  guilds: number;
  members: number;
  commands: number;
  uptime_seconds: number;
  ready: boolean;
}) => {
  setHeadline(
    stats.ready ? "NovaGuard is answering." : "NovaGuard is starting.",
    stats.ready ? "Live checks are still arriving." : "The bot is connecting to Discord.",
  );
  setDot(stats.ready ? OK_GREEN : "hsl(var(--primary))");
  set("status", stats.ready ? "Operational" : "Starting");
  set("version", `v${stats.version} · ${stats.codename}`);
  set("guilds", fmt(stats.guilds));
  set("members", fmt(stats.members));
  set("commands", fmt(stats.commands));
  set("database", "Checking…");
  set("gateway", "Checking…");
};

const stampChecked = () => {
  const node = el("[data-status-checked]");
  if (!node) return;
  const time = new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
  node.textContent = `Last checked ${time} · refreshes every 30 s`;
};

function init() {
  stopRuntime?.();
  stopRuntime = null;

  if (!document.querySelector("[data-status-page]")) return;

  if (!base) {
    setHeadline("Status is not connected.", "Set PUBLIC_API_BASE before building the website.");
    setDot("hsl(var(--primary))");
    set("status", "Not configured");
    stampChecked();
    return;
  }

  let stopped = false;
  let uptimeBase = 0;
  let fetchedAt = 0;
  let pollTimer = 0;
  let uptimeTimer = 0;
  let controller: AbortController | null = null;

  const poll = async () => {
    if (stopped || document.hidden) return;
    let statsReceived = false;
    let statsReady = false;
    controller?.abort();
    controller = new AbortController();
    const timeout = window.setTimeout(() => controller?.abort(), 5000);

    try {
      const opts = { signal: controller.signal, cache: "no-store" as RequestCache };
      const statsRequest = fetch(`${base}/api/v1/stats`, opts).then((r) => r.json());
      const healthRequest = fetch(`${base}/api/v1/health`, opts)
        .then((r) => r.json())
        .then(
          (value) => ({ value }),
          (error) => ({ error }),
        );
      const stats = await statsRequest;

      if (stopped) return;
      setQuickStats(stats);
      statsReceived = true;
      statsReady = stats.ready;
      uptimeBase = stats.uptime_seconds;
      fetchedAt = Date.now();

      const healthResult = await healthRequest;
      if ("error" in healthResult) throw healthResult.error;
      const health = healthResult.value;
      if (stopped) return;
      const allGood = health.ok && health.db_ok && stats.ready;
      setHeadline(
        allGood ? "All systems operational." : "Running with a limp.",
        allGood
          ? "NovaGuard is awake and answering."
          : "The bot is up, but something needs attention.",
      );
      setDot(allGood ? OK_GREEN : "var(--accent)");
      set("status", allGood ? "Operational" : "Degraded");
      set("version", `v${stats.version} · ${stats.codename}`);
      set("guilds", fmt(stats.guilds));
      set("members", fmt(stats.members));
      set("commands", fmt(stats.commands));
      set("database", health.db_ok ? "Healthy" : "Degraded");
      set("gateway", health.bot_ready ? "Connected" : "Connecting…");
    } catch (error) {
      if (stopped || (error instanceof DOMException && error.name === "AbortError")) return;
      if (statsReceived) {
        setHeadline(
          statsReady ? "NovaGuard is answering." : "NovaGuard is starting.",
          "Live bot data arrived, but the detailed health check is unavailable right now.",
        );
        setDot("hsl(var(--primary))");
        set("status", "Unverified");
        set("database", "Unknown");
        set("gateway", "Unknown");
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
      if (!stopped) stampChecked();
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
