// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

// Every /dashboard/* request asks the bot whether maintenance is on, so without
// a default stub these tests reach for the real api.novaguard.fun. That passes
// on a developer machine and fails closed in CI, where there is no network —
// the suite would be measuring the network, not the worker. Tests that need a
// different answer override this with their own vi.stubGlobal.
beforeEach(() => {
  vi.spyOn(console, "warn").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({ ok: true, bot_ready: true, db_ok: true, maintenance: { enabled: false } }),
    ),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("production observability", () => {
  it("adds security headers to assets, redirects and errors", async () => {
    const asset = await worker.fetch(new Request("https://novaguard.fun/"), env);
    const redirect = await worker.fetch(
      new Request("https://novaguard.fun/dashboard/"),
      env,
    );
    const error = await worker.fetch(
      new Request("https://novaguard.fun/api/auth/login", { method: "POST" }),
      { ...env, AUTH_PASSWORD: "" },
    );

    for (const response of [asset, redirect, error]) {
      expect(response.headers.get("Strict-Transport-Security")).toContain("max-age=31536000");
      expect(response.headers.get("X-Frame-Options")).toBe("DENY");
      expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
      expect(response.headers.get("Referrer-Policy")).toBe("no-referrer");
      expect(response.headers.get("Permissions-Policy")).toContain("camera=()");
      expect(response.headers.get("Content-Security-Policy")).toContain("frame-ancestors 'none'");
    }
  });

  it("emits structured upstream failures without secrets", async () => {
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
    const call = vi.mocked(console.warn).mock.calls.find(([message]) =>
      String(message).includes("updates_feed_upstream_failed"),
    );
    expect(call).toBeTruthy();
    expect(JSON.parse(call[0])).toMatchObject({
      event: "updates_feed_upstream_failed",
      error: "offline",
    });
    expect(call[0]).not.toContain(env.AUTH_PASSWORD);
  });

  it("turns unexpected edge failures into a safe JSON response", async () => {
    const brokenEnv = {
      ...env,
      ASSETS: {
        fetch: async () => {
          throw new Error("asset binding unavailable");
        },
      },
    };

    const response = await worker.fetch(
      new Request("https://novaguard.fun/assets/broken.js", {
        headers: { "cf-ray": "test-ray" },
      }),
      brokenEnv,
    );
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(body.code).toBe("edge_error");
    const event = JSON.parse(vi.mocked(console.error).mock.calls.at(-1)[0]);
    expect(event).toMatchObject({
      event: "worker_request_failed",
      method: "GET",
      path: "/assets/broken.js",
      ray: "test-ray",
    });
    expect(JSON.stringify(event)).not.toContain(env.AUTH_PASSWORD);
  });

  it("never logs a rejected password value", async () => {
    const attemptedPassword = "wrong-super-secret-value";
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ password: attemptedPassword, next: "/dashboard/" }),
      }),
      env,
    );

    expect(response.status).toBe(303);
    const serializedCalls = JSON.stringify(vi.mocked(console.warn).mock.calls);
    expect(serializedCalls).toContain("auth_login_denied");
    expect(serializedCalls).not.toContain(attemptedPassword);
    expect(serializedCalls).not.toContain(env.AUTH_PASSWORD);
  });
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

  it("never redirects a successful login to another origin", async () => {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        // Browsers normalise a backslash to a slash in a special-scheme URL.
        body: new URLSearchParams({ password: env.AUTH_PASSWORD, next: "/\\evil.example" }),
      }),
      env,
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("https://novaguard.fun/dashboard/");
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

    // 503, like the Discord-driven switch: both mean the same thing to a
    // visitor and to a crawler, so both answer the same way.
    expect(response.status).toBe(503);
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

