# Maintenance Preview Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A code generated at each maintenance activation lets the operator walk through the closed site before anyone else can.

**Architecture:** The bot generates the code, stores only its scrypt hash, and shows the plaintext once in Discord. The worker forwards a submitted code to a new bot endpoint, which answers yes or no; on yes the worker sets a signed cookie bound to that activation, and the maintenance gate lets that visitor through.

**Tech Stack:** Python 3.12 / aiohttp (bot), Cloudflare Workers (JS, vitest), Astro 5 (the form page).

## Global Constraints

- `GET /api/v1/health` is **public**. It may carry `since`; it must never carry the code, the hash, or the salt.
- The code rotates only on the **off → on** transition. Re-running `enable` while already on keeps both the code and `updated_at`, or an open preview session would die on a wording fix.
- The plaintext code is returned to the caller **once** and never written to `data/maintenance.json`.
- Every verification failure — wrong code, no code, maintenance off — returns the **same** 401 body.
- Preview cookie: `ng_preview`, HttpOnly, Secure, SameSite=Lax, HMAC-signed with `AUTH_PASSWORD`, 12-hour TTL, carrying the activation's `since`.
- An unreachable bot grants **no** bypass.
- `_rate_limit(request, "auth")` already throttles 10 requests per 60 s per visitor IP — `_client_ip` reads `CF-Connecting-IP` under `TRUST_PROXY`, so no new counter is needed.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `core/maintenance.py` | Generate, store, clear and verify the code | 1 |
| `cogs/system.py` | Show the code once in the enable embed | 1 |
| `core/webserver.py` | `since` on `/health`; the verify route | 2 |
| `tests/test_webserver.py` | Both bot halves | 1, 2 |
| `website-3/worker/index.js` | Preview cookie, `/api/preview`, gate bypass | 3 |
| `website-3/worker/index.test.js` | Worker behaviour | 3 |
| `website-3/src/pages/preview.astro` | The form | 4 |
| `website-3/src/pages/maintenance.astro` | Drop the dead Sign out button | 4 |

---

### Task 1: The bot owns the code

**Files:**
- Modify: `core/maintenance.py`
- Modify: `cogs/system.py` — the `action.value == "enable"` branch
- Test: `tests/test_webserver.py`

**Interfaces:**
- Consumes: `hash_key(plaintext, salt=None) -> (hash_hex, salt_hex)` and `verify_key(plaintext, key_hash, salt) -> bool` from `core/admin_auth.py`.
- Produces:
  - `generate_preview_code() -> str` — `"ng_preview_<token>"`.
  - `save_maintenance_state(enabled, message=None, updated_by=None) -> dict` — unchanged signature. The returned dict now carries `preview_code` (plaintext, or `None`); the file on disk never does.
  - `verify_preview_code(code) -> str | None` — the activation's `updated_at` when the code is right and maintenance is on, otherwise `None`. Task 2 consumes this.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_webserver.py`, inside the existing maintenance `try:` block, right after the two `/health` checks:

```python
            # ── preview code lifecycle ────────────────────────────────
            first = save_maintenance_state(True, "Preview test", updated_by="test-suite")
            code = first.get("preview_code")
            await check("enabling from off mints a code", bool(code) and code.startswith("ng_preview_"))

            raw_file = json.loads(MAINTENANCE_STATE_FILE.read_text(encoding="utf-8"))
            await check(
                "the code itself is never written to disk",
                "preview_code" not in raw_file
                and code not in raw_file.values()
                and bool(raw_file.get("preview_hash")),
            )

            again = save_maintenance_state(True, "Corrected wording", updated_by="test-suite")
            await check(
                "re-enabling while on keeps the code and the activation time",
                again.get("preview_code") is None
                and again["preview_hash"] == first["preview_hash"]
                and again["updated_at"] == first["updated_at"],
            )

            await check("the right code verifies", verify_preview_code(code) == first["updated_at"])
            await check("a wrong code does not", verify_preview_code("ng_preview_nope") is None)

            save_maintenance_state(False, updated_by="test-suite")
            await check(
                "disabling clears the code",
                verify_preview_code(code) is None
                and load_maintenance_state().get("preview_hash") is None,
            )
```

Replace the existing `core.maintenance` import at the top of the file with:

```python
from core.maintenance import (  # noqa: E402
    MAINTENANCE_STATE_FILE,
    load_maintenance_state,
    save_maintenance_state,
    verify_preview_code,
)
```

