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

  it("documents all persistent browser-storage keys", () => {
    expect(BROWSER_STORAGE.map((row) => row.name)).toEqual([
      "ng-theme",
      "ng-maintenance-theme",
      "ng-status-snapshot-v1",
    ]);
  });

  it("stays aligned with the cookie names implemented by the API and edge worker", () => {
    const api = readFileSync(resolve(process.cwd(), "../core/webserver.py"), "utf8");
    const worker = readFileSync(resolve(process.cwd(), "worker/index.js"), "utf8");
    const legacyPolicy = readFileSync(resolve(process.cwd(), "../docs/privacy.html"), "utf8");
    const runtime = `${api}\n${worker}`;

    for (const cookie of ESSENTIAL_COOKIES) {
      expect(runtime).toContain(`"${cookie.name}"`);
      expect(legacyPolicy).toContain(`<code>${cookie.name}</code>`);
    }
  });
});
