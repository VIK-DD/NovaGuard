import { describe, expect, it } from "vitest";
import { MeResponseSchema, OkResponseSchema } from "./authSchemas";

describe("dashboard auth response parsers", () => {
  it("accepts the minimal session response needed to boot the dashboard", () => {
    expect(
      MeResponseSchema.parse({ user: { id: "42", username: "Victor", avatar: null } }),
    ).toEqual({ user: { id: "42", username: "Victor", avatar: null } });
  });

  it("rejects malformed session and operation responses", () => {
    expect(() => MeResponseSchema.parse({ user: { id: 42 } })).toThrow("Invalid session user response.");
    expect(() => OkResponseSchema.parse({ ok: "yes" })).toThrow("Invalid operation response.");
  });
});
