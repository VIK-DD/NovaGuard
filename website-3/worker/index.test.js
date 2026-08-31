// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PUBLIC_LAUNCH_AT_MS,
  hasPublicLaunchPassed,
} from "../launch-config.js";
import worker, { loginRateLimitKey } from "./index.js";
import { INLINE_SCRIPT_HASHES, INLINE_STYLE_HASHES } from "./inline-hashes.js";
import { collectInlineHashes } from "../scripts/inline-csp-hashes.mjs";
import { createHash } from "node:crypto";

const env = {
  AUTH_PASSWORD: "test-password",
  LOGIN_RATE_LIMITER: {
    limit: async () => ({ success: true }),
  },
  ASSETS: {
    fetch: async (request) => new Response(new URL(request.url).pathname, { status: 200 }),
  },
};

// Stands in for a token the worker minted on a previous /login/ render. Any
// value matching the worker's token shape works; what is under test is that the
// cookie and the form field have to agree.
const CSRF_TOKEN = "Zm9ybS10b2tlbi1mb3ItdGhlLXdvcmtlci10ZXN0cw";

// A form post the way a browser sends one from a page we served: same-origin,
// carrying the cookie the worker set and the field it stitched into the form.
function formPost(path, fields, { origin = "https://novaguard.fun", cookie, token } = {}) {
  const headers = { "Content-Type": "application/x-www-form-urlencoded" };
  if (origin) headers.Origin = origin;
  const cookies = [cookie, token === null ? null : `__Host-ng_csrf=${token ?? CSRF_TOKEN}`].filter(
    Boolean,
  );
  if (cookies.length) headers.Cookie = cookies.join("; ");

  const body = new URLSearchParams(fields);
  if (token !== null && !("csrf_token" in fields)) body.set("csrf_token", token ?? CSRF_TOKEN);
  return new Request(`https://novaguard.fun${path}`, { method: "POST", headers, body });
}

function loginRequest(overrides = {}) {
  return formPost(
    "/api/auth/login",
    { password: env.AUTH_PASSWORD, next: "/dashboard/" },
    overrides,
  );
}

