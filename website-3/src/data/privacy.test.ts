import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  BROWSER_STORAGE,
  DATA_CATEGORIES,
  ESSENTIAL_COOKIES,
  RETENTION_ROWS,
  THIRD_PARTIES,
} from "./privacy";

describe("privacy inventory", () => {
  it("documents every production cookie and its exact lifetime", () => {
    expect(ESSENTIAL_COOKIES.map(({ name, lifetime }) => ({ name, lifetime }))).toEqual([
      { name: "ng_state", lifetime: "10 minutes" },
      { name: "ng_session", lifetime: "7 days, or until logout" },
      { name: "ng_gate", lifetime: "2 hours" },
      { name: "ng_preview", lifetime: "12 hours at most" },
    ]);
  });

  it("covers message processing, the audit trail and optional AI transfer", () => {
    const inventory = JSON.stringify({ DATA_CATEGORIES, RETENTION_ROWS, THIRD_PARTIES });
    expect(inventory).toContain("Message content");
    expect(inventory).toContain("90 days");
    expect(inventory).toContain("Anthropic");
    expect(inventory).toContain("/ask");
  });

  it("discloses the Cloudflare analytics beacon and conditional security cookie", () => {
    const inventory = JSON.stringify({ DATA_CATEGORIES, THIRD_PARTIES });
    expect(inventory).toContain("Cloudflare Web Analytics");
    expect(inventory).toContain("page-performance");
    expect(inventory).toContain("__cf_bm");
    expect(inventory).toContain("30 minutes");
  });

  it("publishes a basis for every data category", () => {
    for (const category of DATA_CATEGORIES) {
      expect(category.basis.length).toBeGreaterThan(20);
    }
  });

  it("discloses production hosting, encrypted backups and every enforced retention", () => {
    const inventory = JSON.stringify({ RETENTION_ROWS, THIRD_PARTIES });
    for (const disclosure of [
      "Oracle Cloud Infrastructure",
      "Germany",
      "Google Drive",
      "encrypted",
      "180 days",
      "365 days",
      "90 days",
      "13 months",
      "30 days",
      "deletion tokens",
    ]) {
      expect(inventory).toContain(disclosure);
    }
  });

  it("discloses that a removed server keeps its data for a bounded window", () => {
    // The bot waits PRIVACY_GUILD_GRACE_DAYS before erasing a server it was
    // removed from. A policy that omits the window contradicts the code.
    const inventory = JSON.stringify(RETENTION_ROWS);
    expect(inventory).toContain("after NovaGuard is removed");
    expect(inventory).toContain("Erased 30 days after removal");
    expect(inventory).toContain("adding NovaGuard back");
  });

  it("documents all persistent browser-storage keys", () => {
    expect(BROWSER_STORAGE.map((row) => row.name)).toEqual([
      "ng-theme",
      "ng-maintenance-theme",
    ]);
  });

  it("does not persist public status data in browser storage", () => {
    const base = readFileSync(resolve(process.cwd(), "src/layouts/Base.astro"), "utf8");
    const status = readFileSync(resolve(process.cwd(), "src/scripts/status.ts"), "utf8");

    expect(`${base}\n${status}`).not.toContain("ng-status-snapshot-v1");
  });

  it("stays aligned with the cookie names implemented by the API and edge worker", () => {
    const api = readFileSync(resolve(process.cwd(), "../core/webserver.py"), "utf8");
    const worker = readFileSync(resolve(process.cwd(), "worker/index.js"), "utf8");
    const runtime = `${api}\n${worker}`;

    for (const cookie of ESSENTIAL_COOKIES) {
      expect(runtime).toContain(`"${cookie.name}"`);
    }
  });

  it("keeps one canonical privacy and terms source", () => {
    const legacyPrivacy = readFileSync(resolve(process.cwd(), "../docs/privacy.html"), "utf8");
    const legacyTerms = readFileSync(resolve(process.cwd(), "../docs/terms.html"), "utf8");

    expect(legacyPrivacy).toContain('rel="canonical" href="https://novaguard.fun/privacy"');
    expect(legacyPrivacy).toContain("url=https://novaguard.fun/privacy");
    expect(legacyTerms).toContain('rel="canonical" href="https://novaguard.fun/terms"');
    expect(legacyTerms).toContain("url=https://novaguard.fun/terms");
    expect(legacyPrivacy).not.toContain("third-party analytics");
    expect(legacyTerms).not.toContain("Disclaimer and Liability");
  });
});
