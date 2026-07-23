# NovaGuard Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `website-3/` into the full NovaGuard site — editorial landing + React admin dashboard consuming the bot's `/api/v1` (spec: `docs/superpowers/specs/2026-07-18-novaguard-website-design.md`).

**Architecture:** Astro 5 static site; landing pages are zero-JS Astro components; the dashboard is a React 19 island under `/dashboard` using TanStack Router (basepath) + TanStack Query; a shared typed API client with Zod schemas mirrors `docs/API.md` exactly. Legacy Coming Soon page is preserved byte-identical under `public/coming-soon/`.

**Tech Stack:** Astro ^5, @astrojs/react, React ^19, tailwindcss ^4 (@tailwindcss/vite), @tanstack/react-router, @tanstack/react-query ^5, zod ^3, @fontsource-variable/newsreader, @fontsource-variable/inter, vitest + @testing-library/react + happy-dom.

## Global Constraints

- Node ≥ 20 (machine has v24.13.1). TypeScript `strict: true`.
- No dependencies beyond the Tech Stack list. No motion library — CSS transitions only; every animation guarded by `prefers-reduced-motion`.
- All copy in English. Creator credit: `Developed by VIK & CloudMediaSRL`.
- Coming Soon page files byte-identical (git mv only). `_redirects` keeps `/hq https://novaguard.fun 301`.
- API errors branch on `code` field, never message text (API.md contract).
- Every fetch to the API sends `credentials: "include"`. Login is a browser navigation, not fetch.
- Design tokens (single source, `src/styles/global.css`): paper `#FAF9F5`, surface `#FFFFFF`, ink `#1C1917`, ink-muted `#6F6A61`, line `#E7E3DA`, accent `#8C2B1A` (brick — 8.0:1 on paper, 8.5:1 white-on-accent, AA+), display font Newsreader Variable, UI font Inter Variable.
- `PUBLIC_API_BASE` env var = bot API origin, no trailing slash (dev default `http://localhost:8081`; adjust in `.env` if the bot uses another port).
- Commit after every task on branch `claude/discord-bot-website-0ee62c`.

---

### Task 1: Scaffold, legacy preservation, tokens, Base layout

**Files:**
- Move (git mv, byte-identical): `website-3/index.html` → `website-3/public/coming-soon/index.html`; `website-3/overrides.css` → `website-3/public/coming-soon/overrides.css`; `website-3/assets/` → `website-3/public/coming-soon/assets/`
- Copy: `website-3/public/coming-soon/assets/novaguard-icon.png` → `website-3/public/favicon.png`
- Create: `website-3/package.json`, `website-3/astro.config.mjs`, `website-3/tsconfig.json`, `website-3/.gitignore`, `website-3/.env.example`, `website-3/src/styles/global.css`, `website-3/src/layouts/Base.astro`, `website-3/src/pages/index.astro` (placeholder shell, real content Task 2)
- Rewrite: `website-3/_redirects` → `website-3/public/_redirects`

**Interfaces:**
- Produces: `Base.astro` props `{ title: string; description?: string }`; token CSS vars + Tailwind theme (`bg-paper`, `text-ink`, `text-ink-muted`, `border-line`, `bg-accent`, `font-display`, `font-sans`) used by every later task.

- [ ] **Step 1: Relocate legacy page (byte-identical) and favicon**

```bash
cd website-3
mkdir -p public/coming-soon
git mv index.html public/coming-soon/index.html
git mv overrides.css public/coming-soon/overrides.css
git mv assets public/coming-soon/assets
cp public/coming-soon/assets/novaguard-icon.png public/favicon.png
git rm _redirects   # recreated in public/ below
```
Legacy `index.html` references `./assets/…` and `./overrides.css` — relative paths stay valid at `/coming-soon/`.

- [ ] **Step 2: `public/_redirects`**