`json` is already imported in this file.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_webserver.py`
Expected: `ImportError: cannot import name 'verify_preview_code'`.

- [ ] **Step 3: Write the implementation**

In `core/maintenance.py`, add to the imports:

```python
import secrets

from .admin_auth import hash_key, verify_key
```

Add beside the other constants:

```python
PREVIEW_PREFIX = "ng_preview_"
PREVIEW_BYTES = 24
```

Extend `_default_state`:

```python
def _default_state():
    return {
        "enabled": False,
        "message": DEFAULT_MAINTENANCE_MESSAGE,
        "updated_at": None,
        "updated_by": None,
        # Only ever the hash. The code itself is shown once, in Discord.
        "preview_hash": None,
        "preview_salt": None,
    }
```

Add:

```python
def generate_preview_code():
    """A fresh preview code. Returned in plaintext once, never stored."""
    return f"{PREVIEW_PREFIX}{secrets.token_urlsafe(PREVIEW_BYTES)}"
```

Replace `save_maintenance_state`:

```python
def save_maintenance_state(enabled, message=None, updated_by=None):
    previous = load_maintenance_state()
    state = _default_state()
    state["enabled"] = bool(enabled)
    state["message"] = normalize_maintenance_message(message)
    state["updated_at"] = datetime.now(UTC).isoformat()
    state["updated_by"] = updated_by

    code = None
    if state["enabled"]:
        if previous.get("enabled") and previous.get("preview_hash"):
            # Already on — this is a wording fix, not a new maintenance window.
            # Keeping the hash and the timestamp keeps the operator's own open
            # preview session alive; rotating here would lock them out for
            # correcting a typo.
            state["preview_hash"] = previous.get("preview_hash")
            state["preview_salt"] = previous.get("preview_salt")
            state["updated_at"] = previous.get("updated_at") or state["updated_at"]
        else:
            code = generate_preview_code()
            state["preview_hash"], state["preview_salt"] = hash_key(code)

    MAINTENANCE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = MAINTENANCE_STATE_FILE.with_name(MAINTENANCE_STATE_FILE.name + ".tmp")
    temp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temp_path, MAINTENANCE_STATE_FILE)

    # After the write, so the plaintext reaches the caller and nothing else.
    return {**state, "preview_code": code}


def verify_preview_code(code):
    """The activation's timestamp when the code opens the site, else None."""
    state = load_maintenance_state()
    if not state.get("enabled"):
        return None
    if not verify_key(code, state.get("preview_hash"), state.get("preview_salt")):
        return None
    return state.get("updated_at")
