# Maintenance Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/maintenance enable` in Discord closes the website dashboard and shows the same reason on the maintenance page, with no redeploy.

**Architecture:** The bot publishes its maintenance state on the existing `/api/v1/health` endpoint. The Cloudflare worker — which already polls that endpoint for the status snapshot — reads the state, caches it for 30 s, and serves the maintenance page on `/dashboard/*` when it is on. The message is substituted into the page's HTML by the worker, escaped.

**Tech Stack:** Python 3.12 / aiohttp (bot API), Cloudflare Workers (JS, vitest), Astro 5 (the page).

## Global Constraints

- Freshness window **30 s**; `/health` fetch timeout **2.5 s**; grace window **120 s** — copied verbatim from the spec.
- `apiBase` resolves as `env.STATUS_API_BASE || DEFAULT_STATUS_API_BASE`, trailing slashes stripped — same as the status snapshot already does.
- A missing `maintenance` field on `/health` means **not** in maintenance, never an error. Deploy order must not matter.
- The maintenance response is **503**, `Cache-Control: no-store`, `Retry-After: 120`.
- `/health` keeps returning **200** while maintenance is on.
- No blocking I/O on the event loop: file reads go through `asyncio.to_thread`.
- Python tests are `unittest`, runnable standalone, with the `sys.path.insert` every file in `tests/` has.
- Colours, type scale and motion for the page come from `website-3/public/coming-soon/assets/index-CAD1rHsh.css`.
- `/maintenance` already requires `/admin unlock` via `require_admin`. Do not touch that gate.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `core/webserver.py` | Publish maintenance state on `/health` | 1 |
| `tests/test_webserver.py` | Assert the payload, both states | 1 |
| `website-3/worker/index.js` | Read state, cache it, gate `/dashboard/*` | 2 |
| `website-3/worker/index.js` | Serve the page: 503, no-store, message | 3 |
| `website-3/worker/index.test.js` | Assert both, plus the failure paths | 2, 3 |
| `website-3/src/pages/maintenance.astro` | The page, in the Coming Soon theme | 4 |
| `cogs/system.py` | Confirmation embed mentions the dashboard | 4 |

---

### Task 1: `/health` reports maintenance state

**Files:**
- Modify: `core/webserver.py:939-946` (`handle_health`), plus the import block at `core/webserver.py:48-55`
- Test: `tests/test_webserver.py`

**Interfaces:**
- Consumes: `load_maintenance_state()` from `core/maintenance.py`, returning `{"enabled": bool, "message": str, "updated_at": str|None, "updated_by": str|None}`.
- Produces: `GET /api/v1/health` gains a `maintenance` key — `{"enabled": true, "message": "…"}` when on, `{"enabled": false}` when off. Task 2 consumes exactly this shape.

- [ ] **Step 1: Write the failing test**

In `tests/test_webserver.py`, immediately after the existing health block (the one asserting `health 200 + db_ok`), add:

```python
        # ── maintenance state rides along on /health ──────────────────
        # Saved and restored around the checks: this writes the real
        # data/maintenance.json, and a test must not leave the bot shut down.
        original_maintenance = load_maintenance_state()
        try:
            save_maintenance_state(True, "Testing the sync", updated_by="test-suite")
            async with http.get(f"{V1}/health") as r:
                data = await r.json()
                await check(
                    "health reports maintenance on, with the message",
                    r.status == 200
                    and data["maintenance"]["enabled"] is True
                    and data["maintenance"]["message"] == "Testing the sync",
                )

            save_maintenance_state(False, updated_by="test-suite")
            async with http.get(f"{V1}/health") as r:
                data = await r.json()
                await check(
                    "health reports maintenance off, and leaks no stale message",
                    data["maintenance"]["enabled"] is False
                    and "message" not in data["maintenance"],
                )
        finally:
            save_maintenance_state(
                original_maintenance["enabled"],
                original_maintenance["message"],
                updated_by=original_maintenance.get("updated_by"),
            )
```

Add to the import block near the other `core.` imports at the top of the file:

```python
from core.maintenance import load_maintenance_state, save_maintenance_state  # noqa: E402
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_webserver.py`
Expected: `FAIL health reports maintenance on, with the message` — `KeyError: 'maintenance'` surfaces as a failed check, and the run exits 1.

- [ ] **Step 3: Write the implementation**

