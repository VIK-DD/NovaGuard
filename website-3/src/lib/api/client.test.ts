import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { ApiError, apiFetch, pathSegment } from "./client";

const okJson = (data: unknown, init?: ResponseInit) =>
  new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

describe("apiFetch", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses OK responses through the schema", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okJson({ ok: true })));
    const data = await apiFetch("/health", z.object({ ok: z.boolean() }));
    expect(data.ok).toBe(true);
  });

  it("sends credentials: include and hits /api/v1", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({}));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/me", z.object({}));
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/v1/me"), expect.anything());
    const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
    expect(requestInit.credentials).toBe("include");
    expect(new Headers(requestInit.headers).has("Content-Type")).toBe(false);
  });

  it("adds JSON content type only when a request has a body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({}));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/guilds/1/config", z.object({}), {
      method: "PUT",
      body: JSON.stringify({ automod: { spam: true } }),
    });
    const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(requestInit.headers).get("Content-Type")).toBe("application/json");
  });

  it("throws ApiError with the stable machine code on API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(okJson({ error: "Nope", code: "forbidden" }, { status: 403 })),
    );
    const err = await apiFetch("/guilds", z.object({})).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("forbidden");
    expect((err as ApiError).status).toBe(403);
    expect((err as ApiError).message).toBe("Nope");
  });

  it("captures Retry-After seconds and validation details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: "Rejected",
            code: "validation_failed",
            details: ["welcome_channel: not a text channel"],
          }),
          { status: 429, headers: { "Retry-After": "7", "Content-Type": "application/json" } },
        ),
      ),
    );
    const err = await apiFetch("/x", z.object({})).catch((e: unknown) => e);
    expect((err as ApiError).retryAfter).toBe(7);
    expect((err as ApiError).details).toEqual(["welcome_channel: not a text channel"]);
  });

  it("maps network failures to code network_error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const err = await apiFetch("/stats", z.object({})).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("network_error");
    expect((err as ApiError).status).toBe(0);
  });

  it("falls back to internal_error when the error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>boom</html>", { status: 500 })),
    );
    const err = await apiFetch("/stats", z.object({})).catch((e: unknown) => e);
    expect((err as ApiError).code).toBe("internal_error");
    expect((err as ApiError).status).toBe(500);
  });
});

describe("pathSegment", () => {
  // guildId comes from the route and TanStack Router percent-DECODES a path
  // param, so `..%2F..%2Fadmin` arrives as `../../admin`. Interpolated raw the
  // browser collapses it and the authenticated request lands on a different
  // API path entirely; a trailing `?` makes the rest of the template a query
  // string, so the whole path becomes attacker-chosen.
  it("stops a traversal segment from changing the path", () => {
    expect(pathSegment("../../admin")).toBe("..%2F..%2Fadmin");
    expect(new URL(`/api/v1/guilds/${pathSegment("../../admin")}/config`, "https://api.test").pathname).toBe(
      "/api/v1/guilds/..%2F..%2Fadmin/config",
    );
  });

  it("stops a segment from opening a query string", () => {
    const url = new URL(
      `/api/v1/guilds/${pathSegment("../../admin/shutdown?")}/config`,
      "https://api.test",
    );
    expect(url.search).toBe("");
    expect(url.pathname.startsWith("/api/v1/guilds/")).toBe(true);
  });

  it("leaves an ordinary snowflake alone", () => {
    expect(pathSegment("1454829495021338842")).toBe("1454829495021338842");
  });

  it("accepts a number as readily as a string", () => {
    expect(pathSegment(123)).toBe("123");
  });
});
