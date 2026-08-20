#!/usr/bin/env node
// Scoped security audit for the hosts we actually operate.
//
// Run it against production:
//   NG_AUDIT_PASSWORD=... npm run security:audit
//
// Or against a local `wrangler dev`:
//   npm run security:audit -- --base http://127.0.0.1:8787
//
// It signs in through the soft-launch gate on its own, so the site never has
// to be opened to the public for a scan. Exit status is non-zero when a real
// finding is attributable to us, which makes it usable in CI.

import { readFile, readdir, stat } from "node:fs/promises";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

import {
  auditBuildArtifacts,
  auditResponse,
  isOurHost,
  worstSeverity,
} from "./security-audit-rules.mjs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DIST = join(HERE, "..", "dist");

const SEVERITY_RANK = { info: 0, low: 1, medium: 2, high: 3 };
const LABEL = { high: "HIGH", medium: "MEDIUM", low: "LOW", info: "INFO" };

function parseArgs(argv) {
  const args = {
    base: "https://novaguard.fun",
    api: "https://api.novaguard.fun",
    password: process.env.NG_AUDIT_PASSWORD || "",
    failOn: "low",
    skipBuild: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    const value = () => argv[++i];
    if (flag === "--base") args.base = value();
    else if (flag === "--api") args.api = value();
    else if (flag === "--password") args.password = value();
    else if (flag === "--fail-on") args.failOn = value();
    else if (flag === "--skip-build") args.skipBuild = true;
  }
  return args;
}

// --- cookie jar ------------------------------------------------------------

function makeJar() {
  const jar = new Map();
  return {
    store(setCookieHeaders) {
      for (const raw of setCookieHeaders) {
        const [pair] = raw.split(";");
        const index = pair.indexOf("=");
        if (index < 0) continue;
        jar.set(pair.slice(0, index).trim(), pair.slice(index + 1).trim());
      }
    },
    header() {
      return [...jar.entries()].map(([k, v]) => `${k}=${v}`).join("; ");
    },
    has(name) {
      return jar.has(name);
    },
  };
}

function splitSetCookie(response) {
  // Node exposes repeated Set-Cookie headers through getSetCookie().
  if (typeof response.headers.getSetCookie === "function") return response.headers.getSetCookie();
  const single = response.headers.get("set-cookie");
  return single ? [single] : [];
}

async function request(url, jar, init = {}) {
  const headers = { "User-Agent": "NovaGuard-security-audit", ...(init.headers || {}) };
  const cookies = jar.header();
  if (cookies) headers.Cookie = cookies;
  const response = await fetch(url, { ...init, headers, redirect: "manual" });
  const setCookie = splitSetCookie(response);
  jar.store(setCookie);
  const body = await response.text();
  return {
    url,
    status: response.status,
    headers: Object.fromEntries([...response.headers.entries()]),
    setCookie,
    body,
    location: response.headers.get("location"),
  };
}

/** True when the response is the soft-launch gate turning the request away. */
function isLoginRedirect(response) {
  return (
    response.status >= 300 &&
    response.status < 400 &&
    /\/login\//.test(response.location || "")
  );
}

// --- gate sign-in ----------------------------------------------------------

async function signIn(base, password, jar) {
  const loginPage = await request(`${base}/login/`, jar, {});
  const token = (loginPage.body.match(/name="csrf_token"\s+value="([^"]+)"/) || [])[1];
  if (!token) return { ok: false, reason: "no CSRF token on the login page" };

  const form = new URLSearchParams({ password, csrf_token: token, next: "/" });
  const posted = await request(`${base}/api/auth/login`, jar, {
    method: "POST",
    body: form,
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Referer: `${base}/login/`,
      Origin: base,
    },
  });

  if (posted.status === 403) return { ok: false, reason: "CSRF rejected" };
  if (!jar.has("ng_gate")) {
    return { ok: false, reason: `password refused (status ${posted.status})` };
  }
  return { ok: true };
}

// --- route discovery -------------------------------------------------------

async function walk(dir) {
  const out = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await walk(full)));
    else out.push(full);
  }
  return out;
}

async function discoverRoutes() {
  const files = await walk(DIST);
  const routes = new Set(["/"]);
  for (const file of files) {
    if (!file.endsWith(`${sep}index.html`)) continue;
    const rel = relative(DIST, file).split(sep).slice(0, -1).join("/");
    routes.add(rel ? `/${rel}/` : "/");
  }
  return [...routes].sort();
}

// --- reporting -------------------------------------------------------------

