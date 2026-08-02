import { describe, expect, it } from "vitest";
import { isValidEntry, shouldReplaceArchive } from "./sync-updates-archive.mjs";

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