In `core/webserver.py`, add to the relative import block (alphabetical, between `.levels_settings` and `.storage`):

```python
from .maintenance import DEFAULT_MAINTENANCE_MESSAGE, load_maintenance_state
```

Replace `handle_health`:

```python
    async def handle_health(self, request):
        db_ok = await asyncio.to_thread(db_ping)
        # The website reads this to decide whether to close the dashboard, so
        # it is a small file read — off the event loop, like db_ping above.
        state = await asyncio.to_thread(load_maintenance_state)
        maintenance = {"enabled": bool(state.get("enabled"))}
        if maintenance["enabled"]:
            maintenance["message"] = state.get("message") or DEFAULT_MAINTENANCE_MESSAGE
        payload = {
            # Maintenance is deliberately absent from `ok`: this endpoint
            # answers "is the API alive", not "is the site open". Folding them
            # together would make the public status widget cry outage during a
            # routine update.
            "ok": bool(db_ok and self.bot.is_ready()),
            "bot_ready": self.bot.is_ready(),
            "db_ok": db_ok,
            "maintenance": maintenance,
        }
        return web.json_response(payload, status=200 if db_ok else 503)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_webserver.py`
Expected: both new checks PASS, and the final line reports every check passing.

Run: `python -m pytest tests -q`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add core/webserver.py tests/test_webserver.py
git commit -m "Report maintenance state on /health"
```

---

### Task 2: The worker reads the state and gates the dashboard

**Files:**
- Modify: `website-3/worker/index.js` — constants near the top (beside `MAINTENANCE_VALUES` at line 9), new functions before `export default`, and the `/dashboard/` branch inside `fetch`
- Test: `website-3/worker/index.test.js`

**Interfaces:**
- Consumes: `GET {apiBase}/health` → `{"maintenance": {"enabled": bool, "message"?: string}}` from Task 1.
- Produces: `readMaintenance(request, env, ctx)` → `Promise<{enabled: boolean, message: string, fetchedAt: number, unreachable?: true}>`. Task 3 consumes this object.

- [ ] **Step 1: Write the failing test**

Append to `website-3/worker/index.test.js`:

```javascript
describe("maintenance sync", () => {
  const apiEnv = { ...env, STATUS_API_BASE: "https://api.example.test/api/v1" };

  function healthStub(maintenance) {
    return vi.fn(async () =>
      Response.json({ ok: true, bot_ready: true, db_ok: true, ...maintenance }),
    );
  }

  async function dashboardRequest(testEnv, path = "/dashboard/") {
    const login = await worker.fetch(loginRequest(), testEnv);
    const cookie = login.headers.get("set-cookie").split(";")[0];
    return worker.fetch(
      new Request(`https://novaguard.fun${path}`, { headers: { cookie } }),
      testEnv,
    );
  }

  it("closes the dashboard when the bot says it is in maintenance", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true, message: "Music install" } }));

    const response = await dashboardRequest(apiEnv);

    expect(response.status).toBe(503);
    await expect(response.text()).resolves.toBe("/maintenance/");
  });

  it("serves the dashboard shell when maintenance is off", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: false } }));

    const response = await dashboardRequest(apiEnv, "/dashboard/g/123");

    expect(response.status).toBe(200);
    await expect(response.text()).resolves.toBe("/dashboard/");
  });

  it("treats a bot that predates the field as open, not broken", async () => {
    // The worker deploys before the bot restarts. If a missing field read as an
    // error, the dashboard would black out in the gap between the two.
    vi.stubGlobal("fetch", healthStub({}));

    const response = await dashboardRequest(apiEnv);

    expect(response.status).toBe(200);
  });

  it("never asks the bot about a public page", async () => {
    const upstream = healthStub({ maintenance: { enabled: true } });
    vi.stubGlobal("fetch", upstream);

    const response = await worker.fetch(new Request("https://novaguard.fun/"), apiEnv);

    expect(response.status).toBe(200);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("rides out a restart on the last known answer", async () => {
    // A pm2 restart is seconds long. Flipping the dashboard closed for it would
    // be worse than briefly serving a slightly old answer.
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: false } }));
    expect((await dashboardRequest(apiEnv)).status).toBe(200);

    vi.setSystemTime(Date.now() + 60_000); // past freshness, inside grace
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("connection refused");
      }),
    );

    expect((await dashboardRequest(apiEnv)).status).toBe(200);
  });

  it("closes the dashboard once the API has been gone past the grace window", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: false } }));
    expect((await dashboardRequest(apiEnv)).status).toBe(200);

    vi.setSystemTime(Date.now() + 180_000); // past the 120 s grace
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("host unreachable");
      }),
    );

    // The dashboard cannot work without the API, so saying so beats rendering
    // a page that will only fill with network errors.
    expect((await dashboardRequest(apiEnv)).status).toBe(503);
  });
});
```

**Isolation note:** `lastMaintenanceState` is module-level and survives between tests in the same file. Add this as the first thing inside the `describe`:

```javascript
  // Advanced, never reset: afterEach restores the real clock, so a jump
  // measured from `Date.now()` would land at roughly the same instant every
  // time and leave the previous test's answer inside the 30 s freshness window.
  let clock = Date.now();

  beforeEach(() => {
    clock += 10 * 60 * 1000;
    // Only Date is faked. Faking the timers too would break
    // AbortSignal.timeout inside readMaintenance, aborting every upstream call
    // and making the fail-closed path look like the answer.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(clock);
  });