describe("maintenance sync", () => {
  const apiEnv = { ...env, STATUS_API_BASE: "https://api.example.test/api/v1" };

  // Advanced, never reset: afterEach restores the real clock, so a jump
  // measured from `Date.now()` would land at roughly the same instant every
  // time and leave the previous test's answer inside the 30 s freshness window.
  let clock = Date.now();

  beforeEach(() => {
    // Must exceed the largest jump any single test makes (currently one hour),
    // or a test that travelled forward leaves cached state dated *after* the
    // next test's clock, and the worker reads it as fresh.
    clock += 6 * 60 * 60 * 1000;
    // Only Date is faked. Faking the timers too would break
    // AbortSignal.timeout inside readMaintenance, aborting every upstream call
    // and making the fail-closed path look like the answer.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(clock);
  });

  function healthStub(maintenance) {
    return vi.fn(async () =>
      Response.json({ ok: true, bot_ready: true, db_ok: true, ...maintenance }),
    );
  }

  async function dashboardRequest(testEnv, path = "/dashboard/") {
    const login = await worker.fetch(loginRequest(), testEnv);
    const cookie = login.headers.get("set-cookie").split(";")[0];
    return worker.fetch(
      new Request(`https://novaguard.fun${path}`, { headers: { cookie } }),
      testEnv,
    );
  }

  it("closes the dashboard when the bot says it is in maintenance", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true, message: "Music install" } }));

    const response = await dashboardRequest(apiEnv);

    expect(response.status).toBe(503);
    await expect(response.text()).resolves.toBe("/maintenance/");
  });

  it("serves the dashboard shell when maintenance is off", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: false } }));

    const response = await dashboardRequest(apiEnv, "/dashboard/g/123");

    expect(response.status).toBe(200);
    await expect(response.text()).resolves.toBe("/dashboard/");
  });

  it("treats a bot that predates the field as open, not broken", async () => {
    // The worker deploys before the bot restarts. If a missing field read as an
    // error, the dashboard would black out in the gap between the two.
    vi.stubGlobal("fetch", healthStub({}));

    const response = await dashboardRequest(apiEnv);

    expect(response.status).toBe(200);
  });

  it("closes every page, not just the dashboard", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true, message: "Music Update" } }));

    for (const path of ["/", "/home/", "/updates/", "/terms/"]) {
      const response = await worker.fetch(new Request(`https://novaguard.fun${path}`), apiEnv);
      expect(response.status, `${path} should be closed`).toBe(503);
    }
  });

  it("closes a page for a visitor with no session, without bouncing them to login", async () => {
    // Sending someone to a login form for a site that is shut anyway is a
    // worse answer than telling them it is shut.
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true } }));

    const response = await worker.fetch(new Request("https://novaguard.fun/home/"), apiEnv);

    expect(response.status).toBe(503);
    expect(response.headers.get("Location")).toBeNull();
  });

  it("keeps serving the assets the maintenance page is built from", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true } }));

    const asset = await worker.fetch(
      new Request("https://novaguard.fun/_astro/app.123abc.js"),
      apiEnv,
    );

    expect(asset.status).toBe(200);
  });

  it("leaves the site open when maintenance is off", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: false } }));

    const response = await worker.fetch(new Request("https://novaguard.fun/"), apiEnv);

    expect(response.status).toBe(200);
  });

  it("rides out a restart on the last known answer", async () => {
    // A pm2 restart is seconds long. Flipping the dashboard closed for it would
    // be worse than briefly serving a slightly old answer.
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: false } }));
    expect((await dashboardRequest(apiEnv)).status).toBe(200);

    vi.setSystemTime(Date.now() + 60_000); // past freshness, inside grace
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("connection refused");
      }),
    );

    expect((await dashboardRequest(apiEnv)).status).toBe(200);
  });

  it("closes the dashboard once the API has been gone past the grace window", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: false } }));
    expect((await dashboardRequest(apiEnv)).status).toBe(200);

    vi.setSystemTime(Date.now() + 180_000); // past the 120 s grace
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("host unreachable");
      }),
    );

    // The dashboard cannot work without the API, so saying so beats rendering
    // a page that will only fill with network errors.
    expect((await dashboardRequest(apiEnv)).status).toBe(503);
  });

  async function previewCookie(testEnv, code = "ng_preview_good") {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ code }),
      }),
      testEnv,
    );
    const header = response.headers.get("set-cookie");
    return { response, cookie: header ? header.split(";")[0] : null };
  }

  function previewStub({ ok = true, since = "2026-08-11T06:16:05+00:00" } = {}) {
    return vi.fn(async (input) => {
      const target = String(typeof input === "string" ? input : input.url);
      if (target.endsWith("/maintenance/preview")) {
        return ok
          ? Response.json({ ok: true, since })
          : Response.json({ code: "invalid_preview_code" }, { status: 401 });
      }
      return Response.json({
        ok: true,
        maintenance: { enabled: true, message: "Music Update", since },
      });
    });
  }

  it("lets a holder of the code walk the closed site", async () => {
    vi.stubGlobal("fetch", previewStub());

    const { cookie } = await previewCookie(apiEnv);
    expect(cookie).toContain("ng_preview=");

    // Asserted as 200, not merely "not 503": the code has to stand in for the
    // soft-launch password too, or the holder lands on a login form and the
    // only way to share a preview is to share the site password.
    const page = await worker.fetch(
      new Request("https://novaguard.fun/home/", { headers: { cookie } }),
      apiEnv,
    );
    expect(page.status).toBe(200);
    await expect(page.text()).resolves.toBe("/home/");

    const dashboard = await worker.fetch(
      new Request("https://novaguard.fun/dashboard/g/1", { headers: { cookie } }),
      apiEnv,
    );
    expect(dashboard.status).toBe(200);
    await expect(dashboard.text()).resolves.toBe("/dashboard/");
  });

  it("still sends someone with no preview cookie to the maintenance page", async () => {
    vi.stubGlobal("fetch", previewStub());

    const page = await worker.fetch(new Request("https://novaguard.fun/home/"), apiEnv);

    expect(page.status).toBe(503);
  });

  it("refuses a wrong code without setting a cookie", async () => {
    vi.stubGlobal("fetch", previewStub({ ok: false }));

    const { response, cookie } = await previewCookie(apiEnv, "ng_preview_wrong");

    // Back to the form with a flag, not a bare error page: a wrong code is
    // usually a typo, and the visitor needs somewhere to retype it.
    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toContain("/preview/?error=1");
    expect(cookie).toBeNull();
  });

  it("sets no cookie when the bot cannot be reached", async () => {
    // Failing closed on the door is the opposite of failing closed on the site,
    // and both are the safe direction.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("connection refused");
      }),
    );

    const { cookie } = await previewCookie(apiEnv);

    expect(cookie).toBeNull();
  });

  it("stops honouring a code once a new maintenance window opens", async () => {
    vi.stubGlobal("fetch", previewStub({ since: "2026-08-11T06:00:00+00:00" }));
    const { cookie } = await previewCookie(apiEnv);

    vi.setSystemTime(Date.now() + 60 * 60 * 1000);
    // Same site, new activation: the cookie is bound to the old one.
    vi.stubGlobal("fetch", previewStub({ since: "2026-08-11T09:00:00+00:00" }));

    const page = await worker.fetch(
      new Request("https://novaguard.fun/home/", { headers: { cookie } }),
      apiEnv,
    );

    expect(page.status).toBe(503);
  });

  it("keeps the marketing pages up when the API is gone", async () => {
    // Deliberate maintenance closes the whole site; an outage must not. The
    // marketing pages never needed the bot, so a dead API is no reason to
    // take them down with it.
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: false } }));
    expect((await worker.fetch(new Request("https://novaguard.fun/"), apiEnv)).status).toBe(200);

    vi.setSystemTime(Date.now() + 180_000); // past the 120 s grace
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("host unreachable");
      }),
    );

    expect((await worker.fetch(new Request("https://novaguard.fun/"), apiEnv)).status).toBe(200);
    expect((await dashboardRequest(apiEnv)).status).toBe(503);
  });

  const pageEnv = {
    ...env,
    STATUS_API_BASE: "https://api.example.test/api/v1",
    ASSETS: {
      fetch: async (request) =>
        new URL(request.url).pathname === "/maintenance/"
          ? new Response('<p class="message"><!--ng:message--></p>', {
              status: 200,
              headers: { "Content-Type": "text/html" },
            })
          : new Response(new URL(request.url).pathname, { status: 200 }),
    },
  };

  it("puts the bot's message on the page", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true, message: "Music install" } }));

    const response = await dashboardRequest(pageEnv);

    expect(response.status).toBe(503);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(response.headers.get("Retry-After")).toBe("120");
    await expect(response.text()).resolves.toContain("Music install");
  });

  it("escapes a message instead of rendering it", async () => {
    vi.stubGlobal(
      "fetch",
      healthStub({ maintenance: { enabled: true, message: "<img src=x onerror=alert(1)>" } }),
    );

    const body = await (await dashboardRequest(pageEnv)).text();

    expect(body).not.toContain("<img");
    expect(body).toContain("&lt;img");
  });

  it("leaves the placeholder empty when there is no message", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true } }));

    const body = await (await dashboardRequest(pageEnv)).text();

    expect(body).toContain('<p class="message"></p>');
  });
});
