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

  it("moves the current state when a newer version appears", () => {
    const root = document.createElement("div");
    const previous = versionCard(group("2.1", true));
    const latest = versionCard(group("2.2", true));
    root.append(previous, latest);

    syncCurrentVersion(root, "2.2");

    expect(root.querySelectorAll("[data-current-release]")).toHaveLength(1);
    expect(previous.hasAttribute("data-current-release")).toBe(false);
    expect(latest.hasAttribute("data-current-release")).toBe(true);
    expect(previous.querySelector<HTMLElement>("[data-current-release-marker]")?.hidden).toBe(true);
    expect(latest.querySelector<HTMLElement>("[data-current-release-marker]")?.hidden).toBe(false);
  });
});
