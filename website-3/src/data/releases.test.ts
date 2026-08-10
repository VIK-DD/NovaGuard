import { describe, expect, it } from "vitest";

import archive from "./updates-archive.json";
import {
  ALPHA_CUTOFF_ISO,
  BETA_PHASE,
  UPDATES_PER_VERSION,
  alphaSlotSizes,
  assignReleases,
  cleanText,
  currentRelease,
  isSignificant,
  releaseGroups,
} from "./releases";
import type { Release } from "./updates";

const FEATURE = "\u{1F680} Setup wizard upgraded with select menus";
const CHORE = "Tidied internal helpers";

const ALPHA_DAY = (day: number) => `2026-01-${String(day).padStart(2, "0")}T00:00:00+00:00`;
const BETA_DAY = (day: number) => `2026-09-${String(day).padStart(2, "0")}T00:00:00+00:00`;

function entry(build: number, highlights: string[] = [], created_at?: string): Release {
  return { build, highlights, created_at: created_at ?? ALPHA_DAY(Math.min(build, 28)) };
}

function betaEntry(offset: number, highlights: string[] = []): Release {
  return entry(100 + offset, highlights, BETA_DAY(Math.min(offset, 28)));
}

function history(count: number): Release[] {
  return Array.from({ length: count }, (_, index) => entry(index + 1));
}

describe("significance", () => {
  it("counts a feature highlight", () => {
    expect(isSignificant(entry(1, [FEATURE]))).toBe(true);
  });

  it("counts new commands however the engine phrased them", () => {
    // The wording has changed over the engine's life. Matching only one
    // spelling would freeze the version number without anyone noticing.
    for (const text of [
      "New commands ready to try: /filter",
      "Added commands: `!github`, `!ping`",
      "ADDED COMMANDS: /rank",
    ]) {
      expect(isSignificant(entry(1, [text]))).toBe(true);
    }
  });

  it("does not count ordinary work", () => {
    // It is still published - it just must not move the version.
    for (const text of [CHORE, "Fixed a typo in an embed", "Updated documentation"]) {
      expect(isSignificant(entry(1, [text]))).toBe(false);
    }
  });

  it("does not count an update with nothing in it", () => {
    expect(isSignificant(entry(1))).toBe(false);
  });

  it("keeps the feed classification after display text was cleaned", () => {
    expect(isSignificant({ ...entry(1, ["Clean text"]), significant: true })).toBe(true);
    expect(isSignificant({ ...entry(1, [FEATURE]), significant: false })).toBe(false);
  });
});

describe("alpha phase", () => {
  it("spreads history across exactly ten versions", () => {
    const versions = new Set(assignReleases(history(31)).map((item) => item.release));

    expect(versions.size).toBe(10);
    expect(versions.has("1.0")).toBe(true);
    expect(versions.has("1.9")).toBe(true);
  });

  it("keeps every slot within one update of the others", () => {
    for (const total of [0, 1, 9, 10, 31, 38, 47]) {
      const sizes = alphaSlotSizes(total);
      expect(sizes).toHaveLength(10);
      expect(sizes.reduce((sum, size) => sum + size, 0)).toBe(total);
      expect(Math.max(...sizes) - Math.min(...sizes)).toBeLessThanOrEqual(1);
    }
  });

  it("never renumbers history when new updates land", () => {
    // A visitor who read "1.3" yesterday has to find the same updates there
    // tomorrow, which is the whole reason the cutoff is frozen.
    const before = new Map(assignReleases(history(31)).map((i) => [i.build, i.release]));
    const withBeta = assignReleases([
      ...history(31),
      ...Array.from({ length: 20 }, (_, index) => betaEntry(index + 1, [FEATURE])),
    ]);

    for (const item of withBeta.filter((i) => i.phase === "alpha")) {
      expect(item.release).toBe(before.get(item.build));
    }
  });
});

describe("phase boundary", () => {
  it("decides by date, never by build number", () => {
    // Build numbers repeat across engine resets and differ between the bot's
    // archive and this one, so they cannot carry the boundary.
    expect(assignReleases([entry(9999, [FEATURE], ALPHA_DAY(3))])[0].phase).toBe("alpha");
    expect(assignReleases([entry(1, [FEATURE], BETA_DAY(3))])[0].phase).toBe(BETA_PHASE);
  });

  it("keeps two updates that share a build number", () => {
    const stamped = assignReleases([
      entry(5, [FEATURE], ALPHA_DAY(5)),
      entry(5, [FEATURE], BETA_DAY(5)),
    ]);

    expect(stamped).toHaveLength(2);
    expect(stamped.map((item) => item.phase)).toEqual(["alpha", BETA_PHASE]);
  });

  it("orders by date rather than build number", () => {
    const stamped = assignReleases([
      entry(100, [CHORE], ALPHA_DAY(2)),
      entry(1, [CHORE], ALPHA_DAY(1)),
    ]);

    expect(stamped.map((item) => item.build)).toEqual([1, 100]);
  });
});