```
# NovaGuard redirects (Netlify / Cloudflare Pages)

# MAINTENANCE MODE — uncomment while shipping bot updates to route the
# whole site to the classic Coming Soon page, redeploy, then re-comment:
# /*  /coming-soon/  302!

/hq  https://novaguard.fun  301

# Dashboard is a client-routed SPA — deep links fall back to its shell:
/dashboard/*  /dashboard/  200
```

- [ ] **Step 3: `package.json`**

```json
{
  "name": "novaguard-website",
  "type": "module",
  "private": true,
  "scripts": {
    "dev": "astro dev",
    "build": "astro check && astro build",
    "preview": "astro preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@astrojs/check": "^0.9.4",
    "@astrojs/react": "^4.2.0",
    "@fontsource-variable/inter": "^5.2.5",
    "@fontsource-variable/newsreader": "^5.2.5",
    "@tailwindcss/vite": "^4.1.0",
    "@tanstack/react-query": "^5.66.0",
    "@tanstack/react-router": "^1.112.0",
    "astro": "^5.7.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "tailwindcss": "^4.1.0",
    "typescript": "^5.7.0",
    "zod": "^3.24.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.2.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "happy-dom": "^17.0.0",
    "vitest": "^3.0.0"
  }
}
```

- [ ] **Step 4: `astro.config.mjs`, `tsconfig.json`, `.gitignore`, `.env.example`**

```js
// astro.config.mjs
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: "https://novaguard.fun",
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
});
```

```json
// tsconfig.json
{
  "extends": "astro/tsconfigs/strict",
  "compilerOptions": { "jsx": "react-jsx", "jsxImportSource": "react" },
  "include": ["src/**/*"],
  "exclude": ["dist"]
}
```

```
# .gitignore
node_modules/
dist/
.astro/
.env
```

```
# .env.example — copy to .env for local dev
PUBLIC_API_BASE=http://localhost:8081
```

- [ ] **Step 5: `src/styles/global.css` (tokens — single source of truth)**

```css
@import "tailwindcss";
@import "@fontsource-variable/newsreader";
@import "@fontsource-variable/inter";

@theme {
  --color-paper: #faf9f5;
  --color-surface: #ffffff;
  --color-ink: #1c1917;
  --color-ink-muted: #6f6a61;
  --color-line: #e7e3da;
  --color-accent: #8c2b1a;
  --color-accent-soft: #f6ebe8;
  --font-display: "Newsreader Variable", Georgia, "Times New Roman", serif;
  --font-sans: "Inter Variable", system-ui, -apple-system, sans-serif;
}

html {
  background: var(--color-paper);
  color: var(--color-ink);
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
  scroll-behavior: smooth;
}

::selection { background: var(--color-accent); color: #fff; }

/* Editorial scroll reveal — pure CSS + tiny observer added in Task 2 */
.reveal { opacity: 0; transform: translateY(12px); transition: opacity 0.6s ease, transform 0.6s ease; }
.reveal.is-visible { opacity: 1; transform: none; }

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .reveal { opacity: 1; transform: none; transition: none; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
```

- [ ] **Step 6: `src/layouts/Base.astro`**

```astro
---
import "../styles/global.css";
interface Props { title: string; description?: string }
const { title, description = "NovaGuard — the friendly guardian for your Discord community." } = Astro.props;
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#faf9f5" />
    <title>{title}</title>
    <meta name="description" content={description} />
    <meta property="og:title" content={title} />
    <meta property="og:description" content={description} />
    <meta property="og:type" content="website" />
    <meta property="og:image" content="/favicon.png" />
    <link rel="icon" type="image/png" href="/favicon.png" />
    <link rel="apple-touch-icon" href="/favicon.png" />
  </head>
  <body class="min-h-screen bg-paper text-ink font-sans">
    <slot />
  </body>
</html>
```

- [ ] **Step 7: placeholder `src/pages/index.astro`**

