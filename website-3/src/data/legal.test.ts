import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  LEGAL_EFFECTIVE_DATE,
  LEGAL_INFRASTRUCTURE,
  LEGAL_OPERATOR,
  MOLDOVA_AUTHORITY,
} from "./legal";

describe("public legal identity", () => {
  it("contains the operator-confirmed identity and infrastructure", () => {
    expect(LEGAL_EFFECTIVE_DATE).toBe("August 12, 2026");
    expect(LEGAL_OPERATOR).toEqual({
      name: "Breabin Victor",
      contactAddress: "breabinvc@gmail.com",
      privacyEmail: "breabinvc@gmail.com",
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
    expect(privacy).toContain('id="your-choices"');
    expect(privacy.indexOf('id="your-choices"')).toBeGreaterThan(privacy.indexOf("05 · Providers"));
  });
});
