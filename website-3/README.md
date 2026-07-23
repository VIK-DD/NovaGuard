# NovaGuard Website

Editorial landing page and administration dashboard built with Astro 5 and a
React 19 dashboard island. The site exports to static files and is served by a
Cloudflare Worker that protects private routes with a shared password.

## Develop

```bash
npm install
npm run dev               # http://localhost:4321
```

Set `PUBLIC_API_BASE` to the public NovaGuard bot API origin for local work.
Production builds already use `https://api.novaguard.fun` from `.env.production`.

The `/status` page reads `GET /api/v1/health` and `GET /api/v1/stats` from this
origin. For production, use an HTTPS hostname published through Cloudflare
Tunnel, not `localhost` or the Pi's private address.

## Test and build

```bash
npm test                  # API client and configuration-form tests
npm run build             # static Astro export into dist/
```

`npm run build` runs the soft-launch step after the Astro export. It copies
the preserved Coming Soon page onto `dist/index.html`, while the full landing
remains available at `/home/`.

To export the full landing at `/` without the Coming Soon override:

```bash
npm run build:launch
```

## Deploy to Cloudflare

The Worker serves `dist/`, validates the signed password cookie, and sends
unauthenticated visitors to `/login/`. The root Coming Soon page and its assets
remain public.

Set the password once, then deploy:

```bash
npx wrangler secret put AUTH_PASSWORD
npm run deploy
```

Protected routes can be temporarily replaced with the update page by setting the
Worker variable `MAINTENANCE_MODE`.

```bash
npx wrangler secret put MAINTENANCE_MODE
# type: protected
```

Turn it back off with:

```bash
npx wrangler secret put MAINTENANCE_MODE
# type: off
```

Accepted enabled values are `1`, `true`, `on`, `enabled`, `protected` and
`private`. When enabled, users still enter the password first, then private
routes serve `/maintenance/`.

Cloudflare Access applications must be disabled for this hostname because the
custom Worker performs the access check.

Bot-side requirements:

- `WEB_ENABLED=true`, `DISCORD_CLIENT_ID`, and `DISCORD_CLIENT_SECRET`
- `WEB_CORS_ORIGIN` includes this website origin
- `WEB_AFTER_LOGIN` points to `https://<site>/dashboard/`

## Structure

```text
src/pages/              Astro landing, login, legal, status and dashboard shell
src/components/         Astro landing components and React visual islands
src/app/                existing dashboard application and TanStack Router
src/lib/api/            typed API client and Zod schemas
public/coming-soon/     preserved legacy page; do not edit
worker/                 Cloudflare password gate and static asset handler
scripts/soft-launch.mjs root Coming Soon copy step
```