```astro
---
import Base from "../layouts/Base.astro";
---
<Base title="NovaGuard">
  <h1 class="font-display text-5xl p-12">NovaGuard</h1>
</Base>
```

- [ ] **Step 8: Install & verify build**

Run: `cd website-3 && npm install && npm run build`
Expected: `astro check` 0 errors; `dist/` contains `index.html`, `coming-soon/index.html` (byte-identical to legacy), `_redirects`, `favicon.png`.

- [ ] **Step 9: Commit**

```bash
git add -A website-3 && git commit -m "feat(website): scaffold Astro 5 site, preserve Coming Soon page + /hq redirect"
```

---

### Task 2: Landing — Nav, Hero, Features, CTA, Footer, 404

**Files:**
- Create: `website-3/src/components/Nav.astro`, `Hero.astro`, `Features.astro`, `Cta.astro`, `Footer.astro`, `website-3/src/pages/404.astro`
- Modify: `website-3/src/pages/index.astro` (replace placeholder)

**Interfaces:**
- Consumes: `Base.astro`, tokens from Task 1.
- Produces: `Nav.astro` and `Footer.astro` reused by Tasks 3/4; `.reveal` observer script pattern.

Layout direction (editorial): centered column `max-w-5xl`, generous vertical rhythm (`py-24`+), hairline dividers (`border-t border-line`), small-caps kicker labels (`text-xs uppercase tracking-[0.2em] text-ink-muted`), huge Newsreader headlines with `font-medium italic` accents. No cards with shadows — rules and whitespace only.

- [ ] **Step 1: `Nav.astro`**

```astro
---
const links = [
  { href: "/commands", label: "Commands" },
  { href: "/dashboard", label: "Dashboard" },
];
---
<header class="border-b border-line">
  <nav class="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
    <a href="/" class="flex items-center gap-2.5 font-display text-xl italic">
      <img src="/favicon.png" alt="" width="28" height="28" class="rounded-md" />
      NovaGuard
    </a>
    <div class="flex items-center gap-7 text-sm">
      {links.map((l) => (
        <a href={l.href} class="text-ink-muted transition-colors hover:text-ink">{l.label}</a>
      ))}
      <a href="#" data-invite
        class="rounded-full bg-accent px-4 py-1.5 text-white transition-opacity hover:opacity-90">
        Add to Discord
      </a>
    </div>
  </nav>
</header>
<script>
  // Invite goes straight to the bot API redirect when configured.
  const base = import.meta.env.PUBLIC_API_BASE;
  document.querySelectorAll<HTMLAnchorElement>("[data-invite]").forEach((a) => {
    if (base) a.href = `${base}/api/v1/invite`;
  });
</script>
```

- [ ] **Step 2: `Hero.astro`**

```astro
<section class="mx-auto max-w-5xl px-6 pb-20 pt-24 text-center sm:pt-32">
  <p class="text-xs uppercase tracking-[0.25em] text-ink-muted">Self-hosted · Open source · Raspberry Pi friendly</p>
  <h1 class="mx-auto mt-6 max-w-3xl font-display text-5xl leading-[1.05] sm:text-7xl">
    The friendly <em class="text-accent">guardian</em> for your Discord community.
  </h1>
  <p class="mx-auto mt-6 max-w-xl text-lg text-ink-muted">
    Moderation, levels, tickets, giveaways and a real setup wizard — run from
    hardware you own, configured from your browser.
  </p>
  <div class="mt-10 flex items-center justify-center gap-4">
    <a href="#" data-invite class="rounded-full bg-accent px-6 py-3 text-white transition-opacity hover:opacity-90">Add to Discord</a>
    <a href="/dashboard" class="rounded-full border border-line px-6 py-3 transition-colors hover:border-ink">Open dashboard</a>
  </div>
</section>
```
(The `data-invite` rewriting script from Nav covers these too — Nav is on every page.)

