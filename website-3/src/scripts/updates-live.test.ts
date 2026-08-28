import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import type { ReleaseGroup } from "../data/releases";
import { applyStyleScope, syncCurrentVersion, versionCard } from "./updates-live";

describe("style scope on cards built at runtime", () => {
  // Astro scopes a component's CSS with a data-astro-cid-* attribute stamped
  // onto the elements it renders, and the built rule needs it on BOTH sides:
  //   details[data-astro-cid-rp3sgb2s][open] .chevron[data-astro-cid-rp3sgb2s]
  // Nothing built here at runtime receives it, so every scoped rule skipped
  // the newest card — the chevron never turned, the panel never animated, the
  // rows never rose. Only the chevron was obvious enough to notice.

  function accordion(): HTMLElement {
    const root = document.createElement("div");
    root.className = "release-accordion";
    root.setAttribute("data-astro-cid-rp3sgb2s", "");
    return root;
  }

  function group(version: string) {
    return {
      version,
      phase: "stable",
      phaseLabel: "",
      updates: [],
      updateCount: 0,
      significantCount: 0,
      startedAt: null,
      releasedAt: null,
      current: true,
    } as ReleaseGroup;
  }

  it("stamps the scope onto the card and everything inside it", () => {
    const card = versionCard(group("2.6"));

    applyStyleScope(accordion(), card);

    const missing = [card, ...card.querySelectorAll("*")].filter(
      (node) => !node.hasAttribute("data-astro-cid-rp3sgb2s"),
    );
    expect(missing).toEqual([]);
  });

  it("reaches the chevron, which is the part people see", () => {
    const card = versionCard(group("2.6"));

    applyStyleScope(accordion(), card);

    const chevron = card.querySelector(".chevron");
    expect(chevron?.hasAttribute("data-astro-cid-rp3sgb2s")).toBe(true);
  });

  it("does nothing when the page carries no scope attribute", () => {
    // Astro drops the attribute when a component's styles are all global.
    // Inventing one would be worse than leaving the card unstamped.
    const root = document.createElement("div");
    const card = versionCard(group("2.6"));

    expect(() => applyStyleScope(root, card)).not.toThrow();
    expect(card.getAttributeNames().filter((n) => n.startsWith("data-astro-cid-"))).toEqual([]);
  });

  it("ignores data attributes that are not Astro's scope", () => {
    const root = document.createElement("div");
    root.setAttribute("data-release-live", "");
    const card = versionCard(group("2.6"));

    applyStyleScope(root, card);

    expect(card.hasAttribute("data-release-live")).toBe(false);
  });
});

describe("the live feed request", () => {
  const source = readFileSync(
    resolve(process.cwd(), "src/scripts/updates-live.ts"),
    "utf8",
  );

  it("never lets the browser answer it from cache", () => {
    // This request exists to be newer than the page it patches. A Cloudflare
    // Browser Cache TTL of four hours was rewriting the worker's five-minute
    // header on the way out, and a reader who had opened /updates once kept
    // being served that first copy no matter how often they refreshed. The
    // edge cache still absorbs the traffic, so this costs the bot nothing.
    expect(source).toContain('cache: "no-store"');
  });

  it("makes exactly one request, so the guard cannot be sidestepped", () => {
    expect(source.match(/\bfetch\(/g)).toHaveLength(1);
  });
});

function group(
  version: string,
  current: boolean,
  phase = "stable",
  phaseLabel = "",
): ReleaseGroup {
  return {
    version,
    phase,
    phaseLabel,
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
        phase: "stable",
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
  });

  it("labels historical alpha and beta cards, but leaves stable releases clean", () => {
    const alpha = versionCard(group("1.9", false, "alpha", "Alpha"));
    const beta = versionCard(group("2.9", false, "open-beta", "Beta"));
    const current = versionCard(group("3.0", true));

    expect(alpha.querySelector("[data-release-phase-badge]")?.textContent).toBe("Alpha");
    expect(beta.querySelector("[data-release-phase-badge]")?.textContent).toBe("Beta");
    expect(current.hasAttribute("data-current-release")).toBe(true);
    expect(current.querySelector("[data-release-phase-badge]")).toBeNull();
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
    const stat = document.createElement("span");
    stat.dataset.currentReleaseVersion = "";
    stat.textContent = "3.0";
    document.body.append(stat);
    const previous = versionCard(group("3.0", true));
    const latest = versionCard(group("3.1", true));
    previous.open = true;
    previous.dataset.open = "";
    root.append(previous, latest);

    syncCurrentVersion(root, "3.1");

    expect(root.querySelectorAll("[data-current-release]")).toHaveLength(1);
    expect(previous.hasAttribute("data-current-release")).toBe(false);
    expect(latest.hasAttribute("data-current-release")).toBe(true);
    expect(previous.open).toBe(false);
    expect(previous.hasAttribute("data-open")).toBe(false);
    expect(latest.open).toBe(true);
    expect(latest.hasAttribute("data-open")).toBe(true);
    expect(stat.textContent).toBe("3.1");
  });

  it("does not recreate the removed Current status", () => {
    const component = readFileSync(
      resolve(process.cwd(), "src/components/ReleaseAccordion.astro"),
      "utf8",
    );
    const card = versionCard(populatedGroup("2.3", true));

    expect(`${component}\n${card.outerHTML}`).not.toContain("data-current-release-marker");
    expect(card.textContent).not.toContain("Current");
  });

  it("renders the static current version immediately and never asks live stats to override it", () => {
    const page = readFileSync(
      resolve(process.cwd(), "src/pages/updates/[...page].astro"),
      "utf8",
    );

    expect(page).toContain("{release.version}");
    expect(page).not.toContain("&mdash;");
    expect(page).not.toContain("__ngGetLiveStats");
    expect(page).not.toContain("data-release-sync-note");
    expect(page).not.toContain("detailed changelog is syncing");
  });
});
