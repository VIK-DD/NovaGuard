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

  it("keeps the sanitized off-site backup health contract", () => {
    const parsed = DashboardSchema.shape.backup.parse({
      available: true,
      latest_name: "novaguard-full.zip",
      latest_size: 1024,
      latest_size_text: "1 KB",
      latest_at: "2026-08-11T20:00:00+00:00",
      ok: true,
      warnings: [],
      errors: [],
      offsite: {
        configured: true,
        matches_backup: true,
        latest_ok: true,
        uploaded_at: "2026-08-11T20:01:00+00:00",
        check_ok: true,
        checked_at: "2026-08-11T20:02:00+00:00",
      },
    });

    expect(parsed.offsite.matches_backup).toBe(true);
    expect(parsed.offsite.check_ok).toBe(true);
  });
});
