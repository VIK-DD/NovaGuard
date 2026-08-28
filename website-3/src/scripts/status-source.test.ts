import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("status version hydration", () => {
  const page = readFileSync(resolve(process.cwd(), "src/pages/status.astro"), "utf8");
  const runtime = readFileSync(resolve(process.cwd(), "src/scripts/status.ts"), "utf8");

  it("never claims a stale build-time version while the live snapshot loads", () => {
    expect(page).toContain("Checking…");
    expect(`${page}\n${runtime}`).not.toContain("updates-archive.json");
    expect(`${page}\n${runtime}`).not.toContain("PUBLIC_RELEASE");
  });

  it("replaces the pending state with the canonical live release label", () => {
    expect(runtime).toContain("stats.release_label");
    expect(runtime).toContain('set("version", "Unavailable")');
  });
});
