// Deliberately NOT "ng_session": that name belongs to the bot API's login
// cookie on api.novaguard.fun. They live on different hosts today, but a
// future `Domain=.novaguard.fun` on either would make them clobber each other.
const SESSION_COOKIE = "ng_gate";
const SESSION_TTL_SECONDS = 60 * 60 * 2;
const PREVIEW_COOKIE = "ng_preview";
const PREVIEW_TTL_SECONDS = 60 * 60 * 12;
// The `__Host-` prefix is load-bearing here, not decoration. The check below is
// a double-submit comparison, so it is only worth anything while this origin is
// the only thing that can write the cookie. Without the prefix any subdomain of
// novaguard.fun could set `ng_csrf` for the parent domain and then post a form
// carrying the value it had just chosen — the exact attack the token exists to
// stop. The prefix makes the browser refuse a cookie that carries a Domain, or
// arrives without Secure, or is scoped to anything but `/`.
const CSRF_COOKIE = "__Host-ng_csrf";
const CSRF_FIELD = "csrf_token";
const CSRF_TTL_SECONDS = 60 * 60 * 4;
const CSRF_TOKEN_PATTERN = /^[A-Za-z0-9_-]{22,86}$/;
const SAFE_NEXT_ORIGIN = "https://novaguard.invalid";
const DEFAULT_STATUS_API_BASE = "https://api.novaguard.fun/api/v1";
const STATUS_SNAPSHOT_TIMEOUT_MS = 8000;
const UPDATES_FEED_TIMEOUT_MS = 8000;
const MAINTENANCE_VALUES = new Set(["1", "true", "on", "enabled", "protected", "private"]);
const SECURITY_SCAN_OPEN_VALUES = new Set(["1", "true", "on", "enabled", "open"]);
const MAINTENANCE_FRESH_MS = 30_000;
const MAINTENANCE_GRACE_MS = 120_000;
const MAINTENANCE_TIMEOUT_MS = 2_500;
const MAINTENANCE_EDGE_CACHE_HEADERS = {
  "Cache-Control": "public, max-age=30, stale-while-revalidate=120",
  "X-Content-Type-Options": "nosniff",
};
const encoder = new TextEncoder();
let lastGoodStatusSnapshot = null;
// Mirrors lastGoodStatusSnapshot: the edge cache is shared between isolates but
// missing in tests and on a cold start, so each isolate keeps its own copy.
let lastMaintenanceState = null;
const STATUS_CLIENT_HEADERS = {
  "Cache-Control": "no-store, private",
  "CDN-Cache-Control": "no-store",
  "Cloudflare-CDN-Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};
const STATUS_EDGE_CACHE_HEADERS = {
  "Cache-Control": "public, max-age=30, stale-while-revalidate=120",
  "X-Content-Type-Options": "nosniff",
};
const SECURITY_HEADERS = {
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Resource-Policy": "same-site",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "Referrer-Policy": "no-referrer",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "X-XSS-Protection": "0",
};

function contentSecurityPolicy(nonce = "") {
  const nonceSource = nonce ? ` 'nonce-${nonce}'` : "";
  return [
    "default-src 'self'",
    "base-uri 'none'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "img-src 'self' data: https://cdn.discordapp.com https://*.discordapp.com https://*.discordapp.net",
    "font-src 'self'",
    `style-src 'self'${nonceSource}`,
    "style-src-attr 'none'",
    `script-src 'self'${nonceSource}`,
    "connect-src 'self' https://api.novaguard.fun",
  ].join("; ");
}

function createCspNonce() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

class NonceElements {
  constructor(nonce) {
    this.nonce = nonce;
  }

  element(element) {
    element.setAttribute("nonce", this.nonce);
  }
}

function errorMessage(error) {
  const message = error instanceof Error ? error.message : "Unknown error";
  return message.replace(/\s+/g, " ").slice(0, 240);
}

function hardenResponse(response) {
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    if (!headers.has(name)) headers.set(name, value);
  }
  const isHtml = headers.get("Content-Type")?.toLowerCase().includes("text/html");
  const nonce = isHtml ? createCspNonce() : "";
  headers.set("Content-Security-Policy", contentSecurityPolicy(nonce));
  if (isHtml) headers.delete("Content-Length");

  const hardened = new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });

  // The site keeps a few pre-paint scripts inline so the saved theme never
  // flashes. A fresh response nonce permits only those exact elements instead
  // of allowing arbitrary inline code or styles across the whole document.
  if (!isHtml || typeof HTMLRewriter !== "function") return hardened;
  return new HTMLRewriter()
    .on("script", new NonceElements(nonce))
    .on("style", new NonceElements(nonce))
    .transform(hardened);
}

