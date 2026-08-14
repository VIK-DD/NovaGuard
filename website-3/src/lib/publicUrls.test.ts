import { describe, expect, it } from "vitest";
import { publicInviteUrl } from "./publicUrls";

describe("publicInviteUrl", () => {
  it("writes the API invitation into static HTML", () => {
    expect(publicInviteUrl("https://api.novaguard.fun/")).toBe(
      "https://api.novaguard.fun/api/v1/invite",
    );
  });

  it("falls back safely when no usable API origin is configured", () => {
    expect(publicInviteUrl("")).toBe("/dashboard/");
    expect(publicInviteUrl("javascript:alert(1)")).toBe("/dashboard/");
    expect(publicInviteUrl("not a URL")).toBe("/dashboard/");
  });
});
