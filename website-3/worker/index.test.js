// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest";
import worker from "./index.js";

const env = {
  AUTH_PASSWORD: "test-password",
  ASSETS: {
    fetch: async (request) => new Response(new URL(request.url).pathname, { status: 200 }),
  },
};

function loginRequest() {
  return new Request("https://novaguard.fun/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ password: env.AUTH_PASSWORD, next: "/dashboard/" }),
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("password session", () => {
  it("serves the landing page to a session, and never from a shared cache", async () => {
    const login = await worker.fetch(loginRequest(), env);
    const cookie = login.headers.get("set-cookie").split(";")[0];
    const response = await worker.fetch(
      new Request("https://novaguard.fun/home/", { headers: { cookie } }),
      env,
    );

    expect(response.status).toBe(200);
    // The page is behind the password now, so a `public` header could let a
    // shared cache hand it to a visitor with no session.
    expect(response.headers.get("Cache-Control")).toBe("private, max-age=60");
    // `private` is the part that matters: a shared cache must never hold a page
    // that required a session to reach.
    expect(response.headers.get("Cache-Control")).not.toContain("public");
    await expect(response.text()).resolves.toBe("/home/");
  });

  it("combines public bot status into one short-lived snapshot", async () => {
    const upstream = vi.fn(async (request) => {
      const pathname = new URL(typeof request === "string" ? request : request.url).pathname;
      if (pathname.endsWith("/stats")) {
        return Response.json({
          version: "2.0",
          phase: "open-beta",
          phase_label: "Open Beta",
          release_label: "2.0 Open Beta",
          runtime_version: "3.1.0",
          codename: "Nova",
          guilds: 5,
          members: 132,
          commands: 90,
          uptime_seconds: 120,
          ready: true,
        });
      }
      return Response.json({ ok: true, bot_ready: true, db_ok: true });
    });
    vi.stubGlobal("fetch", upstream);

    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/status-snapshot"),
      { ...env, STATUS_API_BASE: "https://api.example.test/api/v1" },
    );
    const snapshot = await response.json();

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store, private");
    expect(response.headers.get("Cloudflare-CDN-Cache-Control")).toBe("no-store");
    expect(snapshot.stats.uptime_seconds).toBe(120);
    expect(snapshot.health.db_ok).toBe(true);
    expect(upstream).toHaveBeenCalledTimes(2);
  });

  it("serves the last good status snapshot instead of a false offline state", async () => {
    const upstream = vi.fn(async (request) => {
      const pathname = new URL(typeof request === "string" ? request : request.url).pathname;
      if (pathname.endsWith("/stats")) {
        return Response.json({
          version: "2.0",
          phase: "open-beta",
          phase_label: "Open Beta",
          release_label: "2.0 Open Beta",
          runtime_version: "3.1.0",
          codename: "Nova",
          guilds: 5,
          members: 169,
          commands: 66,
          uptime_seconds: 600,
          ready: true,
        });
      }
      return Response.json({ ok: true, bot_ready: true, db_ok: true });
    });
    vi.stubGlobal("fetch", upstream);

    const firstResponse = await worker.fetch(
      new Request("https://novaguard.fun/api/status-snapshot"),
      { ...env, STATUS_API_BASE: "https://api.example.test/api/v1" },
    );
    expect(firstResponse.status).toBe(200);

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("temporary upstream timeout");
      }),
    );

    const staleResponse = await worker.fetch(
      new Request("https://novaguard.fun/api/status-snapshot"),
      { ...env, STATUS_API_BASE: "https://api.example.test/api/v1" },
    );
    const snapshot = await staleResponse.json();

    expect(staleResponse.status).toBe(200);
    expect(staleResponse.headers.get("Cache-Control")).toBe("no-store, private");
    expect(snapshot.stale).toBe(true);
    expect(snapshot.stats.ready).toBe(true);
    expect(snapshot.health.bot_ready).toBe(true);
  });

  it("sets a two-hour cookie", async () => {
    const response = await worker.fetch(loginRequest(), env);

    expect(response.status).toBe(303);
    expect(response.headers.get("Set-Cookie")).toContain("Max-Age=7200");
  });

  it("expires access after two hours", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-19T12:00:00Z"));

    const login = await worker.fetch(loginRequest(), env);
    const cookie = login.headers.get("Set-Cookie").split(";", 1)[0];

    const active = await worker.fetch(
      new Request("https://novaguard.fun/dashboard/", { headers: { Cookie: cookie } }),
      env,
    );
    expect(active.status).toBe(200);
    await expect(active.text()).resolves.toBe("/dashboard/");

    vi.advanceTimersByTime((2 * 60 * 60 + 1) * 1000);
    const expired = await worker.fetch(
      new Request("https://novaguard.fun/dashboard/", { headers: { Cookie: cookie } }),
      env,
    );

    expect(expired.status).toBe(302);
    expect(expired.headers.get("Location")).toContain("/login/?next=%2Fdashboard%2F");
  });

  it("serves the dashboard shell for nested client routes", async () => {
    const login = await worker.fetch(loginRequest(), env);
    const cookie = login.headers.get("Set-Cookie").split(";", 1)[0];

    const response = await worker.fetch(
      new Request("https://novaguard.fun/dashboard/g/1001/settings", { headers: { Cookie: cookie } }),
      env,
    );

    expect(response.status).toBe(200);
    await expect(response.text()).resolves.toBe("/dashboard/");
  });

  it("serves maintenance over private routes when enabled", async () => {
    const login = await worker.fetch(loginRequest(), env);
    const cookie = login.headers.get("Set-Cookie").split(";", 1)[0];

    const response = await worker.fetch(
      new Request("https://novaguard.fun/dashboard/", { headers: { Cookie: cookie } }),
      { ...env, MAINTENANCE_MODE: "protected" },
    );

    expect(response.status).toBe(200);
    await expect(response.text()).resolves.toBe("/maintenance/");
  });

  it("protects direct maintenance preview", async () => {
    const response = await worker.fetch(new Request("https://novaguard.fun/maintenance/"), env);

    expect(response.status).toBe(302);
    expect(response.headers.get("Location")).toContain("/login/?next=%2Fmaintenance%2F");
  });

  it("caches hashed static assets without caching protected HTML", async () => {
    const asset = await worker.fetch(
      new Request("https://novaguard.fun/_astro/app.123abc.js"),
      env,
    );
    expect(asset.headers.get("Cache-Control")).toBe("public, max-age=31536000, immutable");

    const login = await worker.fetch(loginRequest(), env);
    const cookie = login.headers.get("Set-Cookie").split(";", 1)[0];
    const page = await worker.fetch(
      new Request("https://novaguard.fun/dashboard/", { headers: { Cookie: cookie } }),
      env,
    );
    expect(page.headers.get("Cache-Control")).toBeNull();
  });
});