function logWorkerEvent(level, event, details = {}) {
  // Never pass request bodies, cookies, full URLs or env values here. The
  // password and preview-code endpoints deliberately log outcomes only.
  const payload = JSON.stringify({ event, ...details });
  if (level === "error") console.error(payload);
  else if (level === "warn") console.warn(payload);
  else console.log(payload);
}

function base64UrlEncode(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlDecode(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function importSigningKey(secret) {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

async function createSession(secret) {
  const issuedAt = Math.floor(Date.now() / 1000);
  const payload = base64UrlEncode(
    encoder.encode(JSON.stringify({ iat: issuedAt, exp: issuedAt + SESSION_TTL_SECONDS })),
  );
  const key = await importSigningKey(secret);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return `${payload}.${base64UrlEncode(new Uint8Array(signature))}`;
}

async function isValidSession(value, secret) {
  if (!value || !secret) return false;
  const [payload, signature] = value.split(".");
  if (!payload || !signature) return false;

  try {
    const key = await importSigningKey(secret);
    const valid = await crypto.subtle.verify(
      "HMAC",
      key,
      base64UrlDecode(signature),
      encoder.encode(payload),
    );
    if (!valid) return false;

    const session = JSON.parse(new TextDecoder().decode(base64UrlDecode(payload)));
    const now = Math.floor(Date.now() / 1000);
    return (
      Number.isFinite(session.iat) &&
      Number.isFinite(session.exp) &&
      session.iat <= now + 60 &&
      session.exp > now &&
      session.exp - session.iat <= SESSION_TTL_SECONDS &&
      now - session.iat < SESSION_TTL_SECONDS
    );
  } catch {
    return false;
  }
}

function readCookie(request, name) {
  const header = request.headers.get("Cookie") || "";
  for (const part of header.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return value.join("=");
  }
  return null;
}

function safeNext(value) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return "/dashboard/";
  }

  try {
    // A backslash is treated as a slash in special-scheme URLs. Checking only
    // for `//` would therefore allow `/\\outside.example` to turn into an
    // external redirect when it is passed to `new URL` below.
    const destination = new URL(value, SAFE_NEXT_ORIGIN);
    if (destination.origin !== SAFE_NEXT_ORIGIN) return "/dashboard/";
    return `${destination.pathname}${destination.search}${destination.hash}`;
  } catch {
    return "/dashboard/";
  }
}

function loginUrl(request, error = false) {
  const url = new URL("/login/", request.url);
  const current = new URL(request.url);
  const next = `${current.pathname}${current.search}`;
  url.searchParams.set("next", safeNext(next));
  if (error) url.searchParams.set("error", "1");
  return url;
}

function isPublicPath(pathname) {
  return (
    pathname === "/" ||
    pathname === "/index.html" ||
    // `/home` and `/updates` are deliberately NOT here: the site is not publicly
    // launched, so every real page sits behind the password. Only the Coming Soon
    // face at `/`, the login page, and the assets both need stay open.
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/coming-soon/") ||
    // Crawlers fetch this before anything else and never authenticate. Behind
    // the gate it would answer a redirect to the login page, which says
    // nothing about what may be indexed. Deliberately absent from
    // isAlwaysOpenPath: during maintenance a 503 here is the right signal,
    // because a 5xx on robots.txt makes crawlers pause the whole site.
    pathname === "/robots.txt" ||
    pathname.startsWith("/_astro/") ||
    pathname.startsWith("/assets/") ||
    pathname === "/favicon.png" ||
    pathname === "/favicon.ico" ||
    pathname === "/overrides.css"
  );
}

// The few paths that must answer even mid-maintenance, because the maintenance
// page itself is built from them. Everything else — including `/` and the
// Coming Soon face — closes.
function isAlwaysOpenPath(pathname) {
  return (
    // The way back in. Linked from nowhere, but it has to answer while the
    // site is shut or the code would have nowhere to be typed.
    pathname === "/preview" ||
    pathname === "/preview/" ||
    pathname.startsWith("/_astro/") ||
    pathname.startsWith("/assets/") ||
    pathname === "/favicon.png" ||
    pathname === "/favicon.ico" ||
    pathname === "/overrides.css"
  );
}

function isMaintenanceEnabled(env) {
  return MAINTENANCE_VALUES.has(String(env.MAINTENANCE_MODE || "").trim().toLowerCase());
}

function isSecurityScanOpen(env) {
  return SECURITY_SCAN_OPEN_VALUES.has(String(env.SECURITY_SCAN_OPEN || "").trim().toLowerCase());
}

function assetCacheControl(pathname) {
  // These pages now sit behind the password. A `public` header on an
  // authenticated response could be stored by a shared cache and handed to a
  // visitor with no session, so they are never publicly cacheable.
  if (
    pathname === "/login" ||
    pathname === "/login/" ||
    pathname === "/preview" ||
    pathname === "/preview/" ||
    pathname === "/maintenance" ||
    pathname === "/maintenance/"
  ) {
    // These pages can carry an error flag or serve as a maintenance access
    // door. No browser or intermediary should retain a previous response.
    return "no-store";
  }
  if (
    pathname === "/home" ||
    pathname.startsWith("/home/") ||
    pathname === "/status" ||
    pathname.startsWith("/status/") ||
    pathname === "/updates" ||
    pathname.startsWith("/updates/")
  ) {
    // `private` keeps these out of any shared cache, which is what the password
    // gate requires. Letting the visitor's own browser hold them for a minute is
    // what makes paging through /updates and going back feel instant.
    return "private, max-age=60";
  }
  if (
    pathname.startsWith("/_astro/") ||
    pathname.startsWith("/assets/") ||
    pathname.startsWith("/coming-soon/assets/")
  ) {
    return "public, max-age=31536000, immutable";
  }
  if (pathname === "/overrides.css") return "public, max-age=3600, stale-while-revalidate=86400";
  if (pathname === "/favicon.png" || pathname === "/favicon.ico") {
    return "public, max-age=86400, stale-while-revalidate=604800";
  }
  return null;
}

async function handleStatusSnapshot(request, env, ctx) {
  if (request.method !== "GET") {
    return Response.json(
      { error: "Method not allowed", code: "method_not_allowed" },
      { status: 405, headers: { Allow: "GET" } },
    );
  }

  const url = new URL(request.url);
  const cacheKey = new Request(`${url.origin}/api/status-snapshot`);
  const edgeCache = globalThis.caches?.default;
  const cached = edgeCache ? await edgeCache.match(cacheKey) : null;
  if (cached) {
    return Response.json(await cached.json(), { headers: STATUS_CLIENT_HEADERS });
  }

  const apiBase = String(env.STATUS_API_BASE || DEFAULT_STATUS_API_BASE).replace(/\/+$/, "");
  const upstreamOptions = {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(STATUS_SNAPSHOT_TIMEOUT_MS),
  };

  try {
    const [statsResponse, healthResponse] = await Promise.all([
      fetch(`${apiBase}/stats`, upstreamOptions),
      fetch(`${apiBase}/health`, upstreamOptions),
    ]);
    if (!statsResponse.ok || (healthResponse.status >= 500 && healthResponse.status !== 503)) {
      throw new Error(`Status upstream failed: ${statsResponse.status}/${healthResponse.status}`);
    }

    const [stats, health] = await Promise.all([statsResponse.json(), healthResponse.json()]);
    const snapshot = { stats, health, fetched_at: Date.now(), stale: false };
    lastGoodStatusSnapshot = snapshot;

    if (edgeCache && ctx?.waitUntil) {
      ctx.waitUntil(edgeCache.put(cacheKey, Response.json(snapshot, { headers: STATUS_EDGE_CACHE_HEADERS })));
    }
    return Response.json(snapshot, { headers: STATUS_CLIENT_HEADERS });
  } catch (error) {
    logWorkerEvent("warn", "status_snapshot_upstream_failed", {
      error: errorMessage(error),
      fallback: lastGoodStatusSnapshot ? "stale_snapshot" : "none",
    });
    if (lastGoodStatusSnapshot) {
      return Response.json(
        {
          ...lastGoodStatusSnapshot,
          stale: true,
          stale_reason: error instanceof Error ? error.message : "Status upstream unavailable",
        },
        { headers: STATUS_CLIENT_HEADERS },
      );
    }

    return Response.json(
      { error: "Status snapshot unavailable", code: "status_unavailable" },
      { status: 502, headers: STATUS_CLIENT_HEADERS },
    );
  }
}

async function handleUpdatesFeed(request, env, ctx) {
  if (request.method !== "GET") {
    return Response.json(
      { error: "Method not allowed", code: "method_not_allowed" },
      { status: 405, headers: { Allow: "GET" } },
    );
  }

  const url = new URL(request.url);
  const cacheKey = new Request(`${url.origin}/api/updates-feed`);
  const edgeCache = globalThis.caches?.default;
  const cached = edgeCache ? await edgeCache.match(cacheKey) : null;
  if (cached) return cached;

  const apiBase = String(env.STATUS_API_BASE || DEFAULT_STATUS_API_BASE).replace(/\/+$/, "");

  try {
    const upstream = await fetch(`${apiBase}/updates?limit=200`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(UPDATES_FEED_TIMEOUT_MS),
    });
    if (!upstream.ok) throw new Error(`Updates upstream failed: ${upstream.status}`);

    const payload = await upstream.json();
    // Releases land minutes apart at best, so a long window keeps the Pi quiet
    // without the page ever looking stale.
    const response = Response.json(payload, {
      headers: {
        "Cache-Control": "public, max-age=300, stale-while-revalidate=1800",
        "X-Content-Type-Options": "nosniff",
      },
    });

    if (edgeCache && ctx?.waitUntil) {
      ctx.waitUntil(edgeCache.put(cacheKey, response.clone()));
    }
    return response;
  } catch (error) {
    logWorkerEvent("warn", "updates_feed_upstream_failed", {
      error: errorMessage(error),
    });
    // The page ships its own archive, so an unreachable bot costs only the
    // newest entries — never the page itself.
    return Response.json(
      { error: "Updates unavailable", code: "updates_unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}

// The only two pages that post back to the worker. Both are rendered by Astro
// as static HTML, so the token cannot be baked in at build time — it is stitched
// into the response on the way out, which is also why these two must never be
// stored by a shared cache (see assetCacheControl).
function isFormPage(pathname) {
  return (
    pathname === "/login" ||
    pathname === "/login/" ||
    pathname === "/preview" ||
    pathname === "/preview/"
  );
}

function createCsrfToken() {
  return base64UrlEncode(crypto.getRandomValues(new Uint8Array(32)));
}

// Reuse the token the visitor already holds rather than minting one per render.
// A fresh token on every page load would invalidate whichever tab was opened
// first, so opening the login page twice would break the older tab's submit for
// no security gain — both tabs are the same person either way.
function currentCsrfToken(request) {
  const existing = readCookie(request, CSRF_COOKIE);
  return existing && CSRF_TOKEN_PATTERN.test(existing) ? existing : createCsrfToken();
}

function csrfCookie(token) {
  return `${CSRF_COOKIE}=${token}; Path=/; Max-Age=${CSRF_TTL_SECONDS}; HttpOnly; Secure; SameSite=Strict`;
}

async function withCsrfField(response, token) {
  const html = await response.text();
  const body = html.replace(
    /<form\b[^>]*>/gi,
    (tag) => `${tag}<input type="hidden" name="${CSRF_FIELD}" value="${escapeHtml(token)}">`,
  );

  const headers = new Headers(response.headers);
  // The token travels in the body, so the body is now per-visitor.
  headers.set("Cache-Control", "no-store");
  headers.delete("Content-Length");
  headers.append("Set-Cookie", csrfCookie(token));
  return new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

// Second, independent check. The token proves the form came from a page we
// rendered; this proves the request itself was sent by one of our own pages.
// Either alone would do, and a browser that drops one still fails the other.
function isSameOriginRequest(request) {
  const target = new URL(request.url).origin;
  const origin = request.headers.get("Origin");
  if (origin) return origin === target;

  // Origin is absent on some same-origin form posts from older browsers, where
  // Referer is what does get sent. Neither header at all means the request did
  // not come from a page in a browsing context, so it is refused.
  const referer = request.headers.get("Referer");
  if (!referer) return false;
  try {
    return new URL(referer).origin === target;
  } catch {
    return false;
  }
}

async function hasValidCsrf(request, form) {
  const cookieToken = readCookie(request, CSRF_COOKIE);
  const formToken = String(form.get(CSRF_FIELD) || "");
  if (!cookieToken || !formToken || !CSRF_TOKEN_PATTERN.test(cookieToken)) return false;
  return timingSafeEqual(cookieToken, formToken);
}

function csrfRejection(event) {
  logWorkerEvent("warn", event);
  return new Response("This form expired. Reload the page and try again.", {
    status: 403,
    headers: { "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8" },
  });
}

async function serveAsset(request, env) {
  const response = await env.ASSETS.fetch(request);
  const pathname = new URL(request.url).pathname;
  const cacheControl = assetCacheControl(pathname);
  if (!response.ok) return response;

  let served = response;
  if (cacheControl) {
    const headers = new Headers(response.headers);
    headers.set("Cache-Control", cacheControl);
    served = new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  }

  if (!isFormPage(pathname)) return served;
  return withCsrfField(served, currentCsrfToken(request));
}

async function timingSafeEqual(a, b) {
  // HMAC both values with a throwaway key, then compare the fixed-length MACs
  // byte by byte. A plain string compare returns at the first differing
  // character, which leaks how much of the password prefix was right.
  const key = await crypto.subtle.generateKey({ name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const [macA, macB] = await Promise.all([
    crypto.subtle.sign("HMAC", key, encoder.encode(a)),
    crypto.subtle.sign("HMAC", key, encoder.encode(b)),
  ]);
  const bytesA = new Uint8Array(macA);
  const bytesB = new Uint8Array(macB);
  let diff = 0;
  for (let i = 0; i < bytesA.length; i++) diff |= bytesA[i] ^ bytesB[i];
  return diff === 0;
}

async function handleLogin(request, env) {
  if (!env.AUTH_PASSWORD) {
    logWorkerEvent("error", "auth_password_missing");
    return new Response("AUTH_PASSWORD is not configured.", { status: 500 });
  }

  if (request.method !== "POST") {
    return Response.redirect(new URL("/login/", request.url), 303);
  }

  // A body that is not form data is a malformed request, not a server fault:
  // treat it as an empty form and let the check below turn it away.
  const form = await request.formData().catch(() => new FormData());
  // Before the password is even looked at. Without this an attacker's page can
  // make a visitor's browser post the gate password it already knows, or — once
  // the password leaks to one person — silently open a session in the browser
  // of anyone who loads the attacker's page.
  if (!isSameOriginRequest(request) || !(await hasValidCsrf(request, form))) {
    return csrfRejection("auth_login_csrf_rejected");
  }

  const password = String(form.get("password") || "");
  const next = safeNext(String(form.get("next") || "/dashboard/"));

  if (!(await timingSafeEqual(password, env.AUTH_PASSWORD))) {
    logWorkerEvent("warn", "auth_login_denied");
    const url = new URL("/login/", request.url);
    url.searchParams.set("next", next);
    url.searchParams.set("error", "1");
    return Response.redirect(url, 303);
  }

  const session = await createSession(env.AUTH_PASSWORD);
  return new Response(null, {
    status: 303,
    headers: {
      Location: new URL(next, request.url).toString(),
      "Set-Cookie": `${SESSION_COOKIE}=${session}; Path=/; Max-Age=${SESSION_TTL_SECONDS}; HttpOnly; Secure; SameSite=Lax`,
      "Cache-Control": "no-store",
    },
  });
}

async function createPreviewSession(secret, since) {
  const issuedAt = Math.floor(Date.now() / 1000);
  const payload = base64UrlEncode(
    encoder.encode(JSON.stringify({ iat: issuedAt, exp: issuedAt + PREVIEW_TTL_SECONDS, since })),
  );
  const key = await importSigningKey(secret);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return `${payload}.${base64UrlEncode(new Uint8Array(signature))}`;
}

async function isValidPreview(value, secret, since) {
  if (!value || !secret || !since) return false;
  const [payload, signature] = value.split(".");
  if (!payload || !signature) return false;

  try {
    const key = await importSigningKey(secret);
    const valid = await crypto.subtle.verify(
      "HMAC",
      key,
      base64UrlDecode(signature),
      encoder.encode(payload),
    );
    if (!valid) return false;

    const session = JSON.parse(new TextDecoder().decode(base64UrlDecode(payload)));
    const now = Math.floor(Date.now() / 1000);
    return (
      Number.isFinite(session.exp) &&
      session.exp > now &&
      // Bound to one activation: a code shared during a previous maintenance
      // window opens nothing during this one.
      session.since === since
    );
  } catch (error) {
    return false;
  }
}

async function handlePreview(request, env) {
  if (request.method !== "POST") {
    return new Response("Method not allowed", { status: 405, headers: { Allow: "POST" } });
  }

  const form = await request.formData().catch(() => new FormData());
  if (!isSameOriginRequest(request) || !(await hasValidCsrf(request, form))) {
    return csrfRejection("preview_csrf_rejected");
  }

  const code = String(form.get("code") || "").trim();
  const apiBase = String(env.STATUS_API_BASE || DEFAULT_STATUS_API_BASE).replace(/\/+$/, "");

  let verified = null;
  try {
    const upstream = await fetch(`${apiBase}/maintenance/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ code }),
      signal: AbortSignal.timeout(MAINTENANCE_TIMEOUT_MS),
    });
    if (upstream.ok) verified = await upstream.json();
    else if (upstream.status >= 500) {
      logWorkerEvent("warn", "preview_upstream_rejected", { status: upstream.status });
    }
  } catch (error) {
    logWorkerEvent("warn", "preview_upstream_failed", {
      error: errorMessage(error),
    });
    // Unreachable bot means no bypass. Failing closed on the door is the
    // opposite of failing closed on the site, and both are the safe direction.
    verified = null;
  }

  if (!verified || !verified.since) {
    // Back to the form with a flag rather than an error page: a wrong code is
    // usually a typo. The flag says nothing about which failure it was.
    return new Response(null, {
      status: 303,
      headers: {
        Location: new URL("/preview/?error=1", request.url).toString(),
        "Cache-Control": "no-store",
      },
    });
  }

  const session = await createPreviewSession(env.AUTH_PASSWORD, verified.since);
  return new Response(null, {
    status: 303,
    headers: {
      Location: new URL("/", request.url).toString(),
      "Set-Cookie": `${PREVIEW_COOKIE}=${session}; Path=/; Max-Age=${PREVIEW_TTL_SECONDS}; HttpOnly; Secure; SameSite=Lax`,
      "Cache-Control": "no-store",
    },
  });
}

async function handleLogout(request) {
  // Was reachable by GET, which made `<img src="/api/auth/logout">` on any page
  // on the internet enough to sign a visitor out. Logging someone out is not
  // destructive, but it is still a state change they did not ask for, and the
  // same shape of hole is what lets a forced logout precede a forced login.
  if (request.method !== "POST") {
    return new Response("Method not allowed", {
      status: 405,
      headers: { Allow: "POST", "Cache-Control": "no-store" },
    });
  }

  const form = await request.formData().catch(() => new FormData());
  if (!isSameOriginRequest(request) || !(await hasValidCsrf(request, form))) {
    return csrfRejection("auth_logout_csrf_rejected");
  }

  return new Response(null, {
    status: 303,
    headers: {
      Location: new URL("/login/", request.url).toString(),
      "Set-Cookie": `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`,
      "Cache-Control": "no-store",
    },
  });
}

function maintenanceFromHealth(health) {
  const raw = health && typeof health === "object" ? health.maintenance : null;
  // A bot that predates this field is not in maintenance. This is the rule that
  // makes deploy order irrelevant: the worker ships before the bot restarts, and
  // reading the gap as an error would black the dashboard out in between.
  if (!raw || typeof raw !== "object") return { enabled: false, message: "", since: "" };
  const enabled = Boolean(raw.enabled);
  return {
    enabled,
    message: enabled && typeof raw.message === "string" ? raw.message : "",
    // Which activation this is. Preview cookies bind to it, so a code from a
    // previous window stops opening the site without anyone revoking it.
    since: enabled && typeof raw.since === "string" ? raw.since : "",
  };
}

async function readMaintenance(request, env, ctx) {
  const now = Date.now();
  const url = new URL(request.url);
  const cacheKey = new Request(`${url.origin}/api/maintenance-state`);
  const edgeCache = globalThis.caches?.default;

  let known = lastMaintenanceState;
  if (!known && edgeCache) {
    const cached = await edgeCache.match(cacheKey);
    const parsed = cached ? await cached.json().catch(() => null) : null;
    if (parsed && typeof parsed.fetchedAt === "number") known = parsed;
  }
  if (known && now - known.fetchedAt < MAINTENANCE_FRESH_MS) return known;

  const apiBase = String(env.STATUS_API_BASE || DEFAULT_STATUS_API_BASE).replace(/\/+$/, "");
  try {
    const response = await fetch(`${apiBase}/health`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(MAINTENANCE_TIMEOUT_MS),
    });
    // 503 is what the bot returns when its own database probe fails; the payload
    // is still there and still tells the truth about maintenance.
    if (response.status >= 500 && response.status !== 503) {
      throw new Error(`Maintenance upstream failed: ${response.status}`);
    }
    const state = { ...maintenanceFromHealth(await response.json()), fetchedAt: now };
    lastMaintenanceState = state;
    if (edgeCache && ctx?.waitUntil) {
      ctx.waitUntil(
        edgeCache.put(cacheKey, Response.json(state, { headers: MAINTENANCE_EDGE_CACHE_HEADERS })),
      );
    }
    return state;
  } catch (error) {
    logWorkerEvent("warn", "maintenance_health_unreachable", {
      error: errorMessage(error),
      fallback: known ? "last_known_state" : "fail_closed",
    });
    // A restart lasts seconds; hold the last real answer through it. That answer
    // is deliberately not overwritten here, so recovery is picked up on the very
    // next request instead of after another freshness window.
    if (known && !known.unreachable && now - known.fetchedAt < MAINTENANCE_GRACE_MS) {
      return known;
    }
    // Past the grace window the API is genuinely gone, and a dashboard that
    // cannot reach it would only fill with errors. Remember the verdict so a
    // long outage costs one upstream attempt per window, not one per request.
    const state = { enabled: true, message: "", fetchedAt: now, unreachable: true };
    lastMaintenanceState = state;
    return state;
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function serveMaintenancePage(request, env, state) {
  const asset = await serveAsset(new Request(new URL("/maintenance/", request.url), request), env);
  if (!asset.ok) {
    // The page is missing from the build. The dashboard at least explains
    // itself; serving nothing does not.
    return serveAsset(new Request(new URL("/dashboard/", request.url), request), env);
  }

  const html = await asset.text();
  // Only the bot owner can set this text, but it is escaped anyway: the page is
  // public, and the cost of being sure is nothing.
  const body = html.replace(
    '<p class="message" data-ng-maintenance-message></p>',
    state.message ? `<p class="message">${escapeHtml(state.message)}</p>` : '<p class="message"></p>',
  );

  const headers = new Headers(asset.headers);
  // Without no-store a browser keeps showing maintenance after it has ended —
  // a bug that surfaces an hour later, to one person, and looks like nothing.
  headers.set("Cache-Control", "no-store");
  headers.set("Retry-After", "120");
  headers.delete("Content-Length");
  return new Response(body, { status: 503, headers });
}

async function handleRequest(request, env, ctx) {
  const url = new URL(request.url);

  if (url.pathname === "/api/status-snapshot") return handleStatusSnapshot(request, env, ctx);
  if (url.pathname === "/api/updates-feed") return handleUpdatesFeed(request, env, ctx);
  if (url.pathname === "/api/auth/login") return handleLogin(request, env);
  if (url.pathname === "/api/auth/logout") return handleLogout(request);
  if (url.pathname === "/api/preview") return handlePreview(request, env);
  // Assets answer first: the maintenance page is built from them, so gating
  // them would leave it unable to render itself.
  if (isAlwaysOpenPath(url.pathname)) return serveAsset(request, env);

  // `/maintenance` toggles the whole site, before the password gate, so a
  // visitor with no session sees the notice rather than a login form for a
  // site that is closed anyway.
  const maintenance = await readMaintenance(request, env, ctx);
  let previewHolder = false;
  if (maintenance.enabled && !maintenance.unreachable) {
    previewHolder = await isValidPreview(
      readCookie(request, PREVIEW_COOKIE),
      env.AUTH_PASSWORD,
      maintenance.since,
    );
    if (!previewHolder) return serveMaintenancePage(request, env, maintenance);
  }
  if (isMaintenanceEnabled(env)) {
    return serveMaintenancePage(request, env, { message: "" });
  }

  if (url.pathname === "/login") return Response.redirect(new URL("/login/", request.url), 308);
  if (isPublicPath(url.pathname)) return serveAsset(request, env);

  // A preview code stands in for the soft-launch password. The alternative
  // pushes the operator to hand out that password to show someone an update,
  // and it is fixed and never expires; a preview code is 24 random bytes,
  // rotates every maintenance window, and dies in twelve hours.
  const authenticated =
    isSecurityScanOpen(env) ||
    previewHolder ||
    (await isValidSession(readCookie(request, SESSION_COOKIE), env.AUTH_PASSWORD));
  if (!authenticated) return Response.redirect(loginUrl(request), 302);

  if (url.pathname === "/maintenance") {
    return Response.redirect(new URL("/maintenance/", request.url), 308);
  }

  if (url.pathname.startsWith("/dashboard/")) {
    // An unreachable API closes only this: the dashboard genuinely cannot
    // work without it, while the marketing pages never needed the bot at all.
    // Deliberate maintenance closed everything above; an outage should not.
    // A preview holder already passed that check, so they are let through.
    if (maintenance.enabled && !previewHolder) {
      return serveMaintenancePage(request, env, maintenance);
    }

    // The dashboard owns its nested routes client-side. Serve its static
    // shell on direct visits so refreshes at /dashboard/g/:id keep working.
    if (url.pathname !== "/dashboard/") {
      return serveAsset(new Request(new URL("/dashboard/", request.url), request), env);
    }
  }

  return serveAsset(request, env);
}

export default {
  async fetch(request, env, ctx) {
    try {
      return hardenResponse(await handleRequest(request, env, ctx));
    } catch (error) {
      const url = new URL(request.url);
      logWorkerEvent("error", "worker_request_failed", {
        method: request.method,
        path: url.pathname,
        ray: request.headers.get("cf-ray") || undefined,
        error: errorMessage(error),
      });
      return hardenResponse(Response.json(
        { error: "The website edge is temporarily unavailable.", code: "edge_error" },
        {
          status: 500,
          headers: {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
          },
        },
      ));
    }
  },
};
