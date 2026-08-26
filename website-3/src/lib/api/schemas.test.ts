import { describe, expect, it } from "vitest";
import { AuditSchema, DashboardSchema } from "./schemas";

describe("dashboard API schemas", () => {
  it("keeps cursor metadata for audit pagination", () => {
    const parsed = AuditSchema.parse({
      audit: [
        {
          id: 42,
          username: "Victor",
          user_id: "1",
          action: "config_update",
          changes: { log_channel: "2" },
          created_at: "2026-08-11T20:00:00+00:00",
        },
      ],
      next_cursor: 41,
    });

    expect(parsed.audit[0].id).toBe(42);
    expect(parsed.next_cursor).toBe(41);
  });

  it("does not expose instance-wide backup state in a guild contract", () => {
    expect("backup" in DashboardSchema.shape).toBe(false);
  });
});
