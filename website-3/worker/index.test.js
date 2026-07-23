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
    body: new URLSearchParams({ password: env.AUTH_PASSWORD, next: "/home/" }),
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("password session", () => {
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
      new Request("https://novaguard.fun/home/", { headers: { Cookie: cookie } }),
      env,
    );
    expect(active.status).toBe(200);
    await expect(active.text()).resolves.toBe("/home/");

    vi.advanceTimersByTime((2 * 60 * 60 + 1) * 1000);
    const expired = await worker.fetch(
      new Request("https://novaguard.fun/home/", { headers: { Cookie: cookie } }),
      env,
    );

    expect(expired.status).toBe(302);
    expect(expired.headers.get("Location")).toContain("/login/?next=%2Fhome%2F");
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
      new Request("https://novaguard.fun/home/", { headers: { Cookie: cookie } }),
      env,
    );
    expect(page.headers.get("Cache-Control")).toBeNull();
  });
});
