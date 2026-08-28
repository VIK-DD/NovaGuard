import { describe, expect, it } from "vitest";

import { z, ZodError } from "./zod";

describe("CSP-safe Zod configuration", () => {
  it("keeps JIT disabled globally while preserving validation", () => {
    expect(z.config().jitless).toBe(true);

    const schema = z.object({ ready: z.boolean() });
    expect(schema.parse({ ready: true })).toEqual({ ready: true });
    expect(() => schema.parse({ ready: "yes" })).toThrow(ZodError);
  });
});
