// Pure security-audit rules, with no network or filesystem access, so every
// rule below is directly testable from a synthetic response.
//
// Why this exists: an external scanner run against novaguard.fun follows the
// outbound links in the privacy and terms pages and reports whatever it finds
// on discord.com, github.com and the rest. Those alerts are real, but they are
// not ours to fix, and they drown the handful that would be. These rules only
// ever look at hosts we actually operate.

const OUR_HOSTS = new Set(["novaguard.fun", "www.novaguard.fun", "api.novaguard.fun"]);

const SEVERITY_ORDER = ["info", "low", "medium", "high"];

// Directives that do NOT fall back to default-src. Leaving one out is the same
// as allowing anything for it, which is the alert ZAP raises as 10055-13.
const NO_FALLBACK_DIRECTIVES = ["base-uri", "form-action", "frame-ancestors"];

// Four octets required, so a version string like "10.0.0" cannot match.
const PRIVATE_IP =
  /\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|127\.0\.0\.1)\b/;

// Ten-digit epoch seconds in the 2022-2033 range, but only where surrounding
// syntax identifies the number as a time. Bare ten-digit values are common in
// third-party edge scripts, generated IDs and phone-like content.
const UNIX_TIMESTAMP_CONTEXTS = [
  /[?&](?:t|ts|time|timestamp|expires?|exp)=(1[6-9]\d{8})\b/i,
  /["']?(?:timestamp|unix_(?:time|timestamp)|created_at|updated_at|expires?|exp|iat)["']?\s*[:=]\s*["']?(1[6-9]\d{8})\b/i,
  /data-(?:timestamp|unix-time)\s*=\s*["'](1[6-9]\d{8})\b/i,
];

// A leading space keeps `element.onclick = fn` in bundled JS from matching:
// only an HTML attribute has whitespace in front of it.
const INLINE_EVENT_HANDLER =
  /\son(?:click|load|error|mouseover|mouseout|submit|change|focus|blur|keydown|keyup)\s*=/i;

const SOURCE_MAP_REFERENCE = /sourceMappingURL\s*=/;

const MIXED_CONTENT = /\b(?:src|href)\s*=\s*["']http:\/\//i;

// Deliberately narrow. A loose pattern would fire on minified bundles and the
// audit would stop being believed.
const SECRET_PATTERNS = [
  [/-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----/, "private key block"],
  [/\bAKIA[0-9A-Z]{16}\b/, "AWS access key id"],
  [/\bghp_[A-Za-z0-9]{36}\b/, "GitHub personal access token"],
  [/\bxox[baprs]-[A-Za-z0-9-]{10,}/, "Slack token"],
  [/\bsk-[A-Za-z0-9]{32,}\b/, "API secret key"],
];

const FORBIDDEN_BUILD_FILES = [
  [/(?:^|\/)\.env(?:\.|$)/, "environment file"],
  [/\.map$/, "source map"],
  [/\.(?:bak|orig|swp|tmp)$/, "editor or merge leftover"],
  [/~$/, "editor backup"],
  [/(?:^|\/)\.git(?:\/|$)/, "git metadata"],
  [/(?:^|\/)\.DS_Store$/, "macOS metadata"],
];

// Paths whose responses must never be stored by a shared cache.
const SENSITIVE_PATH = /^\/(?:login|logout|dashboard|app|api)(?:\/|$)/;

/** True only for hosts we operate. Subdomain lookalikes are rejected. */
export function isOurHost(url) {
  try {
    return OUR_HOSTS.has(new URL(url).hostname.toLowerCase());
  } catch {
    return false;
  }
}

/** Detect an interstitial Cloudflare response that replaced the requested page. */
export function isCloudflareChallenge(response) {
  const headers = lowerKeys(response?.headers);
  if ((headers["cf-mitigated"] || "").toLowerCase() === "challenge") return true;
  const body = response?.body || "";
  return /window\._cf_chl_opt\b|<title>\s*just a moment/i.test(body);
}

/** The highest severity present, or null when there is nothing to report. */
export function worstSeverity(findings) {
  let worst = null;
  let rank = -1;
  for (const finding of findings) {
    const index = SEVERITY_ORDER.indexOf(finding.severity);
    if (index > rank) {
      rank = index;
      worst = finding.severity;
    }
  }
  return worst;
}

function lowerKeys(headers) {
  if (!headers) return {};
  if (typeof headers.entries === "function") {
    return Object.fromEntries([...headers.entries()].map(([k, v]) => [k.toLowerCase(), v]));
  }
  return Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
}

function pathOf(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return "/";
  }
}

/**
 * Audit one HTTP response. Returns a list of findings; an empty list means the
 * response is clean by every rule here.
 *
 * @param {{url: string, status: number, headers: object, setCookie?: string[], body?: string}} response
 */
export function auditResponse(response) {
  const { url, status = 200, body = "" } = response;
  const headers = lowerKeys(response.headers);
  const setCookie = response.setCookie || [];
  const findings = [];
  const add = (rule, severity, detail) => findings.push({ rule, severity, url, detail });

  const contentType = headers["content-type"] || "";
  const isHtml = contentType.toLowerCase().includes("text/html");

  // --- Transport ---------------------------------------------------------
  const hsts = headers["strict-transport-security"];
  if (!hsts) {
    add("hsts-missing", "medium", "No Strict-Transport-Security header.");
  } else {
    const maxAge = Number((hsts.match(/max-age\s*=\s*(\d+)/i) || [])[1] || 0);
    if (maxAge < 31536000) {
      add("hsts-weak", "low", `Strict-Transport-Security max-age is ${maxAge}, below one year.`);
    }
  }

  // --- Content sniffing and framing ---------------------------------------
  if ((headers["x-content-type-options"] || "").toLowerCase() !== "nosniff") {
    add("content-type-options-missing", "low", "X-Content-Type-Options is not 'nosniff'.");
  }
  if (!headers["referrer-policy"]) {
    add("referrer-policy-missing", "low", "No Referrer-Policy header.");
  }

  // --- Content Security Policy --------------------------------------------
  const csp = headers["content-security-policy"];
  if (!csp) {
    add("csp-missing", "medium", "No Content-Security-Policy header.");
  } else {
    const policy = csp.toLowerCase();
    const missing = NO_FALLBACK_DIRECTIVES.filter(
      (directive) => !new RegExp(`(?:^|;)\\s*${directive}\\s`, "i").test(csp),
    );
    if (missing.length > 0) {
      add(
        "csp-no-fallback-directive",
        "medium",
        `Missing directives that do not fall back to default-src: ${missing.join(", ")}.`,
      );
    }
    if (!/(?:^|;)\s*default-src\s/i.test(csp)) {
      add("csp-no-default-src", "medium", "No default-src directive.");
    }
    const unsafe = ["'unsafe-inline'", "'unsafe-eval'"].filter((token) => policy.includes(token));
    if (unsafe.length > 0) {
      add("csp-unsafe", "medium", `Policy allows ${unsafe.join(" and ")}.`);
    }
    const hashBasedScriptPolicy =
      /(?:^|;)\s*script-src\s+[^;]*'sha256-[^']+'/i.test(csp) &&
      !/(?:^|;)\s*script-src\s+[^;]*'nonce-[^']+'/i.test(csp);
    const cacheControl = headers["cache-control"] || "";
    if (isHtml && hashBasedScriptPolicy && !/(?:^|,)\s*no-transform\s*(?:,|$)/i.test(cacheControl)) {
      add(
        "hash-csp-transformable",
        "medium",
        "HTML uses a hash-based script policy without Cache-Control: no-transform; an edge rewrite can invalidate its hashes.",
      );
    }
    if (isHtml && !headers["x-frame-options"] && !/(?:^|;)\s*frame-ancestors\s/i.test(csp)) {
      add("framing-unrestricted", "medium", "Neither X-Frame-Options nor frame-ancestors is set.");
    }
  }

  // --- Isolation headers, only meaningful for documents --------------------
  if (isHtml && !headers["cross-origin-opener-policy"]) {
    add("coop-missing", "info", "No Cross-Origin-Opener-Policy on an HTML document.");
  }
  if (isHtml && !headers["permissions-policy"]) {
    add("permissions-policy-missing", "info", "No Permissions-Policy on an HTML document.");
  }

  // --- Cross-origin sharing ------------------------------------------------
  const allowOrigin = headers["access-control-allow-origin"];
  if (allowOrigin === "*") {
    const withCredentials =
      (headers["access-control-allow-credentials"] || "").toLowerCase() === "true";
    add(
      "cors-wildcard",
      withCredentials ? "high" : "medium",
      withCredentials
        ? "Access-Control-Allow-Origin is '*' together with credentials."
        : "Access-Control-Allow-Origin is '*'.",
    );
  }

  // --- Cookies -------------------------------------------------------------
  for (const cookie of setCookie) {
    const name = cookie.split("=")[0].trim();
    const attributes = cookie.toLowerCase();
    if (!attributes.includes("secure")) {
      add("cookie-insecure", "medium", `Cookie '${name}' is missing the Secure attribute.`);
    }
    if (!attributes.includes("httponly")) {
      add("cookie-httponly", "low", `Cookie '${name}' is readable by scripts (no HttpOnly).`);
    }
    if (!/samesite\s*=/.test(attributes)) {
      add("cookie-samesite", "low", `Cookie '${name}' has no SameSite attribute.`);
    } else if (/samesite\s*=\s*none/.test(attributes)) {
      add("cookie-samesite-none", "low", `Cookie '${name}' uses SameSite=None.`);
    }
  }

  // --- Caching of sensitive responses --------------------------------------
  if (SENSITIVE_PATH.test(pathOf(url)) && status === 200) {
    const cacheControl = (headers["cache-control"] || "").toLowerCase();
    if (!cacheControl.includes("no-store")) {
      add(
        "sensitive-cacheable",
        "medium",
        `Response on a sensitive path is not 'no-store' (got '${
          headers["cache-control"] || "nothing"
        }').`,
      );
    }
  }

  // --- Caching of pages that required signing in ---------------------------
  // `requiresAuth` is supplied by the runner, which probes each path without a
  // session first. Left undefined, this rule stays quiet rather than guessing.
  if (response.requiresAuth === true) {
    const cacheControl = (headers["cache-control"] || "").toLowerCase();
    if (/\bpublic\b/.test(cacheControl)) {
      add(
        "authenticated-public-cache",
        "medium",
        `A page behind the gate is marked '${headers["cache-control"]}'. 'public' lets a` +
          " shared cache keep a copy of it.",
      );
    }
  }

  // --- Server fingerprinting -----------------------------------------------
  if (headers["x-powered-by"]) {
    add("server-banner", "info", `X-Powered-By reveals '${headers["x-powered-by"]}'.`);
  }
  if (headers.server && /\d/.test(headers.server)) {
    add("server-banner", "info", `Server header reveals a version: '${headers.server}'.`);
  }

  // --- Response body -------------------------------------------------------
  const privateIp = body.match(PRIVATE_IP);
  if (privateIp) {
    add("private-ip", "medium", `Body exposes an internal address: ${privateIp[0]}.`);
  }
  const timestamp = UNIX_TIMESTAMP_CONTEXTS.map((pattern) => `${url} ${body}`.match(pattern)).find(
    Boolean,
  );
  if (timestamp) {
    add("unix-timestamp", "low", `A unix timestamp is published: ${timestamp[1]}.`);
  }
  if (INLINE_EVENT_HANDLER.test(body)) {
    add("inline-event-handler", "medium", "An inline event handler attribute is present.");
  }
  if (SOURCE_MAP_REFERENCE.test(body)) {
    add("source-map-published", "low", "A sourceMappingURL points at published source maps.");
  }
  if (MIXED_CONTENT.test(body)) {
    add("mixed-content", "medium", "A subresource is referenced over plain http://.");
  }
  for (const [pattern, label] of SECRET_PATTERNS) {
    if (pattern.test(body)) add("secret-exposed", "high", `Body appears to contain a ${label}.`);
  }

  return findings;
}

/**
 * Audit the built output before it is ever served.
 *
 * @param {{path: string, content: string}[]} files
 */
export function auditBuildArtifacts(files) {
  const findings = [];
  for (const file of files) {
    const add = (rule, severity, detail) =>
      findings.push({ rule, severity, url: file.path, detail });

    for (const [pattern, label] of FORBIDDEN_BUILD_FILES) {
      if (pattern.test(file.path)) {
        add("build-forbidden-file", "medium", `Published ${label}.`);
        break;
      }
    }

    const content = file.content || "";
    const privateIp = content.match(PRIVATE_IP);
    if (privateIp) {
      add("private-ip", "medium", `Built file contains an internal address: ${privateIp[0]}.`);
    }
    for (const [pattern, label] of SECRET_PATTERNS) {
      if (pattern.test(content)) {
        add("secret-exposed", "high", `Built file appears to contain a ${label}.`);
      }
    }
  }
  return findings;
}