- [ ] **Step 3: `Features.astro`** — 2-col editorial list from the bot's real feature set (README): Community management / Setup that feels modern / Rich server experience / GitHub-aware developer layer / Levels & economy / Raspberry Pi friendly. Each item: small-caps kicker, one-line serif statement, 1-sentence muted body, `reveal` class, `border-t border-line` separators. Include the IntersectionObserver script:

```astro
<script>
  const io = new IntersectionObserver(
    (entries) => entries.forEach((e) => e.isIntersecting && e.target.classList.add("is-visible")),
    { threshold: 0.15 },
  );
  document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
</script>
```

- [ ] **Step 4: `Cta.astro` + `Footer.astro`**

Footer: hairline top border; left — `NovaGuard` serif wordmark + creator credit exactly `Developed by VIK & CloudMediaSRL`; right — links `/commands`, `/dashboard`, `/coming-soon` (label "Classic page"), `/privacy`, `/terms`, GitHub repo.

- [ ] **Step 5: assemble `index.astro`; create `404.astro`** (Base + Nav + serif "404 — This page drifted off." + link home + Footer).

- [ ] **Step 6: Verify**

Run: `npm run dev` → check `/` and `/404` render, nav links work, reveal animates, reduced-motion disables it.

- [ ] **Step 7: Commit** — `git add -A website-3 && git commit -m "feat(website): editorial landing — hero, features, CTA, footer, 404"`

---

### Task 3: Commands page + privacy/terms

**Files:**
- Create: `website-3/src/data/commands.ts`, `website-3/src/pages/commands.astro`, `website-3/src/pages/privacy.astro`, `website-3/src/pages/terms.astro`

**Interfaces:**
- Produces: `export interface CommandCategory { emoji: string; name: string; blurb: string; commands: string[] }`, `export const commandCategories: CommandCategory[]`.

- [ ] **Step 1: `src/data/commands.ts`** — 15 categories verbatim from `SETUP.md` §5 (Setup 🚀, System ⚙️, Developer 🐙, Utility 🧰, Fun 🎉, Moderation 🛡️, Levels 🏆, Welcome 👋, Logs 📋, Roles 🎭, Giveaways 🎁, Tickets 🎫, AutoMod 🤖, Economy 💰, AI 🧠) with each command string (e.g. `/config view|export|backup|reset`). One-line blurbs summarizing the SETUP.md notes.

- [ ] **Step 2: `commands.astro`** — Nav + header ("Every command, one page.") + per-category sections: kicker = emoji + name, blurb muted, commands as inline `<code>` chips (`rounded-md border border-line bg-surface px-2 py-0.5 text-sm`). Footer. Note under header: "Tip: /help opens an interactive hub inside Discord."

- [ ] **Step 3: `privacy.astro` / `terms.astro`** — port text content from `docs/privacy.html` and `docs/terms.html` into Base layout prose (read those files; keep their wording, restyle with `max-w-2xl` editorial prose).

- [ ] **Step 4: Verify** dev render `/commands`, `/privacy`, `/terms`.

- [ ] **Step 5: Commit** — `git commit -m "feat(website): commands catalog, privacy & terms pages"`

---

### Task 4: Live stats strip

**Files:**
- Create: `website-3/src/components/StatsStrip.astro`
- Modify: `website-3/src/pages/index.astro` (insert between Hero and Features)

**Interfaces:**
- Consumes: public `GET {API}/api/v1/stats` → `{ guilds, members, commands, uptime_seconds, version, ready }`.

- [ ] **Step 1: `StatsStrip.astro`**