```

Both halves are load-bearing, and each was found the hard way: a plain
`vi.useFakeTimers()` aborts every upstream call, and a jump measured from
`Date.now()` does not accumulate across tests.

Add `beforeEach` to the `vitest` import at the top of the file. The file's existing `afterEach` already calls `vi.useRealTimers()`, so nothing leaks into the other suites.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd website-3 && npx vitest run worker/index.test.js`
Expected: FAIL — `expected 200 to be 503`, because nothing gates the dashboard yet.

- [ ] **Step 3: Write the implementation**

In `website-3/worker/index.js`, add beside the other constants near line 9:

```javascript
const MAINTENANCE_FRESH_MS = 30_000;
const MAINTENANCE_GRACE_MS = 120_000;
const MAINTENANCE_TIMEOUT_MS = 2_500;
const MAINTENANCE_EDGE_CACHE_HEADERS = {
  "Cache-Control": "public, max-age=30, stale-while-revalidate=120",
};

// Mirrors `lastGoodStatusSnapshot`: the edge cache is shared between isolates
// but missing in tests and on a cold start, so each isolate keeps its own copy.
let lastMaintenanceState = null;
```

Add these two functions immediately before `export default`:

```javascript
function maintenanceFromHealth(health) {
  const raw = health && typeof health === "object" ? health.maintenance : null;
  // A bot that predates this field is not in maintenance. This is the rule that
  // makes deploy order irrelevant.
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
    // 503 is what the bot returns when its database probe fails; the payload is
    // still there and still tells the truth about maintenance.
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
    // A restart lasts seconds; hold the last real answer through it. The last
    // answer is not overwritten here, so recovery is noticed on the very next
    // request rather than after another freshness window.
    if (known && !known.unreachable && now - known.fetchedAt < MAINTENANCE_GRACE_MS) {
      return known;
    }
    // Past the grace window the API is genuinely gone, and a dashboard that
    // cannot reach it would only render errors. Remember the verdict so a long
    // outage is not one upstream attempt per request.
    const state = { enabled: true, message: "", fetchedAt: now, unreachable: true };
    lastMaintenanceState = state;
    return state;
  }
}
```

In the `fetch` handler, replace the dashboard branch:

```javascript
    // The dashboard owns its nested routes client-side. Serve its static shell
    // on direct visits so refreshes at /dashboard/g/:id keep working.
    if (url.pathname.startsWith("/dashboard/")) {
      const maintenance = await readMaintenance(request, env, ctx);
      if (maintenance.enabled) return serveMaintenancePage(request, env, maintenance);
      if (url.pathname !== "/dashboard/") {
        return serveAsset(new Request(new URL("/dashboard/", request.url), request), env);
      }
    }
```

Add a temporary definition of `serveMaintenancePage` before `export default` — Task 3 replaces its body:

```javascript
async function serveMaintenancePage(request, env, state) {
  const asset = await serveAsset(
    new Request(new URL("/maintenance/", request.url), request),
    env,
  );
  return new Response(asset.body, { status: 503, headers: new Headers(asset.headers) });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd website-3 && npx vitest run worker/index.test.js`
Expected: all four new tests PASS, and every pre-existing test still passes.

- [ ] **Step 5: Commit**