// Every /dashboard/* request asks the bot whether maintenance is on, so without
// a default stub these tests reach for the real api.novaguard.fun. That passes
// on a developer machine and fails closed in CI, where there is no network —
// the suite would be measuring the network, not the worker. Tests that need a
// different answer override this with their own vi.stubGlobal.
beforeEach(() => {
  // The production launch is time-driven. Keep the legacy/gate tests anchored
  // before it so the suite remains deterministic when run years from now.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-08-01T09:00:00Z"));
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

  it("uses a strict CSP and never permits inline styles or scripts", async () => {
    const response = await worker.fetch(new Request("https://novaguard.fun/"), env);
    const csp = response.headers.get("Content-Security-Policy");

    expect(csp).toContain("style-src 'self'");
    expect(csp).toContain("style-src-attr 'none'");
    expect(csp).toContain("script-src 'self'");
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).not.toContain("unsafe-eval");
  });

  it("names the build's own inline scripts by hash, and nothing else", async () => {
    // The nonce this replaced was stamped onto every script and style element
    // by an HTMLRewriter, so it certified "this is a script tag" rather than
    // "we built this". Anything that reached the HTML first was signed by the
    // header meant to stop it.
    const response = await worker.fetch(new Request("https://novaguard.fun/"), env);
    const csp = response.headers.get("Content-Security-Policy");

    expect(csp).not.toContain("nonce-");
    expect(INLINE_SCRIPT_HASHES.length).toBeGreaterThan(0);
    for (const hash of INLINE_SCRIPT_HASHES) expect(csp).toContain(`'${hash}'`);
    for (const hash of INLINE_STYLE_HASHES) expect(csp).toContain(`'${hash}'`);
  });

  it("does not permit a script it did not build", async () => {
    const injected = "alert(document.cookie)";
    const digest = createHash("sha256").update(injected, "utf8").digest("base64");

    const response = await worker.fetch(new Request("https://novaguard.fun/"), env);
    const csp = response.headers.get("Content-Security-Policy");

    expect(csp).not.toContain(digest);
  });

  it("keeps the hash manifest in step with the built pages", async () => {
    // A stale manifest blocks the site's own inline code, so this is the test
    // that has to fail if someone edits a script and forgets to rebuild.
    const built = await collectInlineHashes(new URL("../dist", import.meta.url).pathname);
    if (built.pages === 0) return; // no dist/ in this checkout; CI builds first

    expect(built.script).toEqual(INLINE_SCRIPT_HASHES);
    expect(built.style).toEqual(INLINE_STYLE_HASHES);
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
      formPost("/api/auth/login", { password: attemptedPassword, next: "/dashboard/" }),
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
  it("does not let an environment switch bypass authentication", async () => {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/home/"),
      { ...env, SECURITY_SCAN_OPEN: "true" },
    );

    expect(response.status).toBe(302);
    expect(response.headers.get("Location")).toContain("/login/?next=%2Fhome%2F");
  });

  it("rate limits password guesses at the edge", async () => {
    const limit = vi.fn(async () => ({ success: false }));
    const response = await worker.fetch(loginRequest(), {
      ...env,
      LOGIN_RATE_LIMITER: { limit },
    });

    expect(response.status).toBe(429);
    expect(response.headers.get("Retry-After")).toBe("60");
    expect(response.headers.get("Set-Cookie")).toBeNull();
    expect(limit).toHaveBeenCalledWith({ key: "password-gate" });
  });

  it("fails login closed when its rate-limit binding is unavailable", async () => {
    const { LOGIN_RATE_LIMITER: _missing, ...withoutLimiter } = env;
    const response = await worker.fetch(loginRequest(), withoutLimiter);

    expect(response.status).toBe(503);
    expect(response.headers.get("Retry-After")).toBe("60");
    expect(response.headers.get("Set-Cookie")).toBeNull();
  });

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

  it("never lets a shared cache hold a page the password gate covers", async () => {
    // Every one of these used to fall through to the asset server's
    // `public, max-age=0, must-revalidate`. `public` is an invitation to a CDN
    // edge or a corporate proxy to keep a copy of a page an anonymous visitor
    // is not allowed to read.
    const login = await worker.fetch(loginRequest(), env);
    const cookie = login.headers.get("set-cookie").split(";")[0];

    for (const path of ["/commands/", "/setup/", "/vote/", "/faq/"]) {
      const response = await worker.fetch(
        new Request(`https://novaguard.fun${path}`, { headers: { cookie } }),
        env,
      );
      expect(response.status, path).toBe(200);
      expect(response.headers.get("Cache-Control"), path).toBe("private, max-age=60");
      expect(response.headers.get("Cache-Control"), path).not.toContain("public");
    }
  });

  it("keeps every legal notice public during soft launch", async () => {
    for (const path of [
      "/privacy",
      "/privacy/",
      "/terms",
      "/terms/",
      "/server-admin-notice",
      "/server-admin-notice/",
    ]) {
      const response = await worker.fetch(new Request(`https://novaguard.fun${path}`), env);
      expect(response.status, `${path} should be public`).toBe(200);
      expect(response.headers.get("Location"), path).toBeNull();
      expect(response.headers.get("Cache-Control"), path).toBe(
        "public, max-age=300, stale-while-revalidate=3600",
      );
    }
  });

  it("keeps no copy of the signed-in dashboard shell anywhere", async () => {
    const login = await worker.fetch(loginRequest(), env);
    const cookie = login.headers.get("set-cookie").split(";")[0];
    const response = await worker.fetch(
      new Request("https://novaguard.fun/dashboard/", { headers: { cookie } }),
      env,
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });

  it("answers robots.txt without a session, and hardens it like any other page", async () => {
    // A crawler never authenticates. Behind the gate this redirected to the
    // login page, so the only crawl policy the site published was Cloudflare's
    // generated default, served at the edge with none of these headers.
    const response = await worker.fetch(
      new Request("https://novaguard.fun/robots.txt"),
      env,
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Strict-Transport-Security")).toContain("max-age=");
    expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(response.headers.get("Content-Security-Policy")).toContain("default-src 'self'");
  });

  it("does not cache login and preview access pages", async () => {
    for (const path of ["/login/", "/preview/"]) {
      const response = await worker.fetch(new Request(`https://novaguard.fun${path}`), env);
      expect(response.status).toBe(200);
      expect(response.headers.get("Cache-Control")).toBe("no-store");
    }
  });

  it("combines public bot status into one short-lived snapshot", async () => {
    const upstream = vi.fn(async (request) => {
      const pathname = new URL(typeof request === "string" ? request : request.url).pathname;
      if (pathname.endsWith("/stats")) {
        return Response.json({
          version: "3.0",
          phase: "stable",
          phase_label: "",
          release_label: "3.0",
          runtime_version: "3.0.0",
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
          version: "3.0",
          phase: "stable",
          phase_label: "",
          release_label: "3.0",
          runtime_version: "3.0.0",
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
    // Browsers normalise a backslash to a slash in a special-scheme URL.
    const response = await worker.fetch(
      formPost("/api/auth/login", { password: env.AUTH_PASSWORD, next: "/\\evil.example" }),
      env,
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("https://novaguard.fun/dashboard/");
  });

  it("expires access after two hours", async () => {
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
    // This used to assert `null`, meaning "the worker sets nothing". That is
    // not the same as "not cached": with no rule of our own, the asset
    // server's `public, max-age=0, must-revalidate` reached the browser
    // untouched, and `public` lets a shared cache keep a signed-in page. The
    // mock asset server sends no header, so the old assertion passed here
    // while production shipped the problem.
    expect(page.headers.get("Cache-Control")).toBe("no-store");
  });
});

describe("cross-site request forgery", () => {
  // The site's two forms are static Astro pages, so the token cannot be baked
  // in at build time. It is stitched into the response by the worker instead.
  it("stitches a token into every form it serves, and pins it to a cookie", async () => {
    const formEnv = {
      ...env,
      ASSETS: {
        fetch: async () =>
          new Response('<form action="/api/auth/login" method="post"></form>', {
            status: 200,
            headers: { "Content-Type": "text/html" },
          }),
      },
    };

    const page = await worker.fetch(new Request("https://novaguard.fun/login/"), formEnv);
    const html = await page.text();
    const field = html.match(/name="csrf_token" value="([^"]+)"/);

    expect(field).not.toBeNull();
    // Same value in both places is the whole mechanism: an attacker's page can
    // make a browser send the cookie, but cannot read it to fill in the field.
    expect(page.headers.get("Set-Cookie")).toContain(`__Host-ng_csrf=${field[1]}`);
    // `__Host-` is what stops a subdomain writing the cookie, which would let
    // the attacker choose both halves of the comparison.
    expect(page.headers.get("Set-Cookie")).toContain("Secure");
    expect(page.headers.get("Set-Cookie")).toContain("SameSite=Strict");
    // The body now differs per visitor, so it must not be held anywhere shared.
    expect(page.headers.get("Cache-Control")).toBe("no-store");
  });

  it("keeps one token across renders so a second tab does not break the first", async () => {
    const first = await worker.fetch(new Request("https://novaguard.fun/login/"), env);
    const token = first.headers.get("Set-Cookie").match(/__Host-ng_csrf=([^;]+)/)[1];

    const second = await worker.fetch(
      new Request("https://novaguard.fun/login/", {
        headers: { Cookie: `__Host-ng_csrf=${token}` },
      }),
      env,
    );

    expect(second.headers.get("Set-Cookie")).toContain(`__Host-ng_csrf=${token}`);
  });

  it("returns a same-origin login with a stale token to a fresh form", async () => {
    const response = await worker.fetch(loginRequest({ token: null }), env);

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe(
      "https://novaguard.fun/login/?next=%2Fdashboard%2F&error=csrf",
    );
    expect(response.headers.get("Set-Cookie")).toBeNull();
  });

  it("returns a same-origin login whose token does not match the cookie to a fresh form", async () => {
    const response = await worker.fetch(
      formPost("/api/auth/login", {
        password: env.AUTH_PASSWORD,
        next: "/dashboard/",
        csrf_token: "Zm9yZ2VkLXRva2VuLXRoYXQtd2lsbC1ub3QtbWF0Y2gtdGhl",
      }),
      env,
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe(
      "https://novaguard.fun/login/?next=%2Fdashboard%2F&error=csrf",
    );
    expect(response.headers.get("Set-Cookie")).toBeNull();
  });

  it("refuses a login posted from another origin", async () => {
    const response = await worker.fetch(
      loginRequest({ origin: "https://attacker.example" }),
      env,
    );

    expect(response.status).toBe(403);
  });

  it("accepts a valid token when a privacy-focused browser omits Origin", async () => {
    const response = await worker.fetch(loginRequest({ origin: "" }), env);

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("https://novaguard.fun/dashboard/");
    expect(response.headers.get("Set-Cookie")).toContain("ng_gate=");
  });

  it("refuses a preview code posted from another origin", async () => {
    const response = await worker.fetch(
      formPost("/api/preview", { code: "ng_preview_good" }, { origin: "https://attacker.example" }),
      env,
    );

    expect(response.status).toBe(403);
  });

  it("returns a same-origin preview form with a stale token to a fresh form", async () => {
    const response = await worker.fetch(
      formPost("/api/preview", { code: "ng_preview_good" }, { token: null }),
      env,
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("https://novaguard.fun/preview/?error=csrf");
  });

  // `<img src="/api/auth/logout">` on any page on the internet used to be enough.
  it("no longer signs a visitor out on a bare GET", async () => {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/auth/logout"),
      env,
    );

    expect(response.status).toBe(405);
    expect(response.headers.get("Set-Cookie")).toBeNull();
  });

  it("still signs a visitor out when the page asks properly", async () => {
    const response = await worker.fetch(formPost("/api/auth/logout", {}), env);

    expect(response.status).toBe(303);
    expect(response.headers.get("Set-Cookie")).toContain("ng_gate=;");
  });

  it("never reports the rejection in a way that reveals the expected token", async () => {
    const response = await worker.fetch(loginRequest({ token: null }), env);

    const body = await response.text();
    expect(body).not.toContain("csrf");
    expect(JSON.stringify(vi.mocked(console.warn).mock.calls)).not.toContain(CSRF_TOKEN);
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
  let clock = Date.parse("2026-08-05T00:00:00Z");

  beforeEach(() => {
    // Must exceed the largest jump any single test makes (currently one hour),
    // or a test that travelled forward leaves cached state dated *after* the
    // next test's clock, and the worker reads it as fresh.
    clock += 6 * 60 * 60 * 1000;
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

  it("closes every non-legal page, not just the dashboard", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true, message: "Music Update" } }));

    for (const path of ["/", "/home/", "/updates/"]) {
      const response = await worker.fetch(new Request(`https://novaguard.fun${path}`), apiEnv);
      expect(response.status, `${path} should be closed`).toBe(503);
    }
  });

  it("keeps legal notices available during maintenance", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true, message: "Music Update" } }));

    for (const path of ["/privacy/", "/terms/", "/server-admin-notice/"]) {
      const response = await worker.fetch(new Request(`https://novaguard.fun${path}`), apiEnv);
      expect(response.status, `${path} should remain available`).toBe(200);
      expect(response.headers.get("Cache-Control"), path).toContain("public");
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
    const response = await worker.fetch(formPost("/api/preview", { code }), testEnv);
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
          ? new Response('<p class="message" data-ng-maintenance-message></p>', {
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

describe("gate cookie signing key", () => {
  // AUTH_PASSWORD used to be the HMAC key as well as the password. Every
  // cookie the worker issued was then a (known message, MAC) pair under a
  // human-chosen password, and HMAC-SHA256 has no work factor - one leaked
  // cookie is an offline dictionary attack at whatever speed the attacker's
  // hardware runs.
  const DEDICATED = "P4unRLGiE6mV9wq2Zt7XbKsA0YcNhJ3F";

  // Same shared-clock discipline as "maintenance sync" above, and for the same
  // reason: the worker caches the maintenance answer in module scope, so a test
  // whose clock sits *earlier* than the cached fetchedAt reads that answer as
  // fresh and inherits it. Start after the range that block reaches and stay
  // before PUBLIC_LAUNCH_AT, since these tests are about the pre-launch gate.
  let clock = Date.parse("2026-08-25T00:00:00Z");

  beforeEach(() => {
    clock += 6 * 60 * 60 * 1000;
    vi.setSystemTime(clock);
  });

  async function loginCookie(withEnv) {
    const response = await worker.fetch(
      formPost("/api/auth/login", { password: withEnv.AUTH_PASSWORD, next: "/dashboard/" }),
      withEnv,
    );
    return (response.headers.get("Set-Cookie") || "").split(";")[0];
  }

  it("signs with the dedicated key when one is configured", async () => {
    const signed = { ...env, GATE_SIGNING_KEY: DEDICATED };
    const cookie = await loginCookie(signed);
    expect(cookie).toMatch(/^ng_gate=/);

    // The same cookie must not verify under the password alone.
    const response = await worker.fetch(
      new Request("https://novaguard.fun/home/", { headers: { Cookie: cookie } }),
      env,
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("Location")).toContain("/login/");
  });

  it("a cookie signed with the dedicated key is accepted by it", async () => {
    const signed = { ...env, GATE_SIGNING_KEY: DEDICATED };
    const cookie = await loginCookie(signed);

    const response = await worker.fetch(
      new Request("https://novaguard.fun/home/", { headers: { Cookie: cookie } }),
      signed,
    );
    expect(response.status).toBe(200);
  });

  it("falls back to the password loudly rather than locking the site out", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      const cookie = await loginCookie(env);
      const response = await worker.fetch(
        new Request("https://novaguard.fun/home/", { headers: { Cookie: cookie } }),
        env,
      );
      expect(response.status).toBe(200);
      const events = warn.mock.calls.map((call) => String(call[0]));
      expect(events.some((line) => line.includes("gate_signing_key_missing"))).toBe(true);
    } finally {
      warn.mockRestore();
    }
  });

  it("refuses a key too short to be worth having", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      await loginCookie({ ...env, GATE_SIGNING_KEY: "short" });
      const events = warn.mock.calls.map((call) => String(call[0]));
      expect(events.some((line) => line.includes("gate_signing_key_too_short"))).toBe(true);
    } finally {
      warn.mockRestore();
    }
  });
});

describe("automatic public launch", () => {
  let clock = PUBLIC_LAUNCH_AT_MS;

  beforeEach(() => {
    clock += 6 * 60 * 60 * 1000;
    vi.setSystemTime(clock);
  });

  it("changes state at the exact configured instant", () => {
    expect(hasPublicLaunchPassed(PUBLIC_LAUNCH_AT_MS - 1)).toBe(false);
    expect(hasPublicLaunchPassed(PUBLIC_LAUNCH_AT_MS)).toBe(true);
  });

  it("retires root, login and countdown pages in favour of the official site", async () => {
    for (const path of ["/", "/index.html", "/login/", "/coming-soon/"]) {
      const response = await worker.fetch(new Request(`https://novaguard.fun${path}`), env);
      expect(response.status, path).toBe(302);
      expect(response.headers.get("Location"), path).toBe("https://novaguard.fun/home/");
      expect(response.headers.get("Cache-Control"), path).toBe("no-store");
      expect(response.headers.get("Set-Cookie"), path).toContain("ng_gate=;");
      expect(response.headers.get("Set-Cookie"), path).toContain("__Host-ng_csrf=;");
    }
  });

  it("keeps countdown assets available for tabs opened just before launch", async () => {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/coming-soon/assets/countdown.js"),
      env,
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("public, max-age=31536000, immutable");
  });

  it("opens public pages without the retired password and makes them safely cacheable", async () => {
    const withoutPassword = { ...env, AUTH_PASSWORD: "" };

    for (const path of ["/home/", "/commands/", "/updates/", "/vote/", "/faq/"]) {
      const response = await worker.fetch(
        new Request(`https://novaguard.fun${path}`),
        withoutPassword,
      );
      expect(response.status, path).toBe(200);
      expect(response.headers.get("Location"), path).toBeNull();
      expect(response.headers.get("Cache-Control"), path).toBe(
        "public, max-age=300, stale-while-revalidate=3600",
      );
    }
  });

  it("keeps Discord dashboard routing available without the pre-launch gate", async () => {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/dashboard/g/1001/settings"),
      { ...env, AUTH_PASSWORD: "" },
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    await expect(response.text()).resolves.toBe("/dashboard/");
  });

  it("retires the password API without checking a password or rate limit", async () => {
    const limit = vi.fn(async () => ({ success: true }));
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/auth/login", { method: "POST" }),
      { ...env, AUTH_PASSWORD: "", LOGIN_RATE_LIMITER: { limit } },
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("https://novaguard.fun/home/");
    expect(response.headers.get("Set-Cookie")).toContain("Max-Age=0");
    expect(limit).not.toHaveBeenCalled();
  });

  it("publishes a crawler policy for the official site", async () => {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/robots.txt"),
      env,
    );
    const body = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toContain("text/plain");
    expect(body).toContain("Allow: /");
    expect(body).toContain("Disallow: /dashboard/");
    expect(body).toContain("Disallow: /api/");
  });

  it("keeps maintenance ahead of the automatic launch", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          ok: true,
          maintenance: { enabled: true, message: "Release maintenance" },
        }),
      ),
    );

    const response = await worker.fetch(new Request("https://novaguard.fun/"), {
      ...env,
      STATUS_API_BASE: "https://api.example.test/api/v1",
    });

    expect(response.status).toBe(503);
    expect(response.headers.get("Location")).toBeNull();
    await expect(response.text()).resolves.toBe("/maintenance/");
  });
});