```

`load_maintenance_state` needs no change: it starts from `_default_state()` and updates from the file, so the two new keys default to `None`.

In `cogs/system.py`, in the `action.value == "enable"` branch, after the existing `embed.add_field(name="Presence", …)` line, add:

```python
            preview_code = state.get("preview_code")
            if preview_code:
                embed.add_field(
                    name="Preview code",
                    value=(
                        f"||`{preview_code}`||\n"
                        "Use it at `novaguard.fun/preview/` to walk the closed site. "
                        "Shown once — it will not be repeated."
                    ),
                    inline=False,
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_webserver.py`
Expected: every check passes, including the six new ones.

Run: `python3 -m pytest tests -q`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add core/maintenance.py cogs/system.py tests/test_webserver.py
git commit -m "Mint a preview code when maintenance starts"
```

---

### Task 2: The bot answers whether a code is right

**Files:**
- Modify: `core/webserver.py` — the route table, `handle_health`, a new handler
- Test: `tests/test_webserver.py`

**Interfaces:**
- Consumes: `verify_preview_code(code) -> str | None` from Task 1.
- Produces:
  - `GET /api/v1/health` → `maintenance` gains `since` (the activation timestamp) when enabled.
  - `POST /api/v1/maintenance/preview` → `{"code": "…"}` answers `200 {"ok": true, "since": "…"}` or `401 {"code": "invalid_preview_code", …}`. Task 3 consumes this.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_webserver.py`, immediately after the Task 1 block and still inside the same `try:`:

```python
            # ── the verify route ──────────────────────────────────────
            live = save_maintenance_state(True, "Preview route", updated_by="test-suite")
            live_code = live["preview_code"]

            async with http.get(f"{V1}/health") as r:
                data = await r.json()
                await check(
                    "health publishes when maintenance began, and no secrets",
                    data["maintenance"]["since"] == live["updated_at"]
                    and "preview_hash" not in data["maintenance"]
                    and "preview_salt" not in data["maintenance"]
                    and "preview_code" not in data["maintenance"],
                )

            async with http.post(f"{V1}/maintenance/preview", json={"code": live_code}) as r:
                data = await r.json()
                await check(
                    "the right code is accepted",
                    r.status == 200 and data["ok"] is True and data["since"] == live["updated_at"],
                )

            async with http.post(f"{V1}/maintenance/preview", json={"code": "ng_preview_wrong"}) as r:
                wrong_status, wrong_body = r.status, await r.text()
            await check("a wrong code is refused", wrong_status == 401)

            save_maintenance_state(False, updated_by="test-suite")
            async with http.post(f"{V1}/maintenance/preview", json={"code": live_code}) as r:
                off_status, off_body = r.status, await r.text()
            await check(
                "a code sent while maintenance is off is indistinguishable from a wrong one",
                off_status == wrong_status and off_body == wrong_body,
            )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_webserver.py`
Expected: `FAIL health publishes when maintenance began, and no secrets`, then a 404 on the unknown route.

- [ ] **Step 3: Write the implementation**

In `core/webserver.py`, extend the maintenance import:

```python
from .maintenance import (
    DEFAULT_MAINTENANCE_MESSAGE,
    load_maintenance_state,
    verify_preview_code,
)
```

In `handle_health`, extend the maintenance object:

```python
        maintenance = {"enabled": bool(state.get("enabled"))}
        if maintenance["enabled"]:
            maintenance["message"] = state.get("message") or DEFAULT_MAINTENANCE_MESSAGE
            # Which activation this is. Not a secret — it only says when the
            # window opened — and the website binds preview cookies to it so a
            # code from a previous window stops working.
            maintenance["since"] = state.get("updated_at")
```

Add to the `routes` list, after the `/updates` line:

```python
            ("POST", "/maintenance/preview", self.handle_maintenance_preview),
```

Add the handler beside `handle_health`:

```python
    async def handle_maintenance_preview(self, request):
        # "auth" is 10 requests per 60 s, keyed on the visitor's real address —
        # _client_ip reads CF-Connecting-IP, so the proxy does not merge
        # everyone into one bucket.
        self._rate_limit(request, "auth")
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            body = {}
        code = body.get("code") if isinstance(body, dict) else None
        since = await asyncio.to_thread(
            verify_preview_code, code if isinstance(code, str) else ""
        )
        if not since:
            # One answer for a wrong code, a missing one, and a valid one sent
            # while maintenance is off. Nothing here tells a guesser whether a
            # code exists, let alone whether they are close.
            raise ApiError(401, "That preview code is not valid.", code="invalid_preview_code")
        return web.json_response({"ok": True, "since": since})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_webserver.py`
Expected: all checks pass.

Run: `python3 -m pytest tests -q`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add core/webserver.py tests/test_webserver.py
git commit -m "Answer whether a preview code opens the site"
```

---

### Task 3: The worker lets a holder through

**Files:**
- Modify: `website-3/worker/index.js`
- Test: `website-3/worker/index.test.js`

**Interfaces:**
- Consumes: `POST {apiBase}/maintenance/preview` from Task 2; `readMaintenance(request, env, ctx)` which returns `{enabled, message, since, fetchedAt, unreachable?}`.
- Produces: cookie `ng_preview`; route `POST /api/preview`.

Note: `maintenanceFromHealth` must start carrying `since`, or the cookie has nothing to bind to.

- [ ] **Step 1: Write the failing test**

Add inside the `describe("maintenance sync", …)` block:

```javascript
  async function previewCookie(testEnv, code = "ng_preview_good") {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ code }),
      }),
      testEnv,
    );
    const header = response.headers.get("set-cookie");
    return { response, cookie: header ? header.split(";")[0] : null };
  }

  function previewStub({ ok = true, since = "2026-08-11T06:16:05+00:00" } = {}) {
    return vi.fn(async (input) => {
      const target = String(typeof input === "string" ? input : input.url);
      if (target.endsWith("/maintenance/preview")) {
        return ok
          ? Response.json({ ok: true, since })
          : Response.json({ code: "invalid_preview_code" }, { status: 401 });
      }
      return Response.json({
        ok: true,
        maintenance: { enabled: true, message: "Music Update", since },
      });
    });
  }

  it("lets a holder of the code walk the closed site", async () => {
    vi.stubGlobal("fetch", previewStub());

    const { cookie } = await previewCookie(apiEnv);
    expect(cookie).toContain("ng_preview=");

    const page = await worker.fetch(
      new Request("https://novaguard.fun/home/", { headers: { cookie } }),
      apiEnv,
    );

    expect(page.status).not.toBe(503);
  });

  it("refuses a wrong code without setting a cookie", async () => {
    vi.stubGlobal("fetch", previewStub({ ok: false }));

    const { response, cookie } = await previewCookie(apiEnv, "ng_preview_wrong");

    // Back to the form with a flag, not a bare 401: the visitor needs to be
    // able to retype it.
    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toContain("/preview/?error=1");
    expect(cookie).toBeNull();
  });

  it("sets no cookie when the bot cannot be reached", async () => {
    // Failing closed on the door is the opposite of failing closed on the site,
    // and both are the safe direction.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("connection refused");
      }),
    );

    const { cookie } = await previewCookie(apiEnv);

    expect(cookie).toBeNull();
  });

  it("stops honouring a code once a new maintenance window opens", async () => {
    vi.stubGlobal("fetch", previewStub({ since: "2026-08-11T06:00:00+00:00" }));
    const { cookie } = await previewCookie(apiEnv);

    vi.setSystemTime(Date.now() + 60 * 60 * 1000);
    // Same site, new activation: the cookie is bound to the old one.
    vi.stubGlobal("fetch", previewStub({ since: "2026-08-11T09:00:00+00:00" }));

    const page = await worker.fetch(
      new Request("https://novaguard.fun/home/", { headers: { cookie } }),
      apiEnv,
    );

    expect(page.status).toBe(503);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd website-3 && npx vitest run worker/index.test.js`
Expected: FAIL — `expected null to contain "ng_preview="`, because `/api/preview` does not exist yet.

- [ ] **Step 3: Write the implementation**

In `website-3/worker/index.js`, add beside the other cookie constants:

```javascript
const PREVIEW_COOKIE = "ng_preview";
const PREVIEW_TTL_SECONDS = 60 * 60 * 12;
```

Carry `since` through `maintenanceFromHealth` — replace its return:

```javascript
  return {
    enabled,
    message: enabled && typeof raw.message === "string" ? raw.message : "",
    since: enabled && typeof raw.since === "string" ? raw.since : "",
  };
```

and its early return for a missing field:

```javascript
  if (!raw || typeof raw !== "object") return { enabled: false, message: "", since: "" };
```

Add beside `createSession` / `isValidSession`:

```javascript
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
      // Bound to one activation: a code shared during a previous window opens
      // nothing during this one.
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
  } catch (error) {
    // Unreachable bot means no bypass. Failing closed on the door is the
    // opposite of failing closed on the site, and both are the safe direction.
    verified = null;
  }

  if (!verified || !verified.since) {
    // Back to the form with a flag rather than a bare error page: a wrong code
    // is usually a typo, and the visitor needs somewhere to retype it. The flag
    // says nothing about which failure it was.
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
```

In the `fetch` handler, register the route beside the other `/api/` ones:

```javascript
    if (url.pathname === "/api/preview") return handlePreview(request, env);
```

Let a valid cookie through the gate — replace the whole-site maintenance branch:

```javascript
    const maintenance = await readMaintenance(request, env, ctx);
    if (maintenance.enabled && !maintenance.unreachable) {
      const holder = await isValidPreview(
        readCookie(request, PREVIEW_COOKIE),
        env.AUTH_PASSWORD,
        maintenance.since,
      );
      if (!holder) return serveMaintenancePage(request, env, maintenance);
    }
```

Keep `/preview/` reachable while the site is closed — add to `isAlwaysOpenPath`:

```javascript
    pathname === "/preview" ||
    pathname === "/preview/" ||
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd website-3 && npx vitest run worker/index.test.js`
Expected: every test passes.

- [ ] **Step 5: Commit**

```bash
git add website-3/worker/index.js website-3/worker/index.test.js
git commit -m "Let a preview code open the closed site"
```

---

### Task 4: The form, and the dead button

**Files:**
- Create: `website-3/src/pages/preview.astro`
- Modify: `website-3/src/pages/maintenance.astro` — remove the Sign out link and its styles

**Interfaces:**
- Consumes: `POST /api/preview` from Task 3.
- Produces: nothing other tasks read.

- [ ] **Step 1: Create the form page**

`website-3/src/pages/preview.astro`. It mirrors the maintenance page's palette and type, standalone for the same reason.

```astro
---
// Reachable while the site is closed, and linked from nowhere: a door nobody
// can see is a door nobody rattles. Same standalone construction as the
// maintenance page — it has to render when the rest of the site will not.
const failed = Astro.url.searchParams.has("error");
---

<!doctype html>
<html lang="en" data-theme="dark">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <meta name="theme-color" content="#0a0a0a" />
    <title>Preview access — NovaGuard</title>
    <meta name="robots" content="noindex" />
    <link rel="icon" type="image/png" href="/assets/novaguard-icon-96.png" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@500;600;800&display=swap"
    />
    <style is:global>
      :root {
        color-scheme: dark;
        --background: #0a0a0a;
        --foreground: #f5f5f5;
        --muted: #8a8a8a;
        --line: #2a2a2a;
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        min-height: 100dvh;
        display: grid;
        place-items: center;
        padding: 1.5rem;
        background: var(--background);
        color: var(--foreground);
        font-family: Manrope, ui-sans-serif, system-ui, sans-serif;
      }
      .content {
        width: 100%;
        max-width: 22rem;
        text-align: center;
      }
      h1 {
        margin: 0;
        font-size: clamp(2rem, 7vw, 3rem);
        font-weight: 800;
        letter-spacing: -0.05em;
        line-height: 0.95;
      }
      .eyebrow {
        margin: 0.9rem 0 1.6rem;
        color: var(--muted);
        font-family: "DM Mono", ui-monospace, monospace;
        font-size: 0.9rem;
        letter-spacing: 0.08em;
      }
      input {
        width: 100%;
        padding: 0.7rem 0.9rem;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: transparent;
        color: var(--foreground);
        font-family: "DM Mono", ui-monospace, monospace;
        font-size: 0.85rem;
        text-align: center;
      }
      input:focus {
        border-color: var(--foreground);
        outline: none;
      }
      button {
        width: 100%;
        margin-top: 0.7rem;
        padding: 0.7rem 0.9rem;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: var(--foreground);
        color: var(--background);
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.18s ease;
      }
      button:hover {
        opacity: 0.85;
      }
      .error {
        margin: 1rem 0 0;
        color: var(--muted);
        font-size: 0.8rem;
      }
      @media (prefers-reduced-motion: reduce) {
        * {
          transition: none !important;
        }
      }
    </style>
  </head>
  <body>
    <main class="content">
      <h1>NovaGuard</h1>
      <p class="eyebrow">Preview access</p>

      <form method="POST" action="/api/preview">
        <input
          type="password"
          name="code"
          autocomplete="off"
          autofocus
          aria-label="Preview code"
          placeholder="preview code"
        />
        <button type="submit">Enter</button>
      </form>

      {failed && <p class="error">That code did not work. Check it and try again.</p>}
    </main>
  </body>
</html>
```

- [ ] **Step 2: Remove the dead Sign out button**

In `website-3/src/pages/maintenance.astro`, delete this line from the markup:

```astro
        <a class="signout" href="/api/auth/logout">Sign out</a>
```

and delete its three rules from the `<style is:global>` block — `.signout`, `.signout:hover`, `.signout:focus-visible`.

It made sense when maintenance covered only routes reached after the password gate. The gate now runs first, so clearing the session changed nothing a visitor could see.

- [ ] **Step 3: Build and verify**

Run: `cd website-3 && npm run build`
Expected: build succeeds.

Run: `cd website-3 && grep -c "signout" dist/maintenance/index.html`
Expected: `0`.

Run: `cd website-3 && grep -c "ng:message" dist/maintenance/index.html`
Expected: `1` — the message token must survive the edit.

Run: `cd website-3 && grep -c "preview" dist/maintenance/index.html`
Expected: `0` — the maintenance page must not advertise the door.

- [ ] **Step 4: Run every test**

Run: `python3 -m pytest tests -q`
Expected: no failures.

Run: `cd website-3 && npx vitest run`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add website-3/src/pages/preview.astro website-3/src/pages/maintenance.astro
git commit -m "Add the preview form and drop the dead Sign out button"
```
