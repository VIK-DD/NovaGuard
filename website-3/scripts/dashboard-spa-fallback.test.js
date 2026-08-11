import { describe, expect, it } from "vitest";
import { dashboardShellUrl } from "./dashboard-spa-fallback.mjs";

describe("dashboard development SPA fallback", () => {
  it("serves the dashboard shell for nested client routes", () => {
    expect(dashboardShellUrl("/dashboard/g/1001/settings/music")).toBe("/dashboard/");
  });

  it("preserves a nested route query while rewriting the server request", () => {
    expect(dashboardShellUrl("/dashboard/g/1001/audit?kind=actions")).toBe(
      "/dashboard/?kind=actions",
    );
  });

  it("leaves the shell and unrelated paths alone", () => {
    expect(dashboardShellUrl("/dashboard/")).toBe("/dashboard/");
    expect(dashboardShellUrl("/dashboard-old/g/1001")).toBe("/dashboard-old/g/1001");
    expect(dashboardShellUrl(undefined)).toBeUndefined();
  });
});
