export type LiveStats = {
  version: string;
  codename: string;
  guilds: number;
  members: number;
  commands: number;
  uptime_seconds: number;
  ready: boolean;
};

const base = (import.meta.env.PUBLIC_API_BASE || "").replace(/\/+$/, "");
let request: Promise<LiveStats> | null = null;

// Footer and stats strip share one request per page load. This avoids duplicate
// network work and staggered layout updates when the API is slow.
export function getLiveStats() {
  if (!base) return Promise.reject(new Error("PUBLIC_API_BASE is not configured."));

  request ??= fetch(`${base}/api/v1/stats`, { signal: AbortSignal.timeout(4000) }).then((response) => {
    if (!response.ok) throw new Error(`Stats request failed: ${response.status}`);
    return response.json() as Promise<LiveStats>;
  });

  return request;
}
