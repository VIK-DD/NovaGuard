// Deliberately NOT "ng_session": that name belongs to the bot API's login
// cookie on api.novaguard.fun. They live on different hosts today, but a
// future `Domain=.novaguard.fun` on either would make them clobber each other.
const SESSION_COOKIE = "ng_gate";
const SESSION_TTL_SECONDS = 60 * 60 * 2;
const DEFAULT_STATUS_API_BASE = "https://api.novaguard.fun/api/v1";
const STATUS_SNAPSHOT_TIMEOUT_MS = 8000;
const UPDATES_FEED_TIMEOUT_MS = 8000;
const MAINTENANCE_VALUES = new Set(["1", "true", "on", "enabled", "protected", "private"]);
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
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/dashboard/";
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

function assetCacheControl(pathname) {
  // These pages now sit behind the password. A `public` header on an
  // authenticated response could be stored by a shared cache and handed to a
  // visitor with no session, so they are never publicly cacheable.
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
  } catch {
    // The page ships its own archive, so an unreachable bot costs only the
    // newest entries — never the page itself.
    return Response.json(
      { error: "Updates unavailable", code: "updates_unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}

async function serveAsset(request, env) {
  const response = await env.ASSETS.fetch(request);
  const cacheControl = assetCacheControl(new URL(request.url).pathname);
  if (!response.ok || !cacheControl) return response;

  const headers = new Headers(response.headers);
  headers.set("Cache-Control", cacheControl);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
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
    return new Response("AUTH_PASSWORD is not configured.", { status: 500 });
  }

  if (request.method !== "POST") {
    return Response.redirect(new URL("/login/", request.url), 303);
  }

  const form = await request.formData();
  const password = String(form.get("password") || "");
  const next = safeNext(String(form.get("next") || "/dashboard/"));

  if (!(await timingSafeEqual(password, env.AUTH_PASSWORD))) {
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

function handleLogout(request) {
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
  if (!raw || typeof raw !== "object") return { enabled: false, message: "" };
  const enabled = Boolean(raw.enabled);
  return {
    enabled,
    message: enabled && typeof raw.message === "string" ? raw.message : "",
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

async function serveMaintenancePage(request, env, state) {
  const asset = await serveAsset(new Request(new URL("/maintenance/", request.url), request), env);
  return new Response(asset.body, { status: 503, headers: new Headers(asset.headers) });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/api/status-snapshot") return handleStatusSnapshot(request, env, ctx);
    if (url.pathname === "/api/updates-feed") return handleUpdatesFeed(request, env, ctx);
    if (url.pathname === "/api/auth/login") return handleLogin(request, env);
    if (url.pathname === "/api/auth/logout") return handleLogout(request);
    if (url.pathname === "/login") return Response.redirect(new URL("/login/", request.url), 308);
    if (isPublicPath(url.pathname)) return serveAsset(request, env);

    const authenticated = await isValidSession(readCookie(request, SESSION_COOKIE), env.AUTH_PASSWORD);
    if (!authenticated) return Response.redirect(loginUrl(request), 302);

    if (url.pathname === "/maintenance") {
      return Response.redirect(new URL("/maintenance/", request.url), 308);
    }

    if (isMaintenanceEnabled(env)) {
      return serveAsset(new Request(new URL("/maintenance/", request.url), request), env);
    }

    // The dashboard is the only surface /maintenance closes: the marketing
    // pages stay up, because a two-minute bot restart should not take the whole
    // site down. Public paths returned above, so they never pay for this call.
    if (url.pathname.startsWith("/dashboard/")) {
      const maintenance = await readMaintenance(request, env, ctx);
      if (maintenance.enabled) return serveMaintenancePage(request, env, maintenance);

      // The dashboard owns its nested routes client-side. Serve its static
      // shell on direct visits so refreshes at /dashboard/g/:id keep working.
      if (url.pathname !== "/dashboard/") {
        return serveAsset(new Request(new URL("/dashboard/", request.url), request), env);
      }
    }

    return serveAsset(request, env);
  },
};
