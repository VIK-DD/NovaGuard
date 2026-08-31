import { describe, expect, it } from "vitest";

import {
  auditBuildArtifacts,
  auditResponse,
  isCloudflareChallenge,
  isOurHost,
  worstSeverity,
} from "./security-audit-rules.mjs";

// A response that passes every rule. Each test below starts from this and
// breaks exactly one thing, so a failure names the rule that caught it.
const CLEAN_CSP = [
  "default-src 'self'",
  "base-uri 'none'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "style-src 'self' 'nonce-abc123'",
  "script-src 'self' 'nonce-abc123'",
  "connect-src 'self' https://api.novaguard.fun",
].join("; ");

const clean = (overrides = {}) => ({
  url: "https://novaguard.fun/status",
  status: 200,
  headers: {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "content-security-policy": CLEAN_CSP,
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=()",
    "cache-control": "no-store",
    "content-type": "text/html; charset=utf-8",
  },
  setCookie: [],
  body: "<!doctype html><p>All good.</p>",
  ...overrides,
});

const rules = (findings) => findings.map((f) => f.rule).sort();

const withHeader = (name, value) => {
  const base = clean();
  base.headers[name] = value;
  return base;
};

const withoutHeader = (name) => {
  const base = clean();
  delete base.headers[name];
  return base;
};

describe("host scoping", () => {
  it("claims our own site and api", () => {
    expect(isOurHost("https://novaguard.fun/status")).toBe(true);
    expect(isOurHost("https://api.novaguard.fun/api/v1/stats")).toBe(true);
  });

  it("disowns third-party hosts a crawler wanders into", () => {
    expect(isOurHost("https://discord.com/terms")).toBe(false);
    expect(isOurHost("https://docs.github.com/en")).toBe(false);
  });

  it("rejects lookalike hostnames rather than matching on a substring", () => {
    // Someone else's domain that merely starts with ours.
    expect(isOurHost("https://novaguard.fun.evil.test/")).toBe(false);
    // A subdomain we do not operate. Matching on a suffix would accept this.
    expect(isOurHost("https://evil.novaguard.fun/")).toBe(false);
  });
});

describe("a fully clean response", () => {
  it("produces no findings at all", () => {
    expect(auditResponse(clean())).toEqual([]);
  });
});

describe("required security headers", () => {
  it("flags a missing HSTS header", () => {
    expect(rules(auditResponse(withoutHeader("strict-transport-security")))).toContain(
      "hsts-missing",
    );
  });

  it("flags an HSTS max-age below one year", () => {
    expect(rules(auditResponse(withHeader("strict-transport-security", "max-age=600")))).toContain(
      "hsts-weak",
    );
  });

  it("flags a missing nosniff header", () => {
    expect(rules(auditResponse(withoutHeader("x-content-type-options")))).toContain(
      "content-type-options-missing",
    );
  });

  it("flags a missing referrer policy", () => {
    expect(rules(auditResponse(withoutHeader("referrer-policy")))).toContain(
      "referrer-policy-missing",
    );
  });

  it("flags a missing CSP", () => {
    expect(rules(auditResponse(withoutHeader("content-security-policy")))).toContain("csp-missing");
  });
});

describe("content security policy quality", () => {
  it("flags a directive that has no default-src fallback", () => {
    const csp = CLEAN_CSP.replace("frame-ancestors 'none'; ", "");
    const findings = auditResponse(withHeader("content-security-policy", csp));
    expect(rules(findings)).toContain("csp-no-fallback-directive");
    expect(findings.find((f) => f.rule === "csp-no-fallback-directive").detail).toContain(
      "frame-ancestors",
    );
  });

  it("flags unsafe-inline in script-src", () => {
    const csp = CLEAN_CSP.replace(
      "script-src 'self' 'nonce-abc123'",
      "script-src 'self' 'unsafe-inline'",
    );
    expect(rules(auditResponse(withHeader("content-security-policy", csp)))).toContain("csp-unsafe");
  });

  it("flags unsafe-eval anywhere in the policy", () => {
    const csp = `${CLEAN_CSP} 'unsafe-eval'`;
    expect(rules(auditResponse(withHeader("content-security-policy", csp)))).toContain("csp-unsafe");
  });

  it("flags transformable HTML protected only by script hashes", () => {
    const base = clean();
    base.headers["content-security-policy"] = CLEAN_CSP.replace(
      "script-src 'self' 'nonce-abc123'",
      "script-src 'self' 'sha256-YWJj'",
    );
    base.headers["cache-control"] = "public, max-age=300";

    expect(rules(auditResponse(base))).toContain("hash-csp-transformable");
  });

  it("accepts hash-protected HTML that intermediaries may not transform", () => {
    const base = clean();
    base.headers["content-security-policy"] = CLEAN_CSP.replace(
      "script-src 'self' 'nonce-abc123'",
      "script-src 'self' 'sha256-YWJj'",
    );
    base.headers["cache-control"] = "public, max-age=300, no-transform";

    expect(rules(auditResponse(base))).not.toContain("hash-csp-transformable");
  });
});

