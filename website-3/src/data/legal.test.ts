import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  LEGAL_COPYRIGHT_START_YEAR,
  LEGAL_EFFECTIVE_DATE,
  LEGAL_INFRASTRUCTURE,
  LEGAL_OPERATOR,
  MOLDOVA_AUTHORITY,
} from "./legal";

describe("public legal identity", () => {
  it("contains the operator-confirmed identity and infrastructure", () => {
    expect(LEGAL_EFFECTIVE_DATE).toBe("August 27, 2026");
    expect(LEGAL_OPERATOR).toEqual({
      name: "Breabin Victor",
      contactAddress: "support@novaguard.fun",
      privacyEmail: "support@novaguard.fun",
      country: "Republic of Moldova",
    });
    expect(LEGAL_INFRASTRUCTURE).toEqual({
      hostingProvider: "Oracle Cloud Infrastructure",
      hostingRegion: "Germany",
      backupProvider: "Google Drive",
      backupLocation: "Google's global infrastructure",
    });
  });

  it("publishes one private contact and the competent Moldovan authority", () => {
    expect(LEGAL_OPERATOR.privacyEmail).toBe(LEGAL_OPERATOR.contactAddress);
    expect(MOLDOVA_AUTHORITY.name).toContain("CNPDCP");
    expect(MOLDOVA_AUTHORITY.href).toMatch(/^https:\/\/datepersonale\.md\//);
    expect(MOLDOVA_AUTHORITY.email).toBe("centru@datepersonale.md");
  });

  it("shows a copyright notice that widens with the years on its own", () => {
    // A hardcoded end year quietly goes stale every January. The site rebuilds
    // hourly, so deriving it at build time keeps the notice honest.
    const footer = readFileSync(resolve(process.cwd(), "src/components/Footer.astro"), "utf8");

    expect(LEGAL_COPYRIGHT_START_YEAR).toBe(2019);
    expect(footer).toContain("LEGAL_COPYRIGHT_START_YEAR");
    expect(footer).toContain("getFullYear()");
    expect(footer).toContain("&copy;");
  });

  it("keeps the publishing name distinct from its creator-name credits", () => {
    const root = resolve(process.cwd(), "..");
    const license = readFileSync(resolve(root, "LICENSE"), "utf8");
    const notice = readFileSync(resolve(root, "NOTICE"), "utf8");
    const readme = readFileSync(resolve(root, "README.md"), "utf8");
    const footer = readFileSync(resolve(process.cwd(), "src/components/Footer.astro"), "utf8");

    for (const document of [license, notice, readme, footer]) {
      expect(document).toContain("VIK-DD");
    }
    expect(notice).toContain("Breabin Victor");
    expect(notice).toContain("same person");
    expect(readme).toContain("VIK &amp; CloudMedia creator names");
    expect(footer).toContain("VIK &amp; CloudMedia names");
  });

  it("keeps privacy and terms wired to the shared legal identity", () => {
    const privacy = readFileSync(resolve(process.cwd(), "src/pages/privacy.astro"), "utf8");
    const terms = readFileSync(resolve(process.cwd(), "src/pages/terms.astro"), "utf8");

    for (const page of [privacy, terms]) {
      expect(page).toContain("LEGAL_OPERATOR");
      expect(page).not.toContain("VIK & CloudMedia");
      expect(page).not.toContain("self-hosted Discord bot");
    }
    expect(privacy).toContain("PRIVACY_EFFECTIVE_DATE");
    expect(terms).toContain("LEGAL_EFFECTIVE_DATE");
    expect(privacy).toContain("has applied since August 23, 2026");
    expect(privacy).not.toContain("enters into force on August 23, 2026");
    expect(privacy).toContain("two additional months");
    expect(privacy).toContain("within the first month");
    expect(privacy).toContain('id="your-choices"');
    expect(privacy.indexOf('id="your-choices"')).toBeGreaterThan(privacy.indexOf("05 · Providers"));
  });
});