```bash
git add website-3/worker/index.js website-3/worker/index.test.js
git commit -m "Close the dashboard when the bot reports maintenance"
```

---

### Task 3: The maintenance response carries the message

**Files:**
- Modify: `website-3/worker/index.js` — `serveMaintenancePage`, plus a new `escapeHtml` helper
- Test: `website-3/worker/index.test.js`

**Interfaces:**
- Consumes: `readMaintenance()` from Task 2 → `{enabled, message, …}`.
- Produces: a 503 response whose body has `<!--ng:message-->` replaced by the escaped message, or by nothing when there is no message. Task 4 places that comment in the page.

**Note on approach:** the spec named `HTMLRewriter`. It does not exist in the `@vitest-environment node` harness this suite uses, so every injection test would be unrunnable. The page is under 4 KB and the substitution is one known token, so a string replacement with explicit escaping is used instead. Same result, testable in the harness that exists.

- [ ] **Step 1: Write the failing test**

Add inside the `describe("maintenance sync", …)` block from Task 2, before its closing brace:

```javascript
  const pageEnv = {
    ...env,
    STATUS_API_BASE: "https://api.example.test/api/v1",
    ASSETS: {
      fetch: async (request) =>
        new URL(request.url).pathname === "/maintenance/"
          ? new Response('<p class="message"><!--ng:message--></p>', {
              status: 200,
              headers: { "Content-Type": "text/html" },
            })
          : new Response(new URL(request.url).pathname, { status: 200 }),
    },
  };

  it("puts the bot's message on the page", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true, message: "Music install" } }));

    const response = await dashboardRequest(pageEnv);

    expect(response.status).toBe(503);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(response.headers.get("Retry-After")).toBe("120");
    await expect(response.text()).resolves.toContain("Music install");
  });

  it("escapes a message instead of rendering it", async () => {
    vi.stubGlobal(
      "fetch",
      healthStub({ maintenance: { enabled: true, message: "<img src=x onerror=alert(1)>" } }),
    );

    const body = await (await dashboardRequest(pageEnv)).text();

    expect(body).not.toContain("<img");
    expect(body).toContain("&lt;img");
  });

  it("leaves the placeholder empty when there is no message", async () => {
    vi.stubGlobal("fetch", healthStub({ maintenance: { enabled: true } }));

    const body = await (await dashboardRequest(pageEnv)).text();

    expect(body).toContain('<p class="message"></p>');
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd website-3 && npx vitest run worker/index.test.js`
Expected: FAIL — `expected null to be "no-store"`, and the body still contains the raw comment.

- [ ] **Step 3: Write the implementation**

Add beside the other small helpers in `website-3/worker/index.js`:

```javascript
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
```

Replace `serveMaintenancePage` from Task 2 with:

```javascript
async function serveMaintenancePage(request, env, state) {
  const asset = await serveAsset(
    new Request(new URL("/maintenance/", request.url), request),
    env,
  );
  if (!asset.ok) {
    // The page is missing from the build. The dashboard at least explains
    // itself; serving nothing does not.
    return serveAsset(new Request(new URL("/dashboard/", request.url), request), env);
  }

  const html = await asset.text();
  // The owner is the only one who can set this text, but it still goes through
  // escaping — the page is public and the cost is nothing.
  const body = html.replace("<!--ng:message-->", state.message ? escapeHtml(state.message) : "");

  const headers = new Headers(asset.headers);
  // Without no-store a browser keeps showing maintenance after it ends — a bug
  // that surfaces an hour later, to one person, and looks like nothing.
  headers.set("Cache-Control", "no-store");
  headers.set("Retry-After", "120");
  headers.delete("Content-Length");
  return new Response(body, { status: 503, headers });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd website-3 && npx vitest run worker/index.test.js`
Expected: every test in the file passes.

- [ ] **Step 5: Commit**

```bash
git add website-3/worker/index.js website-3/worker/index.test.js
git commit -m "Show the maintenance reason on the page"
```

---

### Task 4: The page, in the Coming Soon theme

**Files:**
- Rewrite: `website-3/src/pages/maintenance.astro`
- Modify: `cogs/system.py` — the "Maintenance Enabled" embed

**Interfaces:**
- Consumes: the `<!--ng:message-->` token contract from Task 3.
- Produces: nothing other tasks read.

- [ ] **Step 1: Rewrite the page**

Replace the whole of `website-3/src/pages/maintenance.astro`:

```astro
---
// Deliberately standalone: no Base layout, no site CSS, no islands. This page
// renders precisely when something else is broken, so every dependency it drops
// is one less way for it to fail. The look is the Coming Soon face — same
// palette, type scale and motion — so the two read as one product.
---

<!doctype html>
<html lang="en" data-theme="dark">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <meta name="theme-color" content="#0a0a0a" />
    <title>Maintenance — NovaGuard</title>
    <meta name="description" content="The NovaGuard dashboard is briefly closed for maintenance." />
    <meta name="robots" content="noindex" />
    <link rel="icon" type="image/png" href="/assets/novaguard-icon-96.png" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@500;600;800&display=swap"
    />
    <script is:inline>
      // Pre-paint, so the page never flashes the wrong theme. Coming Soon stores
      // its choice under a different key than the rest of the site; read both so
      // a theme picked on either surface holds here.
      (() => {
        let theme = "dark";
        try {
          const stored =
            localStorage.getItem("ng-theme") || localStorage.getItem("ng-maintenance-theme");
          if (stored === "light") theme = "light";
        } catch (error) {
          // Private browsing or blocked storage. Dark is the default anyway.
        }
        document.documentElement.dataset.theme = theme;
      })();
    </script>
    <style is:global>
      :root {
        color-scheme: dark;
        --background: #0a0a0a;
        --foreground: #f5f5f5;
        --muted: #8a8a8a;
        --line: #2a2a2a;
      }
      :root[data-theme="light"] {
        color-scheme: light;
        --background: #fafafa;
        --foreground: #101010;
        --muted: #747474;
        --line: #dedede;
      }
      * {
        box-sizing: border-box;
      }
      html,
      body {
        min-height: 100%;
        max-width: 100%;
        overflow-x: clip;
      }
      body {
        margin: 0;
        background: var(--background);
        color: var(--foreground);
        font-family: Manrope, ui-sans-serif, system-ui, sans-serif;
        transition:
          background-color 0.18s ease,
          color 0.18s ease;
      }
      .page {
        position: relative;
        display: flex;
        min-height: 100dvh;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 1.5rem;
      }
      .theme-toggle {
        position: absolute;
        top: 1.5rem;
        right: 1.5rem;
        display: grid;
        width: 36px;
        height: 36px;
        place-items: center;
        padding: 0;
        border: 1px solid var(--line);
        border-radius: 50%;
        background: transparent;
        color: var(--foreground);
        cursor: pointer;
        transition:
          border-color 0.18s ease,
          transform 0.18s ease;
      }
      .theme-toggle:hover {
        transform: scale(1.06);
      }
      .theme-toggle:focus-visible {
        outline: 2px solid var(--foreground);
        outline-offset: 3px;
      }
      .content {
        display: flex;
        width: 100%;
        max-width: 32rem;
        flex-direction: column;
        align-items: center;
        text-align: center;
      }
      h1 {
        margin: 0;
        font-size: clamp(3rem, 10vw, 8rem);
        font-weight: 800;
        letter-spacing: -0.075em;
        line-height: 0.9;
      }
      .eyebrow {
        margin: 1.15rem 0 0;
        color: var(--muted);
        font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: clamp(1rem, 1.5vw, 1.12rem);
        letter-spacing: 0.08em;
      }
      .description {
        margin: 0.7rem auto 0;
        color: var(--muted);
        font-size: clamp(0.94rem, 1.45vw, 1.04rem);
        line-height: 1.6;
      }
      /* Filled by the worker from whatever the owner typed into /maintenance.
         Empty on a direct visit, and an element holding only a comment still
         counts as :empty, so nothing shows when there is no reason to show. */
      .message {
        margin: 1.1rem auto 0;
        max-width: 26rem;
        padding: 0.55rem 0.9rem;
        border: 1px solid var(--line);
        border-radius: 999px;
        color: var(--foreground);
        font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 0.85rem;
        line-height: 1.5;
      }
      .message:empty {
        display: none;
      }
      .signout {
        margin-top: 1.8rem;
        padding: 0.5rem 1rem;
        border: 1px solid var(--line);
        border-radius: 999px;
        color: var(--muted);
        font-size: 0.82rem;
        text-decoration: none;
        transition:
          color 0.18s ease,
          border-color 0.18s ease;
      }
      .signout:hover {
        border-color: var(--foreground);
        color: var(--foreground);
      }
      .signout:focus-visible {
        outline: 2px solid var(--foreground);
        outline-offset: 3px;
      }
      .credit {
        margin: 2rem 0 0;
        color: var(--muted);
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.08em;
      }
      @media (max-width: 540px) {
        .page {
          padding: 1rem;
        }
        .theme-toggle {
          top: 1rem;
          right: 1rem;
          min-width: 44px;
          min-height: 44px;
        }
        h1 {
          font-size: 50px;
          line-height: 0.92;
        }
        .credit {
          font-size: 0.64rem;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        * {
          transition: none !important;
        }
      }
    </style>
  </head>
  <body>
    <main class="page">
      <button type="button" class="theme-toggle" aria-label="Switch theme"></button>

      <div class="content">
        <h1>NovaGuard</h1>
        <p class="eyebrow">Maintenance</p>
        <p class="description">
          The dashboard is paused for a moment while NovaGuard is being updated.
        </p>
        <p class="message"><!--ng:message--></p>
        <a class="signout" href="/api/auth/logout">Sign out</a>
        <p class="credit">Developed by VIK &amp; CloudMedia</p>
      </div>
    </main>

    <script is:inline>
      (() => {
        const icons = {
          dark: '<svg stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2"></path><path d="M12 20v2"></path><path d="m4.93 4.93 1.41 1.41"></path><path d="m17.66 17.66 1.41 1.41"></path><path d="M2 12h2"></path><path d="M20 12h2"></path><path d="m6.34 17.66-1.41 1.41"></path><path d="m19.07 4.93-1.41 1.41"></path></svg>',
          light: '<svg stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path></svg>',
        };
        const button = document.querySelector(".theme-toggle");

        const render = () => {
          const theme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
          const label = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
          button.innerHTML = icons[theme];
          button.setAttribute("aria-label", label);
          button.setAttribute("title", label);
        };

        button.addEventListener("click", () => {
          const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
          document.documentElement.dataset.theme = next;
          // Written under both keys so the choice survives whichever page the
          // visitor lands on next.
          try {
            localStorage.setItem("ng-theme", next);
            localStorage.setItem("ng-maintenance-theme", next);
          } catch (error) {
            // Storage blocked. The toggle still works for this page view.
          }
          document
            .querySelector('meta[name="theme-color"]')
            ?.setAttribute("content", next === "light" ? "#fafafa" : "#0a0a0a");
          render();
        });

        render();
      })();
    </script>
  </body>
</html>
```

