import { describe, expect, it } from "vitest";
import {
  PUBLIC_LAUNCH_AT,
  PUBLIC_LAUNCH_AT_MS,
  PUBLIC_LAUNCH_PATH,
  hasPublicLaunchPassed,
} from "../launch-config.js";
import {
  countdownBundleUsesLaunchDate,
  injectCountdownRedirect,
  localizeFontImport,
  stampAssetVersions,
} from "./public-launch.mjs";

describe("public launch configuration", () => {
  it("uses midnight in Chisinau as one shared launch instant", () => {
    expect(PUBLIC_LAUNCH_AT).toBe("2026-09-01T00:00:00+03:00");
    expect(new Date(PUBLIC_LAUNCH_AT_MS).toISOString()).toBe("2026-08-31T21:00:00.000Z");
    expect(PUBLIC_LAUNCH_PATH).toBe("/home/");
    expect(hasPublicLaunchPassed(PUBLIC_LAUNCH_AT_MS - 1)).toBe(false);
    expect(hasPublicLaunchPassed(PUBLIC_LAUNCH_AT_MS)).toBe(true);
  });

  it("injects an idempotent redirect into an already-open countdown page", () => {
    const original = "<!doctype html><html><head><title>Countdown</title></head><body></body></html>";
    const once = injectCountdownRedirect(original);
    const twice = injectCountdownRedirect(once);

    expect(once).toContain("data-novaguard-public-launch");
    expect(once).toContain(PUBLIC_LAUNCH_AT);
    expect(once).toContain(PUBLIC_LAUNCH_PATH);
    expect(once).toContain("window.location.replace");
    expect(twice).toBe(once);
  });

  it("detects a countdown bundle that drifted away from the launch date", () => {
    expect(countdownBundleUsesLaunchDate(`const date=${JSON.stringify(PUBLIC_LAUNCH_AT)}`)).toBe(true);
    expect(countdownBundleUsesLaunchDate('const date="2026-09-02T00:00:00+03:00"')).toBe(false);
  });

  it("rejects malformed countdown HTML instead of silently skipping redirect", () => {
    expect(() => injectCountdownRedirect("<html><body>No head</body></html>")).toThrow(
      "does not contain </head>",
    );
  });
});

describe("localizeFontImport", () => {
  // The real import the Coming Soon bundle ships with. The weights are what
  // matter: a Google Fonts URL separates them with semicolons, so anything
  // that stops at the first ";" cuts the URL in half.
  const REAL_IMPORT =
    '@import"https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@500;600;700;800&display=swap";';
  const REST = ":root{color-scheme:dark;--background: #0a0a0a}body{margin:0}";
  const FACES = '@font-face{font-family:Manrope;src:url("./manrope.woff2") format("woff2")}';

  it("swaps the remote import for local faces and keeps the rest of the sheet", () => {
    expect(localizeFontImport(REAL_IMPORT + REST, FACES)).toBe(FACES + REST);
  });

  it("consumes the whole URL even though its weights contain semicolons", () => {
    // The bug this test exists for: `[^;]+;` matched only as far as "wght@400;"
    // and left "500&family=...&display=swap\";" behind. The stray closing quote
    // then opened a CSS string that swallowed every rule after it, so the page
    // shipped with two @font-face rules and no layout at all.
    const result = localizeFontImport(REAL_IMPORT + REST, FACES);

    expect(result).not.toContain("&family=");
    expect(result).not.toContain("display=swap");
    expect(result).toContain(":root{color-scheme:dark");
  });

  it("leaves no unbalanced quote for the CSS parser to choke on", () => {
    const quotes = (localizeFontImport(REAL_IMPORT + REST, FACES).match(/"/g) ?? []).length;

    expect(quotes % 2).toBe(0);
  });

  it("handles single quotes and whitespace around the import", () => {
    const single = "@import 'https://fonts.googleapis.com/css2?family=X:wght@1;2&display=swap' ;";

    expect(localizeFontImport(single + REST, FACES)).toBe(FACES + REST);
  });

  it("takes the import wherever it sits, not only at the very start", () => {
    const withCharset = '@charset "utf-8";' + REAL_IMPORT + REST;

    expect(localizeFontImport(withCharset, FACES)).toBe('@charset "utf-8";' + FACES + REST);
  });

  it("refuses a sheet whose remote import it could not remove", () => {
    // The url() form is not what the bundle ships, so it is not matched. Left
    // unnoticed it would reach the CSP as a blocked request and drop the page
    // to system fonts; silently returning the sheet unchanged is how a broken
    // artifact shipped once already, so this fails the build instead.
    const unquoted = "@import url(https://fonts.googleapis.com/css2?family=X&display=swap);";

    expect(() => localizeFontImport(unquoted + REST, FACES)).toThrow("fonts.googleapis.com");
  });

  it("leaves a sheet that never referenced Google Fonts alone", () => {
    expect(localizeFontImport(REST, FACES)).toBe(REST);
  });
});

describe("stampAssetVersions", () => {
  // soft-launch rewrites an asset's contents but keeps its name, and the edge
  // serves those names as `immutable` for a year. Without a version token a
  // browser that already holds the old copy never asks for the new one, so a
  // fixed stylesheet reaches new visitors only. The page HTML revalidates on
  // every load, which is what makes stamping it work.
  const HTML =
    '<head><link rel="stylesheet" crossorigin href="./assets/index-AbC123.css">' +
    '<link rel="stylesheet" href="./overrides.css"></head>';

  it("adds the version to the asset it was given", () => {
    expect(stampAssetVersions(HTML, { "index-AbC123.css": "9f8e7d6c" })).toContain(
      'href="./assets/index-AbC123.css?v=9f8e7d6c"',
    );
  });

  it("leaves assets it was not given untouched", () => {
    const out = stampAssetVersions(HTML, { "index-AbC123.css": "9f8e7d6c" });

    expect(out).toContain('href="./overrides.css"');
    expect(out).not.toContain("overrides.css?v=");
  });

  it("does not stamp the same asset twice", () => {
    const once = stampAssetVersions(HTML, { "index-AbC123.css": "9f8e7d6c" });
    const twice = stampAssetVersions(once, { "index-AbC123.css": "9f8e7d6c" });

    expect(twice).toBe(once);
  });

  it("keeps the rest of the document byte for byte", () => {
    const out = stampAssetVersions(HTML, { "index-AbC123.css": "9f8e7d6c" });

    expect(out.replace("?v=9f8e7d6c", "")).toBe(HTML);
  });

  it("is a no-op when there is nothing to stamp", () => {
    expect(stampAssetVersions(HTML, {})).toBe(HTML);
  });
});