```astro
<section class="border-y border-line bg-surface">
  <dl data-stats class="mx-auto grid max-w-5xl grid-cols-2 gap-px px-6 py-10 text-center sm:grid-cols-4" hidden>
    <div><dt class="text-xs uppercase tracking-[0.2em] text-ink-muted">Servers</dt><dd data-stat="guilds" class="mt-1 font-display text-4xl">–</dd></div>
    <div><dt class="text-xs uppercase tracking-[0.2em] text-ink-muted">Members</dt><dd data-stat="members" class="mt-1 font-display text-4xl">–</dd></div>
    <div><dt class="text-xs uppercase tracking-[0.2em] text-ink-muted">Commands</dt><dd data-stat="commands" class="mt-1 font-display text-4xl">–</dd></div>
    <div><dt class="text-xs uppercase tracking-[0.2em] text-ink-muted">Uptime</dt><dd data-stat="uptime" class="mt-1 font-display text-4xl">–</dd></div>
  </dl>
  <p data-stats-fallback class="mx-auto max-w-5xl px-6 py-8 text-center text-sm text-ink-muted">
    Live numbers appear when the bot is online.
  </p>
</section>
<script>
  const base = import.meta.env.PUBLIC_API_BASE;
  const dl = document.querySelector<HTMLElement>("[data-stats]");
  const fb = document.querySelector<HTMLElement>("[data-stats-fallback]");
  const fmt = (n: number) => new Intl.NumberFormat("en").format(n);
  const days = (s: number) => (s >= 86400 ? `${Math.floor(s / 86400)}d` : s >= 3600 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 60)}m`);
  if (base && dl && fb) {
    fetch(`${base}/api/v1/stats`, { signal: AbortSignal.timeout(4000) })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((s) => {
        const set = (k: string, v: string) => { const el = dl.querySelector(`[data-stat="${k}"]`); if (el) el.textContent = v; };
        set("guilds", fmt(s.guilds)); set("members", fmt(s.members));
        set("commands", fmt(s.commands)); set("uptime", days(s.uptime_seconds));
        dl.hidden = false; fb.hidden = true;
      })
      .catch(() => {});
  }