describe("open beta", () => {
  const beta = (releases: Release[]) =>
    assignReleases(releases).filter((item) => item.phase === BETA_PHASE);

  it("starts at 2.0", () => {
    expect(beta([...history(31), betaEntry(1, [FEATURE])])[0].release).toBe("2.0");
  });

  it("advances after the agreed number of significant updates", () => {
    const releases = [
      ...history(31),
      ...Array.from({ length: UPDATES_PER_VERSION + 1 }, (_, i) => betaEntry(i + 1, [FEATURE])),
    ];
    const stamped = beta(releases);

    expect(stamped.slice(0, UPDATES_PER_VERSION).map((i) => i.release)).toEqual(
      Array(UPDATES_PER_VERSION).fill("2.0"),
    );
    expect(stamped[UPDATES_PER_VERSION].release).toBe("2.1");
  });

  it("lets ordinary work fill a version too", () => {
    // The threshold used to count only feature work, which parked the number
    // for weeks whenever a run of fixes landed. Every published update counts
    // now; significance only decides the "New" marker.
    const releases = [
      ...history(31),
      ...Array.from({ length: 20 }, (_, index) => betaEntry(index + 1, [CHORE])),
    ];

    expect([...new Set(beta(releases).map((item) => item.release))].sort()).toEqual([
      "2.0",
      "2.1",
      "2.2",
      "2.3",
    ]);
  });

  it("still publishes small changes", () => {
    const stamped = beta([...history(31), betaEntry(1, [CHORE])]);

    expect(stamped).toHaveLength(1);
    expect(stamped[0].significant).toBe(false);
  });
});

describe("grouping", () => {
  const releases = [
    ...history(31),
    ...Array.from({ length: 7 }, (_, index) => betaEntry(index + 1, [index % 2 ? FEATURE : CHORE])),
  ];

  it("puts the newest version first and marks it current", () => {
    const groups = releaseGroups(releases);

    expect(groups[0].current).toBe(true);
    expect(groups.slice(1).every((group) => !group.current)).toBe(true);
  });

  it("orders updates inside a version newest first", () => {
    const dates = releaseGroups(releases)[0].updates.map((item) => item.created_at);

    expect(dates).toEqual([...dates].sort().reverse());
  });

  it("places every update in exactly one version", () => {
    const placed = releaseGroups(releases).flatMap((group) => group.updates);

    expect(placed).toHaveLength(releases.length);
  });

  it("names the live version", () => {
    expect(currentRelease(releases).version).toBe(releaseGroups(releases)[0].version);
    expect(currentRelease(releases).phaseLabel).toBe("Open Beta");
  });

  it("survives an empty archive", () => {
    expect(releaseGroups([])).toEqual([]);
    expect(currentRelease([]).version).toBe("2.0");
  });

  it("never reports closed alpha as the current release", () => {
    const alphaOnly = history(31);

    expect(releaseGroups(alphaOnly).every((group) => !group.current)).toBe(true);
    expect(currentRelease(alphaOnly)).toEqual({ version: "2.0", phaseLabel: "Open Beta" });
  });
});

describe("presentation", () => {
  it("strips emoji from everything shown", () => {
    const stamped = assignReleases([entry(1, [FEATURE])]);

    expect(stamped[0].highlights?.[0]).not.toContain("\u{1F680}");
    expect(stamped[0].highlights?.[0]).toContain("Setup wizard upgraded");
  });

  it("drops decoration-only lines instead of leaving blanks", () => {
    const stamped = assignReleases([entry(1, ["\u{1F680}", "", "Real change"])]);

    expect(stamped[0].highlights).toEqual(["Real change"]);
  });

  it("keeps significance after the emoji is stripped", () => {
    // Detection reads the raw text, so cleaning the display must not quietly
    // demote a feature to a chore.
    expect(assignReleases([entry(1, [FEATURE])])[0].significant).toBe(true);
  });

  it("never empties a real sentence", () => {
    expect(cleanText("\u{1F680} Backups now upload")).toBe("Backups now upload");
  });
});

describe("the real archive", () => {
  // Not a snapshot in time: the archive keeps growing as the site deploys,
  // and real entries have already crossed ALPHA_CUTOFF_ISO into open beta.
  // These assert the invariants that hold regardless of when the suite
  // runs, not a count frozen at whatever the archive happened to contain
  // when this test was written.
  const releases = archive as Release[];

  it("keeps the ten alpha versions exactly as historical entries were split", () => {
    const alpha = releaseGroups(releases).filter((group) => group.phase === "alpha");

    expect(alpha).toHaveLength(10);
    expect([...alpha].map((group) => group.version).sort()).toEqual(
      ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9"].sort(),
    );
  });

  it("loses no update to grouping", () => {
    const placed = releaseGroups(releases).flatMap((group) => group.updates);

    expect(placed).toHaveLength(releases.length);
  });

  it("never puts a pre-cutoff update in open beta or a post-cutoff update in alpha", () => {
    for (const item of assignReleases(releases)) {
      const expectedPhase = item.created_at < ALPHA_CUTOFF_ISO ? "alpha" : BETA_PHASE;
      expect(item.phase).toBe(expectedPhase);
    }
  });

  it("finds real significant updates in it", () => {
    // A guard against the detector matching nothing real: if this ever hits
    // zero, open beta would sit on 2.0 forever.
    expect(releases.filter(isSignificant).length).toBeGreaterThan(0);
  });
});
