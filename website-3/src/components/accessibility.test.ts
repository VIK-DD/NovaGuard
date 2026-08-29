import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("public component accessibility contracts", () => {
  it("keeps the visible theme label inside the accessible name", () => {
    const masthead = readFileSync(resolve(process.cwd(), "src/components/Masthead.astro"), "utf8");

    expect(masthead).toContain("Day edition — switch to light mode");
    expect(masthead).toContain("Night edition — switch to dark mode");
  });

  it("uses list semantics for feature cards instead of an invalid definition list", () => {
    const features = readFileSync(resolve(process.cwd(), "src/components/Features.astro"), "utf8");

    expect(features).toContain("<ol data-reveal-group");
    expect(features).toContain("<li data-reveal-item");
    expect(features).not.toContain("<dl data-reveal-group");
  });
});