</script>
```

- [ ] **Step 2: Verify** — with bot down: fallback line shows, no console errors. (If the bot is running locally with `WEB_ENABLED=true`, numbers replace it.)

- [ ] **Step 3: Commit** — `git commit -m "feat(website): live stats strip with graceful offline fallback"`

---

### Task 5: API foundation — Zod schemas + typed client (TDD)

**Files:**
- Create: `website-3/src/lib/api/schemas.ts`, `website-3/src/lib/api/client.ts`, `website-3/vitest.config.ts`, `website-3/src/lib/api/client.test.ts`

**Interfaces (produced — later tasks import exactly these):**
```ts
// schemas.ts
export const StatsSchema, MeSchema, GuildsSchema, GuildConfigSchema, AuditSchema; // zod objects
export type Stats, Me, Guild, GuildConfig, GuildSettings, AuditEntry;             // z.infer types
export type SettingsPatch = Partial<{
  welcome_channel: string | null; goodbye_channel: string | null;
  log_channel: string | null; update_channel: string | null;
  github_event_channel: string | null; error_log_channel: string | null;
  autorole: string | null; ticket_staff_role: string | null;
  automod: Partial<{ invites: boolean; spam: boolean; badwords: string[] }>;
}>;
// client.ts
export class ApiError extends Error { code: string; status: number; retryAfter?: number; details?: string[] }
export const API_BASE: string;                       // from import.meta.env.PUBLIC_API_BASE
export function loginUrl(): string;                  // `${API_BASE}/api/v1/auth/login`
export function inviteUrl(): string;                 // `${API_BASE}/api/v1/invite`
export async function apiFetch<T>(path: string, schema: ZodType<T>, init?: RequestInit): Promise<T>;
```

Schema fields mirror `docs/API.md` exactly:
- `StatsSchema`: `{ version: string, codename: string, guilds: number, members: number, commands: number, uptime_seconds: number, ready: boolean }`
- `MeSchema`: `{ user: { id, username, avatar: string|null } }`
- `GuildsSchema`: `{ guilds: [{ id, name, icon: string|null, owner: boolean, permissions: number, bot_present: boolean }] }`
- `GuildConfigSchema`: `{ guild: { id, name, icon: string|null, member_count: number }, settings: { welcome_channel/goodbye_channel/log_channel/update_channel/github_event_channel/error_log_channel: string|null, autorole: string|null, ticket_staff_role: string|null, automod: { invites: boolean, spam: boolean, badwords: string[] } }, channels: [{ id, name, category: string|null }], roles: [{ id, name, color: string, assignable: boolean }] }`
- `AuditSchema`: `{ audit: [{ username: string, user_id: string, action: string, changes: Record<string, unknown>, created_at: string }] }`

`apiFetch` behavior (this is the whole error contract):
1. `fetch(`${API_BASE}/api/v1${path}`, { credentials: "include", headers: { "Content-Type": "application/json", ...init?.headers }, ...init })`
2. non-OK → parse body JSON `{ error, code, details? }`; throw `ApiError(message=error, code, status, retryAfter=Number(headers.get("Retry-After"))||undefined, details)`; body parse failure → `code: "internal_error"`.
3. OK → `schema.parse(await res.json())` (ZodError surfaces contract drift loudly in dev).
4. Network failure → `ApiError` with `code: "network_error"`, `status: 0`.

- [ ] **Step 1: `vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";
export default defineConfig({
  test: { environment: "happy-dom", include: ["src/**/*.test.{ts,tsx}"] },
});
```

- [ ] **Step 2: Write failing tests `client.test.ts`** (stub `globalThis.fetch` with `vi.stubGlobal`): ① OK response parses via schema and returns typed data; ② error body `{error:"Nope",code:"forbidden"}` status 403 → throws ApiError with `code==="forbidden"`, `status===403`; ③ 429 with `Retry-After: 7` and `validation_failed` + `details` → `retryAfter===7`, `details` array preserved; ④ fetch rejection → `code==="network_error"`; ⑤ `credentials:"include"` present in every call's init.

- [ ] **Step 3: Run** `npm test` → failing (module not found).
- [ ] **Step 4: Implement `schemas.ts` + `client.ts`** per interface block above.
- [ ] **Step 5: Run** `npm test` → all pass. `npx astro check` → 0 errors.
- [ ] **Step 6: Commit** — `git commit -m "feat(website): typed API client + zod schemas mirroring docs/API.md (TDD)"`

---

### Task 6: Dashboard shell — island, router, auth gate

**Files:**
- Create: `website-3/src/pages/dashboard/index.astro`, `website-3/src/app/main.tsx`, `website-3/src/app/router.tsx`, `website-3/src/app/queries.ts`, `website-3/src/app/components/AuthGate.tsx`, `website-3/src/app/components/Shell.tsx`

**Interfaces:**
- Consumes: `apiFetch`, `loginUrl`, `MeSchema`, `ApiError` (Task 5).
- Produces: `useMe()` query hook in `queries.ts` (`retry: false`); route tree — `/` (picker), `/g/$guildId` (config), `/g/$guildId/audit`; `Shell` = topbar (wordmark → `/`, username + avatar, Sign out button → `POST /auth/logout` then invalidate `me`) + `<Outlet/>`.

- [ ] **Step 1: `dashboard/index.astro`** — Base layout, `<div id="app">` + module `<script>` importing `../../app/main.tsx` (plain `createRoot` mount for full control).
- [ ] **Step 2: `main.tsx`** — `QueryClient` (default `retry: (count, err) => !(err instanceof ApiError && ["unauthorized","session_expired","forbidden"].includes(err.code)) && count < 2`), `RouterProvider` with `createRouter({ routeTree, basepath: "/dashboard" })`.
- [ ] **Step 3: `AuthGate.tsx`** — states: loading (serif "Checking your session…"); ApiError `unauthorized`/`session_expired` → login screen (serif headline "The working section.", one muted sentence, accent button "Continue with Discord" → `window.location.assign(loginUrl())`); `network_error`/`bot_starting` → "Bot unreachable" screen with Retry button; authed → children.
- [ ] **Step 4:** Routes render inside `Shell` inside `AuthGate`; placeholder screens for picker/config/audit (real ones Tasks 7–9).
- [ ] **Step 5: Verify** — `npm run dev` → `/dashboard` shows login screen when API is down/logged out; `astro check` clean.
- [ ] **Step 6: Commit** — `git commit -m "feat(website): dashboard shell — react island, router, query client, auth gate"`

---

### Task 7: Guild picker

**Files:**
- Create: `website-3/src/app/screens/GuildPicker.tsx`; register in `router.tsx` index route; `useGuilds()` added to `queries.ts`.

**Interfaces:**
- Consumes: `apiFetch("/guilds", GuildsSchema)`, `inviteUrl()`.
- Produces: navigation to `/g/$guildId`.

- [ ] **Step 1:** `useGuilds()` hook. Screen: kicker "Your servers", serif headline "Pick a server to configure." Hairline-separated rows: guild icon (URL `https://cdn.discordapp.com/icons/{id}/{icon}.png?size=64` when `icon` non-null, else serif initial in bordered circle), name, `owner` small-caps badge; right side: `bot_present` → "Configure →" link; else muted "Bot not here yet" + Invite link (`inviteUrl()`).
- [ ] **Step 2:** Empty state: "No servers where you can Manage Server." Loading: three skeleton hairline rows (CSS pulse, reduced-motion safe).
- [ ] **Step 3: Verify** in browser (visual QA finalized Task 10).
- [ ] **Step 4: Commit** — `git commit -m "feat(website): dashboard guild picker"`

