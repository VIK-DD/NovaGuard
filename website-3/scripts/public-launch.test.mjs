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
