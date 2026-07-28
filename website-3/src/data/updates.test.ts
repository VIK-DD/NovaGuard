import { describe, expect, it } from "vitest";
import {
  RELEASES_PER_PAGE,
  dedupeByCreatedAt,
  diffSplit,
  formatReleaseDate,
  formatReleaseTime,
  newerThan,
  sortNewestFirst,
  type Release,
} from "./updates";

const older: Release = { build: 1, created_at: "2026-06-28T10:00:00+00:00", changes: ["First"] };
const newer: Release = { build: 2, created_at: "2026-07-01T10:00:00+00:00", changes: ["Second"] };
const newest: Release = { build: 3, created_at: "2026-07-20T10:00:00+00:00", changes: ["Third"] };

describe("sortNewestFirst", () => {
  it("puts the most recent release first", () => {
    expect(sortNewestFirst([older, newest, newer]).map((r) => r.build)).toEqual([3, 2, 1]);
  });

  it("does not mutate its input", () => {
    const input = [older, newest];
    sortNewestFirst(input);
    expect(input.map((r) => r.build)).toEqual([1, 3]);
  });
});

describe("dedupeByCreatedAt", () => {
  it("keeps the first entry for a repeated timestamp", () => {
    const duplicate: Release = { build: 99, created_at: older.created_at, changes: ["Dup"] };
    const result = dedupeByCreatedAt([older, duplicate, newer]);
    expect(result.map((r) => r.build)).toEqual([1, 2]);
  });
});

describe("newerThan", () => {
  it("keeps only entries newer than the cutoff", () => {
    expect(newerThan([newest, newer, older], newer.created_at).map((r) => r.build)).toEqual([3]);
  });

  it("returns nothing when every entry is at or below the cutoff", () => {
    expect(newerThan([older, newer], newest.created_at)).toEqual([]);
  });

  it("returns nothing for an unparsable cutoff", () => {
    expect(newerThan([newest], "not-a-date")).toEqual([]);
  });

  it("returns its results newest first", () => {
    expect(newerThan([newer, newest], older.created_at).map((r) => r.build)).toEqual([3, 2]);
  });
});

describe("diffSplit", () => {
  it("splits the bar proportionally", () => {
    expect(diffSplit({ build: 1, created_at: "x", added_lines: 75, removed_lines: 25 })).toEqual({
      added: 75,
      removed: 25,
      addedPercent: 75,
    });
  });

  it("reports zero width when a release has no diff stats", () => {
    expect(diffSplit({ build: 1, created_at: "x" })).toEqual({
      added: 0,
      removed: 0,
      addedPercent: 0,
    });
  });
});

describe("formatReleaseDate", () => {
  it("renders a readable date", () => {
    expect(formatReleaseDate("2026-07-24T01:28:56+00:00")).toBe("24 July 2026");
  });

  it("passes through an unparsable value", () => {
    expect(formatReleaseDate("not-a-date")).toBe("not-a-date");
  });
});

describe("formatReleaseTime", () => {
  it("renders an evening UTC update in Romania summer time", () => {
    expect(formatReleaseTime("2026-07-26T20:43:18.956521+00:00")).toBe("11:43 PM");
  });

  it("renders a morning UTC update in Romania summer time", () => {
    expect(formatReleaseTime("2026-07-26T05:07:00+00:00")).toBe("8:07 AM");
  });

  it("uses AM for after-midnight Romania releases", () => {
    expect(formatReleaseTime("2026-07-28T00:41:00+00:00")).toBe("3:41 AM");
  });

  it("renders noon UTC as afternoon in Romania", () => {
    expect(formatReleaseTime("2026-07-26T12:00:00+00:00")).toBe("3:00 PM");
  });

  it("returns nothing for an unparsable value so the row can omit it", () => {
    expect(formatReleaseTime("not-a-date")).toBe("");
  });

  it("still resolves a non-UTC offset in Romania time", () => {
    expect(formatReleaseTime("2026-07-26T23:30:00+04:00")).toBe("10:30 PM");
  });
});

describe("timezone pinning", () => {
  // Rendered on the build machine for static pages and in the browser for the
  // live tail: an unpinned zone would let those two disagree about the day.
  it("moves late-evening UTC releases onto the Romania calendar day", () => {
    expect(formatReleaseDate("2026-07-26T23:50:00+00:00")).toBe("27 July 2026");
  });

  it("keeps an early-morning UTC release on its own date", () => {
    expect(formatReleaseDate("2026-07-26T00:10:00+00:00")).toBe("26 July 2026");
  });
});

describe("page size", () => {
  it("is six", () => {
    expect(RELEASES_PER_PAGE).toBe(6);
  });
});