---

### Task 8: Guild config screen (TDD on form logic)

**Files:**
- Create: `website-3/src/app/lib/configForm.ts`, `website-3/src/app/lib/configForm.test.ts`, `website-3/src/app/screens/GuildConfig.tsx`, `website-3/src/app/components/ChannelSelect.tsx`, `website-3/src/app/components/RoleSelect.tsx`, `website-3/src/app/components/BadwordsEditor.tsx`, `website-3/src/app/components/SaveBar.tsx`

**Interfaces:**
- Consumes: `GuildConfigSchema`, `GuildSettings`, `SettingsPatch`, `apiFetch` PUT.
- Produces (pure functions, no React — fully unit-testable):
```ts
// configForm.ts
export function diffSettings(server: GuildSettings, draft: GuildSettings): SettingsPatch;
// only changed keys; automod compared field-by-field, badwords as set-equality; {} when clean
export function isDirty(server: GuildSettings, draft: GuildSettings): boolean;
export function normalizeBadwords(raw: string[]): string[]; // lowercase, trim, dedupe, drop empty/overlong(>40), cap 100 (mirror API.md)
export function mapValidationDetails(details: string[] | undefined): Record<string, string>;
// pairs each detail message to a settings key by substring match; unmatched → "_global"
```

- [ ] **Step 1: failing tests `configForm.test.ts`** — ① diff returns only changed keys (change `welcome_channel`, expect single-key patch); ② clearing a channel yields `null` not `""`; ③ automod: toggling `invites` yields `{automod:{invites:false}}` without `badwords`; ④ badwords set-equality — reordered list ⇒ clean diff; ⑤ `normalizeBadwords([" Spoiler ","spoiler","<41-char string>",""])` → `["spoiler"]`; ⑥ `isDirty` false on identical, true after edit; ⑦ `mapValidationDetails(["welcome_channel: not a text channel"])` → `{ welcome_channel: "…" }`.
- [ ] **Step 2:** `npm test` → new tests fail.
- [ ] **Step 3:** implement `configForm.ts`.
- [ ] **Step 4:** `npm test` green.
- [ ] **Step 5: `GuildConfig.tsx`** — `useQuery` config by guildId; local `draft` state seeded from `settings`, reset on refetch (`useEffect` on `dataUpdatedAt`). Three hairline sections with small-caps kickers:
  - **Channels** — six `ChannelSelect`s (welcome, goodbye, log, update, github_event, error_log): styled native `<select>` (border-line, bg-surface), options grouped by `category` via `<optgroup>`, first option "— none —" → `null`.
  - **Roles** — `RoleSelect` for `autorole` (only `assignable` roles) + `ticket_staff_role` (all roles), color dot from `role.color`.
  - **AutoMod** — two toggle rows (invites/spam; accessible `<button role="switch" aria-checked>`) + `BadwordsEditor`: chips + input (Enter adds via `normalizeBadwords`), chip × removes.
  - `SaveBar` — fixed bottom hairline bar, visible when `isDirty`: "Unsaved changes" + Discard (reset draft) + Save (accent). Save → `useMutation` → `apiFetch(PUT, JSON.stringify(diffSettings(...)))`; success → write returned payload into query cache (contract: same shape as GET); `validation_failed` → `mapValidationDetails` under fields; other ApiError → banner in SaveBar.
