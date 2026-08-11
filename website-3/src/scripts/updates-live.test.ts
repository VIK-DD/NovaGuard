import { beforeEach, describe, expect, it } from "vitest";
import type { ReleaseGroup } from "../data/releases";
import { syncCurrentVersion, versionCard } from "./updates-live";

function group(version: string, current: boolean): ReleaseGroup {
  return {
    version,
    phase: "open-beta",
    phaseLabel: "Open Beta",
    updates: [],
    updateCount: 0,
    significantCount: 0,
    startedAt: null,
    releasedAt: null,
    current,
  };
}

function populatedGroup(version: string, current: boolean): ReleaseGroup {
  return {
    ...group(version, current),
    updates: [
      {
        build: 51,
        created_at: "2026-08-12T00:35:00+00:00",
        highlights: ["Native release card"],
        release: version,
        phase: "open-beta",
        significant: true,
      },
    ],
    updateCount: 1,
    significantCount: 1,
    startedAt: "2026-08-12T00:35:00+00:00",
    releasedAt: "2026-08-12T00:35:00+00:00",
  };
}

describe("live release cards", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    delete document.documentElement.dataset.currentRelease;
  });

  it("styles phase badges through current state, not unconditionally", () => {
    const historic = versionCard(group("2.1", false));
    const current = versionCard(group("2.2", true));

    expect(historic.hasAttribute("data-current-release")).toBe(false);
    expect(current.hasAttribute("data-current-release")).toBe(true);
    expect(historic.querySelector("[data-release-phase-badge]")).not.toBeNull();
    expect(current.querySelector("[data-release-phase-badge]")).not.toBeNull();
  });

  it("builds a complete expandable card for a version added live", () => {
    const current = versionCard(populatedGroup("2.3", true));

    expect(current.open).toBe(true);
    expect(current.hasAttribute("data-open")).toBe(true);
    expect(current.querySelector(".chevron")).not.toBeNull();
    expect(current.querySelector("[data-release-count]")?.textContent).toBe("1 update");
    expect(current.querySelector("[data-release-span]")?.textContent).toBe("12 August 2026");
    expect(current.querySelector(".release-update")?.textContent).toContain("Native release card");
  });

  it("moves the current state when a newer version appears", () => {
    const root = document.createElement("div");
    const note = document.createElement("p");
    note.dataset.releaseSyncNote = "";
    note.hidden = false;
    note.textContent = "Release 2.2 is syncing.";
    document.body.append(note);
    const previous = versionCard(group("2.1", true));
    const latest = versionCard(group("2.2", true));
    previous.open = true;
    previous.dataset.open = "";
    root.append(previous, latest);

    syncCurrentVersion(root, "2.2");

    expect(root.querySelectorAll("[data-current-release]")).toHaveLength(1);
    expect(previous.hasAttribute("data-current-release")).toBe(false);
    expect(latest.hasAttribute("data-current-release")).toBe(true);
    expect(previous.open).toBe(false);
    expect(previous.hasAttribute("data-open")).toBe(false);
    expect(latest.open).toBe(true);
    expect(latest.hasAttribute("data-open")).toBe(true);
    expect(previous.querySelector<HTMLElement>("[data-current-release-marker]")?.hidden).toBe(true);
    expect(latest.querySelector<HTMLElement>("[data-current-release-marker]")?.hidden).toBe(false);
    expect(note.hidden).toBe(true);
    expect(note.textContent).toBe("");
  });
});
