import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("status version hydration", () => {
  const page = readFileSync(resolve(process.cwd(), "src/pages/status.astro"), "utf8");
  const runtime = readFileSync(resolve(process.cwd(), "src/scripts/status.ts"), "utf8");

  it("starts pending but carries the official floor for runtime normalization", () => {
    expect(page).toContain("Checking…");
    expect(page).toContain("updates-archive.json");
    expect(page).toContain("data-release-floor");
    expect(`${page}\n${runtime}`).not.toContain("PUBLIC_RELEASE");
  });

  it("replaces the pending state with the canonical version only", () => {
    expect(runtime).toContain("newestPublicVersion(releaseFloor, stats.version)");
    expect(runtime).not.toContain("Open Beta");
    expect(runtime).toContain('set("version", "Unavailable")');
  });
});