- [ ] **Step 6: Verify** — `astro check` + full `npm test`; browser QA if bot available.
- [ ] **Step 7: Commit** — `git commit -m "feat(website): guild config editor — partial PUT, dirty tracking, validation mapping (TDD)"`

---

### Task 9: Audit screen

**Files:**
- Create: `website-3/src/app/screens/AuditLog.tsx`; register route `/g/$guildId/audit`; tab strip (Config / Audit) in the guild layout in `router.tsx`.

- [ ] **Step 1:** `useAudit(guildId)` → `apiFetch(`/guilds/${id}/audit?limit=50`, AuditSchema)`. Editorial table: hairline rows, `created_at` → `Intl.DateTimeFormat` ("Jul 12, 14:00"), username strong, `action` small-caps, `changes` as `key → value` code chips. Empty state: "No dashboard changes yet."
- [ ] **Step 2: Commit** — `git commit -m "feat(website): guild audit log screen"`

---

### Task 10: README, verification pass, polish

**Files:**
- Rewrite: `website-3/README.md` (dev/build/test commands; `PUBLIC_API_BASE`; deploy to CF Pages/Netlify; **maintenance mode** — the one-line `_redirects` uncomment; bot-side requirements: `WEB_ENABLED=true`, `WEB_CORS_ORIGIN` must include the site origin, `WEB_AFTER_LOGIN` → `https://<site>/dashboard`)
- Modify: root `README.md` — update the "static coming-soon site" sentence to describe the full site (one sentence, keep style).

- [ ] **Step 1:** Write both READMEs.
- [ ] **Step 2: Full gate:** `npm test` all green; `npm run build` clean (`astro check` 0 errors).
- [ ] **Step 3: Browser verification (preview tools):** `/` `/commands` `/privacy` `/terms` `/404` `/coming-soon/` `/dashboard` — desktop 1280 + mobile 375; screenshots; console clean; reveal + reduced-motion; login screen when API down.
- [ ] **Step 4:** Fix anything found (design polish iteration happens here, in-browser).
- [ ] **Step 5: Commit** — `git commit -m "docs(website): README, deploy + maintenance-mode guide; final QA pass"`

## Self-Review Notes

- Spec coverage: landing (T2–T4), commands (T3), coming-soon preserved (T1), dashboard auth/picker/config/audit (T6–T9), error contract (T5), tokens/motion/a11y (T1–T2), README + maintenance toggle (T10), privacy/terms (T3), stats fallback (T4). ✔
- Deviation from spec (improvement): coming-soon served from `public/coming-soon/` (byte-identical passthrough) instead of `pages/coming-soon.astro` re-render — safer preservation, same URL. Footer "Classic page" links to it.
- Type consistency: `GuildSettings`/`SettingsPatch` defined T5, consumed T8; `ApiError.code` strings match the API.md table; `inviteUrl()` defined T5, used T7 and available to Nav.