function printFindings(title, findings) {
  console.log(`\n${title}`);
  if (findings.length === 0) {
    console.log("  none");
    return;
  }
  const ordered = [...findings].sort(
    (a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity],
  );
  for (const f of ordered) {
    console.log(`  [${LABEL[f.severity].padEnd(6)}] ${f.rule}`);
    console.log(`            ${f.url}`);
    console.log(`            ${f.detail}`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const jar = makeJar();
  const findings = [];
  const externalHosts = new Set();
  let scanned = 0;

  console.log("NovaGuard security audit");
  console.log(`  site : ${args.base}`);
  console.log(`  api  : ${args.api}`);

  const routes = await discoverRoutes();
  const targets = [
    ...routes.map((r) => `${args.base}${r}`),
    `${args.base}/robots.txt`,
    `${args.base}/api/status-snapshot`,
    `${args.base}/this-path-does-not-exist`,
    `${args.api}/api/v1/health`,
    `${args.api}/api/v1/stats`,
  ];

  // Learn which paths the gate protects, before holding a session. Signing in
  // first would make every page look public, and a page only a signed-in
  // visitor may read must not then invite a shared cache to keep a copy.
  const gated = new Set();
  for (const target of targets) {
    try {
      const probe = await request(target, makeJar(), {});
      if (isLoginRedirect(probe)) gated.add(target);
    } catch {
      /* the audited pass below records an unreachable target properly */
    }
  }
  console.log(`  gated: ${gated.size} of ${targets.length} paths require signing in`);

  // Sign in so the audit sees the real pages instead of the login gate.
  let gateRefused = false;
  if (args.password) {
    const result = await signIn(args.base, args.password, jar);
    console.log(`  gate : ${result.ok ? "signed in" : `NOT signed in — ${result.reason}`}`);
    // A password was supplied and rejected. That says the audit is
    // misconfigured, not that the site is clean, and finishing green would
    // report a pass for every page the gate then turned away.
    gateRefused = !result.ok;
  } else {
    console.log("  gate : no password given (set NG_AUDIT_PASSWORD to audit pages behind it)");
  }

  for (const target of targets) {
    let response;
    try {
      response = await request(target, jar, {});
      response.requiresAuth = gated.has(target);
    } catch (error) {
      findings.push({
        rule: "unreachable",
        severity: "low",
        url: target,
        detail: `Request failed: ${error.message}`,
      });
      continue;
    }
    scanned += 1;

    // A redirect to the gate means we are auditing the gate, not the page.
    if (isLoginRedirect(response)) {
      findings.push({
        rule: "not-audited",
        severity: "info",
        url: target,
        detail: "Behind the soft-launch gate; rerun with NG_AUDIT_PASSWORD to audit it.",
      });
    }

    findings.push(...auditResponse(response));

    // Record where a crawler would wander off to, so the third-party alerts a
    // generic scanner reports can be recognised for what they are.
    for (const match of response.body.matchAll(/href="(https?:\/\/[^"]+)"/g)) {
      try {
        if (!isOurHost(match[1])) externalHosts.add(new URL(match[1]).hostname);
      } catch {
        /* ignore an unparseable href */
      }
    }
  }

  let buildSkipped = false;

  printFindings(`Live responses — ${scanned} scanned on our hosts only`, findings);

  if (!args.skipBuild) {
    const files = await walk(DIST);
    const artifacts = await Promise.all(
      files.map(async (path) => {
        const info = await stat(path);
        // Reading a large binary as text is pointless and slow; names still count.
        const content = info.size < 2_000_000 ? await readFile(path, "utf8").catch(() => "") : "";
        return { path: relative(DIST, path), content };
      }),
    );
    const buildFindings = auditBuildArtifacts(artifacts);
    findings.push(...buildFindings);
    if (artifacts.length === 0) {
      // "none" under a heading reads as "checked, and clean". With an empty
      // dist/ nothing was read at all, and reporting no findings when it did
      // not look is the one thing a security tool must never do. Seen for real
      // on the VPS, where the site is built by CI and dist/ never exists.
      buildSkipped = true;
      console.log("\nBuild output — NOT CHECKED");
      console.log("  dist/ is empty or missing, so this half of the audit read nothing.");
      console.log("  Run `npm run build` first, or audit from where the site is built.");
    } else {
      printFindings(`Build output — ${artifacts.length} files in dist/`, buildFindings);
    }
  }

  if (externalHosts.size > 0) {
    console.log("\nOutbound links, deliberately NOT audited (not our systems)");
    for (const host of [...externalHosts].sort()) console.log(`  ${host}`);
    console.log(
      "\n  A generic scanner follows these and reports their findings inside your\n" +
        "  report. They belong to those operators, not to NovaGuard.",
    );
  }

  const worst = worstSeverity(findings);
  const threshold = SEVERITY_RANK[args.failOn] ?? 1;
  const actionable = findings.filter((f) => SEVERITY_RANK[f.severity] >= threshold);

  console.log("\n" + "-".repeat(60));
  if (gateRefused) {
    console.log("FAIL — the gate password was refused, so most pages went unread.");
    console.log("       Check NG_AUDIT_PASSWORD matches the live gate, with no stray");
    console.log("       whitespace or newline. This is a configuration fault, not a");
    console.log("       finding about the site.");
    process.exit(1);
  }
  if (actionable.length === 0) {
    // A pass has to describe what was actually read. Pages the gate turned
    // away and an unbuilt dist/ are both half-scans, and calling either one
    // "no findings on our own hosts" is the failure this tool exists to catch.
    const unaudited = findings.filter((f) => f.rule === "not-audited").length;
    const gaps = [];
    if (unaudited) gaps.push(`${unaudited} page(s) behind the gate NOT audited`);
    if (buildSkipped) gaps.push("build output NOT checked");
    const scope = gaps.length ? `part of our hosts — ${gaps.join(", ")}` : "our own hosts";
    console.log(`PASS — no findings at or above '${args.failOn}' on ${scope}.`);
    if (gaps.length) {
      console.log("       This is a PARTIAL pass, not a clean bill of health.");
      if (unaudited) console.log("       Set NG_AUDIT_PASSWORD to reach the gated pages.");
      if (buildSkipped) console.log("       Run `npm run build` first for the build half.");
    }
    if (worst) console.log(`       (${findings.length} informational note(s) above.)`);
    process.exit(0);
  }
  console.log(
    `FAIL — ${actionable.length} finding(s) at or above '${args.failOn}'. Worst: ${LABEL[worst]}.`,
  );
  process.exit(1);
}

main().catch((error) => {
  console.error("Audit crashed:", error);
  process.exit(2);
});
