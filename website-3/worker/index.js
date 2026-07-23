const SESSION_COOKIE = "ng_session";
const SESSION_TTL_SECONDS = 60 * 60 * 2;
const MAINTENANCE_VALUES = new Set(["1", "true", "on", "enabled", "protected", "private"]);
const encoder = new TextEncoder();

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
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/coming-soon/") ||
    pathname.startsWith("/_next/") ||
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

  if (password !== env.AUTH_PASSWORD) {
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

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

    // The dashboard owns its nested routes client-side. Serve its static shell
    // on direct visits so refreshes at /dashboard/g/:id keep working.
    if (url.pathname.startsWith("/dashboard/") && url.pathname !== "/dashboard/") {
      return serveAsset(new Request(new URL("/dashboard/", request.url), request), env);
    }

    return serveAsset(request, env);
  },
};
