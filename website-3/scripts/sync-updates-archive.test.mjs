import { afterEach, describe, expect, it } from "vitest";
import {
  fallbackNotice,
  isValidEntry,
  normalizePublicEntry,
  shouldReplaceArchive,
} from "./sync-updates-archive.mjs";

const entry = (build, created_at = "2026-08-01T23:21:39+00:00") => ({ build, created_at });

describe("isValidEntry", () => {
  it("accepts a feed entry with a build number and parseable date", () => {
    expect(isValidEntry(entry(38))).toBe(true);
  });

  it("rejects entries without a build, with a bad date, or non-objects", () => {
    expect(isValidEntry({ created_at: "2026-08-01T00:00:00Z" })).toBe(false);
    expect(isValidEntry(entry(3, "not-a-date"))).toBe(false);
    expect(isValidEntry(null)).toBe(false);
    expect(isValidEntry("junk")).toBe(false);
  });
});

describe("shouldReplaceArchive", () => {
  it("accepts a feed that grew or stayed the same size", () => {
    expect(shouldReplaceArchive([entry(1)], [entry(1), entry(2)])).toBe(true);
    expect(shouldReplaceArchive([entry(1)], [entry(1)])).toBe(true);
  });

  it("rejects an empty or shrunken feed — upstream state loss must not shrink the archive", () => {
    expect(shouldReplaceArchive([entry(1), entry(2)], [entry(1)])).toBe(false);
    expect(shouldReplaceArchive([entry(1)], [])).toBe(false);
    expect(shouldReplaceArchive([entry(1)], undefined)).toBe(false);
  });

  it("rejects a feed containing malformed entries", () => {
    expect(shouldReplaceArchive([], [entry(1), { build: "x", created_at: "bad" }])).toBe(false);
  });

  it("treats a missing baked archive as replaceable by any valid feed", () => {
    expect(shouldReplaceArchive(undefined, [entry(1)])).toBe(true);
  });
});

describe("fallbackNotice", () => {
  const wasCI = process.env.GITHUB_ACTIONS;
  afterEach(() => {
    if (wasCI === undefined) delete process.env.GITHUB_ACTIONS;
    else process.env.GITHUB_ACTIONS = wasCI;
  });

  it("says how stale the archive it kept is, and why it kept it", () => {
    delete process.env.GITHUB_ACTIONS;

    const notice = fallbackNotice(57, "feed answered 403");

    expect(notice).toContain("57");
    expect(notice).toContain("feed answered 403");
  });

  it("raises a CI annotation so a silent fallback cannot hide in the log", () => {
    // This is the whole point. The published version number is computed from
    // the baked archive, so a fallback nobody notices ships a site claiming an
    // older release than the bot reports — which readers see as the version
    // flickering from the stale value to the real one on every page load.
    process.env.GITHUB_ACTIONS = "true";

    expect(fallbackNotice(57, "feed answered 403")).toMatch(/^::warning/);
  });

  it("stays a plain line outside CI, where the annotation is just noise", () => {
    delete process.env.GITHUB_ACTIONS;

    expect(fallbackNotice(57, "feed unreachable")).not.toMatch(/^::warning/);
  });
});

describe("normalizePublicEntry", () => {
  it("normalizes the legacy 2.10 value into the official stable 3.0 release", () => {
    expect(
      normalizePublicEntry({
        ...entry(93),
        release: "2.10",
        phase: "open-beta",
        phase_label: "Open Beta",
      }),
    ).toMatchObject({ release: "3.0", phase: "stable", phase_label: "" });
  });

  it("keeps historical beta but shortens its label and public wording", () => {
    expect(
      normalizePublicEntry({
        ...entry(92),
        release: "2.9",
        phase: "open-beta",
        phase_label: "Open Beta",
        highlights: ["Improved commands — same names, smoother behavior: /status"],
      }),
    ).toMatchObject({
      release: "2.9",
      phase: "open-beta",
      phase_label: "Beta",
      highlights: ["Improved commands — same commands, smoother behavior: /status"],
    });
  });

  it("removes an obsolete runtime generation from historical public copy", () => {
    expect(
      normalizePublicEntry({
        ...entry(32),
        release: "1.9",
        changes: ['Initial tracked release for v3.1.0 "Nova"'],
      }).changes,
    ).toEqual(["Initial tracked NovaGuard release"]);
  });
});
