import { describe, expect, it } from "vitest";

import { buildMemberNotice, MEMBER_NOTICE_FEATURES } from "./serverAdminNotice";

const email = "privacy@example.test";

describe("server administrator member notice", () => {
  it("offers unique, granular module choices", () => {
    const ids = MEMBER_NOTICE_FEATURES.map((feature) => feature.id);

    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(
      expect.arrayContaining(["moderation", "server-logs", "levels", "economy", "voice", "ai"]),
    );
  });

  it("builds a complete core-only notice without placeholders", () => {
    const notice = buildMemberNotice([], email);

    expect(notice).toContain("Core server management only");
    expect(notice).toContain("None are declared active");
    expect(notice).toContain("/privacy export");
    expect(notice).toContain("/privacy delete");
    expect(notice).toContain(email);
    expect(notice).not.toMatch(/\[(?:replace|insert|add)/i);
  });

  it("includes only the feature details selected by the administrator", () => {
    const notice = buildMemberNotice(["server-logs", "ai"], email);

    expect(notice).toContain("Server Logs, AI-assisted answers (/ask)");
    expect(notice).toContain("Deleted or edited message excerpts");
    expect(notice).toContain("sent to Anthropic");
    expect(notice).not.toContain("keeps virtual balances");
    expect(notice).not.toContain("voice participation time");
  });

  it("ignores unknown and duplicate feature identifiers", () => {
    const notice = buildMemberNotice(["levels", "unknown", "levels"], email);

    expect(notice.match(/\*\*Levels and XP:\*\*/g)).toHaveLength(1);
    expect(notice).not.toContain("unknown");
  });
});