describe("cross-origin exposure", () => {
  it("flags a wildcard CORS origin", () => {
    expect(rules(auditResponse(withHeader("access-control-allow-origin", "*")))).toContain(
      "cors-wildcard",
    );
  });

  it("treats wildcard CORS with credentials as the more serious finding", () => {
    const base = clean();
    base.headers["access-control-allow-origin"] = "*";
    base.headers["access-control-allow-credentials"] = "true";
    const finding = auditResponse(base).find((f) => f.rule === "cors-wildcard");
    expect(finding.severity).toBe("high");
  });
});

describe("cookies", () => {
  it("accepts a fully flagged cookie", () => {
    const base = clean();
    base.setCookie = ["ng_gate=abc; Path=/; HttpOnly; Secure; SameSite=Lax"];
    expect(auditResponse(base)).toEqual([]);
  });

  it("flags a cookie without Secure", () => {
    const base = clean();
    base.setCookie = ["ng_gate=abc; Path=/; HttpOnly; SameSite=Lax"];
    expect(rules(auditResponse(base))).toContain("cookie-insecure");
  });

  it("flags a cookie without SameSite", () => {
    const base = clean();
    base.setCookie = ["ng_gate=abc; Path=/; HttpOnly; Secure"];
    expect(rules(auditResponse(base))).toContain("cookie-samesite");
  });

  it("flags SameSite=None explicitly, the alert ZAP raises", () => {
    const base = clean();
    base.setCookie = ["ng_gate=abc; Path=/; HttpOnly; Secure; SameSite=None"];
    expect(rules(auditResponse(base))).toContain("cookie-samesite-none");
  });
});

describe("information disclosure in the body", () => {
  it("flags an RFC1918 address", () => {
    expect(rules(auditResponse(clean({ body: "upstream 10.0.0.7 refused" })))).toContain(
      "private-ip",
    );
  });

  it("flags a loopback address", () => {
    expect(rules(auditResponse(clean({ body: "http://127.0.0.1:8787/" })))).toContain("private-ip");
  });

  it("does not mistake a version string for an IP", () => {
    expect(rules(auditResponse(clean({ body: "version 10.0.0 released" })))).not.toContain(
      "private-ip",
    );
  });

  it("flags a unix timestamp", () => {
    expect(rules(auditResponse(clean({ body: "?t=1755267600" })))).toContain("unix-timestamp");
  });

  it("flags a semantically named unix timestamp in JSON", () => {
    expect(
      rules(auditResponse(clean({ body: '{"expires":1787735000}' }))),
    ).toContain("unix-timestamp");
  });

  it("does not mistake an unexplained third-party edge value for our timestamp", () => {
    expect(
      rules(auditResponse(clean({ body: "edge generated value 1787735000" }))),
    ).not.toContain("unix-timestamp");
  });

  it("flags an inline event handler", () => {
    expect(rules(auditResponse(clean({ body: '<button onclick="go()">x</button>' })))).toContain(
      "inline-event-handler",
    );
  });

  it("flags a published source map reference", () => {
    expect(rules(auditResponse(clean({ body: "//# sourceMappingURL=app.js.map" })))).toContain(
      "source-map-published",
    );
  });

  it("flags an http:// subresource on an https page", () => {
    expect(
      rules(auditResponse(clean({ body: '<script src="http://cdn.example.test/a.js"></script>' }))),
    ).toContain("mixed-content");
  });
});