- [ ] **Step 2: Build the site and confirm the token survives**

Run: `cd website-3 && npm run build`
Expected: build succeeds.

Run: `cd website-3 && grep -c "ng:message" dist/maintenance/index.html`
Expected: `1` — Astro must not have stripped the HTML comment. If it prints `0`, the comment was removed; replace `<!--ng:message-->` with `<span data-ng-message></span>` in the page, change the `.replace()` target in `serveMaintenancePage` to `'<span data-ng-message></span>'`, adjust the Task 3 tests to match, and re-run both suites.

- [ ] **Step 3: Verify the page in the browser**

Start the dev server with preview_start, open `/maintenance/`, and confirm: dark by default, wordmark at full size, the toggle flips to light and back, no message pill visible. Resize to 375 px wide and confirm the wordmark drops to 50 px with nothing overflowing horizontally.

- [ ] **Step 4: Mention the dashboard in the confirmation embed**

In `cogs/system.py`, in the `action.value == "enable"` branch, replace the embed description:

```python
            embed = make_embed(
                "🛠️ Maintenance Enabled",
                "NovaGuard is now in maintenance mode.\n"
                "Regular users will see a maintenance notice instead of command results, "
                "and the website dashboard is closed with the same message.",
                color=Palette.WARNING,
            )
```

- [ ] **Step 5: Run every test**

Run: `python -m pytest tests -q`
Expected: no failures.

Run: `cd website-3 && npx vitest run`
Expected: no failures.

- [ ] **Step 6: Commit**

```bash
git add website-3/src/pages/maintenance.astro cogs/system.py
git commit -m "Rebuild the maintenance page in the Coming Soon theme"
```

---

## After the plan

`docs/superpowers/plans/2026-08-04-music-system.md` describes a music system that
has since been built differently — with a Lavalink backend and audio filters the
plan never mentioned. Mark it superseded so nobody reads it as instructions.
