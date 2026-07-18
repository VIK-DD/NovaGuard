# NovaGuard Website — Design Spec

**Date:** 2026-07-18
**Scope:** Rebuild `website-3/` from static coming-soon page into the full NovaGuard site: public landing + admin dashboard, consuming the existing bot API (`docs/API.md`, `/api/v1`).

## Decisions (validated with Victor)

| Topic | Decision |
|---|---|
| Scope | Landing + Dashboard in one site |
| Hosting | Static build on CDN (Cloudflare Pages / Netlify); API stays on the Pi behind a tunnel domain, cross-origin |
| Stack | Astro 5 (static) + React 19 island for the dashboard |
| Visual direction | Light editorial — paper background, serif display type, minimal, intuitive; aesthetic details delegated to implementation |
| Coming Soon page | **Preserved.** Kept reachable at `/coming-soon`; re-activating it site-wide (maintenance mode during bot updates) is a one-line `_redirects` change, documented in the README |

## Architecture

```
website-3/
├─ astro.config.mjs, tailwind config, tsconfig (strict)
├─ public/            favicon + logo (reuse existing assets), _redirects
└─ src/
   ├─ styles/tokens.css        single source for color/type/spacing tokens
   ├─ layouts/Base.astro       SEO meta, OG tags, font loading
   ├─ pages/
   │  ├─ index.astro           landing
   │  ├─ commands.astro        command catalog
   │  ├─ coming-soon.astro     preserved legacy page (content ported as-is)
   │  ├─ 404.astro
   │  └─ dashboard/[...app].astro   shell mounting the React island
   ├─ components/              Astro components for landing (zero client JS where possible)
   ├─ app/                     React dashboard: TanStack Router (client) + TanStack Query
   └─ lib/api/                 typed fetch client + Zod schemas mirroring docs/API.md
```

- Landing pages ship as pure static HTML; the dashboard is a `client:only` React island under `/dashboard/*`. Marketing pages load zero dashboard code.
- `_redirects`: SPA fallback for `/dashboard/*` → the dashboard shell; commented-out maintenance line that routes `/*` → `/coming-soon` when activated.

## Landing (public)

- **Home** — editorial hero (large serif headline, one sentence), features grouped by the bot's real command categories, live stats strip from public `GET /stats` (tiny inline script; graceful "offline" fallback), invite CTA via `GET /invite`, creator credit preserved from the current page.
- **Commands** — static catalog of the slash-command categories from `SETUP.md`. No API dependency.
- **Coming Soon** — the current page's content ported unchanged, styled to coexist.
- **404** — minimal editorial page.
- **Footer** — links to the existing `docs/privacy.html` and `docs/terms.html` (ported into the site as static pages so everything lives on one domain).

## Dashboard (`/dashboard`)

- **Auth:** on mount, `GET /me`; 401 → login screen whose button *navigates* the browser to `{API}/api/v1/auth/login` (per API.md, not a fetch). Bot's `WEB_AFTER_LOGIN` must point back to `/dashboard`. Logout via `POST /auth/logout`.
- **Server picker:** `GET /guilds`; bot-present guilds first; guilds without the bot show an invite button.
- **Guild config:** sections driven by `GET /guilds/{id}/config` (Welcome, Autorole, AutoMod, …). Explicit save with "unsaved changes" banner; `PUT` sends only changed keys (partial update per contract). `validation_failed.details[]` maps to per-field error messages.
- **Audit:** `GET /guilds/{id}/audit` — who changed what, when.
- **Error handling branches on `code`, never on message text:** `session_expired` → re-login flow; `bot_starting`/`rate_limited` → retry honoring `Retry-After`; `forbidden` → clear message. TanStack Query centralizes retry/caching; every fetch sends `credentials: "include"`.

## Design system — light editorial

- **Tokens:** warm paper background, near-black ink text, thin hairline rules, a single dark accent (final hue chosen at implementation with WCAG AA contrast check; explicitly not Discord blurple).
- **Type:** variable serif display (Newsreader or similar, optical sizing) for headlines; clean sans (Inter/Geist) for UI and body. Small-caps labels for section markers.
- **Motion:** subtle scroll reveals and short dashboard transitions; `prefers-reduced-motion` fully respected.
- **Cohesion:** dashboard uses the same tokens — it reads as the working section of the same publication, not a different product.

## Edge cases

- Bot offline: landing fully functional (stats show fallback); dashboard shows a "bot unreachable" state.
- Cross-origin: site origin must be added to `WEB_CORS_ORIGIN` on the bot; browser sends `Origin` on mutations automatically (CSRF guard already server-side).
- No bot-side changes required; the API contract is consumed as-is.

## Testing & tooling

- TypeScript strict, `astro check` in build.
- Vitest + Testing Library: API client (envelope/error-code handling), config form logic (dirty tracking, partial PUT payloads, validation error mapping).
- Deploy: `astro build` → static `dist/`; `PUBLIC_API_BASE` env var (dev: local bot port; prod: Pi tunnel domain).

## Out of scope (YAGNI)

- No SSR, no separate backend, no i18n toggle (site ships in English like the rest of the public repo), no docs/changelog pages yet (Coming Soon page covers the update-mode story).