describe("Cloudflare challenge detection", () => {
  it("recognises the documented cf-mitigated response header", () => {
    expect(isCloudflareChallenge(clean({ headers: { "cf-mitigated": "challenge" } }))).toBe(true);
  });

  it("recognises an interstitial body when an intermediary strips the header", () => {
    expect(
      isCloudflareChallenge(clean({ body: "<script>window._cf_chl_opt={cITimeS:1787735000}</script>" })),
    ).toBe(true);
  });

  it("does not classify an ordinary NovaGuard page as a challenge", () => {
    expect(isCloudflareChallenge(clean())).toBe(false);
  });
});

describe("caching of pages that sit behind authentication", () => {
  // `public` invites a shared cache — a CDN edge, a corporate proxy — to keep
  // a copy of a page only a signed-in visitor should have seen. Which paths
  // are gated is the runner's business; the rule only needs to be told.
  it("flags a public cache directive on a page that required signing in", () => {
    const base = clean({ url: "https://novaguard.fun/commands/", requiresAuth: true });
    base.headers["cache-control"] = "public, max-age=0, must-revalidate";
    expect(rules(auditResponse(base))).toContain("authenticated-public-cache");
  });

  it("accepts a private cache directive on the same page", () => {
    const base = clean({ url: "https://novaguard.fun/commands/", requiresAuth: true });
    base.headers["cache-control"] = "private, max-age=60";
    expect(rules(auditResponse(base))).not.toContain("authenticated-public-cache");
  });

  it("leaves genuinely public pages alone", () => {
    const base = clean({ url: "https://novaguard.fun/", requiresAuth: false });
    base.headers["cache-control"] = "public, max-age=0, must-revalidate";
    expect(rules(auditResponse(base))).not.toContain("authenticated-public-cache");
  });

  it("says nothing when the runner could not determine whether a page is gated", () => {
    const base = clean({ url: "https://novaguard.fun/commands/" });
    base.headers["cache-control"] = "public, max-age=0, must-revalidate";
    expect(rules(auditResponse(base))).not.toContain("authenticated-public-cache");
  });
});

describe("server fingerprinting", () => {
  it("flags x-powered-by", () => {
    expect(rules(auditResponse(withHeader("x-powered-by", "Express")))).toContain("server-banner");
  });

  it("flags a version number in the server header", () => {
    expect(rules(auditResponse(withHeader("server", "nginx/1.25.3")))).toContain("server-banner");
  });

  it("accepts a bare server name", () => {
    expect(rules(auditResponse(withHeader("server", "cloudflare")))).not.toContain("server-banner");
  });
});

describe("build artifacts", () => {
  it("passes a clean build", () => {
    expect(auditBuildArtifacts([{ path: "index.html", content: "<p>hi</p>" }])).toEqual([]);
  });

  it("flags a published environment file", () => {
    const findings = auditBuildArtifacts([{ path: ".env", content: "SECRET=1" }]);
    expect(rules(findings)).toContain("build-forbidden-file");
  });

  it("flags a published source map file", () => {
    const findings = auditBuildArtifacts([{ path: "_astro/app.js.map", content: "{}" }]);
    expect(rules(findings)).toContain("build-forbidden-file");
  });

  it("flags a leftover editor backup", () => {
    const findings = auditBuildArtifacts([{ path: "index.html.bak", content: "x" }]);
    expect(rules(findings)).toContain("build-forbidden-file");
  });

  it("flags a private IP baked into a built file", () => {
    const findings = auditBuildArtifacts([
      { path: "_astro/app.js", content: "const host='192.168.1.10'" },
    ]);
    expect(rules(findings)).toContain("private-ip");
  });
});

describe("severity ranking", () => {
  it("reports the worst severity present", () => {
    expect(worstSeverity([{ severity: "low" }, { severity: "high" }, { severity: "info" }])).toBe(
      "high",
    );
  });

  it("returns null when there is nothing to report", () => {
    expect(worstSeverity([])).toBeNull();
  });
});