describe("login rate-limit key", () => {
  // The gate used one route-wide key, so ten attempts a minute from anyone
  // locked out everyone. That caps brute force and hands over a denial of
  // service in exchange, which is the wrong trade for a door.

  const withIp = (ip) =>
    new Request("https://novaguard.fun/api/auth/login", {
      method: "POST",
      headers: ip ? { "CF-Connecting-IP": ip } : {},
    });

  it("gives two different clients two different buckets", async () => {
    const first = await loginRateLimitKey(withIp("203.0.113.7"));
    const second = await loginRateLimitKey(withIp("198.51.100.9"));
    expect(first).not.toBe(second);
  });

  it("gives the same client the same bucket every time", async () => {
    const first = await loginRateLimitKey(withIp("203.0.113.7"));
    const second = await loginRateLimitKey(withIp("203.0.113.7"));
    expect(first).toBe(second);
  });

  it("never puts the address itself in the key", async () => {
    // The limiter has to tell clients apart, not know who they are.
    const key = await loginRateLimitKey(withIp("203.0.113.7"));
    expect(key).not.toContain("203.0.113.7");
    expect(key).toMatch(/^pg:[A-Za-z0-9_-]{1,32}$/);
  });

  it("falls back to the shared bucket when there is no address", async () => {
    // Capped rather than uncapped: stripping the header must not be a way out
    // of the limit.
    expect(await loginRateLimitKey(withIp(null))).toBe("password-gate");
  });

  it("reads X-Forwarded-For when CF-Connecting-IP is absent", async () => {
    const request = new Request("https://novaguard.fun/api/auth/login", {
      method: "POST",
      headers: { "X-Forwarded-For": "203.0.113.7, 70.41.3.18" },
    });
    expect(await loginRateLimitKey(request)).toBe(
      await loginRateLimitKey(withIp("203.0.113.7")),
    );
  });
});

describe("safeNext normalization", () => {
  // The prefix guard reads the string as it arrived; `new URL` then rewrites
  // it. `/..//evil.example` is not `//`-prefixed on the way in, but
  // normalization pops the empty first segment and hands back the pathname
  // `//evil.example` - which, resolved against the request URL, is a
  // protocol-relative redirect to somebody else's origin.
  const offSite = [
    "/..//evil.example",
    "/./..//evil.example",
    "/a/../..//evil.example",
    "//evil.example",
    "/\\evil.example",
  ];

  for (const probe of offSite) {
    it(`keeps ${probe} on this origin`, async () => {
      const response = await worker.fetch(
        formPost("/api/auth/login", { password: env.AUTH_PASSWORD, next: probe }),
        env,
      );
      expect(response.status).toBe(303);
      expect(new URL(response.headers.get("Location")).origin).toBe("https://novaguard.fun");
    });
  }

  it("still honours an ordinary in-site destination", async () => {
    const response = await worker.fetch(
      formPost("/api/auth/login", { password: env.AUTH_PASSWORD, next: "/updates/2?page=2#top" }),
      env,
    );
    expect(response.headers.get("Location")).toBe("https://novaguard.fun/updates/2?page=2#top");
  });
});