describe("updates feed", () => {
  it("asks for the password before showing the updates page", async () => {
    const response = await worker.fetch(new Request("https://novaguard.fun/updates"), env);
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toContain("/login/");
  });

  it("asks for the password on a deeper updates page too", async () => {
    const response = await worker.fetch(new Request("https://novaguard.fun/updates/3"), env);
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toContain("/login/");
  });

  it("asks for the password on the landing page", async () => {
    const response = await worker.fetch(new Request("https://novaguard.fun/home/"), env);
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toContain("/login/");
  });

  it("keeps the Coming Soon face and the login page open", async () => {
    for (const path of ["/", "/login/", "/coming-soon/"]) {
      const response = await worker.fetch(new Request(`https://novaguard.fun${path}`), env);
      expect(response.status, `${path} should stay public`).toBe(200);
    }
  });

  it("proxies the bot feed and marks it cacheable", async () => {
    const payload = { updates: [{ build: 16, created_at: "2026-07-24T01:28:56+00:00" }], count: 1 };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(payload)),
    );
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/updates-feed"),
      env,
      { waitUntil() {} },
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(payload);
    expect(response.headers.get("Cache-Control")).toBe(
      "public, max-age=300, stale-while-revalidate=1800",
    );
  });

  it("answers 502 when the bot is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("offline");
      }),
    );
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/updates-feed"),
      env,
      { waitUntil() {} },
    );
    expect(response.status).toBe(502);
    expect((await response.json()).code).toBe("updates_unavailable");
  });

  it("rejects a non-GET request", async () => {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/updates-feed", { method: "POST" }),
      env,
      { waitUntil() {} },
    );
    expect(response.status).toBe(405);
  });
});
