# NovaGuard Website

Editorial landing + admin dashboard for NovaGuard, built with Astro 5 and a
React 19 island. Consumes the bot's embedded API (`docs/API.md`, `/api/v1`).

## Develop

```bash
cp .env.example .env      # set PUBLIC_API_BASE to the bot API origin
npm install
npm run dev               # http://localhost:4321
```

## Test & build

```bash
npm test                  # vitest — API client + config form logic
npm run build             # astro check + static build into dist/
```

## Deploy (Cloudflare Pages / Netlify)

Static output — publish `dist/`. Build command `npm run build`, no server needed.
Set `PUBLIC_API_BASE` as a build-time environment variable pointing at the
public bot API origin (e.g. the Cloudflare Tunnel domain of the Pi).

Bot-side requirements (see `docs/API.md`):

- `WEB_ENABLED=true`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`
- `WEB_CORS_ORIGIN` must include this site's origin
- `WEB_AFTER_LOGIN` should point to `https://<site>/dashboard`

## Soft-launch mode (default right now)

`npm run build` physically copies the Coming Soon page onto `dist/index.html`
after the Astro build (`scripts/soft-launch.mjs`), while the full site stays
live at its own routes: `/home` (the real landing), `/commands`, `/status`,
`/dashboard`. Share those links freely — the dashboard is protected by
Discord login regardless.

This uses a file copy rather than a `_redirects` rewrite rule because some
static hosts (Cloudflare Workers static assets, unlike classic Pages) only
honor real redirects (3xx) from `_redirects`, not 200 "rewrite" rules —
confirmed by testing against a live deploy.

**For the public launch:** build with `npm run build:launch` instead (skips
the Coming Soon copy step, so `/` serves the real landing), then redeploy.

## Maintenance mode (classic Coming Soon page)

The original launch page is preserved byte-identical at `/coming-soon/`.
While shipping bot updates, route the whole site to it by uncommenting one
line in `public/_redirects`, then redeploying:

```
/*  /coming-soon/  302!
```

Re-comment and redeploy to go live again. The `/hq` shortcut redirect is kept.

## Structure

```
public/coming-soon/   preserved legacy page (do not edit)
src/pages/            landing, commands, privacy, terms, 404, dashboard shell
src/components/       Astro landing components (zero client JS where possible)
src/app/              React dashboard — TanStack Router + Query
src/lib/api/          typed client + zod schemas mirroring docs/API.md
src/styles/global.css design tokens (single source of truth)
```
